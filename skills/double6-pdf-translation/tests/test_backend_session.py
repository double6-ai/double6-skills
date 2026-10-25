# SPDX-License-Identifier: AGPL-3.0-only
"""长文档共用翻译进程：同一进程接两块，超时后进程退出，版面模型只加载一次。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

SKILL = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(SKILL / "scripts"),
    str(SKILL / "vendor" / "babeldoc"),
    str(SKILL / "vendor" / "pdfmathtranslate_next"),
]

import psutil  # noqa: E402
from babeldoc.docvision.base_doclayout import DocLayoutModel  # noqa: E402
import babeldoc.docvision.base_doclayout as layout  # noqa: E402
from backend_session import (  # noqa: E402
    SESSION_ENV,
    BackendSession,
    invoke_backend_session,
    open_document_backend,
    vendored_pdf2zh_command,
)
from pdf2zh_next.high_level import translate_in_process  # noqa: E402

FAKE_KEY = "unit-test-key"
VENDORED = ["/usr/bin/false", str(SKILL / "scripts" / "pdf2zh_next_vendor.py"), "sample.pdf"]


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "LOCAL_TRANSLATION_API_KEY",
        "OPENAI_API_KEY",
        "GLM_API_KEY",
        "PDF2ZH_OPENAI_API_KEY",
        "PDF2ZH_DEBUG",
        "PAPER_TRANSLATION_BOUNDED_OWNERS",
        SESSION_ENV,
    ):
        env.pop(key, None)
    env["PYTHONPATH"] = str(SKILL / "scripts") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _wait_socket(address: str, proc: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"session exited early: {proc.returncode}")
        if os.path.exists(address):
            return
        time.sleep(0.05)
    raise AssertionError("socket did not appear")


def _start_custom(handler_source: str, directory: Path) -> tuple[subprocess.Popen[bytes], str]:
    address = f"/tmp/d6bs-test-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    env = _child_env()
    env["SOCK"] = address
    env["REPORT"] = str(directory / "report.json")
    env["PAPER_TRANSLATION_BOUNDED_OWNERS"] = "nonce-unit"
    proc = subprocess.Popen(
        [sys.executable, "-c", handler_source],
        env=env,
        cwd=str(directory),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_socket(address, proc)
    except Exception:
        if proc.poll() is None:
            proc.kill()
        raise
    return proc, address


def _stop(proc: subprocess.Popen[bytes], address: str) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    try:
        os.unlink(address)
    except OSError:
        pass


_SERVER = """
import json, os, time
from backend_session import serve

def handler(job):
    path = os.environ["REPORT"]
    row = {
        "pid": os.getpid(),
        "nonce": os.environ.get("PAPER_TRANSLATION_BOUNDED_OWNERS"),
        "reuse": os.environ.get("PDF_TRANSLATION_REUSE_LAYOUT"),
        "key": os.environ.get("PDF2ZH_OPENAI_API_KEY"),
    }
    rows = json.loads(path and open(path, encoding="utf-8").read()) if os.path.exists(path) else []
    rows.append(row)
    open(path, "w", encoding="utf-8").write(json.dumps(rows))
    sink = job.get("_log_stream")
    if sink is not None:
        sink.put("started")
    if os.environ.get("SLOW") == "1":
        time.sleep(30)
    return 0, "done"
