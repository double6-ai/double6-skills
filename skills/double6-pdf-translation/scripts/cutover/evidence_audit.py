from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable


EXPECTED_AI_NAMES = (
    "McKinsey & Company",
    "Heather Hanselman",
    "Katherine Ottenbreit",
    "Brittany Presten",
    "Cécile Prinsen",
    "Roger Roberts",
    "Abby Sticha",
)
FORBIDDEN_AI_TRANSLATED_NAMES = ("麦肯锡公司", "希瑟·汉塞尔曼", "凯瑟琳·奥滕布赖特")
MAX_PORTRAIT_MEAN_ABS_RGB_DIFF = 8.0


def normalize_text(value: str) -> str:
    """统一 Unicode、空白与换行，供文本层证据比较使用。"""
    value = unicodedata.normalize("NFKC", value or "")
    return re.sub(r"\s+", " ", value).strip()


def heading_gap(lines: Iterable[dict[str, Any]], heading: str) -> dict[str, Any]:
    ordered = sorted(lines, key=lambda item: (float(item["bbox"][1]), float(item["bbox"][0])))
    target = normalize_text(heading)
    for index, line in enumerate(ordered):
        if normalize_text(str(line.get("text", ""))) != target:
            continue
        heading_bbox = line.get("bbox") or []
        for candidate in ordered[index + 1 :]:
            candidate_bbox = candidate.get("bbox") or []
            if len(heading_bbox) >= 4 and len(candidate_bbox) >= 4 and candidate_bbox[1] >= heading_bbox[1]:
                return {
                    "status": "ok",
                    "gap_pt": max(0.0, float(candidate_bbox[1]) - float(heading_bbox[3])),
                    "heading_line": line,
                    "first_body_line": candidate,
                }
        return {"status": "missing_body", "heading_line": line}
    return {"status": "missing_heading", "heading": heading}


def mean_abs_diff(left: Any, right: Any) -> float:
    left_rgb = left.convert("RGB")
    right_rgb = right.convert("RGB")
    if left_rgb.size != right_rgb.size:
        raise ValueError("images must have the same dimensions")
    left_bytes = left_rgb.tobytes()
    right_bytes = right_rgb.tobytes()
    if not left_bytes:
        return 0.0
    return sum(abs(a - b) for a, b in zip(left_bytes, right_bytes)) / len(left_bytes)


def audit_text(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    missing = [name for name in EXPECTED_AI_NAMES if normalize_text(name) not in normalized]
    forbidden = [name for name in FORBIDDEN_AI_TRANSLATED_NAMES if name in normalized]
    return {"status": "ok" if not missing and not forbidden else "failed", "missing_names": missing, "forbidden_names": forbidden}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计 strict cutover 文本证据")
    parser.add_argument("text_file", type=Path)
    args = parser.parse_args(argv)
    result = audit_text(args.text_file.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
