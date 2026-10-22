# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation commands：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def _command_api_key(args):
    """本地兼容后端需要非空SDK字段；占位值不是上游凭据。"""
    if args.api_key:
        return args.api_key
    from urllib.parse import urlsplit
    if urlsplit(args.base_url).hostname in {'localhost', '127.0.0.1', '::1'}:
        return 'local-no-auth'
    raise ValueError('remote_backend_requires_explicit_api_key')

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
        _command_api_key(args),
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
    target_language = getattr(args, "target_language", "zh") or "zh"
    if target_language != "zh":
        # 中译英：显式把目标语言传给适配器；英译中命令行保持逐字不变。
        command.extend(["--target-language", target_language])
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

_CJK_POLICY_TEXT = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _policy_item_matches_target(item: dict[str, Any], target_language: str = "zh") -> bool:
    """中译英时剔除英译中方向的默认术语映射（译法/禁用译法含汉字），避免提示词要求输出中文。"""
    if target_language != "en":
        return True
    values = [item.get("translation") or item.get("target") or ""]
    forbidden = item.get("forbidden_translations")
    if isinstance(forbidden, list):
        values.extend(str(value) for value in forbidden)
    return not any(_CJK_POLICY_TEXT.search(str(value)) for value in values)


def _policy_item_is_active(item: dict[str, Any]) -> bool:
    """过滤已被评测/审计标记为缺席或停用的策略项，避免把假实体注入模型提示词。"""
    from policy_utils import policy_item_is_active
    return policy_item_is_active(item)

def build_backend_system_prompt(base_prompt: str, output_dir: Path, target_language: str = "zh") -> str:
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
                [item for item in raw_items if isinstance(item, dict) and _policy_item_is_active(item)
                 and _policy_item_matches_target(item, target_language)]
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
        + ("\nTranslate all Chinese prose completely into English. Preserve protected spans verbatim."
           if target_language == "en" else
           "\nTranslate ordinary English prose completely. Preserve protected spans verbatim.")
    )

def build_pdf2zh_command(args: argparse.Namespace, output_dir: Path, context_file: Path | None = None) -> list[str]:
    from pdf_translation_paths import pdf2zh_command_prefix, should_use_qwen_cli_adapter
    command = [
        *pdf2zh_command_prefix(args),
        str(args.input_pdf),
        "--output",
        str(output_dir),
        "--lang-out",
        "zh",
    ]
    target_language = getattr(args, "target_language", "zh") or "zh"
    if target_language != "zh":
        # 中译英：显式声明源/目标语言；英译中保持既有命令行逐字不变（pdf2zh 默认 lang-in=en）。
        command[-2:] = ["--lang-in", TARGET_SOURCE_LANGUAGE[target_language], "--lang-out", target_language]
    if bool(getattr(args, "backend_debug_artifacts", True)):
        command.extend(["--working-dir", str(output_dir / "_backend_working")])
    if getattr(args,'source_cache_mode',None) or bool(getattr(args, "ignore_translation_cache", False)):
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
                _command_api_key(args),
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
            command.append("--disable-same-text-fallback")
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
    elif getattr(args, "pdf2zh_backend", DEFAULT_PDF2ZH_BACKEND) == "vendored" and not args.pdf2zh_binary:
        command.append("--no-dual")
    if args.pages:
        command.extend(["--pages", args.pages])
    return command


def redacted_command(command: list[str], api_key: str) -> list[str]:
    return [item.replace(api_key, "<API_KEY>") if api_key else item for item in command]

def build_latex_direct_requirement(output_dir: Path) -> str:
    def compact_term_policy(payload: dict[str, Any]) -> dict[str, Any]:
        terms = payload.get("terms") if isinstance(payload, dict) else []
        compact_terms = []
        for term in terms if isinstance(terms, list) else []:
            if not isinstance(term, dict) or not _policy_item_is_active(term):
                continue
            source = term.get("source_term")
            if not source:
                continue
            row = {
                "source": source,
                "translation": term.get("translation", ""),
                "action": term.get("action", ""),
            }
            forbidden = term.get("forbidden_translations")
            if forbidden:
                row["forbidden"] = forbidden[:3] if isinstance(forbidden, list) else forbidden
            compact_terms.append(row)
            if len(compact_terms) >= 20:
                break
        return {"terms": compact_terms, "note": "仅列核心术语；未列出的专名按源文和上下文谨慎处理。"}

    def compact_entity_map(payload: dict[str, Any]) -> dict[str, Any]:
        entities = payload.get("entities") if isinstance(payload, dict) else []
        compact_entities = []
        for entity in entities if isinstance(entities, list) else []:
            if not isinstance(entity, dict) or not _policy_item_is_active(entity):
                continue
            source = entity.get("source_term")
            if not source:
                continue
            if not (entity.get("active") or entity.get("source_location") == "body" or entity.get("translation")):
                continue
            compact_entities.append(
                {
                    "source": source,
                    "translation": entity.get("translation", ""),
                    "type": entity.get("entity_type", ""),
                    "forbidden": (entity.get("forbidden_translations") or [])[:2],
                }
            )
            if len(compact_entities) >= 12:
                break
        return {"entities": compact_entities}

    def compact_protected_spans(payload: dict[str, Any]) -> dict[str, Any]:
        spans = payload.get("spans") if isinstance(payload, dict) else []
        compact_spans = []
        important_kinds = {"url", "doi", "email", "citation", "reference"}
        for span in spans if isinstance(spans, list) else []:
            if not isinstance(span, dict):
                continue
            kind = str(span.get("kind") or "")
            value = str(span.get("value") or "")
            if kind not in important_kinds and len(compact_spans) >= 8:
                continue
            if not value:
                continue
            compact_spans.append({"kind": kind, "value": value[:160]})
            if len(compact_spans) >= 16:
                break
        return {
            "protected_spans": compact_spans,
            "note": "LaTeX 命令、公式、引用键、URL、DOI、文件名、占位符和环境结构必须原样保留。",
        }

    parts = [
        "将英文论文 LaTeX 源码翻译为自然、准确的简体中文。保留所有 LaTeX 命令、公式、引用键、标签、URL、DOI、文件名、占位符和环境结构。",
        "禁止把 \\section{...}、\\subsection{...}、\\begin{...}、\\end{...}、\\caption{...}、\\footnote{...} 等 LaTeX 结构命令作为普通可见正文输出；只能保留命令结构，并翻译其中人类可读的自然语言参数。只有 URL、DOI、代码、引用键、文件名、公式和占位符可以原样保留。",
        "URL/DOI/inline code 必须在翻译后仍可按原值追踪；TeX 中可因语法需要转义下划线，但不得省略、改写或翻译。",
    ]
    for name, title, compactor in [
        ("term_policy.json", "术语策略", compact_term_policy),
        ("entity_map.json", "实体策略", compact_entity_map),
        ("protected_spans.json", "不可翻译元素", compact_protected_spans),
    ]:
        path = output_dir / name
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        compact = json.dumps(compactor(payload), ensure_ascii=False, separators=(",", ":"))
        parts.append(f"{title}：{compact[:1800]}")
    return "\n\n".join(parts)

