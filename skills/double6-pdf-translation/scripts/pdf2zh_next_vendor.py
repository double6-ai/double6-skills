#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
from __future__ import annotations

import runpy
import sys
import os
from pathlib import Path


def main() -> int:
    skill_root = Path(__file__).resolve().parents[1]
    repo_root = __import__("runtime_paths").workspace_root()
    engine_home = Path(os.environ.get("PAPER_TRANSLATION_ENGINE_HOME", repo_root / ".cache" / "paper-translation" / "pdf2zh-home")).expanduser().resolve()
    for key, path in {
        "HOME": engine_home,
        "XDG_CACHE_HOME": engine_home / ".cache",
        "HF_HOME": engine_home / ".hf-home",
        "UV_CACHE_DIR": engine_home / ".uv-cache",
    }.items():
        os.environ[key] = str(path)
        Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
    vendor_root = skill_root / "vendor" / "pdfmathtranslate_next"
    if not (vendor_root / "pdf2zh_next").exists():
        raise SystemExit(f"vendored PDFMathTranslate-next backend missing: {vendor_root}")
    babeldoc_vendor_root = skill_root / "vendor" / "babeldoc"
    if not (babeldoc_vendor_root / "babeldoc").exists():
        raise SystemExit(f"vendored BabelDOC backend missing: {babeldoc_vendor_root}")
    os.environ["PAPER_TRANSLATION_BABELDOC_VENDOR"] = str(babeldoc_vendor_root)
    sys.path.insert(0, str(vendor_root))
    sys.path.insert(0, str(babeldoc_vendor_root))
    if any(arg in {"-h", "--help"} for arg in sys.argv[1:]):
        print(
            "usage: pdf2zh_next_vendor.py [options] input_files...\n\n"
            "Vendored PDFMathTranslate-next wrapper for paper-translation.\n\n"
            "Common options:\n"
            "  --help                         show this help message and exit\n"
            "  --version                      show pdf2zh-next version\n"
            "  --disable-same-text-fallback   disable fallback translation when LLM output matches input text\n"
            "  --disable-rich-text-translate  disable rich text placeholder translation\n"
            "  --enhance-compatibility        enable compatibility options\n"
        )
        return 0
    runpy.run_module("pdf2zh_next.main", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
