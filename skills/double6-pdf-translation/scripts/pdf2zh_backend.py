#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import runpy
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Wrapper for an installed PDFMathTranslate-next/pdf2zh_next backend.",
        epilog=(
            "Unknown options and input files are passed through to pdf2zh_next.main. "
            "Install the backend separately, or use run_pdf_translation.py with "
            "--pdf2zh-backend path and a pdf2zh executable on PATH."
        ),
    )
    parser.add_argument(
        "backend_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded unchanged to pdf2zh_next.main.",
    )
    return parser


def main() -> int:
    build_parser().parse_known_args(sys.argv[1:])
    repo_root = Path(__file__).resolve().parents[3]
    engine_home = Path(
        os.environ.get(
            "PAPER_TRANSLATION_ENGINE_HOME",
            Path.home() / ".cache" / "double6-pdf-translation" / "pdf2zh-home",
        )
    ).expanduser().resolve()
    for key, path in {
        "HOME": engine_home,
        "XDG_CACHE_HOME": engine_home / ".cache",
        "HF_HOME": engine_home / ".hf-home",
        "UV_CACHE_DIR": engine_home / ".uv-cache",
    }.items():
        os.environ[key] = str(path)
        Path(os.environ[key]).mkdir(parents=True, exist_ok=True)

    try:
        runpy.run_module("pdf2zh_next.main", run_name="__main__")
    except ModuleNotFoundError as exc:
        if exc.name == "pdf2zh_next":
            raise SystemExit(
                "Missing Python module 'pdf2zh_next'. Install a compatible high-fidelity PDF backend, "
                "or use --pdf2zh-backend path with a pdf2zh executable on PATH."
            ) from exc
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
