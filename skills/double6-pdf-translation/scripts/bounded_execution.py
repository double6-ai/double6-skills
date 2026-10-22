"""使用共享执行边界运行单个有界任务，同时观察自身、子进程和 Codex 内存。"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import psutil
from daily_skill_research.execution import _redact_text, run_command, write_failure_receipt


# psutil 对单个进程取属性时可能抛出的错误：进程消失/僵尸（NoSuchProcess、ZombieProcess）、无权限（AccessDenied、
# PermissionError），以及 macOS 上 C 扩展在取 name/cmdline（KERN_PROCARGS2）时从迭代器内部抛出的 SystemError。
PROCESS_QUERY_ERRORS = (psutil.Error, PermissionError, SystemError, OSError)
OWNED_MONITOR_FAILURE = "owned_process_monitor_unavailable"
MONITOR_FAILURE = "resource_monitor_unavailable"


def _process_memory(proc: psutil.Process, metric: str) -> dict[str, Any]:
    rss = proc.memory_info().rss
    try:
        name = proc.name()  # 名称只是遥测，取不到不影响计量
    except PROCESS_QUERY_ERRORS:
        name = None
    row = {"pid": proc.pid, "rss": rss, "name": name}
    if metric == "pss":
        # PSS 按共享页比例分摊；fork 出的后端子进程不再重复计入父进程共享页。
        try:
            row["pss"] = getattr(proc.memory_full_info(), "pss", rss)
        except (psutil.AccessDenied, OSError, AttributeError):
            row["pss"] = rss
    return row


def _unowned_codex_scan() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """非本任务进程的 Codex 内存遥测（只用于 codex_memory_fuse）：逐进程隔离错误。
    不再用 process_iter(attrs)（它在迭代器内部取 name，macOS 上 SystemError 会在循环体之前抛出）；
    迭代器本身的 next() 也受保护：出错即结束本次扫描并记为不完整，不影响本任务计量与其余资源门。"""
    rows: list[dict[str, Any]] = []
    status: dict[str, Any] = {"complete": True, "per_process_errors": 0, "iterator_error": None}
    iterator = psutil.process_iter()
    while True:
        try:
            proc = next(iterator)
        except StopIteration:
            break
        except PROCESS_QUERY_ERRORS as exc:
            status["complete"] = False
            status["iterator_error"] = f"{type(exc).__name__}: {exc}"[:300]
            break
        try:
            name = proc.name() or ""
            lowered = name.lower()
            if "codex" in lowered or "node_repl" in lowered:
                rows.append({"pid": proc.pid, "rss": proc.memory_info().rss, "name": name})
        except PROCESS_QUERY_ERRORS:
            status["per_process_errors"] += 1
    return rows, status


def snapshot(members: list[psutil.Process] | None = None, *, metric: str = "rss") -> dict[str, Any]:
    if metric not in ("rss", "pss"):
        raise ValueError("memory metric must be rss or pss")
    own = psutil.Process()
    owned_errors: list[dict[str, Any]] = []
    try:
        children = own.children(recursive=True) if members is None else members
    except PROCESS_QUERY_ERRORS as exc:
        children = []
        owned_errors.append({"pid": own.pid, "error": f"children: {type(exc).__name__}: {exc}"[:300]})
    process_rows = []
    for proc in [own, *children]:
        try:
            process_rows.append(_process_memory(proc, metric))
        except psutil.NoSuchProcess:
            continue  # 已退出（含僵尸）的本任务进程不再占内存
        except PROCESS_QUERY_ERRORS as exc:
            # 本任务进程计量不到即无法可靠执行内存门：记录下来，由 violation 结构化停止，不静默跳过。
            owned_errors.append({"pid": getattr(proc, "pid", None), "error": f"{type(exc).__name__}: {exc}"[:300]})
    codex, scan = _unowned_codex_scan()
    vm = psutil.virtual_memory()
    rss_sum = sum(row["rss"] for row in process_rows)
    # task_rss 保留旧字段名，数值按 memory_metric 口径计；原始 RSS 和另记于 task_rss_sum。
    task_memory = sum(row.get("pss", row["rss"]) for row in process_rows) if metric == "pss" else rss_sum
    return {"at": time.time(), "processes": process_rows, "codex": codex, "unowned_scan": scan,
            "owned_monitor_errors": owned_errors,
            "memory_metric": metric, "task_rss_sum": rss_sum,
            "task_rss": task_memory, "available": vm.available,
            "total": vm.total, "swap_used": psutil.swap_memory().used,
            "process_count": len(process_rows)}


def violation(current: dict[str, Any], baseline: dict[str, Any], *, rss_limit: int,
              max_processes: int) -> str | None:
    if current.get("owned_monitor_errors"):
        return OWNED_MONITOR_FAILURE
    if any(row["rss"] >= 20 * 1024**3 for row in current["codex"]):
        return "codex_memory_fuse"
    if current["available"] < current["total"] * 0.03:
        return "system_memory_pressure"
    if current["task_rss"] >= rss_limit:
        return "task_memory_limit"
    if current["process_count"] > max_processes:
        return "process_count_limit"
    if current["swap_used"] - baseline["swap_used"] > 256 * 1024**2:
        return "swap_growth"
    return None


def stop_children(children: list[psutil.Process], deadline: float | None = None) -> None:
    # 仅终止本次包装进程的子树，不触碰模型服务器或用户应用。
    for proc in reversed(children):
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    remaining = 2 if deadline is None else max(0, min(1,(deadline-time.monotonic())*.5))
    _, alive = psutil.wait_procs(children, timeout=remaining)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if alive:
        psutil.wait_procs(alive, timeout=.5 if deadline is None else max(0,min(.5,deadline-time.monotonic())))


class OwnedDiscoveryError(RuntimeError):
    """本任务进程树无法可靠枚举（监控本身失败）。携带已核验的启动身份与已确认成员，供后备回收使用。"""

    def __init__(self, message: str, identity: dict[str, Any] | None = None,
                 members: list[psutil.Process] | None = None):
        super().__init__(message)
        self.identity = dict(identity or {})
        self.members = list(members or [])


def read_launch_identity(identity_path: Path, nonce: str) -> dict[str, Any]:
    """读取并核验 bounded_launch 写出的身份（nonce 与父进程 PID 必须是本次）；未发布时返回 {}。"""
    if not identity_path.exists():
        return {}
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if identity.get("nonce") != nonce or identity.get("parent_pid") != os.getpid():
        raise ValueError("bounded launch identity mismatch")
    return identity


def launched_members(identity_path: Path, nonce: str) -> tuple[dict[str, Any], list[psutil.Process]]:
    identity = read_launch_identity(identity_path, nonce)
    if not identity:
        return {}, []
    pid = identity["pid"]
    members: list[psutil.Process] = []
    try:
        root = psutil.Process(pid)
        if abs(root.create_time() - identity["created_at"]) > .001:
            raise ValueError("bounded launch PID was reused")
        members = [root]
        members += root.children(recursive=True)
    except psutil.NoSuchProcess:
        members = []
    except PROCESS_QUERY_ERRORS as exc:
        # 身份已核验：保留根进程（若已确认）交给后备回收，不把未知当空。
        raise OwnedDiscoveryError(f"children of {pid}: {type(exc).__name__}: {exc}"[:300], identity, members) from exc
    # 父命令退出后仍可能有继承 stdout 的孙进程；仅补收本次独立进程组。
    if os.name == "posix" and identity.get("process_group") == pid:
        by_pid = {p.pid: p for p in members}
        # 按 PID 列表逐个检查（不用 process_iter 迭代器）：单个非本任务进程的查询错误只跳过该进程；
        # 取不到 PID 列表本身则无法确认本任务进程树，抛出 OwnedDiscoveryError（带身份与已确认成员）。
        try:
            pids = psutil.pids()
        except PROCESS_QUERY_ERRORS as exc:
            raise OwnedDiscoveryError(f"pids: {type(exc).__name__}: {exc}"[:300], identity, members) from exc
        for other in pids:
            if other in by_pid:
                continue
            try:
                proc = psutil.Process(other)
                same_group = os.getpgid(proc.pid) == pid
                inherited_owner = (proc.create_time() >= identity['created_at']-.001
                    and nonce in proc.environ().get('PAPER_TRANSLATION_BOUNDED_OWNERS','').split(',')) if not same_group else False
                if same_group or inherited_owner:
                    by_pid[proc.pid] = proc
            except (ProcessLookupError, *PROCESS_QUERY_ERRORS):
                continue
        members = list(by_pid.values())
    return identity, members


# ---- 经过身份核验的回收（PR #19 第 8 轮） ----
IDENTITY_TOLERANCE = 0.01


def _identity_state(pid: int, created_at: float) -> tuple[str, psutil.Process | None]:
    """按 PID + create_time 判断原进程的状态：alive / zombie / dead / pid_reused / unknown。"""
    try:
        proc = psutil.Process(pid)
        born = proc.create_time()
    except psutil.NoSuchProcess:
        return "dead", None
    except PROCESS_QUERY_ERRORS:
        return "unknown", None
    if abs(born - created_at) > IDENTITY_TOLERANCE:
        return "pid_reused", None
    try:
        if proc.status() == psutil.STATUS_ZOMBIE:
            return "zombie", proc
    except psutil.NoSuchProcess:
        return "dead", None
    except PROCESS_QUERY_ERRORS:
        pass
    return "alive", proc


def _signal_pid(proc: psutil.Process, created_at: float, sig: int) -> None:
    """发信号前再核对一次 create_time，PID 已被复用则不发。"""
    if abs(proc.create_time() - created_at) > IDENTITY_TOLERANCE:
        raise psutil.NoSuchProcess(proc.pid, msg="pid reused before signal")
    proc.send_signal(sig)


def _signal_group(pgid: int, sig: int) -> None:
    os.killpg(pgid, sig)


def _group_empty(pgid: int) -> bool | None:
    """killpg(pgid, 0)：ESRCH 表示该进程组已没有任何进程；成功表示仍有成员；其它错误为未知。"""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return None
    return False


def _wait(predicate: Callable[[], bool], timeout: float) -> bool:
    end = time.monotonic() + max(0.0, timeout)
    while True:
        if predicate():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.02)


def reclaim_owned_tree(identity: dict[str, Any], known: dict[int, float], deadline: float | None = None,
                       *, discovery_failed: bool = False) -> dict[str, Any]:
    """回收本次启动的进程树，并独立核实结果（不依赖全机进程枚举）。
    1) 逐个已确认成员（PID + create_time）：核验身份后 SIGTERM，超时再 SIGKILL；
    2) 进程组（bounded_launch 以 setsid 新建会话/进程组，pgid == 根 PID）：
       - 组长 PID 存在且 create_time 相符：组是本次的，可整组发信号；
       - 组长 PID 已被另一进程复用：内核在进程组仍有成员时不会复用该 ID，原组必然已空，不发信号；
       - 组长已退出：先 killpg(pgid, 0) 探测，有成员时再核对一次组长 PID 仍未被复用，才整组发信号；
       - 组长状态无法查询：不发信号，记为未核实；
    3) 最后逐个核实：死亡（或僵尸、或 PID 已复用）记入 verified_dead，其余记入 unverified；
       进程组以 killpg(pgid, 0) == ESRCH 核实为空。unverified 非空即 confirmed=False。"""
    budget = 2.0 if deadline is None else max(0.5, min(2.0, deadline - time.monotonic()))
    targets = dict(known)
    if identity.get("pid") and identity.get("created_at") is not None:
        targets[int(identity["pid"])] = float(identity["created_at"])
    report: dict[str, Any] = {"status": "confirmed", "confirmed": True, "verified_dead": [], "unverified": [],
                              "alive_before": [], "signalled": [], "signal_errors": [],
                              "process_group": {"pgid": None, "leader": None, "signalled": [], "empty_verified": None},
                              "not_covered": []}

    def note_error(target: Any, sig: int, exc: BaseException) -> None:
        report["signal_errors"].append({"target": target, "signal": int(sig), "error": f"{type(exc).__name__}: {exc}"[:200]})

    def signal_members(sig: int) -> None:
        for pid, born in targets.items():
            state, proc = _identity_state(pid, born)
            if state != "alive" or proc is None:
                continue
            try:
                _signal_pid(proc, born, sig)
                report["signalled"].append({"pid": pid, "signal": int(sig)})
            except psutil.NoSuchProcess:
                continue
            except PROCESS_QUERY_ERRORS as exc:
                note_error(pid, sig, exc)

    def members_down() -> bool:
        return all(_identity_state(pid, born)[0] != "alive" for pid, born in targets.items())

    for pid, born in targets.items():
        if _identity_state(pid, born)[0] == "alive":
            report["alive_before"].append({"pid": pid, "created_at": born})

    group = report["process_group"]
    pgid = identity.get("process_group") if os.name == "posix" else None
    group_ok = bool(pgid) and pgid == identity.get("pid")
    if group_ok:
        group["pgid"] = pgid
        leader, _ = _identity_state(pgid, float(identity["created_at"]))
        group["leader"] = leader
        if leader == "pid_reused":
            group["empty_verified"] = True   # 内核规则：组仍有成员时其 ID 不会被分配给新进程
            group_ok = False
        elif leader == "unknown":
            group_ok = False
        else:
            occupied = _group_empty(pgid) is False
            if occupied and leader in ("dead",):
                # 组长已退出但组内仍有成员：再核对一次 PID 仍未被复用（复用即说明原组已空，探测到的是别人）
                again, _ = _identity_state(pgid, float(identity["created_at"]))
                if again == "pid_reused":
                    group["leader"] = "pid_reused"; group["empty_verified"] = True; group_ok = False; occupied = False
            if occupied:
                report["alive_before"].append({"pgid": pgid})

    def leader_reused() -> bool:
        # 每次整组发信号/核实前都重新核对组长 PID：被复用即说明原组已空，后续探测到的是别人的组。
        nonlocal group_ok
        if _identity_state(pgid, float(identity["created_at"]))[0] == "pid_reused":
            group["leader"], group["empty_verified"], group_ok = "pid_reused", True, False
            return True
        return False

    def signal_group(sig: int) -> None:
        if not group_ok or leader_reused():
            return
        empty = _group_empty(pgid)
        if empty:
            return
        try:
            _signal_group(pgid, sig)
            group["signalled"].append(int(sig))
        except ProcessLookupError:
            return
        except PROCESS_QUERY_ERRORS as exc:
            note_error({"pgid": pgid}, sig, exc)

    def all_down() -> bool:
        return members_down() and (not group_ok or leader_reused() or _group_empty(pgid) is not False)

    signal_members(signal.SIGTERM if os.name == "posix" else signal.SIGTERM)
    signal_group(signal.SIGTERM)
    if not _wait(all_down, budget * 0.5):
        kill = signal.SIGKILL if os.name == "posix" else signal.SIGTERM
        signal_members(kill)
        signal_group(kill)
        _wait(all_down, budget * 0.5)

    for pid, born in targets.items():
        state, _ = _identity_state(pid, born)
        if state in ("dead", "zombie", "pid_reused"):
            report["verified_dead"].append({"pid": pid, "created_at": born, "evidence": state})
        else:
            report["unverified"].append({"pid": pid, "created_at": born, "reason": "still_alive" if state == "alive" else "state_unknown"})
    if group_ok and not leader_reused():
        empty = _group_empty(pgid)
        group["empty_verified"] = empty is True
        if empty is not True:
            report["unverified"].append({"pgid": pgid, "reason": "group_not_empty" if empty is False else "group_state_unknown"})
    elif group.get("pgid") and group.get("leader") == "unknown":
        report["unverified"].append({"pgid": pgid, "reason": "group_leader_identity_unverifiable"})
    elif identity and not group.get("pgid"):
        if discovery_failed:
            report["unverified"].append({"reason": "no_process_group_and_descendants_unenumerable"})
        report["process_group"]["reason"] = "launcher did not create a process group"
    if discovery_failed:
        report["not_covered"].append("processes that left the launch process group (setsid/setpgid) can only be found by "
                                     "full PID enumeration, which failed")
    if report["unverified"]:
        report["status"], report["confirmed"] = "unconfirmed", False
    return report


def run_bounded(argv: list[str], *, cwd: Path, receipt_dir: Path, operation: str,
                timeout_seconds: float = 300, interval_seconds: float = 2,
                rss_limit: int | None = None, max_processes: int = 32,
                env: dict[str, str] | None = None,
                cancel_event: threading.Event | None = None,
                observer: Callable[[], dict[str, Any]] = snapshot,
                deadline_monotonic: float | None = None,
                cleanup_reserve_seconds: float | None = None,
                memory_metric: str = "rss",
                max_total_fraction: float = 0.25) -> dict[str, Any]:
    start = time.monotonic()
    if not 0 < interval_seconds <= 30 or not 0 < timeout_seconds <= 7200 or (rss_limit is not None and rss_limit <= 0) or max_processes < 1 or not re.fullmatch(r"[A-Za-z0-9_.-]+", operation):
        raise ValueError("bounded timeout, interval, RSS and process limits required")
    receipt_dir = receipt_dir.resolve()
    receipt_dir.mkdir(parents=True, exist_ok=True)
    monitor_path = receipt_dir / f"{operation}.resource.jsonl"
    # 重复 attempt 必须使用新目录，不能覆盖旧收据。
    stream = monitor_path.open("x", encoding="utf-8")
    if memory_metric not in ("rss", "pss") or not 0 < max_total_fraction <= 0.5:
        stream.close()
        raise ValueError("memory metric must be rss or pss and host fraction within (0, 0.5]")
    default_observer = observer is snapshot
    observe = (lambda members=None: snapshot(members, metric=memory_metric)) if default_observer else (lambda members=None: observer())
    try:
        baseline = observe([])
    except Exception as exc:  # 基线都取不到：不启动任务，结构化停止
        stream.write(json.dumps({"at": time.time(), "monitor_error": f"{type(exc).__name__}: {exc}"[:300]}) + "\n")
        stream.close()
        return _monitor_unavailable_outcome(receipt_dir, operation, monitor_path, start, memory_metric, rss_limit, exc)
    rss_limit = min(8 * 1024**3, int(baseline["total"] * .20)) if rss_limit is None else rss_limit
    if rss_limit > baseline["total"] * max_total_fraction or rss_limit > 50 * 1024**3:
        stream.close()
        raise ValueError(f"resource limit exceeds project authorization threshold: {rss_limit} bytes > "
                         f"{max_total_fraction:.0%} of physical memory {baseline['total']} bytes")
    peak = {"task": 0, "rss_sum": 0}

    def record(sample: dict[str, Any]) -> None:
        peak["task"] = max(peak["task"], int(sample.get("task_rss", 0)))
        peak["rss_sum"] = max(peak["rss_sum"], int(sample.get("task_rss_sum", sample.get("task_rss", 0))))
    # 基线与收尾样本同样计入峰值；否则短于一个采样间隔的作业峰值会记为 0。
    record(baseline)
    deadline = min(start+timeout_seconds,deadline_monotonic) if deadline_monotonic is not None else start+timeout_seconds
    reserve = min(5,max(.1,timeout_seconds*.35)) if cleanup_reserve_seconds is None else cleanup_reserve_seconds
    if reserve <= 0 or reserve >= deadline-start:
        stream.close();raise ValueError('positive cleanup reservation within whole job budget required')
    work_deadline = deadline-reserve
    result: dict[str, Any] = {}
    done = threading.Event()
    identity_path = receipt_dir / f"{operation}.launch.json"
    nonce = uuid.uuid4().hex
    task_env = dict(os.environ if env is None else env)
    inherited = task_env.get('PAPER_TRANSLATION_BOUNDED_OWNERS','')
    task_env['PAPER_TRANSLATION_BOUNDED_OWNERS'] = ','.join(filter(None,[inherited,nonce]))
    launch_command = [sys.executable, str(Path(__file__).with_name("bounded_launch.py")), str(identity_path), nonce, *argv]

    def execute():
        try:
            result["command"] = run_command(launch_command, operation=operation, cwd=cwd, env=task_env,
                                            timeout_seconds=max(.1,deadline-time.monotonic()+1), receipt_dir=receipt_dir)
        except Exception as exc:
            result["exception"] = type(exc).__name__
            # 收据保留真实错误消息（脱敏、截断），不再只剩异常类型名。
            result["exception_message"] = _redact_text(str(exc))[:500]
        finally:
            done.set()

    trigger = violation(baseline, baseline, rss_limit=rss_limit, max_processes=max_processes)
    if cancel_event and cancel_event.is_set():
        trigger = trigger or "cancelled"
    monitor_error: dict[str, Any] = {}
    children: dict[int, psutil.Process] = {}

    identities: dict[int,float] = {}
    launch_identity: dict[str, Any] = {}

    def remember(members: list[psutil.Process]) -> None:
        for proc in members:
            children[proc.pid] = proc
            try:
                identities.setdefault(proc.pid, proc.create_time())
            except PROCESS_QUERY_ERRORS:
                pass

    def discover() -> tuple[dict[str, Any], list[psutil.Process]]:
        # 本任务进程树枚举失败：保留已核验的启动身份与已确认成员（后备回收用），并记为监控失败（结构化停止）。
        try:
            identity, members = launched_members(identity_path, nonce)
        except OwnedDiscoveryError as exc:
            monitor_error.setdefault("detail", str(exc))
            monitor_error["owned_discovery_failed"] = True
            identity, members = exc.identity, exc.members
            if identity:
                launch_identity.update(identity)
                identities.setdefault(int(identity["pid"]), float(identity["created_at"]))
            remember(members)
            return identity, list(children.values())
        if identity:
            launch_identity.update(identity)
            identities.setdefault(int(identity["pid"]), float(identity["created_at"]))
        remember(members)
        return identity, members

    def reclaim() -> dict[str, Any]:
        return reclaim_owned_tree(launch_identity, identities, deadline,
                                  discovery_failed=bool(monitor_error.get("owned_discovery_failed")))
    cleanup_passes: list[dict[str, Any]] = []
    worker = None
    try:
        stream.write(json.dumps(baseline) + "\n"); stream.flush()
        if not trigger:
            worker = threading.Thread(target=execute, daemon=True)
            worker.start()
            # 启动后尽快采第一次样（50 ms），之后按 interval 采样，避免快作业完全漏采。
            wait = min(.05, interval_seconds)
            while not done.wait(max(.001,min(wait,max(0,work_deadline-time.monotonic())))):
                wait = interval_seconds
                identity, members = discover()
                try:
                    current = observe(members)
                except Exception as exc:
                    # 监控本身失败：不能继续无监控运行，按资源门同样的路径停止并清理本任务进程树。
                    monitor_error["detail"] = f"{type(exc).__name__}: {exc}"[:300]
                    stream.write(json.dumps({"at": time.time(), "monitor_error": monitor_error["detail"]}) + "\n")
                    stream.flush()
                    current = None
                    trigger = MONITOR_FAILURE
                if current is not None:
                    record(current)
                    stream.write(json.dumps(current) + "\n"); stream.flush()
                    trigger = violation(current, baseline, rss_limit=rss_limit, max_processes=max_processes)
                if monitor_error.get("owned_discovery_failed"):
                    trigger = trigger or OWNED_MONITOR_FAILURE
                if time.monotonic() >= work_deadline:
                    trigger = trigger or "task_timeout"
                if cancel_event and cancel_event.is_set():
                    trigger = trigger or "cancelled"
                if trigger:
                    identity_path.with_suffix(".cancel").touch(exist_ok=False)
                    if not identity and not done.is_set():
                        for _ in range(40):
                            if done.wait(.05):
                                break
                            identity, members = discover()
                            if identity:
                                break
                    cleanup_passes.append(reclaim())
                    done.wait(max(0,min(1,deadline-time.monotonic())))
                    break
            discover()
            # 成功或异常退出均回收本次身份链中的残留（已确认成员 + 经核验的进程组），不能留下孤儿继续写。
            final_cleanup = reclaim()
            cleanup_passes.append(final_cleanup)
            if final_cleanup["alive_before"]:
                trigger = trigger or 'owned_descendants_after_command'
                done.wait(max(0,min(1,deadline-time.monotonic())))
            _, members = discover()
            try:
                final = observe(members)
            except Exception as exc:
                monitor_error["detail"] = monitor_error.get("detail") or f"{type(exc).__name__}: {exc}"[:300]
                stream.write(json.dumps({"at": time.time(), "monitor_error": monitor_error["detail"]}) + "\n")
                final = None
                trigger = trigger or MONITOR_FAILURE
            if final is not None:
                record(final)
                stream.write(json.dumps(final) + "\n"); stream.flush()
                trigger = trigger or violation(final, baseline, rss_limit=rss_limit, max_processes=max_processes)
            if monitor_error.get("owned_discovery_failed"):
                trigger = trigger or OWNED_MONITOR_FAILURE
    finally:
        stream.close()
    command = result.get("command")
    # 最终核实（独立于前面的回收过程）：任务未启动时没有身份也没有成员，核实结果为空且已确认。
    cleanup = reclaim() if (launch_identity or identities) else {
        "status": "confirmed", "confirmed": True, "verified_dead": [], "unverified": [], "alive_before": [],
        "signalled": [], "signal_errors": [], "not_covered": [],
        "process_group": {"pgid": None, "leader": None, "signalled": [], "empty_verified": None,
                          "reason": "task never published a launch identity"}}
    cleanup["passes"] = len(cleanup_passes) + 1
    # 汇总所有回收轮次：signalled/process_group.signalled/alive_before/signal_errors 是整次运行的记录，
    # verified_dead/unverified/empty_verified 是最后一次独立核实的结果。
    for key in ("signalled", "alive_before", "signal_errors"):
        cleanup[key] = [row for p in cleanup_passes for row in p[key]] + cleanup[key]
    cleanup["process_group"]["signalled"] = ([sig for p in cleanup_passes for sig in p["process_group"]["signalled"]]
                                             + cleanup["process_group"]["signalled"])
    alive = [{"pid": row["pid"], "created_at": row["created_at"]} for row in cleanup["unverified"] if row.get("reason") == "still_alive"]
    elapsed=time.monotonic()-start
    if not cleanup["confirmed"]:trigger=trigger or 'owned_tree_cleanup_incomplete'
    if time.monotonic()>deadline:trigger=trigger or 'whole_job_deadline_exceeded'
    status = ("cleanup_unconfirmed" if not cleanup["confirmed"] else
              "stopped" if trigger else "succeeded" if command and command.success else "failed")
    outcome = {"status": status,
               "stop_reason": trigger, "operation": operation, "elapsed_seconds": elapsed,
               "whole_job_budget_seconds":deadline-start,"cleanup_reserve_seconds":reserve,
               "deadline_met":time.monotonic()<=deadline,"owned_tree_alive":alive,
               "observed_owned_identities":[{'pid':pid,'created_at':born}for pid,born in identities.items()],
               "resource_receipt": str(monitor_path), "command": command.as_dict() if command else None,
               "launch_receipt": str(identity_path) if identity_path.exists() else None,
               "rss_limit_bytes": rss_limit,
               "memory_metric": memory_metric,
               "peak_task_memory_bytes": peak["task"],
               "peak_task_rss_sum_bytes": peak["rss_sum"],
               "exception": result.get("exception"),
               "exception_message": result.get("exception_message"),
               "monitor_error": monitor_error.get("detail"),
               "launch_identity": {k: launch_identity.get(k) for k in ("pid", "created_at", "process_group")} if launch_identity else None,
               "cleanup": cleanup}
    if trigger or result.get("exception") or not cleanup["confirmed"]:
        outcome["failure_receipt"] = write_failure_receipt(
            receipt_dir=receipt_dir, operation=operation, domain="resource",
            failure_code=("owned_tree_cleanup_unconfirmed" if not cleanup["confirmed"] else trigger or "execution_exception"),
            retryable=False,
            detail=(f"{trigger}: {monitor_error['detail']}" if trigger and monitor_error.get("detail") else trigger) or ": ".join(filter(None, [result.get("exception"), result.get("exception_message")])),
            metadata={"resource_receipt": str(monitor_path), "memory_metric": memory_metric,
                      "rss_limit_bytes": rss_limit, "peak_task_memory_bytes": peak["task"],
                      "stop_reason": trigger, "cleanup": cleanup, "launch_identity": outcome["launch_identity"]})
    return outcome


def _monitor_unavailable_outcome(receipt_dir: Path, operation: str, monitor_path: Path, start: float,
                                 memory_metric: str, rss_limit: int | None, exc: BaseException) -> dict[str, Any]:
    detail = f"{type(exc).__name__}: {exc}"[:300]
    outcome = {"status": "stopped", "stop_reason": MONITOR_FAILURE, "operation": operation,
               "elapsed_seconds": time.monotonic() - start, "owned_tree_alive": [],
               "observed_owned_identities": [], "resource_receipt": str(monitor_path), "command": None,
               "launch_receipt": None, "rss_limit_bytes": rss_limit, "memory_metric": memory_metric,
               "peak_task_memory_bytes": 0, "peak_task_rss_sum_bytes": 0, "exception": None,
               "exception_message": None, "monitor_error": detail, "launch_identity": None,
               "cleanup": {"status": "confirmed", "confirmed": True, "verified_dead": [], "unverified": [],
                           "alive_before": [], "signalled": [], "signal_errors": [], "not_covered": [],
                           "process_group": {"pgid": None, "leader": None, "signalled": [], "empty_verified": None,
                                             "reason": "task not launched (baseline monitor failure)"}}}
    outcome["failure_receipt"] = write_failure_receipt(
        receipt_dir=receipt_dir, operation=operation, domain="resource", failure_code=MONITOR_FAILURE,
        retryable=False, detail=f"{MONITOR_FAILURE}: {detail}",
        metadata={"resource_receipt": str(monitor_path), "memory_metric": memory_metric})
    return outcome
