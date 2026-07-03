#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import policy_utils
import visual_layout

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "Imported by run_pdf_translation.py for path resolution, backend command construction, and runtime defaults."

DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_API_KEY = os.environ.get("LOCAL_TRANSLATION_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")
DEFAULT_REASONING_EFFORT = "none"
DEFAULT_TRANSLATOR_MODE = "auto"
DEFAULT_CLI_MAX_TOKENS = 4096
DEFAULT_LOCAL_MAX_CONCURRENCY = 3
DEFAULT_HYMT_COMPAT_PROXY_PORT = 18082
DEFAULT_PDF2ZH_BACKEND = "path"
DEFAULT_LATEX_RENDER_MODE = "auto"
DEFAULT_LATEX_PROJECT_MODE = "in-place"
DEFAULT_LATEX_DOCKER_IMAGE = "paper-translation-tex:2026-05-21"
DEFAULT_HYMT2_TEMPERATURE = 0.7
PDF2ZH_BINARY_ENV = "PAPER_TRANSLATION_PDF2ZH_BINARY"
LATEX_SOURCE_HINT_ENV = "PAPER_TRANSLATION_LATEX_SOURCE_HINT"
LATEX_SOURCE_ROOTS_ENV = "PAPER_TRANSLATION_LATEX_SOURCE_ROOTS"
DEFAULT_SYSTEM_PROMPT = (
    "You are a professional, authentic machine translation engine. "
    "Translate academic PDFs into fluent Simplified Chinese while preserving "
    "formulas, citations, URLs, named entities, terminology, and layout-sensitive placeholders. "
    "Only output the translated result without additional explanation. "
    "Do not leave ordinary English words untranslated; translate residual prose words such as "
    "'overwhelmingly' into natural Chinese unless they are protected spans, code, URLs, emails, or approved names."
)
PROTECTED_CHECK_VALUES = [
    "LLMs",
    "AI sovereignty",
    "Human-Centered AI",
    "Stanford Institute for Human-Centered AI",
    "Hong Kong Polytechnic University",
]
PROTECTED_CHECK_TRANSLATIONS = {
    "LLMs": ["大型语言模型", "LLMs"],
    "AI sovereignty": ["人工智能主权"],
    "Human-Centered AI": ["以人为本人工智能"],
    "Stanford Institute for Human-Centered AI": ["斯坦福以人为本人工智能研究院", "斯坦福大学以人为本人工智能研究院"],
    "Hong Kong Polytechnic University": ["香港理工大学"],
}
LATEX_MAIN_NAME_HINTS = {"main", "paper", "acl_latex", "ms", "article"}
LATEX_BAD_NAME_HINTS = {"merge_中文", "merge_english", "output", "template", "test"}
LATEX_REFLOW_LINE_WIDTH_CJK = 38.0
LATEX_REFLOW_LINES_PER_PAGE = 84


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def paper_translation_project_root() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_PROJECT_ROOT", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else repo_root() / path
    return repo_root() / "projects" / "double6-pdf-translation"


def paper_translation_run_root() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_RUN_ROOT", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else repo_root() / path
    return paper_translation_project_root() / "runs" / "default"


def paper_translation_shared_library_dir() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_SHARED_LIBRARY_DIR", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else repo_root() / path
    return repo_root() / "shared_resources"


