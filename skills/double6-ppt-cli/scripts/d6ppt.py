#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def _reexec_into_runtime_python() -> None:
    """Re-run under the bootstrapped runtime venv when core deps are missing.

    ``bootstrap`` installs the pinned Python dependencies into
    ``<runtime-dir>/python``; without this hop every later command would fail
    with ImportError unless the user knew to call that interpreter directly.
    """
    import importlib.util
    import os

    if os.environ.get("D6PPT_NO_REEXEC") or all(
        importlib.util.find_spec(name) for name in ("lxml", "PIL", "pptx")
    ):
        return
    from double6_ppt_cli.common import default_runtime_dir

    runtime = None
    argv = sys.argv[1:]
    for index, value in enumerate(argv):
        if value == "--runtime-dir" and index + 1 < len(argv):
            runtime = Path(argv[index + 1]).expanduser()
        elif value.startswith("--runtime-dir="):
            runtime = Path(value.split("=", 1)[1]).expanduser()
    runtime = runtime or default_runtime_dir()
    python = runtime / "python" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    # Compare venv prefixes, not resolved binaries: venv interpreters are symlinks.
    if python.is_file() and Path(sys.prefix).resolve() != (runtime / "python").resolve():
        os.environ["D6PPT_NO_REEXEC"] = "1"
        if os.name == "nt":
            import subprocess

            raise SystemExit(subprocess.call([str(python), str(Path(__file__).resolve()), *argv]))
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *argv])


_reexec_into_runtime_python()

from double6_ppt_cli.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
