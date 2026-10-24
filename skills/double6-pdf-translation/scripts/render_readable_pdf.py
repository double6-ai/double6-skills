#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from html import escape
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def markdown_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    buffer: list[str] = []
    for raw_line in text.replace("\f", "\n").splitlines():
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


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont

    pdfmetrics.registerFont(UnicodeCIDFont(REFLOW_FONT))
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "ChineseBase",
        parent=styles["Normal"],
        fontName=REFLOW_FONT,
        fontSize=10.5,
        leading=16,
        textColor=colors.HexColor("#202124"),
        spaceAfter=6,
    )
    return {
        "base": base,
        "heading1": ParagraphStyle("H1", parent=base, fontSize=18, leading=24, spaceBefore=10, spaceAfter=12),
        "heading2": ParagraphStyle("H2", parent=base, fontSize=15, leading=21, spaceBefore=8, spaceAfter=10),
        "heading3": ParagraphStyle("H3", parent=base, fontSize=12.5, leading=18, spaceBefore=6, spaceAfter=8),
        "bullet": ParagraphStyle("Bullet", parent=base, leftIndent=12, firstLineIndent=-8),
    }


def _reflow_pdf(text: str, output_path: Path, *, heading: str = "", title: str = "") -> None:
    """原有的 reportlab 重排（STSong-Light）；只用于不含数学结构的页。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    styles = _styles()
    story = []
    if heading:
        story.append(Paragraph(clean_inline(heading), styles["heading1"]))
        story.append(Spacer(1, 4 * mm))
    for kind, value in markdown_blocks(text):
        if value == "---":
            story.append(PageBreak())
            continue
        style = styles.get(kind, styles["base"])
        prefix = "• " if kind == "bullet" else ""
        story.append(Paragraph(prefix + clean_inline(value), style))
    if not story:
        story.append(Spacer(1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title,
    )
    doc.build(story)


# ---- PR #25 公式保真：可读版不得丢失数学字形或压平上下标/矩阵/大型运算符 ----
REFLOW_FONT = "STSong-Light"
PAGE_MARKER = re.compile(r"^<!--\s*page:(\d+)\s*-->\s*$", re.MULTILINE)
REFUSAL_CODES = (
    "readable_page_mapping_unknown",       # 有数学页，但译文 Markdown 与主版式 PDF 的页对应关系无法确定
    "readable_math_page_repair_conflict",  # QA 修复改动了需整页矢量保留的数学页文字，无法同时保真
    "readable_math_source_structure_lost", # 主版式成品该页的上/下标层级本身已丢失（见 formula_structure_check）
    "readable_codepoint_loss",             # 成品可读版文字层丢失了 Markdown 中的字符（字体不覆盖等）
    "readable_vector_copy_mismatch",       # 整页矢量复制后的文字层与主版式页不一致
    "readable_math_source_missing",        # 原文含数学结构，但没有可矢量复制的主版式译文 PDF（如后端失败）
    "readable_math_structure_unverifiable", # 原文含数学结构，但原文/主版式的数学证据或结构核对无法完成
)


def significant_codepoints(text: str) -> Counter:
    """重排字体可能不覆盖、且一旦丢失就改变内容的字符：非 ASCII、非空白、非汉字/全角标点。"""
    counter: Counter = Counter()
    for ch in text:
        code = ord(ch)
        if ch.isascii() or ch.isspace() or unicodedata.category(ch)[0] in "ZC":
            continue
        if 0x4E00 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F or 0xFF00 <= code <= 0xFFEF:
            continue
        counter[ch] += 1
    return counter


def _codepoint_loss(expected: Counter, actual: Counter) -> dict[str, list[int]]:
    return {f"U+{ord(ch):04X}": [count, actual.get(ch, 0)] for ch, count in sorted(expected.items())
            if actual.get(ch, 0) < count}


def _rendered_text(pdf_path: Path) -> str:
    import fitz

    with fitz.open(pdf_path) as doc:
        return "".join(page.get_text() for page in doc)


def _markdown_text_for_census(text: str) -> str:
    """与重排输入一致的可见文字：去掉注释行，按 clean_inline 的规则去掉 Markdown 标记。"""
    parts = []
    for kind, value in markdown_blocks(text):
        if value == "---":
            continue
        visible = re.sub(r"`([^`]+)`", r"\1", value)
        visible = re.sub(r"\*\*([^*]+)\*\*", r"\1", visible)
        visible = re.sub(r"\*([^*]+)\*", r"\1", visible)
        parts.append(visible)
    return "\n".join(parts)


def split_markdown_pages(text: str) -> tuple[dict[int, str] | None, str]:
    """按页切分译文 Markdown：PyMuPDF/pypdf 抽取带 ``<!-- page:N -->``，pdftotext 用换页符分页。
    返回 ({页号: 文本}, 方式)；无法确定页边界时返回 (None, 原因)。"""
    markers = list(PAGE_MARKER.finditer(text))
    if markers:
        pages: dict[int, str] = {}
        if text[: markers[0].start()].strip():
            return None, "text_before_first_page_marker"
        for index, match in enumerate(markers):
            number = int(match.group(1))
            stop = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            if number in pages:
                return None, "duplicate_page_marker"
            pages[number] = text[match.end(): stop]
        return pages, "page_markers"
    if "\f" in text:
        return {index + 1: chunk for index, chunk in enumerate(text.split("\f"))}, "form_feed"
    return {1: text}, "single_segment"


def page_math_evidence(page) -> dict[str, Any]:
    """主版式页里重排无法无损表示的数学证据：数学字体字形、数学符号/希腊字母、私用区（拆件括号等）字形、
    上/下标关系。任意一项非零即该页须整页矢量保留。"""
    import formula_structure_check as structure
    from pdf_input_preflight import _is_math_char

    glyphs = structure._glyphs(page)
    math_font = sum(1 for g in glyphs if structure.STRICT_MATH_FONT.search(g["font"]))
    math_chars = sum(1 for g in glyphs if _is_math_char(g["c"]))
    private_use = sum(1 for g in glyphs if 0xE000 <= ord(g["c"]) <= 0xF8FF)
    relations = len(structure.script_relations(page))
    return {"math_font_glyphs": math_font, "math_codepoints": math_chars, "private_use_glyphs": private_use,
            "script_relations": relations, "has_math": bool(math_font or math_chars or private_use or relations)}


def explicit_input_unavailable(path: Path | str | None) -> str | None:
    """显式提供的输入文件能否读取：None 表示未提供或可读；否则返回不可用原因（不存在、不是普通文件、
    无读取权限、stat/打开抛 OSError 等）。调用方据此拒绝，不把“读不到”当作“没有数学”。"""
    import os
    import stat

    if path is None:
        return None
    try:
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            return "not_a_regular_file"
        with open(path, "rb") as handle:
            handle.read(1)
    except FileNotFoundError:
        return "missing"
    except PermissionError as exc:
        return f"permission_denied: {exc}"
    except (OSError, ValueError) as exc:  # ValueError：路径含 NUL 等
        return f"{type(exc).__name__}: {exc}"
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _reflow_loss(segment: str, part: Path, *, heading: str = "", title: str = "") -> tuple[dict[str, list[int]], int]:
    _reflow_pdf(segment, part, heading=heading, title=title)
    expected = significant_codepoints(_markdown_text_for_census(segment) + ("\n" + heading if heading else ""))
    return _codepoint_loss(expected, significant_codepoints(_rendered_text(part))), sum(expected.values())


def render_pdf(markdown_path: Path, output_path: Path, title: str = "", *, math_source_pdf: Path | None = None,
               source_pdf: Path | None = None, original_markdown_path: Path | None = None) -> dict[str, Any]:
    """渲染可读版。含数学结构（或重排字体会丢字符）的页整页矢量复制主版式成品页（公式、上下标、矩阵括号、
    Δ、† 等逐字形保留），其余页按原方式重排；交付前逐部分核对字符与矢量页。任何不能保真的情况都在写出前
    拒绝（status=refused，reason_code 见 REFUSAL_CODES），不写出损坏的 final_readable.pdf。"""
    import fitz

    text = load_text(markdown_path)
    manifest: dict[str, Any] = {
        "version": 2,
        "status": "ok",
        "input_markdown": str(markdown_path),
        "output_pdf": str(output_path),
        "renderer": "reportlab+pymupdf_vector_page_copy",
        "font": REFLOW_FONT,
        "title": title,
        "delivery_type": "readable_fallback_pdf",
        "math_fidelity": {"policy": "math_pages_vector_copied_from_translated_pdf_v1",
                          "math_source_pdf": str(math_source_pdf) if math_source_pdf else None},
        "notes": [
            "该 PDF 是 QA 修复后的可读交付件，不承诺复刻原 PDF 版式。",
            "原版式译文 PDF 仍保留在 render_manifest.outputs 中。",
            "含数学结构（数学字体、数学符号、上下标、拆件括号）或重排字体不覆盖其字符的页，整页矢量复制主版式译文页，不做文字重排。",
        ],
    }
    fidelity = manifest["math_fidelity"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()  # 不留下上一次的成品冒充本次结果
    tmp = output_path.with_name(output_path.name + ".tmp-parts")
    tmp.mkdir(exist_ok=True)

    def refuse(code: str, **details: Any) -> dict[str, Any]:
        assert code in REFUSAL_CODES
        manifest.update(status="refused", reason_code=code, refusal=details, output_pdf=None)
        return manifest

    pages, split_method = split_markdown_pages(text)
    fidelity["markdown_page_split"] = split_method
    mono = None
    try:
        # 显式提供的原件 / 主版式成品不可用时不能悄悄按“无数学”处理（review-4）：原件不可用直接拒绝；
        # 主版式成品不可用按“没有可复制的主版式”处理（原文含数学 → readable_math_source_missing），
        # 且没有原件可核对时拒绝。source_pdf / math_source_pdf 为 None 才是独立的普通 Markdown 入口。
        source_unavailable = explicit_input_unavailable(source_pdf)
        if source_unavailable is not None:
            return refuse("readable_math_structure_unverifiable", stage="source_pdf_unavailable",
                          source_pdf=str(source_pdf), error=source_unavailable)
        math_source_unavailable = explicit_input_unavailable(math_source_pdf)
        if math_source_unavailable is None and math_source_pdf is not None:
            try:
                mono = fitz.open(math_source_pdf)
            except Exception as exc:
                math_source_unavailable = f"{type(exc).__name__}: {exc}"
        if math_source_unavailable is not None:
            fidelity["math_source_unavailable"] = math_source_unavailable
            if source_pdf is None:
                return refuse("readable_math_structure_unverifiable", stage="math_source_pdf_unavailable",
                              math_source_pdf=str(math_source_pdf), error=math_source_unavailable)
        evidence: dict[int, dict[str, Any]] = {}
        evidence_error = None
        if mono is not None:
            try:
                for index in range(len(mono)):
                    evidence[index + 1] = page_math_evidence(mono[index])
            except Exception as exc:  # 字形数超限等：主版式页无法判定是否含数学
                evidence_error = f"{type(exc).__name__}: {exc}"
        fidelity["page_evidence"] = {str(k): v for k, v in evidence.items()}
        # 原文侧：数学页与结构核对按原文/主版式结构报告判定，不只看主版式页本身
        # （主版式已经丢掉数学特征时，按“无数学页”重排就会放过损坏）。
        source_math: list[int] = []
        source_pages = None
        if source_pdf is not None:
            try:
                with fitz.open(source_pdf) as original:
                    source_pages = len(original)
                    source_evidence = {index + 1: page_math_evidence(original[index]) for index in range(len(original))}
            except Exception as exc:
                return refuse("readable_math_structure_unverifiable", stage="source_page_evidence",
                              error=f"{type(exc).__name__}: {exc}")
            source_math = [n for n, v in source_evidence.items() if v["has_math"]]
            fidelity["source_page_evidence"] = {str(k): v for k, v in source_evidence.items()}
        if evidence_error is not None:
            if source_math or source_pdf is None:
                return refuse("readable_math_structure_unverifiable", stage="main_layout_page_evidence",
                              error=evidence_error)
            evidence = {}
        mapped = bool(mono is not None and pages is not None and not set(pages) - set(evidence)
                      and (split_method != "single_segment" or len(mono) == 1))
        fidelity["page_mapping"] = "known" if mapped else "unknown"
        vector = {k for k, v in evidence.items() if v["has_math"]}
        if mono is None and source_math:
            # 没有主版式成品可复制时，原文含数学结构的页只能重排，会压平上下标/矩阵：写出前拒绝。
            return refuse("readable_math_source_missing", source_math_pages=source_math)
        if mono is not None and source_math:
            import formula_structure_check as structure

            try:
                check = structure.check_formula_structure(source_pdf, math_source_pdf)
            except Exception as exc:
                return refuse("readable_math_structure_unverifiable", stage="structure_check",
                              error=f"{type(exc).__name__}: {exc}")
            fidelity["source_structure_check"] = {k: check.get(k) for k in ("status", "severity", "flagged_pages",
                                                                             "source_relations", "target_relations", "lost")}
            if check.get("status") != "evaluated":
                return refuse("readable_math_structure_unverifiable", stage="structure_check",
                              status=check.get("status"), reason=check.get("reason"))
            flagged = sorted(check.get("flagged_pages") or [])
            if flagged:
                # 主版式的上/下标层级已丢失：无论主版式页是否还剩数学特征，可读版都不能交付（矢量复制会复制损坏，重排会压平）。
                return refuse("readable_math_source_structure_lost", pages=flagged, evidence="script_relations_lost",
                              samples=[s for p in check["pages"] if p["page"] in flagged for s in p["samples"]][:12])
            if source_pages == len(mono):
                vanished = [n for n in source_math if not evidence[n]["has_math"]]
                fidelity["source_page_mapping"] = "same_page_count"
            else:
                # 重新分页（如 LaTeX 直出）：逐页对应未知，只能按整份判断；主版式整份不剩任何数学特征即视为丢失。
                vanished = source_math if not any(v["has_math"] for v in evidence.values()) else []
                fidelity["source_page_mapping"] = "document_level"
            if vanished:
                return refuse("readable_math_source_structure_lost", pages=vanished,
                              evidence="main_layout_math_evidence_missing",
                              source_evidence={str(n): fidelity["source_page_evidence"][str(n)] for n in vanished},
                              main_layout_evidence={str(n): evidence.get(n) for n in vanished})
        if vector and not mapped:
            return refuse("readable_page_mapping_unknown", markdown_page_split=split_method,
                          markdown_pages=sorted(pages) if pages else None, pdf_pages=len(mono))
        if mapped:
            # 纯文字页若重排字体会丢字符，同样整页矢量保留（不交付缺字的重排页）。
            for number in sorted(set(pages) - vector):
                lost, _ = _reflow_loss(pages[number], tmp / "probe.pdf")
                if lost:
                    vector.add(number)
                    evidence[number]["reflow_codepoint_loss"] = lost
        math_pages = sorted(vector)
        appendix = ""
        if math_pages and original_markdown_path is not None:
            markdown_unavailable = explicit_input_unavailable(original_markdown_path)
            if markdown_unavailable is not None:
                # 无法核对 QA 修复是否改动了矢量页：不按“未改动”放行。
                return refuse("readable_math_structure_unverifiable", stage="original_markdown_unavailable",
                              original_markdown=str(original_markdown_path), error=markdown_unavailable)
            # QA 修复对矢量页文字的改动无法在矢量页上体现：逐页与修复前译文核对，末页之后的追加内容作为附录重排。
            original, _ = split_markdown_pages(load_text(Path(original_markdown_path)))
            if original is None or set(original) != set(pages):
                return refuse("readable_page_mapping_unknown", reason="original_translation_pages_differ")
            last = max(pages)
            for number in math_pages:
                before, after = original.get(number, "").rstrip(), pages.get(number, "").rstrip()
                if number == last and after.startswith(before):
                    appendix = after[len(before):]
                    continue
                if _norm(before) != _norm(after):
                    return refuse("readable_math_page_repair_conflict", page=number)
        if pages is None:
            pages = {1: text}
        plan: list[tuple[str, Any]] = []
        numbers = sorted(set(pages) | set(math_pages))
        for number in numbers:
            if number in vector:
                plan.append(("vector", number))
            elif plan and plan[-1][0] == "reflow":
                plan[-1][1].append(number)
            else:
                plan.append(("reflow", [number]))
        if appendix.strip():
            plan.append(("appendix", appendix))
        fidelity["page_modes"] = {str(n): ("vector_page_copy" if n in vector else "reflow") for n in numbers}
        result = fitz.open()
        checks = []
        try:
            for index, (mode, value) in enumerate(plan):
                if mode == "vector":
                    page = mono[value - 1]
                    target = result.new_page(width=page.rect.width, height=page.rect.height)
                    target.show_pdf_page(target.rect, mono, value - 1)
                    identical = _norm(target.get_text()) == _norm(page.get_text())
                    checks.append({"mode": "vector_page_copy", "source_page": value, "readable_page": len(result),
                                   "text_identical": identical})
                    if not identical:
                        return refuse("readable_vector_copy_mismatch", page=value)
                    continue
                segment = "\n\n".join(pages.get(n, "") for n in value) if mode == "reflow" else value
                part = tmp / f"part-{index:04d}.pdf"
                heading = title if index == 0 else ""
                lost, total = _reflow_loss(segment, part, heading=heading, title=title)
                checks.append({"mode": mode, "markdown_pages": value if mode == "reflow" else None,
                               "readable_page": len(result) + 1, "significant_codepoints": total,
                               "lost_codepoints": lost})
                if lost:
                    return refuse("readable_codepoint_loss", markdown_pages=value if mode == "reflow" else "appendix",
                                  lost_codepoints=lost)
                with fitz.open(part) as rendered:
                    result.insert_pdf(rendered)
            result.set_metadata({**(result.metadata or {}), "title": title or markdown_path.stem,
                                 "producer": "double6-pdf-translation readable"})
            staged = tmp / "staged.pdf"
            result.save(str(staged), garbage=3, deflate=True)
            staged.replace(output_path)
        finally:
            result.close()
        fidelity["checks"] = checks
        fidelity["vector_pages"] = math_pages
        return manifest
    finally:
        if mono is not None:
            mono.close()
        for leftover in tmp.glob("*"):
            leftover.unlink()
        tmp.rmdir()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render repaired Markdown translation to a readable PDF.")
    parser.add_argument("--input", required=True, help="Input Markdown path.")
    parser.add_argument("--output", help="Output PDF path. Defaults to final_readable.pdf beside input.")
    parser.add_argument("--manifest", help="Output manifest JSON. Defaults to final_pdf_manifest.json beside input.")
    parser.add_argument("--title", default="论文译文可读修复版")
    parser.add_argument("--math-source-pdf", help="主版式译文 PDF：含数学结构的页整页矢量复制（公式保真）。")
    parser.add_argument("--source-pdf", help="原文 PDF：用于核对主版式成品的上/下标层级。")
    parser.add_argument("--original-markdown", help="QA 修复前的 translation.md：核对修复是否改动数学页。")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_name("final_readable.pdf")
    manifest_path = Path(args.manifest) if args.manifest else input_path.with_name("final_pdf_manifest.json")
    manifest = render_pdf(input_path, output_path, title=args.title,
                          math_source_pdf=Path(args.math_source_pdf) if args.math_source_pdf else None,
                          source_pdf=Path(args.source_pdf) if args.source_pdf else None,
                          original_markdown_path=Path(args.original_markdown) if args.original_markdown else None)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "reason_code": manifest.get("reason_code"),
                      "output_pdf": manifest.get("output_pdf"), "manifest": str(manifest_path)}, ensure_ascii=False, indent=2))
    return 0 if manifest["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
