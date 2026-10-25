# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-25：长文档共用一个已加载的翻译进程；变更见 Skill 根目录 MODIFICATIONS.md。
"""长文档的电子块共用一个翻译进程，版面模型只加载一次。

编排进程拉起本模块的 ``--serve``。每一块把本来要交给 ``pdf2zh_next_vendor.py`` 的命令
发到本机套接字上，由这个进程在内部执行。块与块之间进程不退出，已加载的版面模型留着。

某一块碰到时间上限时，那一块的连接断开，本进程随之退出，避免超时的工作还占着模型。
下一块由编排进程再拉起一个新进程，只重新加载一次。父进程先退出时，本进程也会退出。

套接字上的请求带有这一块的后端环境（含凭据）。凭据不写入本进程的日志，也不进入命令行。
本进程不登记进块的 launch 回执，尝试后的进程树回收不会把它当成某一块泄漏的子进程。
"""
from __future__ import annotations

import io
import json
import logging
import os
import queue
import select
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Callable, TextIO

from credential_env import BACKEND_ENV_STRIP

SESSION_ENV = "PDF_TRANSLATION_BACKEND_SESSION"
REUSE_LAYOUT_ENV = "PDF_TRANSLATION_REUSE_LAYOUT"
# 只把翻译这一块真正要用的变量送进长寿命进程。启动 nonce 不在其中，
# 尝试后的回收扫描就不会把这个进程当成某一块还活着。
SESSION_ENV_KEYS = (
    "HOME",
    "XDG_CACHE_HOME",
    "HF_HOME",
    "UV_CACHE_DIR",
    "PYTHONUNBUFFERED",
    "PDF2ZH_OPENAI_API_KEY",
    "PDF_TRANSLATION_THINKING",
    "DOUBLE6_OVERFLOW_FALLBACK_DOCUMENT_CAP",
    "PAPER_TRANSLATION_ENGINE_HOME",
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
)
_CREDENTIAL_KEYS = (*BACKEND_ENV_STRIP, "GLM_API_KEY")
_MAX_REQUEST_BYTES = 8_000_000
Handler = Callable[[dict[str, Any]], tuple[int, str]]


def vendored_pdf2zh_command(command: list[str]) -> bool:
    return len(command) >= 2 and Path(command[1]).name == "pdf2zh_next_vendor.py"


def session_env(env: dict[str, str]) -> dict[str, str]:
    picked: dict[str, str] = {}
    for key in SESSION_ENV_KEYS:
        value = env.get(key)
        if isinstance(value, str) and value != "":
            picked[key] = value
    return picked


def apply_job_env(env: dict[str, str]) -> None:
    """用这一块的环境盖住上一块留下的同名变量，并强制留住已加载的版面模型。"""
    filtered = session_env(env)
    for key in SESSION_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.pop("PAPER_TRANSLATION_BOUNDED_OWNERS", None)
    for key, value in filtered.items():
        os.environ[key] = value
    os.environ[REUSE_LAYOUT_ENV] = "1"


def clear_job_credentials() -> None:
    for key in _CREDENTIAL_KEYS:
        os.environ.pop(key, None)


def install_vendor_paths() -> None:
    """把内置后端加进搜索路径。这里不导入翻译模块，空闲进程不加载版面模型。"""
    skill_root = Path(__file__).resolve().parents[1]
    vendor_root = skill_root / "vendor" / "pdfmathtranslate_next"
    babeldoc_root = skill_root / "vendor" / "babeldoc"
    if not (vendor_root / "pdf2zh_next").exists():
        raise RuntimeError("vendored PDFMathTranslate-next backend missing")
    if not (babeldoc_root / "babeldoc").exists():
        raise RuntimeError("vendored BabelDOC backend missing")
    os.environ["PAPER_TRANSLATION_BABELDOC_VENDOR"] = str(babeldoc_root)
    for folder in (str(babeldoc_root), str(vendor_root)):
        if folder not in sys.path:
            sys.path.insert(0, folder)


