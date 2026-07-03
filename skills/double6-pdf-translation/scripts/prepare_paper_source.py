#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html.parser
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
HTML_EXTENSIONS = {".html", ".htm"}
PDF_EXTENSIONS = {".pdf"}
LATEX_EXTENSIONS = {".tex"}
LOW_TEXT_TOTAL_THRESHOLD = 500
LOW_TEXT_PAGE_THRESHOLD = 200
PAGE_MARKER_RE = re.compile(r"<!--\s*page:(\d+)\s*-->")
LONG_ALPHA_TOKEN_RE = re.compile(r"\b[A-Za-z]{18,}\b")
METADATA_LINE_RE = re.compile(r"(?i)\b(?:doi|arxiv|isbn|issn|copyright|license|corresponding author|@|https?://)\b")
NOISY_HEADING_PREFIXES = (
    "proceedings of",
    "transactions of",
    "journal of",
    "copyright",
    "published by",
)
PDF_METADATA_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("page_number", re.compile(r"^\s*(?:page\s*)?\d+\s*$", re.I)),
    ("article_marker", re.compile(r"^\s*ARTICLE\s*$", re.I)),
    ("article_open_marker", re.compile(r"^\s*OPEN\s*$", re.I)),
    ("decorative_glyph_probe", re.compile(r"^\s*1234567890\(\):,;\s*$")),
    ("copyright", re.compile(r"(?i)\b(?:copyright|©|all rights reserved|published by|license)\b")),
    ("doi_footer", re.compile(r"(?i)^\s*(?:doi|https?://doi\.org|www\.nature\.com|nature\.com)\b")),
    ("journal_footer", re.compile(r"(?i)\b(?:humanities and social sciences communications|nature|springer|elsevier|acm|ieee)\b.*\|\s*(?:\(?\d{4}\)?|\d+)")),
    ("arxiv_footer", re.compile(r"(?i)^\s*arxiv\s*:\s*\d{4}\.\d+")),
]
PROTECTED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("url", re.compile(r"https?://[^\s)>\]]+")),
    ("doi", re.compile(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+")),
    ("citation", re.compile(r"\[(?:\d+|[A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,?\s+\d{4})(?:\s*[,;]\s*(?:\d+|[A-Z][A-Za-z-]+(?:\s+et\s+al\.)?,?\s+\d{4}))*\]")),
    ("inline_math", re.compile(r"(?<!\\)\$[^$\n]{1,240}(?<!\\)\$")),
    ("latex_command", re.compile(r"\\[A-Za-z]+(?:\*|\[[^\]]{0,120}\]|\{[^{}]{0,160}\})*")),
    ("inline_code", re.compile(r"`[^`\n]{1,200}`")),
    ("variable", re.compile(r"\b(?:[A-Za-z]+_[A-Za-z0-9_]+|[A-Za-z]+[A-Z][A-Za-z0-9]*|[A-Z]{2,}[A-Za-z0-9]*)\b")),
]
LIGATURE_REPLACEMENTS = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}


class TextHTMLParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "br", "div", "section", "article", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "h1", "h2", "h3", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)
                self.parts.append(" ")

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line).strip()


def read_html(path: Path) -> str:
    parser = TextHTMLParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.text()


def strip_latex_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        index = 0
        cut = len(line)
        while True:
            pos = line.find("%", index)
            if pos == -1:
                break
            if pos > 0 and line[pos - 1] == "\\":
                index = pos + 1
                continue
            cut = pos
            break
        lines.append(line[:cut])
    return "\n".join(lines)


def extract_latex_braced_value(text: str, command: str) -> str:
    marker = "\\" + command
    start = text.find(marker)
    if start == -1:
        return ""
    brace = text.find("{", start + len(marker))
    if brace == -1:
        return ""
    depth = 0
    for index in range(brace, len(text)):
        char = text[index]
        if char == "{" and (index == 0 or text[index - 1] != "\\"):
            depth += 1
        elif char == "}" and (index == 0 or text[index - 1] != "\\"):
            depth -= 1
            if depth == 0:
                return text[brace + 1 : index]
    return ""


