"""LaTeX identity: verified_match only, never cache-root highest-score .tex."""
from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .constants import (
    CACHE_TEX_WALK_LIMIT,
    IDENTITY_PAGE_WINDOW,
    LATEX_CACHE_ROOT_ENV,
    LATEX_STATUS_AMBIGUOUS,
    LATEX_STATUS_EXPECTED_BUT_MISSING,
    LATEX_STATUS_NOT_APPLICABLE,
    LATEX_STATUS_NOT_FOUND_UNKNOWN,
    LATEX_STATUS_VERIFIED_MATCH,
    TITLE_SIMILARITY_THRESHOLD,
)

ARXIV_RE = re.compile(r"(?i)\b(?:arxiv\s*:?\s*)?(\d{4}\.\d{4,5})(?:v\d+)?\b")
DOI_RE = re.compile(r"(?i)\b10\.\d{4,9}/[-._;()/:A-Z0-9]+")
LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z@]+\*?")
BRACES_RE = re.compile(r"[{}]")
SPACE_RE = re.compile(r"\s+")
SKIP_DIR_NAMES = {".git", ".venv", "node_modules", "__pycache__", ".tox"}


def normalize_fingerprint(value: str) -> str:
    text = LATEX_COMMAND_RE.sub(" ", value)
    text = BRACES_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip().lower()
    return text


def extract_braced_command(text: str, command: str) -> str:
    marker = "\\" + command
    start = text.find(marker)
    if start == -1:
        return ""
    brace = text.find("{", start + len(marker))
    if brace == -1:
        return ""
    depth = 0
    chars: list[str] = []
    for char in text[brace:]:
        if char == "{":
            depth += 1
            if depth == 1:
                continue
        elif char == "}":
            depth -= 1
            if depth == 0:
                break
        if depth:
            chars.append(char)
    return normalize_fingerprint("".join(chars))


def extract_arxiv_id(text: str) -> str | None:
    match = ARXIV_RE.search(text or "")
    return match.group(1) if match else None


def extract_doi(text: str) -> str | None:
    match = DOI_RE.search(text or "")
    return match.group(0).lower().rstrip(").,;") if match else None


def _pdf_identity_text(path: Path) -> str:
    parts = [path.name, path.stem]
    try:
        import fitz
    except Exception:
        return " ".join(parts)
    try:
        document = fitz.open(path)
    except Exception:
        return " ".join(parts)
    try:
        metadata = document.metadata or {}
        for key in ("title", "author", "subject", "keywords"):
            value = metadata.get(key)
            if value:
                parts.append(str(value))
        window = min(IDENTITY_PAGE_WINDOW, document.page_count)
        for index in range(window):
            parts.append(document[index].get_text("text") or "")
    finally:
        document.close()
    return "\n".join(parts)


def extract_pdf_identity(path: Path) -> dict[str, Any]:
    blob = _pdf_identity_text(path)
    title = ""
    author = ""
    try:
        import fitz

        document = fitz.open(path)
        try:
            metadata = document.metadata or {}
            title = normalize_fingerprint(str(metadata.get("title") or ""))
            author = normalize_fingerprint(str(metadata.get("author") or ""))
        finally:
            document.close()
    except Exception:
        pass
    return {
        "arxiv_id": extract_arxiv_id(blob),
        "doi": extract_doi(blob),
        "title": title,
        "author": author,
        "blob": blob,
        "expected_latex": bool(extract_arxiv_id(blob)),
    }


def extract_tex_identity(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    blob = f"{path.name}\n{text[:20000]}"
    return {
        "path": str(path),
        "arxiv_id": extract_arxiv_id(blob),
        "doi": extract_doi(blob),
        "title": extract_braced_command(text, "title"),
        "author": extract_braced_command(text, "author"),
        "blob": blob,
    }


def identities_match(pdf_identity: dict[str, Any], tex_identity: dict[str, Any]) -> tuple[bool, str | None]:
    pdf_arxiv = pdf_identity.get("arxiv_id")
    tex_arxiv = tex_identity.get("arxiv_id")
    if pdf_arxiv and tex_arxiv and pdf_arxiv == tex_arxiv:
        return True, "arxiv_id"
    pdf_doi = pdf_identity.get("doi")
    tex_doi = tex_identity.get("doi")
    if pdf_doi and tex_doi and pdf_doi == tex_doi:
        return True, "doi"
    pdf_title = str(pdf_identity.get("title") or "")
    tex_title = str(tex_identity.get("title") or "")
    if pdf_title and tex_title:
        ratio = SequenceMatcher(None, pdf_title, tex_title).ratio()
        if ratio >= TITLE_SIMILARITY_THRESHOLD:
            pdf_author = str(pdf_identity.get("author") or "")
            tex_author = str(tex_identity.get("author") or "")
            if not pdf_author or not tex_author or SequenceMatcher(None, pdf_author, tex_author).ratio() >= 0.5:
                return True, "title_author_fingerprint"
    return False, None


def iter_tex_candidates(root: Path, *, limit: int = CACHE_TEX_WALK_LIMIT) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".tex":
        return [root]
    if not root.exists() or not root.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIR_NAMES]
        for name in filenames:
            if not name.lower().endswith(".tex"):
                continue
            found.append(Path(dirpath) / name)
            if len(found) >= limit:
                return found
    return found


