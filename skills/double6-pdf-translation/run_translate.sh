#!/usr/bin/env bash
# Launcher for the double6-pdf-translation skill.
# Normalizes local paths and forwards only the arguments explicitly supplied by the user.
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

# --- P17: normalize the backend binary path to a NATIVE Windows path. ---
#   Windows subprocess cannot resolve Git-Bash MSYS paths like /c/Users/.../pdf2zh.exe
#   (WinError 2: system cannot find the file). Convert via `cygpath -w` under MSYS.
#   PYTHON_BIN is executed by bash (which converts /c/... on exec), but the pdf2zh
#   binary is handed to Windows Python subprocess, so it MUST be a native C:\... path.
if [ -n "${MSYSTEM:-}" ] && command -v cygpath >/dev/null 2>&1; then
  DEFAULT_PDF2ZH="$(cygpath -w "$DEFAULT_PDF2ZH" 2>/dev/null || echo "$DEFAULT_PDF2ZH")"
fi

# --- P19: path-argument normalizer (shared by binary + input/output args) ---
#   Under Git Bash (MSYS) a path like /d/WorkBuddySpace/... is passed verbatim to
#   Windows Python, which mis-parses it as D:\d\WorkBuddySpace\... (doubled drive
#   letter). That sends outputs to the wrong place and breaks later JSON reads
#   (FileNotFoundError). Convert any path to a native C:\... before handing it to
#   Windows Python. On macOS/Linux (no MSYSTEM) the path is already native.
normalize_path() {
  local p="$1"
  if [ -z "$p" ]; then
    echo ""
    return
  fi
  if [ -n "${MSYSTEM:-}" ] && command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$p" 2>/dev/null || echo "$p"
  else
    echo "$p"
  fi
}

if [ ! -f "$PYTHON_BIN" ]; then
  echo "ERROR: Python interpreter not found at: $PYTHON_BIN" >&2
  echo "       Fix: run scripts/setup_venv.sh or set PDFTR_VENV explicitly." >&2
  exit 2
fi

# --- Backend presence check (fail fast with an actionable message) ---
PDF2ZH_BIN_RAW="${PAPER_TRANSLATION_PDF2ZH_BINARY:-$DEFAULT_PDF2ZH}"
if [ ! -f "$PDF2ZH_BIN_RAW" ]; then
  # P17: maybe the path is an MSYS path that needs conversion for the check itself
  _NATIVE="$(cygpath -w "$PDF2ZH_BIN_RAW" 2>/dev/null || echo "$PDF2ZH_BIN_RAW")"
  if [ ! -f "$_NATIVE" ]; then
    echo "ERROR: pdf2zh backend not found at: $PDF2ZH_BIN_RAW" >&2
    echo "       The skill needs the 'pdf2zh_next' package (NOT the unrelated PyPI 'pdf2zh')." >&2
    echo "       Fix: run  scripts/setup_venv.sh  to install it safely." >&2
    echo "       (See references/known-pitfalls.md P1/P17 for details.)" >&2
    exit 2
  fi
  PDF2ZH_BIN="$_NATIVE"
else
  PDF2ZH_BIN="$PDF2ZH_BIN_RAW"
fi
# P17: normalize to a native Windows path before handing to Windows subprocess
if [ -n "${MSYSTEM:-}" ] && command -v cygpath >/dev/null 2>&1; then
  PDF2ZH_BIN="$(cygpath -w "$PDF2ZH_BIN" 2>/dev/null || echo "$PDF2ZH_BIN")"
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

# --- Pre-run scanned-PDF warning (see SKILL.md 适用范围 / known-pitfalls P15) ---
# This skill targets NON-scanned PDFs. Detect image-only / very-low-text
# inputs BEFORE translation and remind the user early. Warning only — we do
# not hard-block, since some mixed PDFs still translate fine.
INPUT_PDF=""
for a in "$@"; do
  case "$a" in
    -*) continue ;;
    *) [ -f "$a" ] && [[ "$a" == *.pdf ]] && INPUT_PDF="$(normalize_path "$a")" && break ;;
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

# --- P19: rewrite ALL path-valued arguments to NATIVE Windows paths ---
#   See normalize_path() above. We walk "$@" and convert every path argument so
#   Windows Python never sees an MSYS /d/... path.
REW_PATH_FLAGS="--output-dir --pdf2zh-binary --source-override --latex-source --latex-baseline-pdf --engine-home --latex-source-root"
NEW_ARGS=()
input_pdf_rewritten=0
while [ $# -gt 0 ]; do
  arg="$1"
  shift
  # --flag=value form (order matters: longer prefix first so --latex-source-root
  # is not swallowed by --latex-source)
  case "$arg" in
    --latex-source-root=*|--latex-source=*|--output-dir=*|--pdf2zh-binary=*|--source-override=*|--latex-baseline-pdf=*|--engine-home=*)
      flag="${arg%%=*}"
      val="${arg#*=}"
      NEW_ARGS+=("${flag}=$(normalize_path "$val")")
      continue
      ;;
  esac
  # --flag <value> form
  matched=0
  for pf in $REW_PATH_FLAGS; do
    if [ "$arg" = "$pf" ]; then
      NEW_ARGS+=("$arg")
      if [ $# -gt 0 ]; then
        NEW_ARGS+=("$(normalize_path "$1")")
        shift
      fi
      matched=1
      break
    fi
  done
  if [ "$matched" -eq 1 ]; then
    continue
  fi
  # Normalize only the first existing positional PDF. This avoids rewriting an
  # unrelated option value merely because its text happens to end in ".pdf".
  if [ "$input_pdf_rewritten" -eq 0 ] && [[ "$arg" != -* ]] && [[ "$arg" == *.pdf ]] && [ -f "$arg" ]; then
    NEW_ARGS+=("$(normalize_path "$arg")")
    input_pdf_rewritten=1
  else
    NEW_ARGS+=("$arg")
  fi
done

exec "$PYTHON_BIN" "$SKILL_DIR/scripts/run_pdf_translation.py" "${NEW_ARGS[@]}"
