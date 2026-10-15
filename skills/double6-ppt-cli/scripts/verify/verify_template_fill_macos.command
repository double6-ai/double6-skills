#!/bin/bash
cd "$(dirname "$0")"
python3 verify_template_fill.py "$@"
read -n 1 -s -r -p "按任意键关闭 / press any key"