def extract_latex_environment(text: str, env: str) -> str:
    pattern = re.compile(rf"\\begin\{{{re.escape(env)}\}}(?P<body>.*?)\\end\{{{re.escape(env)}\}}", re.S)
    match = pattern.search(text)
    return match.group("body") if match else ""


def replace_latex_citations(text: str) -> str:
    text = re.sub(r"\\(?:cite|citep|citet|parencite|textcite)(?:\[[^\]]*\]){0,2}\{([^{}]+)\}", r"[cite:\1]", text)
    text = re.sub(r"\\(?:ref|eqref|autoref|cref|Cref)\{([^{}]+)\}", r"[ref:\1]", text)
    return text


def latex_to_plain_text(text: str) -> str:
    text = replace_latex_citations(text)
    text = re.sub(r"\\url\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\href\{([^{}]+)\}\{([^{}]+)\}", r"\2 (\1)", text)
    text = re.sub(r"\\(?:textbf|textit|emph|texttt|underline|textsc|textsuperscript|textsubscript)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:section|subsection|subsubsection)\*?\{([^{}]+)\}", r"\n\n## \1\n\n", text)
    text = re.sub(r"\\paragraph\*?\{([^{}]+)\}", r"\n\n### \1\n\n", text)
    text = re.sub(r"\\caption\{([^{}]+)\}", r"\n\nCaption: \1\n\n", text)
    text = re.sub(r"\\item(?:\[[^\]]+\])?", "\n- ", text)
    text = re.sub(r"\\begin\{(?:itemize|enumerate|description)\}|\\end\{(?:itemize|enumerate|description)\}", "\n", text)
    text = re.sub(r"\\begin\{(?:table|figure|table\*|figure\*)\}.*?\\end\{(?:table|figure|table\*|figure\*)\}", lambda match: "\n\n" + "\n".join(re.findall(r"\\caption\{([^{}]+)\}", match.group(0))) + "\n\n", text, flags=re.S)
    text = re.sub(r"\\begin\{(?:equation|align|align\*|gather|gather\*)\}.*?\\end\{(?:equation|align|align\*|gather|gather\*)\}", " [display_math] ", text, flags=re.S)
    text = re.sub(r"\$\$.*?\$\$|\\\[.*?\\\]", " [display_math] ", text, flags=re.S)
    text = re.sub(r"(?<!\\)\$[^$\n]{1,240}(?<!\\)\$", " [inline_math] ", text)
    text = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?(?:\{([^{}]*)\})?", lambda match: match.group(1) or " ", text)
    text = text.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_").replace("\\#", "#")
    text = re.sub(r"[{}]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [" ".join(line.split()).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def read_latex(path: Path) -> str:
    raw = strip_latex_comments(path.read_text(encoding="utf-8", errors="replace"))
    document = extract_latex_environment(raw, "document") or raw
    document = re.sub(r"\\maketitle\b", "", document)
    title = extract_latex_braced_value(raw, "title")
    abstract = extract_latex_environment(document, "abstract")
    document_without_abstract = re.sub(r"\\begin\{abstract\}.*?\\end\{abstract\}", "", document, flags=re.S)
    parts = []
    if title:
        parts.append("# " + latex_to_plain_text(title))
    if abstract:
        parts.append("## Abstract\n\n" + latex_to_plain_text(abstract))
    parts.append(latex_to_plain_text(document_without_abstract))
    return "\n\n".join(part for part in parts if part.strip()).strip()


def try_pymupdf(path: Path) -> tuple[str, int | None]:
    try:
        try:
            import fitz  # type: ignore
        except Exception:
            import pymupdf as fitz  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"PyMuPDF unavailable: {exc}") from exc

    text_parts: list[str] = []
    with fitz.open(str(path)) as doc:  # type: ignore[attr-defined]
        for index, page in enumerate(doc, start=1):
            page_text = page.get_text("text") or ""
            if page_text.strip():
                text_parts.append(f"\n\n<!-- page:{index} -->\n\n{page_text.strip()}")
        return "\n".join(text_parts).strip(), len(doc)


