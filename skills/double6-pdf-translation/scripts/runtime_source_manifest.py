# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""冻结当前安装的完整Python执行源码，覆盖入口拆分后的实现模块。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

SCRIPT_INTERFACE = 'cli'
SCRIPT_INTERFACE_REASON = '为调用方生成冻结合同使用的实际安装源码引用。'


def implementation_refs(root=None):
    scripts = Path(root) if root is not None else Path(__file__).resolve().parent
    result = []
    for path in sorted(scripts.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        if path.is_symlink():
            raise ValueError('implementation_source_symlink')
        result.append({'path': str(path.resolve()),
                       'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='列出当前安装的完整Python执行源码引用')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump({'schema_version': 1, 'implementation_refs': implementation_refs()},
                  stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
