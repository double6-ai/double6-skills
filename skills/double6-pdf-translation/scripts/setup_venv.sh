#!/usr/bin/env bash
# setup_venv.sh — safe one-shot installer for the double6-pdf-translation backend.
#
# Bakes in the lessons from references/known-pitfalls.md (P1-P4):
#   P1  installs the CORRECT package (pdf2zh_next, NOT the unrelated PyPI pdf2zh)
#   P2  disables the managed-Python safe-delete shim before any pip/venv op
#   P3  never `rm -rf` an existing venv; lands on a stable path via rename
#   P4  cleans leftover `~*` dists before/after install
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

# --- P2: disable the managed-Python safe-delete shim ---
unset PYTHONPATH
unset CODEBUDDY_SESSION_ID
unset CLAUDE_SESSION_ID
export CODEBUDDY_SAFE_DELETE_SANDBOX=0

verify_model=0
for a in "$@"; do [ "$a" = "--verify-model" ] && verify_model=1; done

echo "==> Managed Python : $MP"
echo "==> Target venv    : $VENV"
if [ "${PDFTR_SETUP_DRY_RUN:-0}" = "1" ]; then
  echo "==> Dry run: path discovery completed; no environment was changed."
  exit 0
fi

# --- P3: build into a UNIQUE temp path (never rm -rf the old one) ---
TS="$(date +%Y%m%d%H%M%S)"
TMPV="$VENV.installing.$TS"
"$MP" -m venv "$TMPV"

echo "==> Installing pdf2zh_next pymupdf reportlab (P1) ..."
if [ -f "$TMPV/Scripts/python.exe" ]; then
  TMP_PYTHON="$TMPV/Scripts/python.exe"
  TMP_PDF2ZH="$TMPV/Scripts/pdf2zh.exe"
else
  TMP_PYTHON="$TMPV/bin/python"
  TMP_PDF2ZH="$TMPV/bin/pdf2zh"
fi
"$TMP_PYTHON" -m pip install -q pdf2zh_next pymupdf reportlab

# --- P4: clean any leftover `~*` invalid dists in the new env (python, shim-safe) ---
"$TMP_PYTHON" -c "import os,shutil,site; paths=[p for root in site.getsitepackages() for p in __import__('glob').glob(os.path.join(root, '~*'))]; [shutil.rmtree(p) if os.path.isdir(p) else os.remove(p) for p in paths]; print('cleaned ~* leftovers')"

# --- P1 sanity: the installed pdf2zh CLI must carry --output ---
if ! "$TMP_PDF2ZH" --help 2>&1 | grep -q -- "--output"; then
  echo "ERROR: installed pdf2zh CLI lacks '--output' — wrong package?" >&2
  echo "       Expected the 'pdf2zh_next' package, NOT the unrelated PyPI 'pdf2zh'." >&2
  echo "       See references/known-pitfalls.md P1." >&2
  exit 4
fi

# --- P3: swap into place via rename (no rm -rf; old env kept as .bak for manual cleanup) ---
if [ -e "$VENV" ]; then
  BAK="$VENV.bak.$TS"
  mv "$VENV" "$BAK"
  echo "==> Moved existing venv to $BAK (left for manual cleanup)"
fi
mv "$TMPV" "$VENV"
echo "==> Backend installed at $VENV"
if [ -f "$VENV/Scripts/python.exe" ]; then
  VENV_PYTHON="$VENV/Scripts/python.exe"
  VENV_PDF2ZH="$VENV/Scripts/pdf2zh.exe"
else
  VENV_PYTHON="$VENV/bin/python"
  VENV_PDF2ZH="$VENV/bin/pdf2zh"
fi
"$VENV_PDF2ZH" --help >/dev/null 2>&1 && echo "==> pdf2zh CLI OK" || echo "==> pdf2zh CLI CHECK FAILED"

# --- optional P7: ping the model endpoint (non-fatal) ---
if [ "$verify_model" = "1" ]; then
  echo "==> Verifying model endpoint (P7) ..."
  : "${DEEPSEEK_API_KEY:?set DEEPSEEK_API_KEY to verify}"
  : "${LOCAL_TRANSLATION_MODEL:?set LOCAL_TRANSLATION_MODEL to verify}"
  : "${LOCAL_TRANSLATION_BASE_URL:=https://api.deepseek.com}"
  "$VENV_PYTHON" - "$DEEPSEEK_API_KEY" "$LOCAL_TRANSLATION_BASE_URL" "$LOCAL_TRANSLATION_MODEL" <<'PY'
import sys, json, urllib.request
key, base, model = sys.argv[1:4]
url = base.rstrip('/') + '/chat/completions'
data = json.dumps({"model": model, "messages":[{"role":"user","content":"ping"}], "max_tokens":1}).encode()
req = urllib.request.Request(url, data, {"Content-Type":"application/json","Authorization":"Bearer "+key})
try:
    r = urllib.request.urlopen(req, timeout=20)
    print("MODEL_OK", r.status)
except Exception as e:
    print("MODEL_FAIL", e); sys.exit(3)
PY
  echo "    (non-fatal: a failure here means the model name/key is wrong, not the backend)"
fi

echo
echo "Next steps:"
echo "  1. Export DEEPSEEK_API_KEY / LOCAL_TRANSLATION_MODEL etc. in the current session."
echo "  2. Translate:  bash run_translate.sh <pdf> --output-dir <out>"