def try_pypdf(path: Path) -> tuple[str, int | None]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"pypdf unavailable: {exc}") from exc

    reader = PdfReader(str(path))
    text_parts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        if page_text.strip():
            text_parts.append(f"\n\n<!-- page:{index} -->\n\n{page_text.strip()}")
    return "\n".join(text_parts).strip(), len(reader.pages)


def try_pdftotext(path: Path) -> tuple[str, int | None]:
    binary = shutil.which("pdftotext")
    if not binary:
        raise RuntimeError("pdftotext unavailable")
    result = subprocess.run(
        [binary, "-layout", str(path), "-"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "pdftotext failed")
    return result.stdout.strip(), None


def normalize_pdf_extracted_text(text: str) -> tuple[str, dict[str, Any]]:
    """修复 PDF 文本抽取中高置信度、可逆性较强的伪影。"""
    changes = {
        "ligature_replacements": 0,
        "hyphenated_line_break_repairs": 0,
        "drop_cap_line_break_repairs": 0,
    }
    normalized = text
    for source, target in LIGATURE_REPLACEMENTS.items():
        count = normalized.count(source)
        if count:
            normalized = normalized.replace(source, target)
            changes["ligature_replacements"] += count

    def repair_hyphenated_break(match: re.Match[str]) -> str:
        before = match.group(1)
        after = match.group(2)
        if after[:1].isupper() or before in {"AI", "NMT", "LLM", "SMT"}:
            return f"{before}-{after}"
        return before + after

    normalized, hyphen_count = re.subn(r"\b([A-Za-z]+)-\n([A-Za-z]+)\b", repair_hyphenated_break, normalized)
    changes["hyphenated_line_break_repairs"] = hyphen_count

    lines = normalized.splitlines()
    repaired_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if (
            re.fullmatch(r"\s*[A-Z]\s*", line)
            and re.match(r"\s*[a-z][A-Za-z,;:)]", next_line)
        ):
            indent = re.match(r"\s*", next_line).group(0)
            repaired_lines.append(f"{indent}{line.strip()}{next_line.strip()}")
            changes["drop_cap_line_break_repairs"] += 1
            index += 2
            continue
        repaired_lines.append(line)
        index += 1
    normalized = "\n".join(repaired_lines)
    return normalized, {
        "enabled": True,
        **changes,
        "changed": any(changes.values()),
    }


def element_type_for(text: str, *, in_code: bool = False) -> str:
    stripped = text.strip()
    if in_code or stripped.startswith("```"):
        return "code"
    if re.match(r"^#{1,6}\s+\S+", stripped):
        return "heading"
    if re.match(r"^(abstract|introduction|related work|methodology|methods|experiments|results|discussion|conclusion|references)\b", stripped, re.I):
        return "heading"
    if stripped.startswith("|") and stripped.endswith("|"):
        return "table"
    if stripped.startswith(("$$", "\\[", "\\begin{equation", "\\begin{align")):
        return "equation"
    if re.match(r"^(figure|fig\.|table)\s+\d+", stripped, re.I):
        return "caption"
    return "paragraph"


def build_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    page: int | None = None
    section = ""
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        nonlocal buffer, section
        value = "\n".join(buffer).strip()
        buffer = []
        if not value:
            return
        element_type = element_type_for(value, in_code=False)
        if element_type == "heading":
            section = re.sub(r"^#{1,6}\s*", "", value.splitlines()[0]).strip()
        block_id = f"block-{len(blocks) + 1:04d}"
        blocks.append(
            {
                "block_id": block_id,
                "text": value,
                "page": page,
                "section": section,
                "element_type": element_type,
                "char_count": len(value),
                "confidence": "high" if value else "low",
            }
        )

    for raw_line in text.splitlines():
        marker = PAGE_MARKER_RE.search(raw_line)
        if marker:
            flush()
            page = int(marker.group(1))
            continue
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            if not in_code:
                flush()
                buffer.append(line)
                in_code = True
            else:
                buffer.append(line)
                value = "\n".join(buffer).strip()
                block_id = f"block-{len(blocks) + 1:04d}"
                blocks.append(
                    {
                        "block_id": block_id,
                        "text": value,
                        "page": page,
                        "section": section,
                        "element_type": "code",
                        "char_count": len(value),
                        "confidence": "high",
                    }
                )
                buffer = []
                in_code = False
            continue
        if in_code:
            buffer.append(line)
            continue
        if not line.strip():
            flush()
            continue
        if element_type_for(line) == "heading":
            flush()
            buffer.append(line)
            flush()
            continue
        buffer.append(line)
    flush()
    return blocks


def build_protected_spans(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    spans: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for block in blocks:
        text = str(block.get("text") or "")
        if block.get("element_type") == "code":
            token = f"PTS_{len(spans) + 1:04d}"
            spans.append(
                {
                    "span_id": token,
                    "token": token,
                    "kind": "code_block",
                    "value": text,
                    "block_id": block.get("block_id"),
                    "page": block.get("page"),
                    "start": 0,
                    "end": len(text),
                }
            )
            block["protected_span_ids"] = [token]
            continue
        block_span_ids: list[str] = []
        occupied: list[tuple[int, int]] = []
        for kind, pattern in PROTECTED_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if kind in {"url", "doi"}:
                    value = value.rstrip(".,;:")
                key = (kind, value, str(block.get("block_id")))
                if key in seen:
                    continue
                if any(match.start() < end and match.end() > start for start, end in occupied):
                    continue
                seen.add(key)
                occupied.append((match.start(), match.end()))
                token = f"PTS_{len(spans) + 1:04d}"
                spans.append(
                    {
                        "span_id": token,
                        "token": token,
                        "kind": kind,
                        "value": value,
                        "block_id": block.get("block_id"),
                        "page": block.get("page"),
                        "start": match.start(),
                        "end": match.end(),
                    }
                )
                block_span_ids.append(token)
        if block_span_ids:
            block["protected_span_ids"] = block_span_ids
    return {"version": 1, "spans": spans}


def repeated_page_lines(text: str) -> list[str]:
    pages = re.split(r"<!--\s*page:\d+\s*-->", text)
    counts: dict[str, int] = {}
    for page in pages:
        seen_on_page: set[str] = set()
        for raw_line in page.splitlines():
            line = " ".join(raw_line.split()).strip()
            if not line or len(line) > 140:
                continue
            if len(line) < 16:
                continue
            if re.fullmatch(r"\d+", line):
                continue
            seen_on_page.add(line)
        for line in seen_on_page:
            counts[line] = counts.get(line, 0) + 1
    return [line for line, count in counts.items() if count >= 2][:10]


def looks_like_abnormal_heading(block: dict[str, Any]) -> bool:
    if block.get("element_type") != "heading":
        return False
    text = " ".join(str(block.get("text") or "").split()).lstrip("# ").strip()
    if not text:
        return False
    lower = text.lower()
    return len(text.split()) > 14 or any(lower.startswith(prefix) for prefix in NOISY_HEADING_PREFIXES)


def analyze_extraction_quality(text: str, blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    alpha_tokens = re.findall(r"\b[A-Za-z]+\b", text)
    long_tokens = LONG_ALPHA_TOKEN_RE.findall(text)
    repeated_lines = repeated_page_lines(text)
    hyphenated_line_breaks = re.findall(r"[A-Za-z]-\n[A-Za-z]", text)
    metadata_lines = [
        " ".join(line.split())
        for line in text.splitlines()
        if METADATA_LINE_RE.search(line) and len(line.strip()) >= 20
    ]
    abnormal_headings = [str(block.get("text") or "") for block in (blocks or []) if looks_like_abnormal_heading(block)]
    long_blocks = [
        str(block.get("block_id") or "")
        for block in (blocks or [])
        if int(block.get("char_count") or 0) >= 4500
    ]
    examples: list[str] = []
    for token in [*long_tokens, *repeated_lines, *metadata_lines, *abnormal_headings]:
        if token not in examples:
            examples.append(token)
        if len(examples) >= 8:
            break
    max_alpha_token_length = max((len(token) for token in alpha_tokens), default=0)
    avg_alpha_token_length = round(sum(len(token) for token in alpha_tokens) / len(alpha_tokens), 2) if alpha_tokens else 0.0
    two_column_risk = len(long_tokens) >= 5 or max_alpha_token_length >= 35
    status = "warn" if (
        two_column_risk
        or len(repeated_lines) >= 3
        or len(metadata_lines) >= 8
        or len(abnormal_headings) >= 2
        or len(long_blocks) >= 1
    ) else "ok"
    return {
        "status": status,
        "alpha_token_count": len(alpha_tokens),
        "long_alpha_token_count": len(long_tokens),
        "max_alpha_token_length": max_alpha_token_length,
        "avg_alpha_token_length": avg_alpha_token_length,
        "hyphenated_line_break_count": len(hyphenated_line_breaks),
        "repeated_header_footer_candidates": repeated_lines,
        "metadata_mixed_line_count": len(metadata_lines),
        "metadata_mixed_examples": metadata_lines[:5],
        "abnormal_heading_count": len(abnormal_headings),
        "abnormal_heading_examples": abnormal_headings[:5],
        "long_block_count": len(long_blocks),
        "long_block_ids": long_blocks[:10],
        "possible_two_column_or_token_sticking": two_column_risk,
        "suspicious_examples": examples,
    }


def classify_pdf_noise_line(line: str, repeated_lines: set[str] | None = None) -> str:
    normalized = " ".join(line.split()).strip()
    if not normalized:
        return ""
    for reason, pattern in PDF_METADATA_PATTERNS:
        if pattern.search(normalized):
            return reason
    if repeated_lines and normalized in repeated_lines:
        return "repeated_header_footer"
    if len(normalized) <= 140 and METADATA_LINE_RE.search(normalized):
        return "metadata_line"
    return ""


def clean_pdf_noise_text(text: str) -> tuple[str, list[dict[str, Any]]]:
    repeated = set(repeated_page_lines(text))
    page: int | None = None
    cleaned_lines: list[str] = []
    metadata_blocks: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        marker = PAGE_MARKER_RE.search(raw_line)
        if marker:
            page = int(marker.group(1))
            cleaned_lines.append(raw_line)
            continue
        reason = classify_pdf_noise_line(raw_line, repeated)
        if reason:
            value = " ".join(raw_line.split()).strip()
            metadata_blocks.append(
                {
                    "metadata_id": f"metadata-{len(metadata_blocks) + 1:04d}",
                    "page": page,
                    "element_type": "metadata",
                    "noise_reason": reason,
                    "text": value,
                    "char_count": len(value),
                }
            )
            continue
        cleaned_lines.append(raw_line)
    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", cleaned).strip()
    return cleaned, metadata_blocks


def is_dependency_error(error: str) -> bool:
    return "unavailable" in error.lower() or "no module named" in error.lower()


def is_protected_pdf_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in ["password", "encrypted", "decrypt", "permission"])


def is_corrupt_pdf_error(error: str) -> bool:
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in [
            "broken",
            "damaged",
            "truncated",
            "malformed",
            "eof",
            "xref",
            "cannot open",
            "syntax error",
            "not a pdf",
            "no objects",
            "startxref",
        ]
    )


def classify_pdf_failure(attempts: list[dict[str, Any]]) -> tuple[str, str]:
    text_attempts = [item for item in attempts if item.get("method") in {"pymupdf", "pypdf", "pdftotext"}]
    errors = [str(item.get("error") or "") for item in text_attempts if item.get("status") == "error"]
    ok_attempts = [item for item in text_attempts if item.get("status") == "ok"]
    non_dependency_errors = [error for error in errors if not is_dependency_error(error)]
    if any(is_protected_pdf_error(error) for error in errors):
        return "protected_pdf", "PDF 可能受密码、权限或加密保护，当前无法可靠抽取文本。"
    if any(is_corrupt_pdf_error(error) for error in errors):
        return "corrupt_pdf", "PDF 读取报错疑似文件损坏、下载截断或内部结构异常；应先重新获取文件。"
    if non_dependency_errors and not ok_attempts:
        return "pdf_read_error", "PDF 抽取工具可用但读取失败；需要查看 attempts 中的错误并确认文件状态。"
    if not ok_attempts:
        return "needs_pdf_dependency", "当前环境没有可用的 PDF 文本抽取工具；可选工具包括 PyMuPDF、pypdf 或 pdftotext。"
    return "needs_ocr", "PDF 文本抽取为空，疑似扫描件或图片型 PDF，需要 OCR。"


def try_ocrmypdf(path: Path, output_dir: Path) -> tuple[str, int | None, dict[str, Any]]:
    binary = shutil.which("ocrmypdf")
    if not binary:
        raise RuntimeError("ocrmypdf unavailable")
    sidecar = output_dir / "ocr_sidecar.txt"
    ocr_pdf = output_dir / "ocr_source.pdf"
    result = subprocess.run(
        [binary, "--skip-text", "--sidecar", str(sidecar), str(path), str(ocr_pdf)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    detail = {
        "command": [binary, "--skip-text", "--sidecar", str(sidecar), str(path), str(ocr_pdf)],
        "returncode": result.returncode,
        "stdout": result.stdout[-2000:],
        "stderr": result.stderr[-2000:],
        "ocr_pdf": str(ocr_pdf),
        "sidecar": str(sidecar),
    }
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ocrmypdf failed")
    text = sidecar.read_text(encoding="utf-8", errors="replace") if sidecar.exists() else ""
    return text.strip(), None, detail


def extract_pdf(path: Path, output_dir: Path, enable_ocr: bool) -> tuple[str, str, int | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    page_count: int | None = None
    for method, extractor in [
        ("pymupdf", try_pymupdf),
        ("pypdf", try_pypdf),
        ("pdftotext", try_pdftotext),
    ]:
        try:
            text, pages = extractor(path)
            page_count = pages or page_count
            attempts.append({"method": method, "status": "ok", "chars": len(text), "pages": pages})
            if text.strip():
                return text, method, page_count, attempts
        except Exception as exc:  # noqa: BLE001
            attempts.append({"method": method, "status": "error", "error": str(exc)})

    if enable_ocr:
        try:
            text, pages, detail = try_ocrmypdf(path, output_dir)
            attempts.append({"method": "ocrmypdf", "status": "ok", "chars": len(text), **detail})
            if text.strip():
                return text, "ocrmypdf_sidecar", pages or page_count, attempts
        except Exception as exc:  # noqa: BLE001
            attempts.append({"method": "ocrmypdf", "status": "error", "error": str(exc)})

    return "", "", page_count, attempts


def default_output_dir(input_path: Path | None) -> Path:
    if input_path:
        return input_path.with_name(f"{input_path.stem}-zh")
    return Path.cwd() / "paper-translation-zh"


def write_outputs(
    *,
    text: str,
    output_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / "source.md"
    manifest_path = output_dir / "source_manifest.json"
    protected_spans_path = output_dir / "protected_spans.json"
    blocks = build_blocks(text)
    protected_spans = build_protected_spans(blocks)
    manifest["blocks"] = blocks
    manifest["extraction_quality"] = analyze_extraction_quality(text, blocks)
    if manifest.get("input_type") == "pdf" and manifest["extraction_quality"]["status"] == "warn":
        warnings = manifest.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append("PDF 抽取文本存在页眉页脚、元数据混排、断词、异常长 token 或长 block 风险；翻译前应抽样核对 source.md。")
    source_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    protected_spans_path.write_text(json.dumps(protected_spans, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["output_files"] = {
        "source": str(source_path),
        "manifest": str(manifest_path),
        "protected_spans": str(protected_spans_path),
        "glossary": str(output_dir / "glossary.tsv"),
        "translation": str(output_dir / "translation.md"),
        "translation_blocks": str(output_dir / "translation_blocks.jsonl"),
        "alignment_report": str(output_dir / "alignment_report.json"),
        "document_memory": str(output_dir / "document_memory.json"),
        "qa_checks": str(output_dir / "qa_checks.json"),
        "quality_report": str(output_dir / "quality_report.md"),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def prepare_source(args: argparse.Namespace) -> dict[str, Any]:
    input_path: Path | None = Path(args.input).expanduser().resolve() if args.input else None
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir(input_path).resolve()
    warnings: list[str] = []
    text = ""
    input_type = "inline_text"
    extraction_method = "inline_text"
    page_count: int | None = None
    attempts: list[dict[str, Any]] = []
    metadata_blocks: list[dict[str, Any]] = []
    original_char_count: int | None = None
    pdf_text_normalization: dict[str, Any] | None = None

    if args.text is not None:
        text = args.text
    elif args.stdin:
        text = sys.stdin.read()
        extraction_method = "stdin"
    elif input_path:
        suffix = input_path.suffix.lower()
        if not input_path.exists():
            raise FileNotFoundError(input_path)
        if suffix in TEXT_EXTENSIONS:
            input_type = "text"
            extraction_method = "read_text"
            text = input_path.read_text(encoding="utf-8", errors="replace")
        elif suffix in LATEX_EXTENSIONS:
            input_type = "latex"
            extraction_method = "latex_source_parser"
            text = read_latex(input_path)
        elif suffix in HTML_EXTENSIONS:
            input_type = "html"
            extraction_method = "html_parser"
            text = read_html(input_path)
        elif suffix in PDF_EXTENSIONS:
            input_type = "pdf"
            text, extraction_method, page_count, attempts = extract_pdf(input_path, output_dir, enable_ocr=not args.no_ocr)
            if text.strip():
                text, pdf_text_normalization = normalize_pdf_extracted_text(text)
            if text.strip() and not args.keep_pdf_noise:
                original_char_count = len(text.strip())
                text, metadata_blocks = clean_pdf_noise_text(text)
        else:
            input_type = "unsupported_file"
            extraction_method = "unsupported"
            warnings.append(f"暂不支持的文件类型: {suffix or '(no extension)'}")
    else:
        raise ValueError("Provide an input file, --text, or --stdin.")

    char_count = len(text.strip())
    density = None
    if page_count:
        density = round(char_count / max(page_count, 1), 2)

    status = "ready"
    if input_type == "unsupported_file":
        status = "unsupported_layout"
    elif input_type == "pdf":
        if not text.strip():
            status, warning = classify_pdf_failure(attempts)
            warnings.append(warning)
        elif density is not None and density < LOW_TEXT_PAGE_THRESHOLD:
            status = "needs_ocr_review"
            warnings.append("PDF 文本密度偏低，可能存在扫描页、图像页或抽取遗漏。")
        elif char_count < LOW_TEXT_TOTAL_THRESHOLD:
            status = "needs_ocr_review"
            warnings.append("PDF 抽取文本过短，请确认是否只抽到了封面、目录或少量页面。")
    elif not text.strip():
        status = "empty_source"
        warnings.append("源文本为空。")

    manifest: dict[str, Any] = {
        "status": status,
        "input": str(input_path) if input_path else "inline",
        "input_type": input_type,
        "extraction_method": extraction_method,
        "page_count": page_count,
        "character_count": char_count,
        "original_character_count": original_char_count,
        "text_density_chars_per_page": density,
        "warnings": warnings,
        "attempts": attempts,
        "pdf_noise_cleaning": {
            "enabled": input_type == "pdf" and not args.keep_pdf_noise,
            "metadata_block_count": len(metadata_blocks),
        },
        "pdf_text_normalization": pdf_text_normalization or {"enabled": input_type == "pdf", "changed": False},
        "metadata_blocks": metadata_blocks,
    }
    if metadata_blocks:
        manifest["warnings"].append(
            f"已从 PDF 正文翻译流中分离 {len(metadata_blocks)} 条页眉页脚、期刊页脚、版权或元数据噪声；详见 metadata_blocks。"
        )
    return write_outputs(text=text, output_dir=output_dir, manifest=manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare an academic paper source for translation.")
    parser.add_argument("input", nargs="?", help="Input text/markdown/html/pdf file.")
    parser.add_argument("--text", help="Inline source text.")
    parser.add_argument("--stdin", action="store_true", help="Read source text from stdin.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to <input-stem>-zh next to the input.")
    parser.add_argument("--no-ocr", action="store_true", help="Do not try optional OCR tools such as ocrmypdf.")
    parser.add_argument("--keep-pdf-noise", action="store_true", help="Keep PDF header/footer and metadata-like lines in source.md.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = prepare_source(args)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