def latex_cache_root(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit
    raw = os.environ.get(LATEX_CACHE_ROOT_ENV, "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path.resolve() if path.exists() else path


def find_verified_matches(
    pdf_identity: dict[str, Any],
    candidates: list[Path],
) -> list[tuple[Path, str]]:
    matches: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        matched, method = identities_match(pdf_identity, extract_tex_identity(resolved))
        if matched and method:
            matches.append((resolved, method))
    return matches


def resolve_latex_identity(
    input_pdf: Path,
    *,
    explicit_override: Path | None = None,
    adjacent_candidate: Path | None = None,
    cache_root: Path | None = None,
    searched_roots: list[str] | None = None,
) -> dict[str, Any]:
    notes: list[str] = []
    record: dict[str, Any] = {
        "policy": "latex_identity",
        "source_path": None,
        "match_method": None,
        "candidate_count": 0,
        "searched_roots": list(searched_roots or []),
        "expected_key": None,
        "notes": notes,
    }
    if explicit_override is not None:
        path = explicit_override.expanduser().resolve()
        record.update(
            {
                "status": LATEX_STATUS_VERIFIED_MATCH,
                "source_path": str(path),
                "match_method": "source_override",
                "candidate_count": 1,
            }
        )
        notes.append("显式 --source-override 视为已核验身份。")
        return record

    pdf_identity = extract_pdf_identity(input_pdf)
    if pdf_identity.get("arxiv_id"):
        record["expected_key"] = f"arxiv:{pdf_identity['arxiv_id']}"
    elif pdf_identity.get("doi"):
        record["expected_key"] = f"doi:{pdf_identity['doi']}"

    candidates: list[Path] = []
    if adjacent_candidate is not None:
        candidates.append(adjacent_candidate)
    root = latex_cache_root(cache_root)
    if root is not None:
        record["searched_roots"].append(str(root))
        if root.exists():
            cache_candidates = iter_tex_candidates(root)
            notes.append("缓存根只按身份匹配，不取最高分 .tex。")
            candidates.extend(cache_candidates)
        else:
            notes.append("声明的 LaTeX 缓存根不存在。")

    matches = find_verified_matches(pdf_identity, candidates)
    record["candidate_count"] = len(matches)
    if len(matches) > 1:
        record.update(
            {
                "status": LATEX_STATUS_AMBIGUOUS,
                "source_path": None,
                "match_method": None,
                "match_paths": [str(path) for path, _method in matches],
            }
        )
        notes.append("多个已核验 LaTeX 候选，停止 LaTeX 路线。")
        return record
    if len(matches) == 1:
        path, method = matches[0]
        record.update(
            {
                "status": LATEX_STATUS_VERIFIED_MATCH,
                "source_path": str(path),
                "match_method": method,
            }
        )
        return record
    if pdf_identity.get("expected_latex"):
        record["status"] = LATEX_STATUS_EXPECTED_BUT_MISSING
        notes.append("PDF 像有 arXiv/LaTeX 身份，但没有核验过的 .tex。")
        return record
    if adjacent_candidate is not None:
        record["status"] = LATEX_STATUS_NOT_FOUND_UNKNOWN
        notes.append("邻近目录有 .tex，但身份未核验，不能走进 latex_direct。")
        return record
    if root is not None:
        record["status"] = LATEX_STATUS_NOT_FOUND_UNKNOWN
        notes.append("缓存根没有与当前 PDF 身份匹配的 .tex。")
        return record
    record["status"] = LATEX_STATUS_NOT_APPLICABLE
    return record
