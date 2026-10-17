# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""安装目录与用户运行目录分离；导入时不创建文件。"""
from pathlib import Path
import os
SKILL_ROOT = Path(__file__).resolve().parents[1]
def workspace_root():
    configured = os.environ.get("PAPER_TRANSLATION_WORKSPACE")
    return Path(configured).expanduser().resolve() if configured else Path.home() / ".local/share/double6-pdf-translation"


def engine_home():
    configured = os.environ.get("PAPER_TRANSLATION_ENGINE_HOME")
    return Path(configured).expanduser().resolve() if configured else workspace_root() / ".cache/paper-translation/pdf2zh-home"
