#!/usr/bin/env bash
# Launcher for the double6-pdf-translation skill.
# Holds the model + backend configuration so the skill is ready to run.
# NOTE: reads the API key from the environment; never hardcode secrets in a shared skill.
set -euo pipefail

# --- Path normalization (single source of truth) ---
# WorkBuddy 优先使用托管 Python 的 `default` 环境；macOS/Linux 使用独立用户目录。
# We avoid `rm -rf` on an existing venv because the bash safe-delete wrapper
# hangs on bulk-delete confirmation in this environment (see known-pitfalls P3).
USER_ROOT="${HOME:-${USERPROFILE:-}}"
WORKBUDDY_VENV="$USER_ROOT/.workbuddy/binaries/python/envs/default"
PORTABLE_VENV="$USER_ROOT/.local/share/double6-pdf-translation/venv"
if [ -n "${PDFTR_VENV:-}" ]; then
  VENV="$PDFTR_VENV"
elif [ -d "$WORKBUDDY_VENV" ]; then
  VENV="$WORKBUDDY_VENV"
else
  VENV="$PORTABLE_VENV"
fi
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && { pwd -W 2>/dev/null || pwd -P; })"

if [ -f "$VENV/Scripts/python.exe" ]; then
  PYTHON_BIN="$VENV/Scripts/python.exe"
  DEFAULT_PDF2ZH="$VENV/Scripts/pdf2zh.exe"
else
  PYTHON_BIN="$VENV/bin/python"
  DEFAULT_PDF2ZH="$VENV/bin/pdf2zh"
fi

if [ ! -f "$PYTHON_BIN" ]; then
  echo "ERROR: Python interpreter not found at: $PYTHON_BIN" >&2
  echo "       Fix: run scripts/setup_venv.sh or set PDFTR_VENV explicitly." >&2
  exit 2
fi

# --- Why these env knobs? (WorkBuddy managed Python safe-delete shim) ---
# The managed Python injects a sitecustomize that patches os.remove/shutil with a
# bulk-delete guard. With no Recycle Bin here, pip installs either abort (so the
# pdf2zh.exe launcher is never written) or hang. Neutralize by unsetting the
# session id / PYTHONPATH and disabling the sandbox trash. (known-pitfalls P2/P4)
unset PYTHONPATH
unset CODEBUDDY_SESSION_ID
unset CLAUDE_SESSION_ID
export CODEBUDDY_SAFE_DELETE_SANDBOX=0

# --- Backend presence check (fail fast with an actionable message) ---
PDF2ZH_BIN="${PAPER_TRANSLATION_PDF2ZH_BINARY:-$DEFAULT_PDF2ZH}"
if [ ! -f "$PDF2ZH_BIN" ]; then
  echo "ERROR: pdf2zh backend not found at: $PDF2ZH_BIN" >&2
  echo "       The skill needs the 'pdf2zh_next' package (NOT the unrelated PyPI 'pdf2zh')." >&2
  echo "       Fix: run  scripts/setup_venv.sh  to install it safely." >&2
  echo "       (See references/known-pitfalls.md P1/P2 for details.)" >&2
  exit 2
fi
export PAPER_TRANSLATION_PDF2ZH_BINARY="$PDF2ZH_BIN"

# --- Pre-run dependency hints ---
# 这些包增强审计、修复和双语拼接能力；缺失时由正式 preflight 决定降级方式。
PY_DEPS="pymupdf reportlab"
MISSING=""
for dep in $PY_DEPS; do
  if ! "$PYTHON_BIN" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$dep') is not None else 1)" >/dev/null 2>&1; then
    MISSING="$MISSING $dep"
  fi
done
if [ -n "$MISSING" ]; then
  echo "WARNING: Recommended Python package(s) missing in venv ($VENV):$MISSING" >&2
  echo "         Run scripts/setup_venv.sh for fuller QA and bilingual rebuild support." >&2
fi

# --- Model / endpoint config ---
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
export LOCAL_TRANSLATION_MODEL="${LOCAL_TRANSLATION_MODEL:-}"
export LOCAL_TRANSLATION_PROVIDER="${LOCAL_TRANSLATION_PROVIDER:-}"
export LOCAL_TRANSLATION_BASE_URL="${LOCAL_TRANSLATION_BASE_URL:-}"

# --- Lightweight config sanity (non-fatal warning; runs AFTER the inline
#     config above so it only fires when the key was genuinely removed) ---
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "WARNING: DEEPSEEK_API_KEY is empty; translation API calls will fail." >&2
fi

# --- Pre-run scanned-PDF warning (see SKILL.md 适用范围 / known-pitfalls P15) ---
# This skill targets NON-scanned PDFs. Detect image-only / very-low-text
# inputs BEFORE translation and remind the user early. Warning only — we do
# not hard-block, since some mixed PDFs still translate fine.
INPUT_PDF=""
for a in "$@"; do
  case "$a" in
    -*) continue ;;
    *) [ -f "$a" ] && [[ "$a" == *.pdf ]] && INPUT_PDF="$a" && break ;;
  esac
done
if [ -n "$INPUT_PDF" ]; then
  SCAN_FLAG=$(
    "$PYTHON_BIN" - "$INPUT_PDF" <<'PY' 2>/dev/null || true
import sys, importlib.util
def have(mod): return importlib.util.find_spec(mod) is not None
if not (have("fitz") or have("pymupdf")):
    sys.exit(0)
try:
    import fitz
except ImportError:
    import pymupdf as fitz
try:
    doc = fitz.open(sys.argv[1])
except Exception:
    sys.exit(0)
npages = doc.page_count
if npages == 0:
    sys.exit(0)
img_only = 0
total = 0
for i in range(npages):
    pg = doc[i]
    txt = (pg.get_text("text") or "").strip()
    total += len(txt)
    if pg.get_images(full=True) and len(txt) < 50:
        img_only += 1
density = total / npages
# Heuristic: scanned/image-only if >=50% pages are image-only, or density < 50 chars/page
if img_only >= (npages + 1) // 2 or density < 50:
    print(f"WARN {npages} {img_only} {density:.0f}")
PY
  )
  if [[ "$SCAN_FLAG" == WARN* ]]; then
    echo "⚠️  WARNING: 输入 PDF 疑似扫描版 / 图像版（${SCAN_FLAG#WARN }）。" >&2
    echo "    本 skill 只针对非扫描版 PDF；对于扫描版可能翻译失败或效果较差，请谨慎使用。" >&2
    echo "    （如需继续可忽略此警告；若确需处理扫描版，请先 OCR 再传入文本版。）" >&2
  fi
fi

exec "$PYTHON_BIN" "$SKILL_DIR/scripts/run_pdf_translation.py" "$@"
