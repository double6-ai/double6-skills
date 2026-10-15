"""pytest 入口：让 `pytest` 无需手动设置 PYTHONPATH 即可导入 double6_ppt_cli。

依赖：先执行 `pip install -r requirements-core.lock pytest`（skill 根目录）。
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