serve(os.environ["SOCK"], handler)
"""


def test_two_chunks_share_one_process_and_drop_the_nonce() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        proc, address = _start_custom(_SERVER, directory)
        previous = os.environ.get(SESSION_ENV)
        os.environ[SESSION_ENV] = address
        log_path = directory / "chunk.log"
        try:
            with log_path.open("w", encoding="utf-8") as log:
                first = invoke_backend_session(
                    VENDORED, cwd=directory, env={"PDF2ZH_OPENAI_API_KEY": FAKE_KEY, "HOME": tmp},
                    timeout=5, log=log,
                )
                second = invoke_backend_session(
                    VENDORED, cwd=directory, env={"PDF2ZH_OPENAI_API_KEY": FAKE_KEY, "HOME": tmp},
                    timeout=5, log=log,
                )
            assert first == 0 and second == 0
            text = log_path.read_text(encoding="utf-8")
            assert text.count("BACKEND_SESSION: reused") == 2
            rows = json.loads((directory / "report.json").read_text(encoding="utf-8"))
            assert rows[0]["pid"] == rows[1]["pid"] == proc.pid
            assert rows[0]["nonce"] is None and rows[1]["nonce"] is None
            assert rows[0]["reuse"] == "1" and rows[1]["reuse"] == "1"
            assert rows[0]["key"] == FAKE_KEY and rows[1]["key"] == FAKE_KEY
            assert text.count(f"BACKEND_SESSION: pid {proc.pid}") == 2
        finally:
            if previous is None:
                os.environ.pop(SESSION_ENV, None)
            else:
                os.environ[SESSION_ENV] = previous
            _stop(proc, address)


def test_timeout_closes_the_shared_process() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        env = _child_env()
        # 复用上面的服务，但让处理函数停住，模拟一块翻译还没结束。
        source = _SERVER
        address = f"/tmp/d6bs-test-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
        env["SOCK"] = address
        env["REPORT"] = str(directory / "report.json")
        env["SLOW"] = "1"
        proc = subprocess.Popen(
            [sys.executable, "-c", source],
            env=env,
            cwd=str(directory),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        previous = os.environ.get(SESSION_ENV)
        try:
            _wait_socket(address, proc)
            os.environ[SESSION_ENV] = address
            with (directory / "chunk.log").open("w", encoding="utf-8") as log:
                code = invoke_backend_session(
                    VENDORED, cwd=directory, env={"HOME": tmp}, timeout=1.5, log=log,
                )
            assert code == 124
            proc.wait(timeout=3)
            assert proc.returncode is not None
        finally:
            if previous is None:
                os.environ.pop(SESSION_ENV, None)
            else:
                os.environ[SESSION_ENV] = previous
            _stop(proc, address)


def test_idle_worker_does_not_inherit_credentials_or_the_chunk_nonce() -> None:
    saved = {key: os.environ.get(key) for key in (
        "LOCAL_TRANSLATION_API_KEY", "GLM_API_KEY", "PAPER_TRANSLATION_BOUNDED_OWNERS",
    )}
    os.environ["LOCAL_TRANSLATION_API_KEY"] = FAKE_KEY
    os.environ["GLM_API_KEY"] = FAKE_KEY
    os.environ["PAPER_TRANSLATION_BOUNDED_OWNERS"] = "nonce-unit"
    session = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            session = BackendSession.start(Path(tmp))
            child = psutil.Process(session.proc.pid).environ()
            assert "LOCAL_TRANSLATION_API_KEY" not in child
            assert "GLM_API_KEY" not in child
            assert "PDF2ZH_OPENAI_API_KEY" not in child
            assert "PAPER_TRANSLATION_BOUNDED_OWNERS" not in child
            assert child.get("OMP_NUM_THREADS") == "1"
            assert os.environ[SESSION_ENV] == session.address
            session.close()
            session = None
            assert SESSION_ENV not in os.environ
            assert FAKE_KEY.encode() not in (Path(tmp) / "backend-session.log").read_bytes()
    finally:
        if session is not None:
            session.close()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_dead_worker_is_started_again() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = BackendSession.start(Path(tmp))
        try:
            first = session.proc.pid
            session.proc.kill()
            session.proc.wait(timeout=3)
            session.ensure()
            assert session.proc.pid != first
            assert session.proc.poll() is None
            assert os.environ[SESSION_ENV] == session.address
        finally:
            session.close()


def test_scanned_route_does_not_start_a_worker_and_missing_socket_falls_back() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        assert open_document_backend(Path(tmp), "scanned_ocr") is None
        assert SESSION_ENV not in os.environ
        assert vendored_pdf2zh_command(["/usr/bin/false", "/tmp/pdf2zh"]) is False
        previous = os.environ.get(SESSION_ENV)
        os.environ[SESSION_ENV] = f"/tmp/d6bs-missing-{uuid.uuid4().hex}.sock"
        try:
            assert invoke_backend_session(
                VENDORED, cwd=tmp, env={}, timeout=1, log=None,
            ) is None
            assert invoke_backend_session(
                ["/usr/bin/false", "/tmp/not-the-vendor.py"], cwd=tmp, env={}, timeout=1, log=None,
            ) is None
        finally:
            if previous is None:
                os.environ.pop(SESSION_ENV, None)
            else:
                os.environ[SESSION_ENV] = previous


def test_layout_model_stays_loaded_only_for_the_shared_process() -> None:
    original = DocLayoutModel.load_onnx
    calls: list[object] = []

    def fake_load() -> object:
        model = object()
        calls.append(model)
        return model

    saved = os.environ.get("PDF_TRANSLATION_REUSE_LAYOUT")
    layout._reused_layout_model = None
    DocLayoutModel.load_onnx = staticmethod(fake_load)
    try:
        os.environ["PDF_TRANSLATION_REUSE_LAYOUT"] = "1"
        first = DocLayoutModel.load_available()
        second = DocLayoutModel.load_available()
        assert first is second and len(calls) == 1
        os.environ.pop("PDF_TRANSLATION_REUSE_LAYOUT", None)
        third = DocLayoutModel.load_available()
        assert third is not first and len(calls) == 2
    finally:
        DocLayoutModel.load_onnx = original
        layout._reused_layout_model = None
        if saved is None:
            os.environ.pop("PDF_TRANSLATION_REUSE_LAYOUT", None)
        else:
            os.environ["PDF_TRANSLATION_REUSE_LAYOUT"] = saved


def test_in_process_translation_follows_the_reuse_flag() -> None:
    settings = SimpleNamespace(basic=SimpleNamespace(debug=False))
    saved = {
        key: os.environ.get(key)
        for key in (
            "PDF_TRANSLATION_REUSE_LAYOUT",
            "PAPER_TRANSLATION_SOURCE_CACHE_MODE",
            "PAPER_TRANSLATION_BOUNDED_OWNERS",
        )
    }
    try:
        for key in saved:
            os.environ.pop(key, None)
        assert translate_in_process(settings) is False
        os.environ["PDF_TRANSLATION_REUSE_LAYOUT"] = "1"
        assert translate_in_process(settings) is True
        os.environ.pop("PDF_TRANSLATION_REUSE_LAYOUT", None)
        os.environ["PAPER_TRANSLATION_SOURCE_CACHE_MODE"] = "read"
        os.environ["PAPER_TRANSLATION_BOUNDED_OWNERS"] = "nonce-unit"
        assert translate_in_process(settings) is True
        settings.basic.debug = True
        os.environ.pop("PAPER_TRANSLATION_SOURCE_CACHE_MODE", None)
        os.environ.pop("PAPER_TRANSLATION_BOUNDED_OWNERS", None)
        assert translate_in_process(settings) is True
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
