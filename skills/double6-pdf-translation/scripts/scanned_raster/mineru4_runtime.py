# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""MinerU 4.0.4 runtime checks and explicit model preparation.

Translation runs call :func:`doctor` only. Model downloads are confined to the
explicit ``prepare`` command so a PDF cannot trigger an unexpected download.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    scripts_root = Path(__file__).resolve().parent.parent
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))
    from scanned_raster.constants import MINERU_VERSION
else:
    from .constants import MINERU_VERSION

MINERU_HOME_ENV = "PAPER_TRANSLATION_MINERU_HOME"
DEFAULT_MINERU_HOME = Path(".cache/paper-translation/mineru4")
SUPPORTED_PREPARE_TIERS = ("basic", "standard")
SUPPORTED_DOCTOR_TIERS = ("basic", "standard", "advanced")
SUPPORTED_MODEL_SOURCES = ("modelscope", "huggingface", "auto")
DEFAULT_MODEL_SOURCE = "modelscope"


def repo_root() -> Path:
    from runtime_paths import workspace_root
    return workspace_root()


def mineru_home() -> Path:
    configured = os.environ.get(MINERU_HOME_ENV, "").strip()
    path = Path(configured).expanduser() if configured else repo_root() / DEFAULT_MINERU_HOME
    return path.resolve()


def runtime_env() -> dict[str, str]:
    """Return an isolated cache/config environment without copying credentials."""
    root = mineru_home()
    env = dict(os.environ)
    env.update(
        {
            "MINERU_HOME": str(root),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "HF_HOME": str(root / "huggingface"),
            "MODELSCOPE_CACHE": str(root / "modelscope"),
        }
    )
    return env


def installed_version() -> str | None:
    try:
        return importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError:
        return None


def _kit_command() -> list[str] | None:
    executable = shutil.which("mineru-kit")
    if executable:
        return [executable]
    if installed_version() is not None:
        return [sys.executable, "-m", "mineru.kit.main"]
    return None


def _run_kit(arguments: list[str], *, timeout: int) -> dict[str, Any]:
    command = _kit_command()
    if command is None:
        return {"status": "unavailable", "returncode": None, "stdout": "", "stderr": "mineru-kit not installed"}
    completed = subprocess.run(
        [*command, *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=runtime_env(),
    )
    return {
        "status": "ok" if completed.returncode == 0 else "error",
        "returncode": completed.returncode,
        "stdout": completed.stdout[-4000:],
        "stderr": completed.stderr[-4000:],
    }


def doctor(*, tier: str = "basic", verify_models: bool = True) -> dict[str, Any]:
    version = installed_version()
    model_tier = "standard" if tier == "advanced" else tier
    result: dict[str, Any] = {
        "status": "ok",
        "expected_version": MINERU_VERSION,
        "installed_version": version,
        "version_ok": version == MINERU_VERSION,
        "mineru_home": str(mineru_home()),
        "tier": tier,
        "model_tier": model_tier,
        "models_checked": False,
        "models_ready": None,
    }
    if version is None:
        result.update(status="unavailable", error="mineru_not_installed")
        return result
    if version != MINERU_VERSION:
        result.update(status="error", error="mineru_version_mismatch")
        return result
    if verify_models:
        verification = _run_kit(["models", "verify", "--tier", model_tier], timeout=120)
        result["models_checked"] = True
        result["models_ready"] = verification["status"] == "ok"
        result["model_verification"] = verification
        if not result["models_ready"]:
            result.update(status="not_ready", error="mineru_models_not_ready")
    return result


def prepare(*, tier: str, source: str = DEFAULT_MODEL_SOURCE) -> dict[str, Any]:
    if tier not in SUPPORTED_PREPARE_TIERS:
        raise ValueError(f"prepare tier must be one of {SUPPORTED_PREPARE_TIERS}")
    if source not in SUPPORTED_MODEL_SOURCES:
        raise ValueError(f"model source must be one of {SUPPORTED_MODEL_SOURCES}")
    before = doctor(tier=tier, verify_models=False)
    if before["status"] != "ok":
        return before
    mineru_home().mkdir(parents=True, exist_ok=True)
    download = _run_kit(
        ["models", "download", "--tier", tier, "--source", source],
        timeout=7200,
    )
    result = {
        "status": download["status"],
        "expected_version": MINERU_VERSION,
        "installed_version": installed_version(),
        "mineru_home": str(mineru_home()),
        "tier": tier,
        "source": source,
        "download": download,
    }
    if download["status"] == "ok":
        result["verification"] = _run_kit(["models", "verify", "--tier", tier], timeout=300)
        if result["verification"]["status"] != "ok":
            result.update(status="error", error="mineru_model_verification_failed")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the pinned MinerU 4.0.4 runtime.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="Check package and model readiness without downloading.")
    doctor_parser.add_argument("--tier", choices=SUPPORTED_DOCTOR_TIERS, default="basic")
    doctor_parser.add_argument("--skip-model-check", action="store_true")
    prepare_parser = subparsers.add_parser("prepare", help="Explicitly download and verify MinerU models.")
    prepare_parser.add_argument("--tier", choices=SUPPORTED_PREPARE_TIERS, required=True)
    prepare_parser.add_argument(
        "--source",
        choices=SUPPORTED_MODEL_SOURCES,
        default=DEFAULT_MODEL_SOURCE,
        help="Model mirror. Defaults to the domestic ModelScope mirror.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = (
        doctor(tier=args.tier, verify_models=not args.skip_model_check)
        if args.command == "doctor"
        else prepare(tier=args.tier, source=args.source)
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
