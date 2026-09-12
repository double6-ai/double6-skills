from __future__ import annotations

import json
import locale
import subprocess
from pathlib import Path
from typing import Any

from .common import D6PPTError, utc_now, write_json
from .doctor import find_officecli, officecli_argv


def _decode_console_bytes(raw: bytes | None) -> str:
    """Decode subprocess bytes with console-codepage fallbacks (GBK/Windows)."""
    if not raw:
        return ""
    candidates = ["utf-8-sig"]
    preferred = locale.getpreferredencoding(False) or ""
    if preferred:
        candidates.append(preferred)
    candidates += ["utf-8", "gb18030", "cp1252"]
    for encoding in candidates:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


class OfficeCLI:
    def __init__(self, runtime_dir: Path | None = None, log_dir: Path | None = None, timeout: int = 120):
        self.binary = find_officecli(runtime_dir)
        if not self.binary:
            raise D6PPTError(
                "OfficeCLI is not installed in the runtime; run bootstrap to install the pinned 1.0.144 build",
                "officecli_missing",
            )
        self.argv = officecli_argv(self.binary)
        self.log_dir = log_dir
        self.timeout = timeout

    def run(self, args: list[str], *, expect_json: bool = True, timeout: int | None = None) -> dict[str, Any]:
        command = [*self.argv, *args]
        if expect_json and "--json" not in command:
            command.append("--json")
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise D6PPTError(f"OfficeCLI timed out: {' '.join(args)}", "officecli_timeout") from exc
        except OSError as exc:
            raise D6PPTError(
                f"OfficeCLI failed to start ({exc}); on Windows ensure node.exe is on PATH if using officecli.cmd/.js",
                "officecli_launch_failed",
                {"command": command, "error": str(exc)},
            ) from exc
        stdout = _decode_console_bytes(proc.stdout)
        stderr = _decode_console_bytes(proc.stderr)
        receipt: dict[str, Any] = {
            "at": utc_now(), "command": command, "returncode": proc.returncode,
            "stdout": stdout, "stderr": stderr,
        }
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            write_json(self.log_dir / f"officecli_{len(list(self.log_dir.glob('officecli_*.json'))) + 1:03d}.json", receipt)
        if proc.returncode != 0:
            raise D6PPTError(stderr.strip() or stdout.strip() or "OfficeCLI failed", "officecli_failed", receipt)
        if not expect_json:
            return {"ok": True, "data": stdout.strip(), "receipt": receipt}
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = {"ok": True, "data": stdout.strip()}
        payload["_receipt"] = receipt
        return payload

    def validate(self, pptx: Path) -> dict[str, Any]:
        return self.run(["validate", str(pptx)])

    def view(self, pptx: Path, mode: str, *extra: str) -> dict[str, Any]:
        return self.run(["view", str(pptx), mode, *extra])

    def set_property(self, pptx: Path, path: str, name: str, value: Any) -> dict[str, Any]:
        return self.run(["set", str(pptx), path, "--prop", f"{name}={value}"])

    def remove(self, pptx: Path, path: str) -> dict[str, Any]:
        return self.run(["remove", str(pptx), path])

    def save(self, pptx: Path) -> dict[str, Any]:
        return self.run(["save", str(pptx)])

    def close(self, pptx: Path) -> dict[str, Any]:
        return self.run(["close", str(pptx)])