def _reset_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass


class _QueueStream:
    """翻译日志按行送回这一块，不把凭据环境写进本进程自己的输出。"""

    encoding = "utf-8"

    def __init__(self, sink: queue.Queue[str]) -> None:
        self.sink = sink
        self._pending = ""

    def fileno(self) -> int:
        raise io.UnsupportedOperation("fileno")

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self.sink.put(line)
        return len(text)

    def flush(self) -> None:
        if self._pending:
            self.sink.put(self._pending)
            self._pending = ""

    def isatty(self) -> bool:
        return False


def run_vendored_pdf2zh(job: dict[str, Any]) -> tuple[int, str]:
    """在当前进程里跑一次内置 pdf2zh。搜索路径要先就绪，所以导入放在函数内。"""
    install_vendor_paths()
    apply_job_env(job.get("env") or {})
    argv = list(job.get("argv") or [])
    if len(argv) < 2:
        return 2, "backend session: missing argv"
    sys.argv = [argv[1], *argv[2:]]
    cwd = job.get("cwd")
    if isinstance(cwd, str) and cwd:
        os.chdir(cwd)
    sink = job.get("_log_stream")
    buffer: io.StringIO | None
    if isinstance(sink, queue.Queue):
        stream: Any = _QueueStream(sink)
        buffer = None
    else:
        buffer = io.StringIO()
        stream = buffer
    _reset_logging()
    stdout, stderr = sys.stdout, sys.stderr
    sys.stdout = stream
    sys.stderr = stream
    try:
        import asyncio

        # 内置后端不在默认搜索路径上，必须等 install_vendor_paths 之后再导入。
        from pdf2zh_next.main import main as pdf2zh_main

        try:
            code = asyncio.run(pdf2zh_main())
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        return int(code or 0), "" if buffer is None else buffer.getvalue()
    except Exception:
        extra = traceback.format_exc()
        if buffer is not None:
            extra = buffer.getvalue() + extra
        return 1, extra
    finally:
        sys.stdout = stdout
        sys.stderr = stderr
        clear_job_credentials()


def _send(conn: socket.socket, payload: dict[str, Any]) -> None:
    conn.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))


def _readline(conn: socket.socket, deadline: float | None) -> bytes | None:
    chunks = bytearray()
    while b"\n" not in chunks:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            conn.settimeout(min(remaining, 30))
        else:
            conn.settimeout(30)
        try:
            piece = conn.recv(65536)
        except socket.timeout as exc:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError from exc
            continue
        if not piece:
            return None
        chunks.extend(piece)
        if len(chunks) > _MAX_REQUEST_BYTES:
            raise ValueError("backend session request too large")
    line, _, _rest = bytes(chunks).partition(b"\n")
    return line


def _client_gone(conn: socket.socket) -> bool:
    readable, _, _ = select.select([conn], [], [], 0)
    if not readable:
        return False
    try:
        peeked = conn.recv(1, socket.MSG_PEEK)
    except OSError:
        return True
    return peeked == b""


def serve(
    address: str,
    handler: Handler,
    *,
    stop: threading.Event | None = None,
    abandon: Callable[[], None] | None = None,
) -> None:
    """一次只做一块。客户端断开或父进程没了，调用 abandon（默认直接退出）。"""
    if stop is None:
        stop = threading.Event()
    if abandon is None:
        def abandon() -> None:
            try:
                os.unlink(address)
            except OSError:
                pass
            os._exit(0)
    if os.path.exists(address):
        os.unlink(address)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(address)
    os.chmod(address, 0o600)
    server.listen(4)
    server.settimeout(0.5)
    parent = os.getppid()
    try:
        while not stop.is_set():
            if os.getppid() != parent:
                abandon()
                return
            try:
                conn, _addr = server.accept()
            except socket.timeout:
                continue
            try:
                _handle(conn, handler, parent, abandon)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
    finally:
        try:
            server.close()
        except OSError:
            pass


