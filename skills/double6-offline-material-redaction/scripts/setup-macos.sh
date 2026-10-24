#!/bin/sh
# 复用已有受支持Python；不修改全局PATH或系统Python。
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys,platform;sys.exit(not ((3,10)<=sys.version_info[:2]<=(3,14) and platform.machine().lower() in {"arm64","aarch64"}))' 2>/dev/null; then
    exec "$candidate" "$script_dir/bootstrap.py" "$@"
  fi
done
echo '未找到Apple芯片Python3.10–3.14。请从python.org按正常方式安装受支持版本，再运行本入口；不要替换系统Python。' >&2
exit 4
