"""在新候选目录重编译已译 LaTeX 项目并重建交付证据；不调用翻译模型。"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from assess_delivery import inspect_pdf, read_object, sha256
from bounded_execution import run_bounded

DERIVED_RENDER_FIELDS = {
    'visual_layout_report', 'visual_layout_report_path', 'dual_visual_report', 'dual_visual_report_path',
    'dropped_text_audit', 'paragraph_label_audit', 'pymupdf_layout_audit', 'poppler_text_bbox_audit',
    'layout_structure_gate', 'toc_row_map', 'metadata_yband_audit', 'table_region_map',
    'structured_writeback_manifest', 'block_bridge', 'qa_repaired_pdf', 'rerender_candidates',
    'rerender_candidate_count', 'coverage_gate',
}


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clone_candidate(source: Path, destination: Path) -> dict[str, str]:
    """小批次恢复专用；拒绝原地操作、软链接、过大目录和继承旧验收。"""
    source_alias = str(source.absolute())
    source = source.resolve()
    if destination.exists() or source == destination.resolve() or source in destination.resolve().parents:
        raise ValueError("recovery requires a fresh candidate directory outside the source run")
    files = list(source.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("recovery input contains symlinks")
    files = [path for path in files if path.is_file()]
    if len(files) > 3000 or sum(path.stat().st_size for path in files) > 512 * 1024**2:
        raise ValueError("recovery input exceeds 3000 files or 512 MiB; use a narrower case")
    frozen = {str(path.relative_to(source)): sha256(path) for path in files}
    exclusions = {"human_visual_review.json", "semantic_review.json", "visual_review.json",
                  "e2e_result.json", "delivery_assessment.json", "recovery_receipts", "latex_recovery_receipt.json",
                  "final_readable.pdf", "final_pdf_manifest.json", "translation.qa_repaired.md",
                  "visual_layout_report.json", "dual_visual_report.json", "visual_pages",
                  "quality_report.md", "qa_checks.json", "alignment_report.json",
                  "affected_blocks.json", "confirmed_repair_plan.json"}
    exclusions.update(f'{name}.json' for name in DERIVED_RENDER_FIELDS)
    def exclude_reviews(directory: str, names: list[str]) -> list[str]:
        return [name for name in names if name in exclusions or re.fullmatch(
            r"(?:delivery_assessment|human_visual_review|semantic_review|visual_review|e2e_result)(?:_v\d+)?\.json", name)]
    shutil.copytree(source, destination, ignore=exclude_reviews)
    for path in destination.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md"}:
            text = path.read_text(encoding="utf-8")
            updated = text.replace(str(source), str(destination.resolve())).replace(source_alias, str(destination.resolve()))
            if updated != text:
                path.write_text(updated, encoding="utf-8")
    return frozen


def apply_tex_repairs(candidate: Path, repairs: dict[str, Any]) -> list[dict[str, Any]]:
    """先验证全部文件身份及唯一匹配，再应用有来源依据的精确替换。"""
    planned: dict[Path, str] = {}
    changes: list[dict[str, Any]] = []
    cn = (candidate / "latex_direct/paper_cn").resolve()
    for entry in repairs.get("files", []):
        rel = Path(entry["path"])
        path = cn / rel
        if rel.is_absolute() or ".." in rel.parts or path.suffix != ".tex" or path.is_symlink() or not path.resolve().is_relative_to(cn):
            raise ValueError("repair must target a regular TeX file inside paper_cn")
        if path in planned or not path.is_file() or sha256(path) != entry["before_sha256"]:
            raise ValueError("repair source SHA mismatch or duplicate file")
        before = path.read_text(encoding="utf-8")
        after = before
        for patch in entry["replacements"]:
            if not patch.get("reason") or not patch.get("source_evidence") or not patch.get("before") or after.count(patch["before"]) != 1:
                raise ValueError("repair needs source evidence and exactly one match")
            after = after.replace(patch["before"], patch["after"], 1)
        planned[path] = after
        changes.append({"path": str(rel), "before_sha256": entry["before_sha256"], "replacements": entry["replacements"]})
    for path, after in planned.items():
        path.write_text(after, encoding="utf-8")
    for change in changes:
        change["after_sha256"] = sha256(cn / change["path"])
    return changes


def clear_derived_render_evidence(render: dict[str, Any]) -> dict[str, Any]:
    """旧分析只留在源运行及恢复回执，不能跟随新候选路径冒充当前证据。"""
    old = {key: render.pop(key) for key in sorted(DERIVED_RENDER_FIELDS) if key in render}
    if render.get('pdf_backend_skipped'):
        render['pdf_backend_outputs'] = {}
    return old


def refresh_visual_evidence(source_pdf: Path, candidate_pdf: Path, dual_pdf: Path,
                            output_dir: Path, page_count: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not 1 <= page_count <= 20:
        raise ValueError('visual refresh requires 1–20 current pages')
    identities = {'source_pdf_sha256': sha256(source_pdf), 'candidate_pdf_sha256': sha256(candidate_pdf)}
    dual_sha = sha256(dual_pdf)
    execution = run_bounded(
        [sys.executable, str(Path(__file__).with_name('visual_layout.py')), '--source-pdf', str(source_pdf),
         '--translated-pdf', str(candidate_pdf), '--standard-dual-pdf', str(dual_pdf),
         '--output-dir', str(output_dir), '--max-pages', str(page_count), '--pages', f'1-{page_count}'],
        cwd=output_dir, receipt_dir=output_dir/'recovery_receipts/visual', operation='latex-visual-refresh',
        timeout_seconds=180, rss_limit=4*1024**3, max_processes=32)
    write(output_dir/'visual_refresh_execution.json', execution)
    report = read_object(output_dir/'visual_layout_report.json')
    dual = read_object(output_dir/'dual_visual_report.json')
    valid = (execution.get('status') == 'succeeded'
             and report.get('status') in {'ok', 'warn'} and dual.get('status') in {'ok', 'warn'}
             and all(report.get(k) == v and dual.get(k) == v for k, v in identities.items())
             and dual.get('standard_dual_pdf_sha256') == dual_sha
             and report.get('visual_check_pages') == list(range(1, page_count+1))
             and report.get('page_count_checked') == page_count
             and sha256(source_pdf) == identities['source_pdf_sha256']
             and sha256(candidate_pdf) == identities['candidate_pdf_sha256'] and sha256(dual_pdf) == dual_sha)
    if not valid:
        raise ValueError('current visual evidence missing, stale, incomplete or unavailable')
    return report, dual, execution


def apply_asset_repairs(candidate: Path, repairs: dict[str, Any]) -> list[dict[str, Any]]:
    """仅替换有区域写回回执的PDF素材；源项目及旧候选均不修改。"""
    cn=(candidate/'latex_direct/paper_cn').resolve();planned=[]
    entries=repairs.get('assets',[])
    if not 1<=len(entries)<=20:raise ValueError('asset repair count outside budget')
    for entry in entries:
        rel=Path(entry['path']);dest=cn/rel;replacement=Path(entry['replacement_pdf']);receipt_path=Path(entry['region_receipt'])
        if (rel.is_absolute() or '..' in rel.parts or rel.suffix!='.pdf' or dest.is_symlink()
                or not dest.resolve().is_relative_to(cn) or any(x[0]==dest for x in planned)):
            raise ValueError('unsafe or duplicate asset path')
        if (sha256(dest)!=entry['before_sha256'] or replacement.is_symlink() or receipt_path.is_symlink()
                or sha256(replacement)!=entry['replacement_sha256'] or sha256(receipt_path)!=entry['region_receipt_sha256']):
            raise ValueError('asset repair identity mismatch')
        receipt=read_object(receipt_path)
        if (receipt.get('mechanical_region_writeback')!='passed' or receipt.get('candidate_sha256')!=entry['replacement_sha256']
                or receipt.get('inputs',{}).get('base_pdf',{}).get('sha256')!=entry['before_sha256']
                or not entry.get('reason') or not receipt.get('checks')
                or not all(x.get('target_exact') for x in receipt['checks'])
                or not receipt.get('outside_region_checks')
                or not all(x.get('unchanged_outside_regions') for x in receipt['outside_region_checks'])):
            raise ValueError('asset repair lacks passing region evidence')
        if inspect_pdf(replacement,1).get('status')!='ok':raise ValueError('asset must be a bounded one-page PDF')
        planned.append((dest,replacement,entry))
    for dest,replacement,entry in planned:
        shutil.copyfile(replacement,dest)
        if sha256(dest)!=entry['replacement_sha256']:raise ValueError('asset copy mismatch')
    return [dict(entry) for _,_,entry in planned]


def recover(source_run: Path, output_dir: Path, *, max_pages: int = 20, tex_repairs: Path | None = None, asset_repairs: Path | None = None) -> dict[str, Any]:
    import run_pdf_translation as pipeline
    source_run = source_run.resolve()
    output_dir = output_dir.resolve()
    if not 1 <= max_pages <= 20:
        raise ValueError("recovery currently supports at most 20 pages per case")
    old_summary = read_object(source_run / "latex_direct/run_summary.json")
    route = read_object(source_run / "route_manifest.json")
    if route.get("document_route") != "latex_direct" or route.get("dispatch_allowed") is not True:
        raise ValueError("verified LaTeX route required")
    if old_summary.get("latex_project_mode") != "in-place" or old_summary.get("translated_pdf_kind") != "project_main_pdf":
        raise ValueError("project main PDF evidence required")
    source_pdf = Path(route["input_pdf"])
    if route.get("input_sha256") != sha256(source_pdf):
        raise ValueError("source PDF changed since routing")
    if inspect_pdf(source_pdf, max_pages).get("status") != "ok":
        raise ValueError("source PDF exceeds bounded recovery scope")
    frozen = clone_candidate(source_run, output_dir)
    receipt_path = output_dir / "latex_recovery_receipt.json"
    receipt: dict[str, Any] = {"status": "started", "source_run": str(source_run), "source_files_sha256": frozen,
                             "model_calls": 0, "candidate_reexecuted": False, "render_reexecuted": True,
                             "old_acceptance_inherited": False, "output_dir": str(output_dir)}
    write(receipt_path, receipt)
    # 重编译尚未成功时，不能让拷贝来的清单宣称当前候选已通过。
    for name in ("render_manifest.json", "backend_run_manifest.json", "direct_latex_render_manifest.json"):
        pending = read_object(output_dir / name)
        pending.update(status="recovery_pending", errors=["candidate recovery not completed"], recovery_receipt=str(receipt_path))
        if name == "render_manifest.json":
            receipt['invalidated_render_evidence']=clear_derived_render_evidence(pending)
            pending.update(outputs={}, all_pdf_outputs=[], delivery_mode="candidate_pending_review")
        write(output_dir / name, pending)
    if tex_repairs:
        receipt["tex_repairs_manifest_sha256"] = sha256(tex_repairs)
        receipt["tex_repairs"] = apply_tex_repairs(output_dir, read_object(tex_repairs))
        receipt["review_scope"] = "targeted_controller_repairs; fresh semantic and visual review required; not independent candidate evaluation"
        write(receipt_path, receipt)
    if asset_repairs:
        receipt['asset_repairs_manifest_sha256']=sha256(asset_repairs)
        receipt['asset_repairs']=apply_asset_repairs(output_dir,read_object(asset_repairs))
        receipt['review_scope']='controller asset repair; compiled figures require fresh visual review; no old acceptance inherited'
        write(receipt_path,receipt)
    summary_path = output_dir / "latex_direct/run_summary.json"
    summary = read_object(summary_path)
    cn = output_dir / "latex_direct/paper_cn"
    main = str(summary.get("main_tex") or "")
    if Path(main).name != main or not main.endswith(".tex") or not (cn / main).is_file():
        raise ValueError("missing or unsafe main TeX filename")
    segments = pipeline.load_latex_direct_segments_for_gate(summary)
    if not segments:
        raise ValueError("missing translated segment evidence")
    gate = pipeline.build_latex_direct_quality_gate(source_segments=segments)
    if tex_repairs:
        gate["scope_note"] = "Checks preexisting translation segments only; targeted TeX edits require final-PDF semantic and visual review."
    write(output_dir / "latex_direct_quality_gate.json", gate)
    if gate.get("status") != "ok":
        receipt.update(status="blocked", reason="latex_source_quality_gate")
        write(receipt_path, receipt)
        return receipt
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join(["/opt/homebrew/bin", "/Library/TeX/texbin", env.get("PATH", "")])
    compiler = shutil.which("latexmk", path=env["PATH"])
    if not compiler:
        receipt.update(status="blocked", reason="latexmk_missing")
        write(receipt_path, receipt)
        return receipt
    command = [compiler, "-g", "-xelatex", "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", "-no-shell-escape", main]
    compilation = run_bounded(command, cwd=cn, receipt_dir=output_dir / "recovery_receipts/compile",
                              operation="latex-recompile", timeout_seconds=300, env=env)
    receipt["compile"] = compilation
    if compilation["status"] != "succeeded":
        receipt.update(status="blocked", reason=compilation.get("stop_reason") or "compile_failed")
        write(receipt_path, receipt)
        return receipt
    pdf = cn / Path(main).with_suffix(".pdf")
    pdf_info = inspect_pdf(pdf, max_pages)
    if pdf_info.get("status") != "ok" or not pdf_info.get("cjk_count"):
        receipt.update(status="blocked", reason="invalid_compiled_pdf")
        write(receipt_path, receipt)
        return receipt
    summary.update(status="succeeded", pdf=str(pdf), project_pdf=str(pdf), work_pdf=str(pdf),
                   tex=str(cn / main), compile_command=command, error=None)
    write(summary_path, summary)
    direct = read_object(output_dir / "direct_latex_render_manifest.json")
    direct.update(status="ok", returncode=0, errors=[], translated_pdf=str(pdf), project_pdf=str(pdf),
                  translated_tex=str(cn / main), run_summary=str(summary_path), run_summary_status="succeeded",
                  compile_stage_status="succeeded", failure_stage=None, compile_command=command,
                  latex_direct_quality_gate=str(output_dir / "latex_direct_quality_gate.json"),
                  latex_direct_quality_gate_status="ok", recovery_receipt=str(receipt_path))
    write(output_dir / "direct_latex_render_manifest.json", direct)
    render = read_object(output_dir / "render_manifest.json")
    selected = {"translated_pdf": str(pdf), "mono_pdf": str(pdf), "latex_direct_pdf": str(pdf)}
    bilingual = pipeline.build_standard_bilingual_output(source_pdf, output_dir, selected, enabled=True)
    render.update(status="ok", errors=[], actual_render_source="latex_direct", render_source_of_truth="latex_direct",
                  engine="latex-direct-vendored-pdf2zh-skill", engine_role="latex_source_primary",
                  outputs=selected, all_pdf_outputs=[str(pdf), selected.get("dual_pdf")],
                  latex_direct_render=direct, bilingual_pdf=bilingual, delivery_mode="candidate_pending_review",
                  skip_visual_eval=False, recovery_receipt=str(receipt_path))
    text, method = pipeline.extract_pdf_text(pdf)
    render["validation"] = {"has_translated_pdf": True, "cjk_char_count": pdf_info["cjk_count"],
                            "translated_text_chars": len(text), "translated_text_extraction_method": method,
                            "gates": {"status": "partial", "reason": "recovered_candidate_pending_review"}}
    source_manifest = read_object(output_dir / "source_manifest.json")
    pipeline.write_translation_artifacts(output_dir, text, method, source_manifest, str(render.get("model") or "unknown"),
                                         executor_provider="latex_direct")
    write(output_dir / "render_manifest.json", render)
    backend = read_object(output_dir / "backend_run_manifest.json")
    backend.update(status="partial", errors=[], actual_render_source="latex_direct", latex_direct_render=direct,
                   delivery_mode="candidate_pending_review", delivery_gates=render["validation"]["gates"])
    write(output_dir / "backend_run_manifest.json", backend)
    try:
        visual, dual_visual, visual_execution = refresh_visual_evidence(source_pdf, pdf, Path(bilingual['output_pdf']), output_dir, pdf_info['page_count'])
    except (ValueError, KeyError) as exc:
        render.update(status='partial', errors=[str(exc)])
        write(output_dir/'render_manifest.json', render)
        receipt.update(status='blocked', reason='visual_refresh_failed', visual_refresh_error=str(exc))
        write(receipt_path, receipt)
        return receipt
    render.update(visual_layout_report=visual, visual_layout_report_path=str(output_dir/'visual_layout_report.json'),
                  dual_visual_report=dual_visual, dual_visual_report_path=str(output_dir/'dual_visual_report.json'))
    write(output_dir/'render_manifest.json', render)
    receipt['visual_refresh_execution']=str(output_dir/'visual_refresh_execution.json')
    receipt['visual_report_sha256']=sha256(output_dir/'visual_layout_report.json')
    receipt['dual_visual_report_sha256']=sha256(output_dir/'dual_visual_report.json')
    pipeline.run_quality_check(output_dir, render)
    receipt.update(status="render_recovered_pending_quality_review", compiled_pdf=pdf_info,
                   bilingual_status=bilingual.get("status"), original_unchanged=all(
                       sha256(source_run / name) == digest for name, digest in frozen.items()))
    write(receipt_path, receipt)
    return {k: v for k, v in receipt.items() if k != "source_files_sha256"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--tex-repairs", type=Path, help="SHA-bound, source-evidenced exact TeX repairs; produces a fresh review candidate")
    parser.add_argument("--asset-repairs", type=Path, help="SHA-bound one-page PDF replacements with passing region receipts")
    args = parser.parse_args()
    result = recover(args.source_run, args.output_dir, max_pages=args.max_pages, tex_repairs=args.tex_repairs, asset_repairs=args.asset_repairs)
    print(json.dumps({key: result.get(key) for key in ("status", "reason", "output_dir", "model_calls", "original_unchanged", "bilingual_status")}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "render_recovered_pending_quality_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