def _emit_log(conn: socket.socket, line: str, abandon: Callable[[], None]) -> bool:
    try:
        _send(conn, {"type": "log", "line": line})
    except OSError:
        abandon()
        return False
    return True


def _handle(conn: socket.socket, handler: Handler, parent: int, abandon: Callable[[], None]) -> None:
    try:
        raw = _readline(conn, time.monotonic() + 30)
    except (TimeoutError, OSError, ValueError):
        return
    if raw is None:
        return
    try:
        job = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        _emit_log(conn, "backend session: bad request", abandon)
        return
    if not isinstance(job, dict):
        return
    if job.get("cmd") == "ping":
        try:
            _send(conn, {"type": "result", "returncode": 0, "pong": True, "pid": os.getpid()})
        except OSError:
            pass
        return
    apply_job_env(job.get("env") or {})
    log_queue: queue.Queue[str] = queue.Queue()
    job["_log_stream"] = log_queue
    done = threading.Event()
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["value"] = handler(job)
        except Exception:
            box["error"] = traceback.format_exc()
        finally:
            done.set()

    threading.Thread(target=run, name="backend-session-job", daemon=True).start()
    while not done.is_set() or not log_queue.empty():
        if os.getppid() != parent or _client_gone(conn):
            abandon()
            return
        try:
            line = log_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        if not _emit_log(conn, line, abandon):
            return
    if "error" in box:
        code, extra = 1, str(box["error"])
    else:
        value = box.get("value")
        if not isinstance(value, tuple) or len(value) != 2:
            code, extra = 1, "backend session: bad handler result"
        else:
            code, extra = int(value[0]), str(value[1] or "")
    for line in extra.splitlines():
        if not _emit_log(conn, line, abandon):
            return
    try:
        _send(conn, {"type": "result", "returncode": int(code), "pid": os.getpid()})
    except OSError:
        abandon()


def _ping(address: str, timeout: float = 2.0) -> bool:
    try:
        code = _exchange(address, {"cmd": "ping"}, timeout, log=None)
    except OSError:
        return False
    return code == 0


def _read_available_line(conn: socket.socket, pending: bytearray, deadline: float | None) -> bytes | None:
    """一次读到的多行要留住。丢掉行尾后面的内容会把结果和日志一起吞掉。"""
    while b"\n" not in pending:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            conn.settimeout(min(remaining, 30))
        else:
            conn.settimeout(30)
        try:
            piece = conn.recv(65536)
        except socket.timeout as exc:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError from exc
            continue
        if not piece:
            return None
        pending.extend(piece)
        if len(pending) > _MAX_REQUEST_BYTES:
            raise ValueError("backend session response too large")
    line, _, rest = bytes(pending).partition(b"\n")
    pending[:] = rest
    return line


def _exchange(address: str, payload: dict[str, Any], timeout: float | None, log: TextIO | None) -> int | None:
    """发出请求之前连不上，返回 None。已经发出之后失败，返回非 0，避免同一块再翻译一遍。"""
    deadline = None if timeout is None else time.monotonic() + timeout
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    pending = bytearray()
    sent = False
    try:
        if deadline is not None:
            sock.settimeout(max(0.1, deadline - time.monotonic()))
        sock.connect(address)
        if log is not None and payload.get("cmd") != "ping":
            log.write("BACKEND_SESSION: reused\n")
            log.flush()
        sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        sent = True
        while True:
            raw = _read_available_line(sock, pending, deadline)
            if raw is None:
                return 1
            try:
                message = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return 1
            if not isinstance(message, dict):
                continue
            if message.get("type") == "log" and log is not None:
                log.write(str(message.get("line", "")) + "\n")
                log.flush()
            elif message.get("type") == "result":
                if log is not None and message.get("pid") is not None:
                    log.write(f"BACKEND_SESSION: pid {message['pid']}\n")
                    log.flush()
                return int(message.get("returncode", 1))
    except TimeoutError:
        return 124
    except OSError:
        return 1 if sent else None
    except ValueError:
        return 1 if sent else None
    finally:
        try:
            sock.close()
        except OSError:
            pass


