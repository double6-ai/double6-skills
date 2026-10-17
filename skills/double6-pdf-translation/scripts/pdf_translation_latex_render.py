# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation latex render：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def run_latex_direct_render(
    args: argparse.Namespace,
    input_pdf: Path,
    output_dir: Path,
    source_tex: Path | None,
    env: dict[str, str],
) -> dict[str, Any]:
    from pdf_translation_commands import build_latex_direct_command, ensure_tex_docker_wrappers, infer_latex_direct_failure_stage, redacted_command, select_latex_compile_runtime
    from pdf_translation_latex_audit import default_latex_baseline_pdf, write_latex_baseline_audit
    from pdf_translation_latex_quality import build_latex_direct_quality_gate, load_latex_direct_segments_for_gate, write_latex_paragraph_structure_repair_manifest, write_latex_segment_repair_plan
    from pdf_translation_paths import should_enable_hymt_compat_proxy, vendored_pdf2zh_skill_root
    mode = getattr(args, "latex_render_mode", DEFAULT_LATEX_RENDER_MODE)
    manifest_path = output_dir / "direct_latex_render_manifest.json"
    manifest: dict[str, Any] = {
        "version": 1,
        "mode": mode,
        "status": "skipped",
        "source_tex": str(source_tex) if source_tex else None,
        "latex_project_mode": getattr(args, "latex_project_mode", DEFAULT_LATEX_PROJECT_MODE),
        "backend": "vendored_pdf2zh_skill_latex",
        "vendored_backend": str(vendored_pdf2zh_skill_root()),
        "output_dir": str(output_dir / "latex_direct"),
        "command": None,
        "translated_pdf": None,
        "translated_tex": None,
        "english_tex": None,
        "run_summary": None,
        "log_path": str(output_dir / "latex_direct.log"),
        "errors": [],
        "hymt_compat_proxy": {
            "mode": getattr(args, "hymt_compat_proxy", "auto"),
            "enabled": False,
            "upstream_base_url": args.base_url,
            "proxy_base_url": None,
            "stats": {},
        },
        "latex_direct_proxy_stats": {},
        "api_stage_status": "not_started",
        "compile_stage_status": "not_started",
        "failure_stage": None,
        "compile_runtime": None,
        "paper_source_dir": None,
        "paper_cn_dir": None,
        "main_tex": None,
        "translated_files": [],
        "compile_command": None,
        "translated_pdf_kind": None,
        "project_pdf": None,
        "latex_baseline_audit": None,
    }
    if mode == "off" or source_tex is None or source_tex.suffix.lower() != ".tex":
        reason = "disabled" if mode == "off" else "no_latex_source"
        manifest["reason"] = reason
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return manifest

    latex_output_dir = output_dir / "latex_direct"
    latex_output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "latex_direct.log"
    original_base_url = args.base_url
    proxy_server = None
    if should_enable_hymt_compat_proxy(args):
        proxy_config = ProxyConfig(
            model=args.model,
            upstream_base_url=original_base_url.rstrip("/"),
            api_key=args.api_key,
            port=int(getattr(args, "hymt_compat_proxy_port", DEFAULT_HYMT_COMPAT_PROXY_PORT)),
            policy_context_path=str(output_dir / "document_memory.json"),
        )
        try:
            proxy_server = start_hymt_compat_proxy(proxy_config)
            args.base_url = proxy_config.base_url
            manifest["hymt_compat_proxy"] = {
                "mode": getattr(args, "hymt_compat_proxy", "auto"),
                "enabled": True,
                "upstream_base_url": original_base_url,
                "proxy_base_url": proxy_config.base_url,
                "stats": {},
            }
        except OSError as exc:
            if getattr(args, "hymt_compat_proxy", "auto") == "on":
                raise
            manifest["hymt_compat_proxy"] = {
                "mode": getattr(args, "hymt_compat_proxy", "auto"),
                "enabled": False,
                "upstream_base_url": original_base_url,
                "proxy_base_url": None,
                "error": f"proxy_start_failed: {exc}",
                "stats": {},
            }
    command = build_latex_direct_command(args, input_pdf, source_tex, latex_output_dir)
    latex_env = env.copy()
    vendor_root = vendored_pdf2zh_skill_root()
    existing_pythonpath = latex_env.get("PYTHONPATH", "")
    latex_env["PYTHONPATH"] = str(vendor_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    compile_runtime = select_latex_compile_runtime(args)
    manifest["compile_runtime"] = compile_runtime
    if compile_runtime["selected"] == "docker":
        wrapper_dir = ensure_tex_docker_wrappers(output_dir / "_tex_docker_wrappers")
        latex_env["PATH"] = str(wrapper_dir) + os.pathsep + latex_env.get("PATH", "")
        latex_env["PDF2ZH_TEX_DOCKER_IMAGE"] = str(compile_runtime["docker_image"])
        compile_runtime["wrapper_dir"] = str(wrapper_dir)
    elif compile_runtime["selected"] == "missing":
        compile_runtime["error"] = "no local LaTeX compiler and docker is not available"
    manifest["command"] = redacted_command(command, args.api_key)

    started = time.monotonic()
    try:
        with log_path.open("w", encoding="utf-8") as log:
            log.write("COMMAND: " + " ".join(redacted_command(command, args.api_key)) + "\n")
            log.write(f"MODEL: {args.model}\n")
            log.write(f"BASE_URL: {args.base_url}\n")
            log.write(f"LATEX_DIRECT_HYMT_COMPAT_PROXY: {json.dumps(manifest['hymt_compat_proxy'], ensure_ascii=False)}\n")
            log.write(f"LOCAL_MAX_CONCURRENCY: {args.local_max_concurrency}\n")
            log.write(f"LATEX_COMPILE_RUNTIME: {json.dumps(compile_runtime, ensure_ascii=False)}\n")
            log.flush()
            try:
                proc = subprocess.run(
                    command,
                    cwd=output_dir,
                    env=latex_env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=args.latex_render_timeout,
                    check=False,
                )
                manifest["returncode"] = int(proc.returncode)
            except subprocess.TimeoutExpired:
                manifest["returncode"] = 124
                manifest["status"] = "error"
                manifest["errors"].append({"error_type": "timeout", "timeout_seconds": args.latex_render_timeout})
                log.write(f"\nTIMEOUT: exceeded {args.latex_render_timeout} seconds\n")
    finally:
        if proxy_server is not None:
            stats = dict(getattr(proxy_server, "stats", {}) or {})
            manifest["latex_direct_proxy_stats"] = stats
            if isinstance(manifest.get("hymt_compat_proxy"), dict):
                manifest["hymt_compat_proxy"]["stats"] = stats
            proxy_server.shutdown()
        args.base_url = original_base_url

    summary_path = latex_output_dir / "run_summary.json"
    manifest["run_summary"] = str(summary_path) if summary_path.exists() else None
    if manifest.get("returncode") not in {0, None}:
        manifest["status"] = "error"
        manifest["errors"].append({"error_type": "nonzero_exit", "returncode": manifest.get("returncode")})
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            manifest["run_summary_status"] = summary.get("status")
            manifest["translated_pdf"] = summary.get("pdf")
            manifest["translated_tex"] = summary.get("tex")
            manifest["english_tex"] = summary.get("english_tex")
            manifest["quality_report_json"] = summary.get("quality_report_json")
            manifest["quality_report_md"] = summary.get("quality_report_md")
            manifest["quality_issue_count"] = summary.get("quality_issue_count")
            manifest["auto_repairs"] = summary.get("auto_repairs")
            for key in [
                "latex_project_mode",
                "paper_source_dir",
                "paper_cn_dir",
                "main_tex",
                "translated_files",
                "compile_command",
                "translated_pdf_kind",
                "project_pdf",
            ]:
                if key in summary:
                    manifest[key] = summary.get(key)
            if summary.get("status") not in {None, "ok", "succeeded"}:
                manifest["status"] = "error"
                manifest["errors"].append({"error_type": "latex_run_summary_status", "status": summary.get("status")})
        except Exception as exc:
            manifest["status"] = "error"
            manifest["errors"].append({"error_type": "invalid_run_summary", "message": repr(exc)})

    translated_pdf = Path(str(manifest.get("translated_pdf") or ""))
    if manifest.get("status") != "error" and translated_pdf.is_file():
        manifest["status"] = "ok"
    elif manifest.get("status") != "error":
        manifest["status"] = "error"
        manifest["errors"].append({"error_type": "missing_latex_translated_pdf"})
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    manifest.update(infer_latex_direct_failure_stage(log_text, manifest))
    baseline_arg = Path(args.latex_baseline_pdf).expanduser().resolve() if getattr(args, "latex_baseline_pdf", None) else None
    baseline_pdf = baseline_arg if baseline_arg and baseline_arg.is_file() else default_latex_baseline_pdf(source_tex)
    current_pdf = Path(str(manifest.get("project_pdf") or manifest.get("translated_pdf") or ""))
    if baseline_pdf or current_pdf.is_file():
        manifest["latex_baseline_audit"] = write_latex_baseline_audit(
            output_dir,
            baseline_pdf=baseline_pdf,
            current_pdf=current_pdf if current_pdf.is_file() else None,
            source_tex=source_tex,
            summary=summary if "summary" in locals() and isinstance(summary, dict) else None,
        )
    gate_segments = load_latex_direct_segments_for_gate(summary) if "summary" in locals() and isinstance(summary, dict) else []
    quality_gate = build_latex_direct_quality_gate(
        source_segments=gate_segments,
        latex_baseline_audit=manifest.get("latex_baseline_audit"),
    )
    quality_gate_path = output_dir / "latex_direct_quality_gate.json"
    quality_gate_path.write_text(json.dumps(quality_gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    segment_repair_plan = write_latex_segment_repair_plan(output_dir, quality_gate, gate_segments)
    paragraph_structure_manifest = write_latex_paragraph_structure_repair_manifest(output_dir, quality_gate)
    manifest["latex_direct_quality_gate"] = str(quality_gate_path)
    manifest["latex_direct_quality_gate_status"] = quality_gate.get("status")
    manifest["latex_segment_repair_plan"] = segment_repair_plan.get("path")
    manifest["latex_segment_repair_plan_status"] = segment_repair_plan.get("status")
    manifest["latex_paragraph_structure_repair_manifest"] = paragraph_structure_manifest.get("path")
    manifest["latex_paragraph_structure_repair_status"] = paragraph_structure_manifest.get("status")
    manifest["duration_seconds"] = round(time.monotonic() - started, 3)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def prepare_source(input_pdf: Path, output_dir: Path, source_override: Path | None = None) -> dict[str, Any]:
    source_input = source_override or input_pdf
    manifest = prepare_paper_source.prepare_source(
        SimpleNamespace(
            input=str(source_input),
            output_dir=str(output_dir),
            text=None,
            stdin=False,
            no_ocr=True,
            keep_pdf_noise=False,
        )
    )
    if source_override:
        manifest["render_input_pdf"] = str(input_pdf)
        manifest["source_override"] = {
            "path": str(source_override),
            "input_type": manifest.get("input_type"),
            "extraction_method": manifest.get("extraction_method"),
            "reason": "LaTeX source is the translation source of truth; render path is recorded separately in render_manifest.json.",
        }
        (output_dir / "source_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return manifest

def latex_candidate_score(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return -1
    name = path.stem.lower()
    score = 0
    if name in LATEX_MAIN_NAME_HINTS:
        score += 80
    if name in LATEX_BAD_NAME_HINTS or name.startswith("test_"):
        score -= 120
    if "\\begin{document}" in text:
        score += 200
    if "\\title" in text:
        score += 50
    if "\\section" in text:
        score += 30
    if "\\documentclass" in text:
        score += 50
    score += min(len(text) // 5000, 20)
    return score

def iter_latex_candidates(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".tex":
        return [root]
    if not root.exists() or not root.is_dir():
        return []
    candidates: list[Path] = []
    for path in root.rglob("*.tex"):
        parts = {part.lower() for part in path.parts}
        if parts & {".venv", "node_modules", "__pycache__", ".git"}:
            continue
        candidates.append(path)
    return candidates

def discover_latex_source(input_pdf: Path, args: argparse.Namespace) -> tuple[Path | None, dict[str, Any]]:
    from scanned_raster.latex_identity import latex_cache_root, resolve_latex_identity

    if getattr(args, "disable_latex_autodiscovery", False):
        return None, {"policy": "latex_first_auto", "status": "disabled", "identity_status": "not_applicable"}
    explicit = getattr(args, "source_override", None)
    if explicit:
        path = Path(explicit).expanduser().resolve()
        identity = resolve_latex_identity(input_pdf, explicit_override=path)
        return path, {
            "policy": "manual_compat_override",
            "status": "manual",
            "source_path": str(path),
            "identity_status": identity.get("status"),
            "match_method": identity.get("match_method"),
        }
    roots: list[Path] = []
    hint = os.environ.get(LATEX_SOURCE_HINT_ENV, "").strip()
    if hint:
        hinted = Path(hint).expanduser().resolve()
        if hinted.exists():
            if hinted.is_file() and hinted.suffix.lower() == ".tex":
                identity = resolve_latex_identity(input_pdf, explicit_override=hinted)
                return hinted, {
                    "policy": "latex_first_auto",
                    "status": "env_hint_file",
                    "source_path": str(hinted),
                    "identity_status": identity.get("status"),
                    "match_method": "env_hint_file",
                }
            roots.append(hinted)
    for raw in os.environ.get(LATEX_SOURCE_ROOTS_ENV, "").split(os.pathsep):
        if raw.strip():
            roots.append(Path(raw).expanduser().resolve())
    for raw in getattr(args, "latex_source_root", []) or []:
        roots.append(Path(raw).expanduser().resolve())
    pdf_parent = input_pdf.parent
    roots.extend(
        [
            pdf_parent,
            pdf_parent / "source",
            pdf_parent / "paper_source",
            pdf_parent / "latex",
            pdf_parent / "arxiv",
        ]
    )
    cache_root = latex_cache_root()
    cache_resolved = cache_root.resolve() if cache_root is not None and cache_root.exists() else None
    seen: set[Path] = set()
    scored: list[tuple[int, Path]] = []
    for root in roots:
        resolved_root = root.resolve() if root.exists() else root
        if resolved_root in seen:
            continue
        if cache_resolved is not None and resolved_root == cache_resolved:
            continue
        seen.add(resolved_root)
        for candidate in iter_latex_candidates(root):
            score = latex_candidate_score(candidate)
            if score >= 120:
                scored.append((score, candidate.resolve()))
    scored.sort(key=lambda item: (item[0], -len(str(item[1]))), reverse=True)
    adjacent = scored[0][1] if scored else None
    identity = resolve_latex_identity(
        input_pdf,
        adjacent_candidate=adjacent,
        cache_root=cache_root,
        searched_roots=[str(root) for root in roots],
    )
    if identity.get("status") == "verified_match" and identity.get("source_path"):
        source = Path(str(identity["source_path"]))
        return source, {
            "policy": "latex_first_auto",
            "status": "found",
            "source_path": str(source),
            "candidate_count": identity.get("candidate_count", len(scored)),
            "searched_roots": identity.get("searched_roots") or [str(root) for root in roots],
            "identity_status": "verified_match",
            "match_method": identity.get("match_method"),
        }
    if identity.get("status") == "ambiguous":
        return None, {
            "policy": "latex_identity",
            "status": "ambiguous",
            "source_path": None,
            "identity_status": "ambiguous",
            "searched_roots": identity.get("searched_roots") or [str(root) for root in roots],
            "notes": identity.get("notes") or [],
        }
    if adjacent is not None:
        return adjacent, {
            "policy": "latex_first_auto",
            "status": "found",
            "source_path": str(adjacent),
            "candidate_count": len(scored),
            "searched_roots": [str(root) for root in roots],
            "identity_status": identity.get("status"),
            "match_method": None,
            "notes": identity.get("notes") or ["邻近 .tex 未核验身份，不能作为 latex_direct。"],
        }
    return None, {
        "policy": "latex_first_auto",
        "status": "not_found",
        "searched_roots": [str(root) for root in roots],
        "identity_status": identity.get("status") or "not_applicable",
        "notes": identity.get("notes") or [],
    }

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
