"""使用共享执行边界运行单个有界任务，同时观察自身、子进程和 Codex 内存。"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import psutil
from daily_skill_research.execution import _redact_text, run_command, write_failure_receipt


def _process_memory(proc: psutil.Process, metric: str) -> dict[str, Any]:
    rss = proc.memory_info().rss
    row = {"pid": proc.pid, "rss": rss, "name": proc.name()}
    if metric == "pss":
        # PSS 按共享页比例分摊；fork 出的后端子进程不再重复计入父进程共享页。
        try:
            row["pss"] = getattr(proc.memory_full_info(), "pss", rss)
        except (psutil.AccessDenied, OSError, AttributeError):
            row["pss"] = rss
    return row


def snapshot(members: list[psutil.Process] | None = None, *, metric: str = "rss") -> dict[str, Any]:
    if metric not in ("rss", "pss"):
        raise ValueError("memory metric must be rss or pss")
    own = psutil.Process()
    children = own.children(recursive=True) if members is None else members
    process_rows = []
    for proc in [own, *children]:
        try:
            process_rows.append(_process_memory(proc, metric))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    codex = []
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            name = (proc.info["name"] or "").lower()
            if "codex" in name or "node_repl" in name:
                codex.append({"pid": proc.pid, "rss": proc.info["memory_info"].rss, "name": proc.info["name"]})
        except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
            continue
    vm = psutil.virtual_memory()
    rss_sum = sum(row["rss"] for row in process_rows)
    # task_rss 保留旧字段名，数值按 memory_metric 口径计；原始 RSS 和另记于 task_rss_sum。
    task_memory = sum(row.get("pss", row["rss"]) for row in process_rows) if metric == "pss" else rss_sum
    return {"at": time.time(), "processes": process_rows, "codex": codex,
            "memory_metric": metric, "task_rss_sum": rss_sum,
            "task_rss": task_memory, "available": vm.available,
            "total": vm.total, "swap_used": psutil.swap_memory().used,
            "process_count": len(process_rows)}


def violation(current: dict[str, Any], baseline: dict[str, Any], *, rss_limit: int,
              max_processes: int) -> str | None:
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


def launched_members(identity_path: Path, nonce: str) -> tuple[dict[str, Any], list[psutil.Process]]:
    if not identity_path.exists():
        return {}, []
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    if identity.get("nonce") != nonce or identity.get("parent_pid") != os.getpid():
        raise ValueError("bounded launch identity mismatch")
    pid = identity["pid"]
    try:
        root = psutil.Process(pid)
        if abs(root.create_time() - identity["created_at"]) > .001:
            raise ValueError("bounded launch PID was reused")
        members = [root, *root.children(recursive=True)]
    except psutil.NoSuchProcess:
        members = []
    # 父命令退出后仍可能有继承 stdout 的孙进程；仅补收本次独立进程组。
    if os.name == "posix" and identity.get("process_group") == pid:
        by_pid = {p.pid: p for p in members}
        for proc in psutil.process_iter():
            try:
                same_group = os.getpgid(proc.pid) == pid
                inherited_owner = (proc.create_time() >= identity['created_at']-.001
                    and nonce in proc.environ().get('PAPER_TRANSLATION_BOUNDED_OWNERS','').split(',')) if not same_group else False
                if same_group or inherited_owner:
                    by_pid[proc.pid] = proc
            except (ProcessLookupError, PermissionError, psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        members = list(by_pid.values())
    return identity, members


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
    baseline = observe([])
    rss_limit = min(8 * 1024**3, int(baseline["total"] * .20)) if rss_limit is None else rss_limit
    if rss_limit > baseline["total"] * max_total_fraction or rss_limit > 50 * 1024**3:
        stream.close()
        raise ValueError(f"resource limit exceeds project authorization threshold: {rss_limit} bytes > "
                         f"{max_total_fraction:.0%} of physical memory {baseline['total']} bytes")
    peak = {"task": 0, "rss_sum": 0}

    def record(sample: dict[str, Any]) -> None:
        peak["task"] = max(peak["task"], int(sample.get("task_rss", 0)))
        peak["rss_sum"] = max(peak["rss_sum"], int(sample.get("task_rss_sum", sample.get("task_rss", 0))))
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
    children: dict[int, psutil.Process] = {}
    identities: dict[int,float] = {}
    worker = None
    try:
        stream.write(json.dumps(baseline) + "\n"); stream.flush()
        if not trigger:
            worker = threading.Thread(target=execute, daemon=True)
            worker.start()
            while not done.wait(max(.001,min(interval_seconds,max(0,work_deadline-time.monotonic())))):
                identity, members = launched_members(identity_path, nonce)
                for proc in members:
                    children[proc.pid] = proc
                    try:identities[proc.pid]=proc.create_time()
                    except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                current = observe(members)
                record(current)
                stream.write(json.dumps(current) + "\n"); stream.flush()
                trigger = violation(current, baseline, rss_limit=rss_limit, max_processes=max_processes)
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
                            identity, members = launched_members(identity_path, nonce)
                            if identity:
                                children.update({p.pid: p for p in members})
                                break
                    stop_children(list(children.values()),deadline)
                    done.wait(max(0,min(1,deadline-time.monotonic())))
                    break
            _, members = launched_members(identity_path, nonce)
            # 成功或异常退出均回收本次身份链中的残留，不能留下孤儿继续写。
            children.update({p.pid:p for p in members})
            live=[]
            for proc in children.values():
                try:
                    if proc.is_running() and proc.status()!=psutil.STATUS_ZOMBIE:live.append(proc)
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            if live:
                trigger = trigger or 'owned_descendants_after_command'
                stop_children(live,deadline)
                done.wait(max(0,min(1,deadline-time.monotonic())))
            _, members = launched_members(identity_path,nonce)
            final = observe(members)
            stream.write(json.dumps(final) + "\n"); stream.flush()
            trigger = trigger or violation(final, baseline, rss_limit=rss_limit, max_processes=max_processes)
    finally:
        stream.close()
    command = result.get("command")
    alive=[]
    for proc in children.values():
        try:
            if proc.is_running() and proc.status()!=psutil.STATUS_ZOMBIE:alive.append({'pid':proc.pid,'created_at':proc.create_time()})
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    elapsed=time.monotonic()-start
    if alive:trigger=trigger or 'owned_tree_cleanup_incomplete'
    if time.monotonic()>deadline:trigger=trigger or 'whole_job_deadline_exceeded'
    outcome = {"status": "stopped" if trigger else "succeeded" if command and command.success else "failed",
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
               "exception_message": result.get("exception_message")}
    if trigger or result.get("exception"):
        outcome["failure_receipt"] = write_failure_receipt(
            receipt_dir=receipt_dir, operation=operation, domain="resource",
            failure_code=trigger or "execution_exception", retryable=False,
            detail=trigger or ": ".join(filter(None, [result.get("exception"), result.get("exception_message")])),
            metadata={"resource_receipt": str(monitor_path), "memory_metric": memory_metric,
                      "rss_limit_bytes": rss_limit, "peak_task_memory_bytes": peak["task"]})
    return outcome
