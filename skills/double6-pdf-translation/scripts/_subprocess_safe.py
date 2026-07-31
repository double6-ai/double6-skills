"""Safe subprocess helpers for the pdf-translation skill.

Why this exists
----------------
On this Windows + WorkBuddy environment, the `pdftotext` binary that
`shutil.which("pdftotext")` resolves to is the one bundled with the
PortableGit install (`.../mingw64/bin/pdftotext.EXE`). That mingw binary
emits its output in the system code page (e.g. GBK) rather than UTF-8.

When a caller uses ``subprocess.run(..., text=True)``, Python's reader
thread tries to decode the captured bytes as UTF-8, hits an invalid byte
(observed: ``0xb7`` = GBK middle-dot ``·``), and the decode fails inside
the background thread. The result is that ``CompletedProcess.stdout`` ends up
``None`` instead of a string. The next line then does
``result.stdout.strip()`` and dies with
``AttributeError: 'NoneType' object has no attribute 'strip'`` — crashing the
entire translation run before any PDF is produced.

Fix
---
Capture bytes ourselves and decode defensively (UTF-8 -> system preferred
encoding -> GB18030 -> Latin-1 -> replacement) so ``.stdout`` / ``.stderr``
are ALWAYS ``str`` (never ``None``).
Callers can keep writing ``.stdout.strip()`` / ``.stdout[-N:]`` without guards.

This is recorded as pitfall P12 in references/known-pitfalls.md.
"""
from __future__ import annotations

import locale
import os
import subprocess
from typing import Any


_SUBPROCESS_ENV_ALLOWLIST = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "VIRTUAL_ENV",
    "CONDA_PREFIX", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "HTTP_PROXY",
    "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
)


def minimal_subprocess_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Return a narrow child environment without unrelated ambient secrets."""
    env = {
        key: value
        for key in _SUBPROCESS_ENV_ALLOWLIST
        if (value := os.environ.get(key))
    }
    if overrides:
        env.update({str(key): str(value) for key, value in overrides.items()})
    return env


def _decode(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        encodings = ["utf-8", locale.getpreferredencoding(False), "gb18030", "latin-1"]
        for enc in dict.fromkeys(value for value in encodings if value):
            try:
                return raw.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", "replace")
    return raw or ""


def run_text(cmd, **kwargs) -> subprocess.CompletedProcess:
    """Run a command and return a CompletedProcess whose ``.stdout``/``.stderr``
    are always ``str`` (never ``None``).

    Intended as a drop-in replacement for ``subprocess.run(..., text=True)`` when
    the child may emit non-UTF-8 bytes (notably the bundled ``pdftotext``).
    We deliberately capture bytes (``text=True`` / ``capture_output`` are dropped)
    and decode them safely.
    """
    kwargs.pop("text", None)
    kwargs.pop("capture_output", None)
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    kwargs.setdefault("check", False)
    proc = subprocess.run(cmd, **kwargs)
    proc.stdout = _decode(proc.stdout)
    proc.stderr = _decode(proc.stderr)
    return proc
