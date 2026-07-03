#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from html import escape
from pathlib import Path
from typing import Any


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def markdown_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    buffer: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("<!--"):
            continue
        if not line.strip():
            if buffer:
                blocks.append(("paragraph", "\n".join(buffer).strip()))
                buffer = []
            continue
        if line.startswith("#"):
            if buffer:
                blocks.append(("paragraph", "\n".join(buffer).strip()))
                buffer = []
            level = min(len(line) - len(line.lstrip("#")), 3)
            blocks.append((f"heading{level}", line.lstrip("#").strip()))
        elif line.startswith("- "):
            if buffer:
                blocks.append(("paragraph", "\n".join(buffer).strip()))
                buffer = []
            blocks.append(("bullet", line[2:].strip()))
        else:
            buffer.append(line)
    if buffer:
        blocks.append(("paragraph", "\n".join(buffer).strip()))
    return blocks


def clean_inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", escape(text))
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.replace("\n", "<br/>")


def render_pdf(markdown_path: Path, output_path: Path, title: str = "") -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "ChineseBase",
        parent=styles["Normal"],
        fontName="STSong-Light",
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#202124"),
        spaceAfter=6,
    )
    heading1 = ParagraphStyle("H1", parent=base, fontSize=18, leading=24, spaceBefore=10, spaceAfter=12)
    heading2 = ParagraphStyle("H2", parent=base, fontSize=15, leading=21, spaceBefore=8, spaceAfter=10)
    heading3 = ParagraphStyle("H3", parent=base, fontSize=12.5, leading=18, spaceBefore=6, spaceAfter=8)
    bullet = ParagraphStyle("Bullet", parent=base, leftIndent=12, firstLineIndent=-8)
    story = []
    if title:
        story.append(Paragraph(clean_inline(title), heading1))
        story.append(Spacer(1, 4 * mm))
    for kind, value in markdown_blocks(load_text(markdown_path)):
        if value == "---":
            story.append(PageBreak())
            continue
        style = {"heading1": heading1, "heading2": heading2, "heading3": heading3, "bullet": bullet}.get(kind, base)
        prefix = "• " if kind == "bullet" else ""
        story.append(Paragraph(prefix + clean_inline(value), style))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title or markdown_path.stem,
    )
    doc.build(story)
    return {
        "version": 1,
        "status": "ok",
        "input_markdown": str(markdown_path),
        "output_pdf": str(output_path),
        "renderer": "reportlab",
        "font": "STSong-Light",
        "delivery_type": "readable_fallback_pdf",
        "notes": [
            "该 PDF 是 QA 修复后的可读交付件，不承诺复刻原 PDF 版式。",
            "原版式译文 PDF 仍保留在 render_manifest.outputs 中。",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render repaired Markdown translation to a readable PDF.")
    parser.add_argument("--input", required=True, help="Input Markdown path.")
    parser.add_argument("--output", help="Output PDF path. Defaults to final_readable.pdf beside input.")
    parser.add_argument("--manifest", help="Output manifest JSON. Defaults to final_pdf_manifest.json beside input.")
    parser.add_argument("--title", default="论文译文可读修复版")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_name("final_readable.pdf")
    manifest_path = Path(args.manifest) if args.manifest else input_path.with_name("final_pdf_manifest.json")
    manifest = render_pdf(input_path, output_path, title=args.title)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output_pdf": str(output_path), "manifest": str(manifest_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