def default_engine_home() -> Path:
    configured = os.environ.get("PAPER_TRANSLATION_ENGINE_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".cache" / "double6-pdf-translation" / "pdf2zh-home").resolve()


def external_pdf2zh_skill_root() -> Path | None:
    configured = os.environ.get("PAPER_TRANSLATION_PDF2ZH_SKILL_PATH", "").strip()
    return Path(configured).expanduser().resolve() if configured else None


def latex_translation_after_writeback_repair(source: str, translation: str) -> str:
    """返回 LaTeX 写回前实际会进入 TeX 的译文口径。"""
    try:
        external_root = external_pdf2zh_skill_root()
        if external_root and str(external_root) not in sys.path:
            sys.path.insert(0, str(external_root))
        from pdf2zh_skill.latex_ops import fix_translation

        return str(fix_translation(translation, source))
    except Exception:
        return translation


def default_output_dir(input_pdf: Path) -> Path:
    return input_pdf.with_name(f"{input_pdf.stem}-zh")


def find_pdf2zh_binary(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    configured = os.environ.get(PDF2ZH_BINARY_ENV, "").strip()
    if configured:
        return configured
    return shutil.which("pdf2zh") or "pdf2zh"


def resolved_pdf2zh_backend(args: argparse.Namespace) -> dict[str, Any]:
    explicit_binary = str(getattr(args, "pdf2zh_binary", "") or "").strip()
    env_binary = os.environ.get(PDF2ZH_BINARY_ENV, "").strip()
    backend_mode = str(getattr(args, "pdf2zh_backend", DEFAULT_PDF2ZH_BACKEND) or DEFAULT_PDF2ZH_BACKEND)
    if explicit_binary:
        binary = find_pdf2zh_binary(explicit_binary)
        return {"mode": "path", "source": "cli_binary", "binary": binary, "command_prefix": [binary]}
    if env_binary:
        binary = find_pdf2zh_binary(None)
        return {"mode": "path", "source": "env_binary", "binary": binary, "command_prefix": [binary]}
    if backend_mode == "module":
        wrapper = Path(__file__).resolve().with_name("pdf2zh_backend.py")
        return {"mode": "module", "source": "module_wrapper", "binary": "", "wrapper": str(wrapper), "command_prefix": [sys.executable, str(wrapper)]}
    binary = find_pdf2zh_binary(None)
    return {"mode": "path", "source": "path_lookup", "binary": binary, "command_prefix": [binary]}


def pdf2zh_command_prefix(args: argparse.Namespace) -> list[str]:
    return [str(item) for item in resolved_pdf2zh_backend(args)["command_prefix"]]


def _pdf2zh_help_text(args: argparse.Namespace, output_dir: Path) -> str:
    engine_home = Path(str(getattr(args, "engine_home", "") or default_engine_home())).expanduser().resolve()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(engine_home),
            "XDG_CACHE_HOME": str(engine_home / ".cache"),
            "HF_HOME": str(engine_home / ".hf-home"),
            "UV_CACHE_DIR": str(engine_home / ".uv-cache"),
            "PYTHONUNBUFFERED": "1",
        }
    )
    for key in ("XDG_CACHE_HOME", "HF_HOME", "UV_CACHE_DIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [*pdf2zh_command_prefix(args), "--help"],
            cwd=output_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except Exception:
        return ""
    return (result.stdout or "") + "\n" + (result.stderr or "")


def _pdf2zh_supports_option(help_text: str, option: str) -> bool:
    return not help_text or option in help_text


def _append_supported_option(
    command: list[str],
    help_text: str,
    option: str,
    values: list[str] | None = None,
    *,
    skipped: list[str],
) -> None:
    if _pdf2zh_supports_option(help_text, option):
        command.append(option)
        if values:
            command.extend(values)
    else:
        skipped.append(option)


def should_use_qwen_cli_adapter(args: argparse.Namespace) -> bool:
    mode = args.translator_mode
    if mode == "qwen-cli":
        return True
    if mode == "openai":
        return False
    return "qwen" in args.model.lower() and ("localhost" in args.base_url or "127.0.0.1" in args.base_url)


def should_enable_hymt_compat_proxy(args: argparse.Namespace) -> bool:
    mode = str(getattr(args, "hymt_compat_proxy", "auto") or "auto")
    if mode == "off":
        return False
    if mode == "on":
        return not should_use_qwen_cli_adapter(args)
    model = str(args.model).lower()
    return ("hy-mt" in model or "deepseek" in model) and not should_use_qwen_cli_adapter(args)


def pdf_has_toc_like_pages(input_pdf: Path, max_pages: int = 5) -> bool:
    try:
        fitz = visual_layout._load_fitz()
        with fitz.open(str(input_pdf)) as doc:  # type: ignore[attr-defined]
            for page_index in range(min(max_pages, len(doc))):
                lines = visual_layout.normalize_lines(doc[page_index].get_text("text"))
                if visual_layout.looks_like_toc_page(lines):
                    return True
    except Exception:
        return False
    return False


def resolve_pdf_layout_profile(args: argparse.Namespace, input_pdf: Path) -> str:
    profile = str(getattr(args, "pdf_layout_profile", "auto") or "auto")
    if profile in {"default", "toc-safe"}:
        return profile
    return "toc-safe" if pdf_has_toc_like_pages(input_pdf) else "default"


def apply_pdf_direct_text_repairs(
    pdf_path: Path | None,
    source_pdf: Path,
    output_dir: Path,
    *,
    apply_overlay: bool = False,
) -> dict[str, Any]:
    manifest_path = output_dir / "pdf_direct_text_repair_manifest.json"
    if not pdf_path or not pdf_path.is_file():
        manifest = {"version": 1, "status": "skipped", "reason": "missing_pdf", "repairs": []}
    else:
        manifest = {
            "version": 1,
            "status": "skipped",
            "reason": "document_specific_pdf_direct_repairs_not_in_open_source_skill",
            "pdf": str(pdf_path),
            "source_pdf": str(source_pdf),
            "overlay_requested": bool(apply_overlay),
            "overlay_applied": False,
            "delivery_safe": True,
            "note": "Open-source skill keeps high-fidelity backend rendering, layout audits, gates, and rerender plans; it does not ship historical document-specific overlay patches.",
            "repairs": [],
        }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest

def build_qwen_cli_command(args: argparse.Namespace, context_file: Path | None = None) -> str:
    script = Path(__file__).resolve().with_name("qwen_pdf2zh_cli_translator.py")
    cli_timeout = min(int(args.openai_timeout), 300)
    command = [
        sys.executable,
        str(script),
        "--base-url",
        args.base_url,
        "--model",
        args.model,
        "--api-key",
        args.api_key,
        "--reasoning-effort",
        args.openai_reasoning_effort,
        "--temperature",
        str(args.temperature),
        "--max-tokens",
        str(args.cli_max_tokens),
        "--timeout",
        str(cli_timeout),
        "--system-prompt",
        args.custom_system_prompt,
    ]
    if context_file:
        command.extend(["--context-file", str(context_file)])
    return " ".join(shlex.quote(item) for item in command)


def _compact_policy_items(items: list[dict[str, Any]], *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for item in items[:limit]:
        source = str(item.get("source_term") or item.get("source") or item.get("value") or "")
        translation = str(item.get("translation") or item.get("target") or "")
        if not source:
            continue
        line = f"- {source}"
        if translation:
            line += f" => {translation}"
        forbidden = item.get("forbidden_translations")
        if isinstance(forbidden, list) and forbidden:
            line += "；禁用：" + "、".join(str(value) for value in forbidden if value)
        lines.append(line[:240])
    return lines


def _policy_item_is_active(item: dict[str, Any]) -> bool:
    """过滤已被评测/审计标记为缺席或停用的策略项，避免把假实体注入模型提示词。"""
    if item.get("active") is False or item.get("enabled") is False:
        return False
    status = str(item.get("status") or item.get("claim_status") or "").lower()
    if status in {"inactive", "absent", "rejected", "disabled"}:
        return False
    source_location = item.get("source_location")
    if isinstance(source_location, str) and source_location.lower() in {"absent", "not_found", "inactive"}:
        return False
    source_locations = item.get("source_locations")
    if isinstance(source_locations, list) and source_locations:
        normalized = {str(value).lower() for value in source_locations}
        if normalized <= {"absent", "not_found", "inactive"}:
            return False
    return True


def build_backend_system_prompt(base_prompt: str, output_dir: Path) -> str:
    sections: list[str] = []
    for name, title in [
        ("entity_map.json", "专名实体策略"),
        ("term_policy.json", "术语策略"),
    ]:
        path = output_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        raw_items = data.get("entities") if name == "entity_map.json" else data.get("terms")
        if isinstance(raw_items, list):
            lines = _compact_policy_items(
                [item for item in raw_items if isinstance(item, dict) and _policy_item_is_active(item)]
            )
            if lines:
                sections.append(title + "：\n" + "\n".join(lines))
    protected_path = output_dir / "protected_spans.json"
    if protected_path.exists():
        try:
            protected = json.loads(protected_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            protected = {}
        spans = protected.get("spans") if isinstance(protected, dict) else []
        if isinstance(spans, list):
            kind_counts: dict[str, int] = {}
            samples: list[dict[str, Any]] = []
            for span in spans:
                if not isinstance(span, dict):
                    continue
                kind = str(span.get("kind") or "unknown")
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
                if len(samples) < 16 and kind in {"doi", "url", "citation", "inline_math", "display_math", "inline_code"}:
                    samples.append(span)
            sample_lines = _compact_policy_items(samples, limit=16)
            sections.append(
                "不可翻译元素策略：必须逐字保留 DOI、URL、引用编号、公式、代码、占位符和模型名。"
                f"类型计数：{json.dumps(kind_counts, ensure_ascii=False)}"
                + ("\n样例：\n" + "\n".join(sample_lines) if sample_lines else "")
            )
    if not sections:
        return base_prompt
    return (
        base_prompt.rstrip()
        + "\n\nDocument-level constraints from paper-translation QA artifacts:\n"
        + "\n\n".join(sections)
        + "\nTranslate ordinary English prose completely. Preserve protected spans verbatim."
    )


def build_pdf2zh_command(args: argparse.Namespace, output_dir: Path, context_file: Path | None = None) -> list[str]:
    backend_help = _pdf2zh_help_text(args, output_dir)
    skipped_options: list[str] = []
    command = [
        *pdf2zh_command_prefix(args),
        str(args.input_pdf),
        "--output",
        str(output_dir),
        "--lang-out",
        "zh",
    ]
    if bool(getattr(args, "backend_debug_artifacts", True)):
        _append_supported_option(
            command,
            backend_help,
            "--working-dir",
            [str(output_dir / "_backend_working")],
            skipped=skipped_options,
        )
    if bool(getattr(args, "ignore_translation_cache", False)):
        command.append("--ignore-cache")
    if should_use_qwen_cli_adapter(args):
        command.extend(
            [
                "--clitranslator",
                "--clitranslator-command",
                build_qwen_cli_command(args, context_file),
                "--clitranslator-timeout",
                str(min(int(args.openai_timeout), 300)),
            ]
        )
    else:
        command.extend(
            [
                "--openai",
                "--openai-model",
                args.model,
                "--openai-base-url",
                args.base_url,
                "--openai-api-key",
                args.api_key,
                "--openai-timeout",
                str(args.openai_timeout),
                "--openai-temperature",
                str(args.temperature),
                "--openai-send-temprature",
                "--openai-reasoning-effort",
                args.openai_reasoning_effort,
                "--openai-send-reasoning-effort",
                "--term-openai-timeout",
                str(args.openai_timeout),
                "--term-openai-temperature",
                str(args.temperature),
                "--term-openai-send-temprature",
                "--term-openai-reasoning-effort",
                args.openai_reasoning_effort,
                "--term-openai-send-reasoning-effort",
            ]
        )
        if args.openai_json_mode:
            command.append("--openai-enable-json-mode")
        if getattr(args, "disable_same_text_fallback", True):
            _append_supported_option(
                command,
                backend_help,
                "--disable-same-text-fallback",
                skipped=skipped_options,
            )
    setattr(args, "backend_unsupported_options", skipped_options)
    command.extend(
        [
            "--qps",
            str(args.local_max_concurrency),
            "--custom-system-prompt",
            args.custom_system_prompt,
            "--pool-max-workers",
            str(args.local_max_concurrency),
            "--term-qps",
            str(args.local_max_concurrency),
            "--term-pool-max-workers",
            str(args.local_max_concurrency),
            "--no-auto-extract-glossary",
            "--skip-scanned-detection",
            "--watermark-output-mode",
            "no_watermark",
        ]
    )
    if str(getattr(args, "resolved_pdf_layout_profile", getattr(args, "pdf_layout_profile", ""))) == "toc-safe":
        command.extend(
            [
                "--split-short-lines",
                "--short-line-split-factor",
                "0.95",
                "--no-merge-alternating-line-numbers",
            ]
        )
    if args.dual:
        command.append("--dual")
    if args.pages:
        command.extend(["--pages", args.pages])
    return command


def redacted_command(command: list[str], api_key: str) -> list[str]:
    return [item.replace(api_key, "<API_KEY>") if api_key else item for item in command]
