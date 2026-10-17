"""为有限页数的既有译文生成逐页审校证据，不翻译、不修改原运行、不授予验收。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

from assess_delivery import check_bilingual_sides, inspect_pdf, sha256
from build_bilingual_pdf import build_en_left_zh_right_pdf


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_visibility(page: Any) -> dict[str, Any]:
    """文本绘制状态属于候选证据；有色可绘制文字仍可能被后续图像遮挡。"""
    rendered, hidden, suspects = [], [], []
    for span in page.get_texttrace():
        text = "".join(chr(char[0]) for char in span.get("chars", []) if 0 <= char[0] <= 0x10ffff)
        invisible = span.get("type") == 3 or span.get("opacity", 1) == 0
        (hidden if invisible else rendered).append(text)
        color = span.get("color")
        if not invisible and color and all(float(v) >= .98 for v in color):
            suspects.append({"reason": "near_white_text_requires_background_check", "text": text, "bbox": list(span["bbox"])})
    cjk = lambda text: len(re.findall(r"[\u3400-\u9fff]", text))
    return {"painted_text": "\n".join(rendered), "hidden_text": "\n".join(hidden),
            "painted_cjk": sum(cjk(t) for t in rendered), "hidden_cjk": sum(cjk(t) for t in hidden),
            "suspects": suspects, "visibility_accepted": False,
            "limitation": "PDF drawing-state inventory only; occlusion, paper contrast and visual readability require rendered-page review"}


def build_packet(source: Path, target: Path, output: Path, *, scan_regions: Path | None = None,
                 bilingual: Path | None = None, max_pages: int = 5) -> dict[str, Any]:
    import fitz
    source, target, output = source.resolve(), target.resolve(), output.resolve()
    if not 1 <= max_pages <= 20:
        raise ValueError("review packets are limited to 1–20 pages")
    identities = {"source": inspect_pdf(source, max_pages), "candidate": inspect_pdf(target, max_pages)}
    if any(x["status"] != "ok" for x in identities.values()):
        raise ValueError("valid PDFs inside the page budget are required")
    regions = []
    if scan_regions:
        if scan_regions.stat().st_size > 16 * 1024**2:
            raise ValueError("scan region inventory exceeds 16 MiB")
        regions = [json.loads(line) for line in scan_regions.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in regions:
            if row.get("source_pdf_sha256") != identities["source"]["sha256"] or type(row.get("page")) is not int or not 1 <= row["page"] <= identities["source"]["page_count"]:
                raise ValueError("scan region input identity or page mismatch")
    output.mkdir(parents=True, exist_ok=False)
    (output / "pages").mkdir()
    manifest: dict[str, Any] = {"schema_version": 1, "status": "building", "identity": identities,
                              "semantic_accepted": False, "visual_accepted": False, "human_accepted": False,
                              "model_calls": 0, "generator_sha256": sha256(Path(__file__))}
    write(output / "review_packet.json", manifest)
    summaries = []
    with fitz.open(source) as source_doc, fitz.open(target) as target_doc:
        for i in range(max(len(source_doc), len(target_doc))):
            source_text = source_doc[i].get_text() if i < len(source_doc) else None
            target_text = target_doc[i].get_text() if i < len(target_doc) else None
            page_regions = [r for r in regions if r["page"] == i + 1]
            visibility = text_visibility(target_doc[i]) if i < len(target_doc) else {}
            pairs = [{key: r.get(key) for key in ("region_id", "page", "bbox", "layout_role", "reading_order", "normalized_text", "translation", "status", "skip_reason", "overflow", "occluded", "translation_group_id")} for r in page_regions]
            page = {"page": i + 1, "source_text": source_text, "target_text": target_text,
                    "source_ocr_pairs": pairs, "source_ocr_verified": False if pairs else None,
                    "target_visibility": visibility}
            write(output / "pages" / f"page-{i+1:04d}.json", page)
            summaries.append({"page": i + 1, "source_chars": len(source_text or ""), "target_chars": len(target_text or ""),
                              "ocr_regions": len(pairs), "painted_cjk": visibility.get("painted_cjk", 0),
                              "hidden_cjk": visibility.get("hidden_cjk", 0), "visibility_suspects": len(visibility.get("suspects", []))})
    if bilingual is None:
        bilingual = output / "bilingual.review.pdf"
        manifest["bilingual_build"] = build_en_left_zh_right_pdf(source, target, bilingual)
    manifest["bilingual"] = {"path": str(bilingual.resolve()), "sha256": sha256(bilingual),
                             "side_check": check_bilingual_sides(source, target, bilingual, max_pages)}
    if scan_regions:
        manifest["scan_regions"] = {"path": str(scan_regions.resolve()), "sha256": sha256(scan_regions), "source_truth": "OCR candidate; must compare with source page image"}
    manifest.update(status="ready_for_review", pages=summaries,
                    inputs_unchanged=sha256(source) == identities["source"]["sha256"] and sha256(target) == identities["candidate"]["sha256"])
    if not manifest["inputs_unchanged"]:
        manifest["status"] = "invalid_input_changed"
    write(output / "review_packet.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scan-regions", type=Path)
    parser.add_argument("--bilingual", type=Path)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()
    result = build_packet(args.source, args.candidate, args.output, scan_regions=args.scan_regions, bilingual=args.bilingual, max_pages=args.max_pages)
    print(json.dumps({"status": result["status"], "page_count": len(result["pages"]), "bilingual": result["bilingual"]["side_check"]["status"]}))
    return 0 if result["status"] == "ready_for_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
