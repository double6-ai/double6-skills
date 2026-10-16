#!/usr/bin/env python3
"""拦跨场景邻域词和假提交语气。首页主活动仍由各场景今晚检查器负责。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from double6_runtime.domain_remnants import audit_skill_sources  # noqa: E402


def check_domain_remnant_sources() -> list[str]:
    return audit_skill_sources(SKILL)


def check_all() -> dict:
    errors = check_domain_remnant_sources()
    return {"ok": not errors, "failed": len(errors), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="审查领域残留和假提交语气")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check_all()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"领域残留检查失败 {result['failed']} 条")
        for error in result["errors"]:
            print(f"  · {error}")
        if result["ok"]:
            print("运行时没有邻域壳，也没有把本地动作写成已经外发。")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
