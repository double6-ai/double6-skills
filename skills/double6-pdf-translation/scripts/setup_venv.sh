#!/usr/bin/env bash
# 为本skill创建独立新环境，不修改共享Python环境。
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo '用法：bash scripts/setup_venv.sh /absolute/new/venv' >&2
  exit 2
fi
TARGET_ENV="$1"
case "$TARGET_ENV" in /*) ;; *) echo '环境路径须为绝对路径' >&2; exit 2 ;; esac
if [ -e "$TARGET_ENV" ] || [ -L "$TARGET_ENV" ]; then
  echo '目标已存在，请提供全新环境目录' >&2
  exit 2
fi
SKILL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
command -v uv >/dev/null || { echo '请先安装uv和Python 3.12' >&2; exit 2; }
PYTHON_BIN="${PDFTR_PYTHON:-$(uv python find 3.12 --no-python-downloads)}"
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3,12), "需要Python 3.12"'
uv venv --python "$PYTHON_BIN" --no-python-downloads "$TARGET_ENV"
ENV_PYTHON="$TARGET_ENV/bin/python"
uv pip install --python "$ENV_PYTHON" --require-hashes -r "$SKILL_ROOT/requirements-runtime.lock"
# rapidocr 的安装声明会带上带界面的 opencv-python。这里只装本体，图像库用 headless。
uv pip install --python "$ENV_PYTHON" --require-hashes --no-deps -r "$SKILL_ROOT/requirements-rapidocr.lock"
uv pip install --python "$ENV_PYTHON" --require-hashes --no-deps -r "$SKILL_ROOT/requirements-build.lock"
uv pip install --python "$ENV_PYTHON" --no-deps --no-build-isolation "$SKILL_ROOT/vendor/pdfmathtranslate_next"
# 打包 PDFMathTranslate 时用到的工具，运行时不再保留。tomlkit 与 packaging 在运行锁里。
uv pip uninstall --python "$ENV_PYTHON" hatchling editables pathspec pluggy trove-classifiers setuptools
# Python distribution版本来自安装元数据，实际BabelDOC执行优先使用随包修复源码。
"$ENV_PYTHON" - "$SKILL_ROOT" <<'PY'
import pathlib,sys,sysconfig
root=pathlib.Path(sys.argv[1]).resolve()
pth=pathlib.Path(sysconfig.get_paths()['purelib'])/'double6_pdf_translation.pth'
pth.write_text('import sys; sys.path.insert(0, '+repr(str(root/'vendor/babeldoc'))+')\n',encoding='utf-8')
PY
"$ENV_PYTHON" "$SKILL_ROOT/scripts/paper_translation_workflow.py" --help >/dev/null
# 新环境须实际导入主路径原生扩展，避免仅凭 --help 宣告安装成功。
# 首次模块装载属于安装核验；论文处理仍使用其独立资源与时限。
"$ENV_PYTHON" - <<'PY'
import os, subprocess, sys
env = dict(os.environ)
env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1', VECLIB_MAXIMUM_THREADS='1')
subprocess.run(
    [sys.executable, '-c', '''
import importlib.metadata as metadata
import cv2, onnx, onnxruntime, pymupdf, rapidocr_onnxruntime, tomlkit
from sklearn.cluster import DBSCAN
from babeldoc.docvision.doclayout import OnnxModel
from babeldoc.main import create_progress_handler
for name in ("opencv-python", "ruff", "lxml", "huggingface-hub", "uharfbuzz", "babeldoc"):
    try:
        metadata.version(name)
    except metadata.PackageNotFoundError:
        continue
    raise SystemExit("unexpected package: " + name)
metadata.version("opencv-python-headless")
'''],
    env=env, check=True, timeout=180,
)
PY
printf '环境已准备：%s\n' "$ENV_PYTHON"
printf '下一步：按SKILL.md核定输入，并明确配置模型与服务地址。\n'
