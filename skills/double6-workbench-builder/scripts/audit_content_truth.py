#!/usr/bin/env python3
"""审计 Double6 内容真值 JSON；失败时返回非零退出码。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from double6_runtime.content_truth import audit_content_truth_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="审计 Double6 用户可见内容的真值、一致性与安全合同")
    parser.add_argument("bundle", type=Path, help="内容真值表 JSON")
    parser.add_argument("--write-receipt", type=Path, help="可选：写出审计回执")
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    receipt = audit_content_truth_bundle(bundle)
    for item in bundle.get("items", []):
        review = item.get("review", {})
        relative = Path(str(review.get("review_receipt_path") or ""))
        target = (args.bundle.parent / relative).resolve()
        expected = str(review.get("review_receipt_sha256") or "")
        actual = hashlib.sha256(target.read_bytes()).hexdigest() if relative.as_posix() not in {"", "."} and target.is_file() else None
        if actual != expected:
            receipt["findings"].append({"item_id": str(item.get("item_id") or "$unknown"), "code": "review_receipt_hash_mismatch", "severity": "blocking", "message": "独立审稿回执缺失或 SHA256 不匹配。"})
    if receipt["findings"]:
        receipt["finding_count"] = len(receipt["findings"])
        receipt["blocking_count"] = sum(row["severity"] == "blocking" for row in receipt["findings"])
        receipt["major_count"] = sum(row["severity"] == "major" for row in receipt["findings"])
        receipt["status"] = "fail" if receipt["blocking_count"] or receipt["major_count"] else "pass"
    payload = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.write_receipt:
        args.write_receipt.parent.mkdir(parents=True, exist_ok=True)
        args.write_receipt.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if receipt["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
