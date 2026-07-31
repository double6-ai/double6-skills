#!/usr/bin/env bash
# setup_venv.sh — safe one-shot installer for the double6-pdf-translation backend.
#
# Bakes in the lessons from references/known-pitfalls.md (P1, P3, P16):
#   P1  installs the CORRECT package (pdf2zh_next, NOT the unrelated PyPI pdf2zh)
#   P3  never `rm -rf` an existing venv; lands on a stable path via rename
#   P16 `python -m venv` is a SILENT NO-OP on WorkBuddy managed Python — so we
#       REUSE an existing usable venv, or create via venv.EnvBuilder (not the CLI)
#
# Usage:
#   bash scripts/setup_venv.sh                 # install backend into the default venv
#   bash scripts/setup_venv.sh --verify-model  # also ping the model endpoint (needs env vars set)
#   PDFTR_VENV=/path/to/venv bash scripts/setup_venv.sh   # override target venv
#   PDFTR_SETUP_DRY_RUN=1 bash scripts/setup_venv.sh       # only show resolved paths
set -euo pipefail

USER_ROOT="${HOME:-${USERPROFILE:-}}"
WORKBUDDY_VENV="$USER_ROOT/.workbuddy/binaries/python/envs/default"
WORKBUDDY_PYTHON="$(
  find "$USER_ROOT/.workbuddy/binaries/python/versions" -mindepth 2 -maxdepth 2 -type f -name python.exe -print 2>/dev/null \
    | sort -V \
    | tail -n 1 \
    || true
)"

if [ -n "${PDFTR_PYTHON:-}" ]; then
  MP="$PDFTR_PYTHON"
elif [ -f "$WORKBUDDY_PYTHON" ]; then
  MP="$WORKBUDDY_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  MP="$(command -v python3)"
else
  MP="$(command -v python || true)"
fi
if [ -z "$MP" ] || [ ! -f "$MP" ]; then
  echo "ERROR: no usable Python interpreter found." >&2
  echo "       Set PDFTR_PYTHON explicitly or install Python 3.11+." >&2
  exit 2
fi

if [ -n "${PDFTR_VENV:-}" ]; then
  VENV="$PDFTR_VENV"
elif [ -f "$WORKBUDDY_PYTHON" ]; then
  VENV="$WORKBUDDY_VENV"
else
  VENV="$USER_ROOT/.local/share/double6-pdf-translation/venv"
fi

verify_model=0
for a in "$@"; do [ "$a" = "--verify-model" ] && verify_model=1; done

echo "==> Managed Python : $MP"
echo "==> Target venv    : $VENV"
if [ "${PDFTR_SETUP_DRY_RUN:-0}" = "1" ]; then
  echo "==> Dry run: path discovery completed; no environment was changed."
  exit 0
fi

# --- P16: `python -m venv` is a silent no-op on WorkBuddy managed Python ---
#   It exits 0 but creates an EMPTY dir (no Scripts/python.exe). The direct
#   builder works. Strategy:
#     (a) if a usable venv already exists at $VENV, REUSE it — this also avoids
#         stomping shared packages (gradio/pandas/...) in the managed `default` venv;
#     (b) otherwise create via venv.EnvBuilder(with_pip=True) — NOT `python -m venv`.
#   We never `rm -rf` the old env (P3).
if [ -f "$VENV/Scripts/python.exe" ] || [ -f "$VENV/bin/python" ]; then
  TMPV="$VENV"
  REUSED_VENV=1
  echo "==> Reusing existing venv at $VENV (P16: skip venv creation)"
else
  TS="$(date +%Y%m%d%H%M%S)"
  TMPV="$VENV.installing.$TS"
  echo "==> Creating venv via venv.EnvBuilder (P16: NOT 'python -m venv') ..."
  "$MP" -c "import venv, sys; venv.EnvBuilder(with_pip=True, clear=True).create(sys.argv[1])" "$TMPV"
  REUSED_VENV=0
fi

if [ -f "$TMPV/Scripts/python.exe" ]; then
  TMP_PYTHON="$TMPV/Scripts/python.exe"
  TMP_PDF2ZH="$TMPV/Scripts/pdf2zh.exe"
else
  TMP_PYTHON="$TMPV/bin/python"
  TMP_PDF2ZH="$TMPV/bin/pdf2zh"
fi
if [ ! -f "$TMP_PYTHON" ]; then
  echo "ERROR: venv python not found at $TMP_PYTHON (P16 venv creation failed?)" >&2
  exit 3
fi

# --- P1 hardening: the WRONG 'pdf2zh' dist (1.7.9, unrelated) may already be
#   present (e.g. pre-installed in the managed `default` venv). Remove it so it
#   cannot shadow the pdf2zh_next console script. ---
if "$TMP_PYTHON" -m pip show pdf2zh >/dev/null 2>&1; then
  echo "==> Removing wrong 'pdf2zh' dist (P1) ..."
  "$TMP_PYTHON" -m pip uninstall -y pdf2zh >/dev/null 2>&1 || true
fi

echo "==> Installing pdf2zh_next pymupdf reportlab (P1) ..."
"$TMP_PYTHON" -m pip install pdf2zh_next pymupdf reportlab

# --- P1 sanity: the installed pdf2zh CLI must carry --output ---
if ! "$TMP_PDF2ZH" --help 2>&1 | grep -q -- "--output"; then
  echo "ERROR: installed pdf2zh CLI lacks '--output' — wrong package?" >&2
  echo "       Expected the 'pdf2zh_next' package, NOT the unrelated PyPI 'pdf2zh'." >&2
  echo "       See references/known-pitfalls.md P1." >&2
  exit 4
fi

# --- P3: only rename into place when we built a fresh temp venv ---
if [ "$REUSED_VENV" = "1" ]; then
  echo "==> Backend ready at existing venv $VENV"
else
  if [ -e "$VENV" ] && [ "$TMPV" != "$VENV" ]; then
    BAK="$VENV.bak.$TS"
    mv "$VENV" "$BAK"
    echo "==> Moved existing venv to $BAK (left for manual cleanup)"
  fi
  mv "$TMPV" "$VENV"
  echo "==> Backend installed at $VENV"
fi

# Re-resolve executable paths after a fresh temp venv has moved into place.
if [ -f "$VENV/Scripts/python.exe" ]; then
  VENV_PYTHON="$VENV/Scripts/python.exe"
  VENV_PDF2ZH="$VENV/Scripts/pdf2zh.exe"
else
  VENV_PYTHON="$VENV/bin/python"
  VENV_PDF2ZH="$VENV/bin/pdf2zh"
fi
"$VENV_PDF2ZH" --help >/dev/null 2>&1 && echo "==> pdf2zh CLI OK" || echo "==> pdf2zh CLI CHECK FAILED"

# --- optional P7 notice ---
if [ "$verify_model" = "1" ]; then
  echo "==> 跳过安装阶段的 endpoint 探测；请用显式参数运行 preflight_runtime.py --allow-endpoint-check。"
fi

echo
echo "Next steps:"
echo "  1. 用 --provider/--base-url、--model 与 --api-key 显式配置本次运行。"
echo "  2. Translate: bash run_translate.sh <pdf> --output-dir <out> --provider <name> --model <model> --api-key <key>"