def build_latex_direct_command(
    args: argparse.Namespace,
    input_pdf: Path,
    source_tex: Path,
    output_dir: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-c",
        "from pdf2zh_skill.cli import main; raise SystemExit(main())",
        "run",
        "--project",
        str(source_tex.parent),
        "--source-pdf",
        str(input_pdf),
        "--output-dir",
        str(output_dir),
        "--translation-api-key",
        _command_api_key(args),
        "--translation-base-url",
        args.base_url,
        "--translation-model",
        args.model,
        "--workers",
        str(args.local_max_concurrency),
        "--translate-timeout-seconds",
        str(args.latex_translate_timeout),
        "--compile-timeout-seconds",
        str(args.latex_compile_timeout),
        "--retry-untranslated",
        str(args.latex_retry_untranslated),
        "--auto-repair-passes",
        str(args.latex_auto_repair_passes),
        "--project-mode",
        str(getattr(args, "latex_project_mode", DEFAULT_LATEX_PROJECT_MODE)),
        "--requirement",
        build_latex_direct_requirement(output_dir.parent),
        "--glossary-max-candidates",
        "30",
        "--glossary-max-terms",
        "20",
        "--force-prepare",
    ]
    if args.latex_compiler:
        command.extend(["--compiler", args.latex_compiler])
    if args.latex_skip_glossary:
        command.append("--skip-glossary")
    if args.latex_skip_consistency_review:
        command.append("--skip-consistency-review")
    return command

def has_local_latex_compiler() -> bool:
    return any(shutil.which(name) for name in ("xelatex", "lualatex", "pdflatex"))

def ensure_tex_docker_wrappers(wrapper_dir: Path) -> Path:
    wrapper_dir.mkdir(parents=True, exist_ok=True)
    template = """#!/bin/sh
set -eu
image="${{PDF2ZH_TEX_DOCKER_IMAGE:-paper-translation-tex:2026-05-21}}"
work="$(pwd)"
exec docker run --rm -v "$work:/workspace" -w /workspace "$image" {tool} "$@"
"""
    for tool in ("xelatex", "lualatex", "pdflatex", "bibtex", "latexmk"):
        path = wrapper_dir / tool
        path.write_text(template.format(tool=tool), encoding="utf-8")
        path.chmod(0o755)
    return wrapper_dir

def select_latex_compile_runtime(args: argparse.Namespace) -> dict[str, Any]:
    requested = getattr(args, "latex_compile_runtime", "auto")
    local_available = has_local_latex_compiler()
    docker_available = shutil.which("docker") is not None
    if requested == "local":
        selected = "local"
    elif requested == "docker":
        selected = "docker"
    elif local_available:
        selected = "local"
    elif docker_available:
        selected = "docker"
    else:
        selected = "missing"
    return {
        "requested": requested,
        "selected": selected,
        "local_compiler_available": local_available,
        "docker_available": docker_available,
        "docker_image": getattr(args, "latex_docker_image", DEFAULT_LATEX_DOCKER_IMAGE),
    }

def infer_latex_direct_failure_stage(log_text: str, manifest: dict[str, Any]) -> dict[str, str | None]:
    if manifest.get("status") == "ok":
        return {"failure_stage": None, "api_stage_status": "ok", "compile_stage_status": "ok"}
    lowered = log_text.lower()
    if "translation api request failed" in lowered or "httperror" in lowered or "400 client error" in lowered:
        if re.search(r"(?m)^Glossary:", log_text) and not re.search(r"(?m)^Translate:", log_text):
            return {"failure_stage": "glossary_api", "api_stage_status": "error", "compile_stage_status": "not_started"}
        if re.search(r"(?m)^Translate:", log_text):
            return {"failure_stage": "translation_api", "api_stage_status": "error", "compile_stage_status": "not_started"}
        return {"failure_stage": "api", "api_stage_status": "error", "compile_stage_status": "not_started"}
    if "compile" in lowered or "latexmk" in lowered or "tectonic" in lowered:
        return {"failure_stage": "compile", "api_stage_status": "ok", "compile_stage_status": "error"}
    if manifest.get("returncode") not in {0, None}:
        return {"failure_stage": "process_exit", "api_stage_status": "unknown", "compile_stage_status": "unknown"}
    return {"failure_stage": "missing_output", "api_stage_status": "unknown", "compile_stage_status": "unknown"}

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