def invoke_backend_session(
    command: list[str],
    *,
    cwd: str | os.PathLike[str],
    env: dict[str, str],
    timeout: float | None,
    log: TextIO | None,
) -> int | None:
    """把这一块交给已经加载好的进程。没有会话、或套接字还没就绪时返回 None，调用方照旧冷启动。

    请求已经发出之后连接断了，返回非 0，不再另起一个进程把同一块翻译第二遍。
    超过 timeout 返回 124，并断开连接，让那个进程退出。
    """
    address = os.environ.get(SESSION_ENV)
    if not address or not vendored_pdf2zh_command(command):
        return None
    if not os.path.exists(address):
        return None
    payload = {"argv": command, "cwd": str(cwd), "env": session_env(env)}
    try:
        return _exchange(address, payload, timeout, log)
    except TimeoutError:
        return 124


class BackendSession:
    """编排进程持有的那一个翻译进程。"""

    def __init__(self, proc: subprocess.Popen[bytes], address: str, log_handle: BinaryIO, directory: Path) -> None:
        self.proc = proc
        self.address = address
        self.log_handle = log_handle
        self.directory = directory

    @classmethod
    def start(cls, directory: Path) -> BackendSession:
        directory.mkdir(parents=True, exist_ok=True)
        address = f"/tmp/d6bs-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
        log_path = directory / "backend-session.log"
        log_handle = open(log_path, "ab", buffering=0)
        env = os.environ.copy()
        for key in (*_CREDENTIAL_KEYS, "PAPER_TRANSLATION_BOUNDED_OWNERS"):
            env.pop(key, None)
        env["PYTHONUNBUFFERED"] = "1"
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            env[key] = "1"
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--serve", address],
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            cwd=str(directory),
        )
        deadline = time.monotonic() + 15
        ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            if os.path.exists(address) and _ping(address):
                ready = True
                break
            time.sleep(0.05)
        if not ready:
            if proc.poll() is None:
                proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            log_handle.close()
            try:
                os.unlink(address)
            except OSError:
                pass
            raise RuntimeError("backend session did not become ready")
        os.environ[SESSION_ENV] = address
        return cls(proc, address, log_handle, directory)

    def ensure(self) -> None:
        """上一块如果把进程带走了，这里重新拉起。健康的进程直接复用。"""
        if self.proc.poll() is None and os.path.exists(self.address) and _ping(self.address, timeout=1.0):
            os.environ[SESSION_ENV] = self.address
            return
        self._stop_process()
        os.environ.pop(SESSION_ENV, None)
        fresh = BackendSession.start(self.directory)
        self.proc = fresh.proc
        self.address = fresh.address
        self._close_log()
        self.log_handle = fresh.log_handle

    def close(self) -> None:
        self._stop_process()
        self._close_log()
        os.environ.pop(SESSION_ENV, None)

    def _stop_process(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        if self.address:
            try:
                os.unlink(self.address)
            except OSError:
                pass

    def _close_log(self) -> None:
        try:
            self.log_handle.close()
        except OSError:
            pass


def open_document_backend(directory: Path, route: str) -> BackendSession | None:
    """电子长文档启动一次翻译进程。纯扫描不启动。起不来就按原来的方式，每块单独启动。"""
    if route == "scanned_ocr":
        return None
    try:
        return BackendSession.start(directory)
    except Exception as exc:
        try:
            with (directory / "backend-session.log").open("a", encoding="utf-8") as handle:
                handle.write(f"start_failed {type(exc).__name__}\n")
        except OSError:
            pass
        return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--serve"] and len(args) == 2:
        install_vendor_paths()
        serve(args[1], run_vendored_pdf2zh)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
