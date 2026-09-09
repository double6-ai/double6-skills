from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .common import D6PPTError, utc_now, write_json
from .doctor import find_officecli


class OfficeCLI:
    def __init__(self, runtime_dir: Path | None = None, log_dir: Path | None = None, timeout: int = 120):
        self.binary = find_officecli(runtime_dir)
        if not self.binary:
            raise D6PPTError("OfficeCLI v1.0.144 is not installed in the pinned runtime", "officecli_missing")
        self.log_dir = log_dir
        self.timeout = timeout

    def run(self, args: list[str], *, expect_json: bool = True, timeout: int | None = None) -> dict[str, Any]:
        command = [str(self.binary), *args]
        if expect_json and "--json" not in command:
            command.append("--json")
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as exc:
            raise D6PPTError(f"OfficeCLI timed out: {' '.join(args)}", "officecli_timeout") from exc
        receipt: dict[str, Any] = {
            "at": utc_now(), "command": command, "returncode": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr,
        }
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            write_json(self.log_dir / f"officecli_{len(list(self.log_dir.glob('officecli_*.json'))) + 1:03d}.json", receipt)
        if proc.returncode != 0:
            raise D6PPTError(proc.stderr.strip() or proc.stdout.strip() or "OfficeCLI failed", "officecli_failed", receipt)
        if not expect_json:
            return {"ok": True, "data": proc.stdout.strip(), "receipt": receipt}
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = {"ok": True, "data": proc.stdout.strip()}
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
