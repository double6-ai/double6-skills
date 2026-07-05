#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pdf_translation_runtime import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    default_engine_home,
    DEFAULT_TRANSLATION_COMPAT_PROXY_PORT,
    DEFAULT_MODEL,
    DEFAULT_PDF2ZH_BACKEND,
    PDF2ZH_BINARY_ENV,
    provider_base_url_candidates,
    resolve_api_key,
    resolve_base_url,
    resolve_base_url_inference,
    redacted_command,
    resolved_pdf2zh_backend,
)

SCRIPT_INTERFACE = "cli"
SCRIPT_INTERFACE_REASON = "Runtime preflight CLI for portable skill installation and dependency diagnostics."


def check_result(
    check_id: str,
    status: str,
    *,
    severity: str,
    message: str,
    details: dict[str, Any] | None = None,
    remediation: str = "",
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "severity": severity,
        "message": message,
        "details": details or {},
        "remediation": remediation,
    }


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def backend_command_env(args: argparse.Namespace | None = None) -> dict[str, str]:
    env = os.environ.copy()
    raw_engine_home = str(getattr(args, "engine_home", "") or "").strip() if args is not None else ""
    engine_home = Path(raw_engine_home).expanduser().resolve() if raw_engine_home else default_engine_home()
    env.update(
        {
            "HOME": str(engine_home),
            "XDG_CACHE_HOME": str(engine_home / ".cache"),
            "HF_HOME": str(engine_home / ".hf-home"),
            "UV_CACHE_DIR": str(engine_home / ".uv-cache"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    for key in ("XDG_CACHE_HOME", "HF_HOME", "UV_CACHE_DIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return env


def run_command(command: list[str], timeout_seconds: float, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False, env=env)
        return {
            "command": command,
            "returncode": proc.returncode,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout_excerpt": proc.stdout[:2000],
            "stderr_excerpt": proc.stderr[:2000],
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "duration_ms": round(timeout_seconds * 1000, 2),
            "stdout_excerpt": (exc.stdout or "")[:2000] if isinstance(exc.stdout, str) else "",
            "stderr_excerpt": (exc.stderr or "")[:2000] if isinstance(exc.stderr, str) else "",
            "timed_out": True,
        }
    except OSError as exc:
        return {
            "command": command,
            "returncode": 127,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout_excerpt": "",
            "stderr_excerpt": str(exc),
            "timed_out": False,
        }


def check_python() -> dict[str, Any]:
    version = sys.version_info
    ok = (version.major, version.minor) >= (3, 11)
    return check_result(
        "python_version",
        "pass" if ok else "fail",
        severity="required",
        message=f"Python interpreter is {version.major}.{version.minor}.{version.micro}.",
        details={"executable": sys.executable, "version": sys.version},
        remediation="Use Python 3.11 or newer for the skill runtime.",
    )


def check_module(name: str, *, required: bool, remediation: str) -> dict[str, Any]:
    ok = module_available(name)
    return check_result(
        f"python_module_{name.replace('-', '_')}",
        "pass" if ok else ("fail" if required else "warn"),
        severity="required" if required else "optional",
        message=f"Python module {name!r} is {'available' if ok else 'not importable'}.",
        details={"python": sys.executable, "module": name},
        remediation=remediation,
    )


def check_pymupdf(*, required: bool) -> dict[str, Any]:
    fitz_ok = module_available("fitz")
    pymupdf_ok = module_available("pymupdf")
    ok = fitz_ok or pymupdf_ok
    return check_result(
        "python_module_pymupdf_runtime",
        "pass" if ok else ("fail" if required else "warn"),
        severity="required" if required else "optional",
        message="PyMuPDF is importable via fitz/pymupdf." if ok else "PyMuPDF is not importable as fitz or pymupdf.",
        details={"python": sys.executable, "fitz": fitz_ok, "pymupdf": pymupdf_ok},
        remediation="Install PyMuPDF in the release QA Python environment to enable visual/layout PDF audits.",
    )


def check_pdf2zh(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    backend = resolved_pdf2zh_backend(args)
    prefix = [str(item) for item in backend["command_prefix"]]
    command = [*prefix, "--help"]
    engine_home = Path(str(getattr(args, "engine_home", "") or default_engine_home())).expanduser().resolve()
    result = run_command(command, float(args.command_timeout), env=backend_command_env(args))
    combined = "\n".join([str(result.get("stdout_excerpt") or ""), str(result.get("stderr_excerpt") or "")])
    ok = result["returncode"] == 0
    missing_module = "No module named 'pdf2zh_next'" in combined or "Missing Python module 'pdf2zh_next'" in combined
    if missing_module:
        message = "Resolved pdf2zh backend starts but cannot import pdf2zh_next."
    elif ok:
        message = "Resolved pdf2zh backend help command completed."
    else:
        message = "Resolved pdf2zh backend help command failed."
    return (
        check_result(
            "pdf2zh_backend",
            "pass" if ok else "fail",
            severity="required",
            message=message,
            details={
                "backend": backend,
                "command": redacted_command(command, str(getattr(args, "api_key", "") or DEFAULT_API_KEY)),
                "returncode": result["returncode"],
                "stdout_excerpt": result.get("stdout_excerpt", ""),
                "stderr_excerpt": result.get("stderr_excerpt", ""),
                "timed_out": result.get("timed_out", False),
                "missing_pdf2zh_next": missing_module,
                "engine_home": str(engine_home),
            },
            remediation=(
                "Install a compatible PDFMathTranslate-next/pdf2zh_next backend in this Python environment, "
                f"or set {PDF2ZH_BINARY_ENV} / --pdf2zh-binary to a working pdf2zh executable."
            ),
        ),
        backend,
    )


def check_poppler(*, required: bool = False) -> dict[str, Any]:
    command = ["pdftotext", "-v"]
    result = run_command(command, 5)
    ok = result["returncode"] == 0 or bool(result.get("stderr_excerpt"))
    return check_result(
        "poppler_pdftotext",
        "pass" if ok else ("fail" if required else "warn"),
        severity="required" if required else "optional",
        message="Poppler pdftotext is available." if ok else "Poppler pdftotext is not available.",
        details={"command": command, "returncode": result["returncode"], "stderr_excerpt": result.get("stderr_excerpt", "")},
        remediation="Install Poppler for release QA bbox/text side-channel audits.",
    )


def _chat_completions_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def _chat_endpoint_probe(args: argparse.Namespace, base_url: str, *, fallback_from: dict[str, Any] | None = None) -> dict[str, Any]:
    endpoint = _chat_completions_url(base_url)
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "You are a runtime preflight checker."},
            {"role": "user", "content": "Reply with OK."},
        ],
        "max_tokens": 8,
        "stream": False,
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {args.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=float(args.endpoint_timeout)) as response:  # noqa: S310 - operator-configured endpoint preflight
            status = int(getattr(response, "status", 0) or 0)
            ok = 200 <= status < 300
            details = {"base_url": base_url, "endpoint": endpoint, "status": status, "model": args.model}
            if fallback_from:
                details["fallback_from"] = fallback_from
            return check_result(
                "openai_endpoint",
                "pass" if ok else "fail",
                severity="required",
                message=f"OpenAI-compatible chat endpoint responded with HTTP {status}.",
                details=details,
                remediation="Check LOCAL_TRANSLATION_API_KEY, LOCAL_TRANSLATION_MODEL, and LOCAL_TRANSLATION_BASE_URL.",
            )
    except HTTPError as exc:
        details = {
            "base_url": base_url,
            "endpoint": endpoint,
            "model": args.model,
            "status": exc.code,
            "error": str(exc),
        }
        if fallback_from:
            details["fallback_from"] = fallback_from
        return check_result(
            "openai_endpoint",
            "fail",
            severity="required",
            message=f"OpenAI-compatible chat endpoint rejected the preflight request with HTTP {exc.code}.",
            details=details,
            remediation="Verify the API key, model name, and endpoint by sending a minimal chat completions request.",
        )
    except URLError as exc:
        details = {"base_url": base_url, "endpoint": endpoint, "model": args.model, "error": str(exc)}
        if fallback_from:
            details["fallback_from"] = fallback_from
        return check_result(
            "openai_endpoint",
            "fail",
            severity="required",
            message=f"OpenAI-compatible chat endpoint is not reachable: {exc}.",
            details=details,
            remediation="Set LOCAL_TRANSLATION_API_KEY and allow outbound access to the configured endpoint.",
        )


def check_endpoint_config(args: argparse.Namespace) -> dict[str, Any]:
    base_url = str(args.base_url or "").rstrip("/")
    model = str(args.model or "").strip()
    api_key = str(args.api_key or "").strip()
    missing = [
        name
        for name, value in (
            ("base_url", base_url),
            ("model", model),
            ("api_key", api_key),
        )
        if not value
    ]
    if missing:
        return check_result(
            "openai_endpoint",
            "fail",
            severity="required",
            message="Translation model API configuration is incomplete.",
            details={"missing": missing, "base_url": base_url, "model": model},
            remediation="首次运行前必须设置 --model 和 API key；base_url 可通过 --base-url / LOCAL_TRANSLATION_BASE_URL 显式设置，或由单一厂商专属 API key 按 provider-base-urls.md 推断。",
        )
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        return check_result(
            "openai_endpoint",
            "fail",
            severity="required",
            message="OpenAI-compatible base URL is invalid.",
            details={"base_url": base_url},
            remediation="Set LOCAL_TRANSLATION_BASE_URL or --base-url to a valid OpenAI-compatible endpoint.",
        )
    return check_result(
        "openai_endpoint_config",
        "pass",
        severity="required",
        message="Translation model API configuration is complete.",
        details={"base_url": base_url, "model": model},
        remediation="Keep --model and API key explicit; base_url may remain inferred from provider-base-urls.md.",
    )


def check_endpoint(args: argparse.Namespace) -> dict[str, Any]:
    config_check = check_endpoint_config(args)
    if config_check["status"] == "fail":
        return config_check
    base_url = str(args.base_url or "").rstrip("/")
    parsed = urlparse(base_url)
    if "api.deepseek.com" in parsed.netloc or base_url.endswith("/chat/completions"):
        return _chat_endpoint_probe(args, base_url)
    request = Request(
        base_url + "/models",
        headers={"Authorization": f"Bearer {args.api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=float(args.endpoint_timeout)) as response:  # noqa: S310 - reviewed local/operator endpoint preflight
            status = int(getattr(response, "status", 0) or 0)
            ok = 200 <= status < 300
            return check_result(
                "openai_endpoint",
                "pass" if ok else "fail",
                severity="required",
                message=f"OpenAI-compatible endpoint responded with HTTP {status}.",
                details={"base_url": base_url, "status": status, "model": args.model},
                remediation="Start the local model server or adjust LOCAL_TRANSLATION_BASE_URL / --base-url.",
            )
    except HTTPError as exc:
        fallback_from = {"endpoint": base_url + "/models", "status": exc.code, "error": str(exc)}
        return _chat_endpoint_probe(args, base_url, fallback_from=fallback_from)
    except URLError as exc:
        fallback_from = {"endpoint": base_url + "/models", "error": str(exc)}
        return _chat_endpoint_probe(args, base_url, fallback_from=fallback_from)


def check_proxy_port(args: argparse.Namespace) -> dict[str, Any]:
    port = int(args.translation_compat_proxy_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
        return check_result(
            "translation_proxy_port",
            "pass",
            severity="optional",
            message=f"translation compatibility proxy port {port} can be bound.",
            details={"host": "127.0.0.1", "port": port},
            remediation="",
        )
    except OSError as exc:
        return check_result(
            "translation_proxy_port",
            "warn",
            severity="optional",
            message=f"translation compatibility proxy port {port} cannot be bound: {exc}.",
            details={"host": "127.0.0.1", "port": port, "error": str(exc)},
            remediation="Use --translation-compat-proxy off, choose another PAPER_TRANSLATION_COMPAT_PROXY_PORT, or run outside a sandbox that blocks binding.",
        )
    finally:
        sock.close()


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    release_qa = str(getattr(args, "profile", "runtime")) == "release-qa"
    checks.append(check_python())
    pdf2zh_check, backend = check_pdf2zh(args)
    checks.append(pdf2zh_check)
    checks.append(check_module("pdf2zh_next", required=str(args.pdf2zh_backend) == "module", remediation="Install pdf2zh_next when using --pdf2zh-backend module."))
    checks.append(check_module("reportlab", required=release_qa, remediation="Install reportlab to render QA repaired readable PDFs."))
    checks.append(check_pymupdf(required=release_qa))
    checks.append(check_poppler(required=release_qa))
    endpoint_config_check = check_endpoint_config(args)
    if endpoint_config_check["status"] == "fail":
        checks.append(endpoint_config_check)
    elif not args.skip_endpoint_check:
        checks.append(check_endpoint(args))
    else:
        checks.append(
            check_result(
                "openai_endpoint",
                "skipped",
                severity="required",
                message="OpenAI-compatible endpoint check was skipped by request.",
                details={"base_url": args.base_url, "model": args.model},
                remediation="Run without --skip-endpoint-check before real translation.",
            )
        )
    checks.append(check_proxy_port(args))
    required_failures = [item for item in checks if item["severity"] == "required" and item["status"] == "fail"]
    warnings = [item for item in checks if item["status"] == "warn"]
    return {
        "schema_version": "1.0",
        "ok": not required_failures,
        "strict": bool(args.strict),
        "profile": str(getattr(args, "profile", "runtime")),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": {"executable": sys.executable, "version": sys.version},
        "backend": backend,
        "endpoint": {
            "base_url": args.base_url,
            "model": args.model,
            "provider": getattr(args, "provider", None),
            "base_url_inference": getattr(args, "inferred_translation_provider", None),
            "base_url_candidates": provider_base_url_candidates(),
        },
        "summary": {
            "check_count": len(checks),
            "required_failure_count": len(required_failures),
            "warning_count": len(warnings),
            "decision": "pass" if not required_failures else "block-runtime",
        },
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight runtime dependencies for double6-pdf-translation.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when required runtime checks fail.")
    parser.add_argument("--profile", choices=["runtime", "release-qa"], default="runtime", help="Dependency contract to check. runtime checks user-facing essentials; release-qa is a stricter local diagnostics profile.")
    parser.add_argument("--output", help="Optional JSON report path.")
    parser.add_argument("--pdf2zh-binary", default=os.environ.get(PDF2ZH_BINARY_ENV), help="Explicit pdf2zh executable path.")
    parser.add_argument("--pdf2zh-backend", choices=["path", "module"], default=os.environ.get("PAPER_TRANSLATION_PDF2ZH_BACKEND", DEFAULT_PDF2ZH_BACKEND))
    parser.add_argument("--provider", default=os.environ.get("LOCAL_TRANSLATION_PROVIDER", ""), help="Optional provider alias used to infer base URL, e.g. deepseek, openai, qwen, kimi, siliconflow, glm, openrouter, ark.")
    parser.add_argument("--base-url", default=os.environ.get("LOCAL_TRANSLATION_BASE_URL") or DEFAULT_BASE_URL)
    parser.add_argument("--model", default=os.environ.get("LOCAL_TRANSLATION_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--api-key", default=os.environ.get("LOCAL_TRANSLATION_API_KEY") or DEFAULT_API_KEY)
    parser.add_argument("--translation-compat-proxy-port", type=int, default=int(os.environ.get("PAPER_TRANSLATION_COMPAT_PROXY_PORT", str(DEFAULT_TRANSLATION_COMPAT_PROXY_PORT))))
    parser.add_argument("--engine-home", default=os.environ.get("PAPER_TRANSLATION_ENGINE_HOME", str(default_engine_home())))
    parser.add_argument("--command-timeout", type=float, default=10.0)
    parser.add_argument("--endpoint-timeout", type=float, default=3.0)
    parser.add_argument("--skip-endpoint-check", action="store_true", help="Diagnostic only; real translation still requires a reachable model endpoint.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_base_url = args.base_url
    args.base_url = resolve_base_url(args.provider, args.base_url)
    args.api_key = resolve_api_key(args.provider, args.api_key)
    args.inferred_translation_provider = resolve_base_url_inference(args.provider, raw_base_url)
    report = build_report(args)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(text, end="")
    if args.output:
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    if args.strict and not report["ok"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
