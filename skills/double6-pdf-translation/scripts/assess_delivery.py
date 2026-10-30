"""只读验收：分别报告机械、语义、视觉与人工状态，禁止局部成功覆盖失败证据。"""
from __future__ import annotations
from stable_page_raster import stable_get_pixmap

import argparse
import hashlib
import json
import json
import re
from pathlib import Path
from typing import Any

ASSESSMENT_VERSION = 1
ROUTES = {"digital_pdf": "pdf_backend", "latex_verified": "latex_direct"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def qa_findings(text: str) -> list[dict[str, str]]:
    """冻结报告行作为证据；这些是待裁决 finding，不是已确认译文错误。"""
    result = []
    for line in text.splitlines():
        if not re.match(r"^\|\s*(high|medium)\s*\|", line):
            continue
        fields = [value.strip() for value in line.strip("|").split("|")]
        result.append({"finding_id": hashlib.sha256(line.encode()).hexdigest(),
                       "severity": fields[0], "category": fields[1], "evidence": line})
    return result


def receipt_valid(receipt: dict[str, Any], source_sha: str, candidate_sha: str,
                  page_count: int, standards: set[str]) -> bool:
    pages = receipt.get("pages")
    declared = receipt.get("standards")
    return bool(
        source_sha and candidate_sha
        and receipt.get("conclusion") == "accepted"
        and receipt.get("source_sha256") == source_sha
        and receipt.get("candidate_sha256") == candidate_sha
        and str(receipt.get("reviewer") or "").strip()
        and str(receipt.get("reviewed_at") or "").strip()
        and isinstance(pages, list) and all(type(p) is int for p in pages)
        and set(pages) == set(range(1, page_count + 1))
        and isinstance(declared, list) and all(isinstance(s, str) for s in declared) and standards <= set(declared)
    )


def inspect_pdf(path: Path | None, max_pages: int) -> dict[str, Any]:
    try:
        return _inspect_pdf(path, max_pages)
    except (ValueError, OSError, RuntimeError) as exc:
        return {"status": "invalid", "path": str(path), "error_type": type(exc).__name__}


def _inspect_pdf(path: Path | None, max_pages: int) -> dict[str, Any]:
    if not path or not path.is_file():
        return {"status": "missing"}
    import fitz
    with fitz.open(path) as document:
        if document.needs_pass:
            return {"status": "encrypted", "path": str(path)}
        count = document.page_count
        if not 0 < count <= max_pages:
            return {"status": "page_limit", "page_count": count, "path": str(path)}
        pages = [{"page": i + 1, "size": list(page.rect)[2:], "rotation": page.rotation,
                  "cjk_count": len(re.findall(r"[\u3400-\u9fff]", page.get_text()))}
                 for i, page in enumerate(document)]
    return {"status": "ok", "path": str(path), "sha256": sha256(path),
            "page_count": count, "pages": pages,
            "cjk_count": sum(p["cjk_count"] for p in pages)}


def check_bilingual_sides(source_path: Path, target_path: Path, dual_path: Path, max_pages: int) -> dict[str, Any]:
    """逐页验证英左中右的几何、可抽取文字与缩略像素；每次只加载一页。"""
    import fitz
    from PIL import Image, ImageChops, ImageStat
    rows = []
    try:
        with fitz.open(source_path) as source, fitz.open(target_path) as target, fitz.open(dual_path) as dual:
            count = max(len(source), len(target))
            if len(dual) != count or not 0 < count <= max_pages:
                return {"status": "invalid", "reason": "page_count"}
            for i in range(count):
                left = source[i] if i < len(source) else None
                right = target[i] if i < len(target) else None
                left_rect = (left or right).rect
                right_rect = (right or left).rect
                page = dual[i]
                if abs(page.rect.width - left_rect.width - right_rect.width) > 1 or abs(page.rect.height - max(left_rect.height, right_rect.height)) > 1:
                    return {"status": "invalid", "reason": "side_geometry", "page": i + 1}
                for side, expected, x in [("left", left, 0), ("right", right, left_rect.width)]:
                    if expected is None:
                        continue
                    clip = fitz.Rect(x, 0, x + expected.rect.width, expected.rect.height)
                    norm = lambda text: re.sub(r"\s+", "", text)
                    expected_text = norm(expected.get_text())
                    actual_text = norm(page.get_text(clip=clip))
                    text_matches = not actual_text or actual_text == expected_text
                    images = []
                    for pdf_page, region in [(expected, expected.rect), (page, clip)]:
                        # 先将左右裁区移到相同原点，再采样，避免右页非整数位移
                        # 导致额外一列像素及缩放抗锯齿差异被误判为内容变化。
                        matrix = fitz.Matrix(.5, .5).pretranslate(-region.x0, -region.y0)
                        pix = stable_get_pixmap(pdf_page, matrix=matrix, clip=region, colorspace=fitz.csGRAY, alpha=False)
                        images.append(Image.frombytes("L", [pix.width, pix.height], pix.samples).resize((240, 320)))
                    difference = ImageChops.difference(*images)
                    mae = ImageStat.Stat(difference).mean[0]
                    changed = sum(difference.histogram()[33:]) / (240 * 320)
                    ok = text_matches and mae <= 3 and changed <= .04
                    rows.append({"page": i + 1, "side": side, "text_matches": text_matches, "pixel_mae": round(mae, 3), "changed_pixel_fraction": round(changed, 5), "status": "ok" if ok else "mismatch"})
            return {"status": "ok" if all(r["status"] == "ok" for r in rows) else "mismatch", "pages": rows}
    except (ValueError, OSError, RuntimeError) as exc:
        return {"status": "invalid", "error_type": type(exc).__name__}


def assess(output_dir: Path, source_pdf: Path, route: str, *, min_pages: int = 5,
           max_pages: int = 20) -> dict[str, Any]:
    if route not in ROUTES or min_pages < 1 or max_pages < min_pages:
        raise ValueError("invalid route or page bounds")
    output_dir = output_dir.resolve()
    source_pdf = source_pdf.resolve()
    evidence: dict[str, str] = {}
    blockers: list[str] = []

    def load(name: str) -> dict[str, Any]:
        path = output_dir / name
        if path.is_file():
            evidence[name] = sha256(path)
        try:
            return read_object(path)
        except (ValueError, OSError) as exc:
            blockers.append(f"invalid_evidence:{name}:{type(exc).__name__}")
            return {}

    routing = load("route_manifest.json")
    render = load("render_manifest.json")
    source = inspect_pdf(source_pdf, max_pages)
    source_sha = source.get("sha256", "")
    if source.get("status") != "ok":
        blockers.append("source_pdf_unavailable_or_over_limit")
    if not source_sha or routing.get("input_sha256") != source_sha:
        blockers.append("route_input_sha_mismatch")
    if routing.get("dispatch_allowed") is not True or routing.get("document_route") != ROUTES[route]:
        blockers.append("route_not_ready_or_mismatch")

    outputs = render.get("outputs") if isinstance(render.get("outputs"), dict) else {}
    target = outputs.get("translated_pdf") or outputs.get("mono_pdf")
    target_path = Path(target) if target else None
    if target_path and not target_path.is_absolute():
        target_path = output_dir / target_path
    pdf = inspect_pdf(target_path, max_pages)
    if pdf.get("status") != "ok":
        blockers.append("primary_pdf_missing_or_invalid")
    if pdf.get("page_count", 0) < min_pages:
        blockers.append("below_minimum_pages")
    if not pdf.get("cjk_count"):
        blockers.append("searchable_chinese_missing")
    if route != "latex_verified" and pdf.get("page_count") != source.get("page_count"):
        blockers.append("page_count_mismatch")
    if True:
        if render.get("status") != "ok" or render.get("actual_render_source") != ROUTES[route]:
            blockers.append("render_status_or_actual_source_mismatch")
        if render.get("errors"):
            blockers.append("render_errors_unresolved")
        if route != "latex_verified" and render.get("validation", {}).get("gates", {}).get("status") != "ok":
            blockers.append("render_gates_not_ok")

    latex_compile = None
    if route == "latex_verified":
        direct = load("direct_latex_render_manifest.json")
        summary = load("latex_direct/run_summary.json")
        gate = load("latex_direct_quality_gate.json")
        latex_compile = summary.get("status")
        if direct.get("status") != "ok" or latex_compile not in {"ok", "succeeded"} or gate.get("status") != "ok":
            blockers.append("latex_manifest_chain_inconsistent")
        if direct.get("translated_pdf") != target:
            blockers.append("latex_primary_pointer_mismatch")
        gates = render.get("validation", {}).get("gates", {})
        if gates.get("status") != "ok":
            # 恢复器将待语义/视觉审校写在聚合门中。只在当前 PDF、源路由、
            # 编译退出结果和清单指针均匹配时，单独承认机械成功；其它层照常验收。
            recovery = load("latex_recovery_receipt.json")
            compiled = recovery.get("compiled_pdf", {})
            compilation = recovery.get("compile", {})
            command = compilation.get("command", {}) if isinstance(compilation, dict) else {}
            compiled = compiled if isinstance(compiled, dict) else {}
            command = command if isinstance(command, dict) else {}
            frozen = recovery.get("source_files_sha256", {})
            expected_receipt = str(output_dir / "latex_recovery_receipt.json")
            pending_recovery = (
                gates == {"status": "partial", "reason": "recovered_candidate_pending_review"}
                and render.get("delivery_mode") == "candidate_pending_review"
                and recovery.get("status") == "render_recovered_pending_quality_review"
                and recovery.get("output_dir") == str(output_dir)
                and render.get("recovery_receipt") == direct.get("recovery_receipt") == expected_receipt
                and recovery.get("old_acceptance_inherited") is False
                and recovery.get("original_unchanged") is True
                and isinstance(frozen, dict)
                and frozen.get("route_manifest.json") == evidence.get("route_manifest.json")
                and pdf.get("status") == compiled.get("status") == "ok"
                and compiled.get("sha256") == pdf.get("sha256")
                and compiled.get("page_count") == pdf.get("page_count")
                and compiled.get("path") == summary.get("pdf") == summary.get("project_pdf") == target
                and isinstance(compilation, dict) and compilation.get("status") == "succeeded"
                and command.get("status") == "succeeded" and command.get("returncode") == 0
                and command.get("timed_out") is False
                and direct.get("returncode") == 0 and not direct.get("errors")
                and isinstance(summary.get("compile_command"), list) and bool(summary.get("compile_command"))
                and summary.get("compile_command") == direct.get("compile_command")
                and isinstance(command.get("argv"), list)
                and command["argv"][-len(summary["compile_command"]):] == summary["compile_command"]
            )
            if not pending_recovery:
                blockers.append("render_gates_not_ok")

    qa_path = output_dir / "quality_report.md"
    qa_text = qa_path.read_text(encoding="utf-8") if qa_path.exists() else ""
    qa_sha = sha256(qa_path) if qa_path.exists() else None
    if qa_sha:
        evidence["quality_report.md"] = qa_sha
    findings = qa_findings(qa_text)
    match = re.search(r"状态：`([^`]+)`", qa_text)
    qa_status = match.group(1) if match else "missing"
    qa_binding_field = "quality_report_sha256"
    semantic_review = load("semantic_review.json")
    candidate_sha = pdf.get("sha256", "")
    count = pdf.get("page_count", 0)
    semantic_ok = receipt_valid(semantic_review, source_sha, candidate_sha, count,
                               {"accuracy", "coverage", "terminology", "protected_spans"})
    dispositions = semantic_review.get("finding_dispositions", {})
    if not isinstance(dispositions, dict):
        dispositions = {}
    unresolved = [f for f in findings if not (
        isinstance(dispositions.get(f["finding_id"], {}), dict)
        and dispositions.get(f["finding_id"], {}).get("status") in {"false_positive", "allowed_preservation"}
        and dispositions.get(f["finding_id"], {}).get("evidence"))]
    semantic_findings = [f for f in findings if f.get('review_layer', 'semantic') == 'semantic']
    semantic_unresolved = [f for f in unresolved if f.get('review_layer', 'semantic') == 'semantic']
    if semantic_findings and (semantic_review.get(qa_binding_field) != qa_sha or semantic_unresolved):
        semantic_ok = False

    visual = load("visual_review.json")
    visual_ok = receipt_valid(visual, source_sha, candidate_sha, count,
                             {"full_page_sweep", "targeted_region_audit", "readability"})
    human = load("human_visual_review.json")
    human_ok = receipt_valid(human, source_sha, candidate_sha, count,
                            {"full_page_sweep", "readability"}) and human.get("reviewer_kind") == "human"
    if human_ok:
        unresolved = [f for f in unresolved if f.get('review_layer') != 'human']
    automatic_visual = load("visual_layout_report.json")
    automatic_visual_path = output_dir / "visual_layout_report.json"
    automatic_visual_sha = sha256(automatic_visual_path) if automatic_visual_path.is_file() else None
    automatic_visual_findings = []
    for finding in automatic_visual.get("findings", []):
        if isinstance(finding, dict) and finding.get("severity") in {"blocking", "high", "error"}:
            identity = hashlib.sha256(json.dumps(finding, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            automatic_visual_findings.append({**finding, "finding_id": identity})
    automatic_visual_unresolved = list(automatic_visual_findings)
    if automatic_visual_findings:
        identity_current = (automatic_visual.get("source_pdf_sha256") == source_sha
                            and automatic_visual.get("candidate_pdf_sha256") == candidate_sha)
        if not identity_current:
            blockers.append("automatic_visual_identity_mismatch")
        decisions = visual.get("automatic_finding_dispositions", {})
        if not isinstance(decisions, dict):
            decisions = {}
        if identity_current and visual_ok and visual.get("automatic_visual_report_sha256") == automatic_visual_sha:
            automatic_visual_unresolved = [f for f in automatic_visual_findings if not (
                isinstance(decisions.get(f["finding_id"]), dict)
                and decisions[f["finding_id"]].get("status") in {"false_positive", "allowed_preservation"}
                and decisions[f["finding_id"]].get("evidence"))]
        if automatic_visual_unresolved:
            blockers.append("automatic_visual_findings_unresolved")
            visual_ok = False
    dual = outputs.get("standard_bilingual_pdf") or outputs.get("dual_pdf")
    dual_path = Path(dual) if dual else None
    if dual_path and not dual_path.is_absolute():
        dual_path = output_dir / dual_path
    bilingual = inspect_pdf(dual_path, max_pages)
    bilingual_ok = bilingual.get("status") == "ok" and bilingual.get("page_count") == max(count, source.get("page_count", 0))
    if bilingual_ok and source.get("status") == "ok" and pdf.get("status") == "ok":
        bilingual["side_verification"] = check_bilingual_sides(source_pdf, target_path, dual_path, max_pages)
        bilingual_ok = bilingual["side_verification"]["status"] == "ok"
    else:
        bilingual_ok = False
    delivery_mode = render.get("delivery_mode") or render.get("validation", {}).get("gates", {}).get("mode")
    mechanical = "blocked" if blockers else "passed"
    ready = mechanical == "passed" and semantic_ok and visual_ok and human_ok and bilingual_ok and delivery_mode != "fast_full_translation_draft"
    return {"schema_version": ASSESSMENT_VERSION, "output_dir": str(output_dir), "route": route,
            "status": "ready_for_promotion_review" if ready else "blocked" if blockers else "needs_review",
            "layers": {"mechanical": mechanical, "semantic": "passed" if semantic_ok else "needs_review",
                       "visual": "passed" if visual_ok else "needs_review", "human": "accepted" if human_ok else "pending",
                       "bilingual_artifact": "present" if bilingual_ok else "missing_or_inconsistent"},
            "blockers": blockers, "qa_status": qa_status, "findings": findings,
            "qa_evidence_sha256": qa_sha, "component_reviews": component_reviews,
            "unresolved_finding_count": len(unresolved) + len(automatic_visual_unresolved), "automatic_visual_status": automatic_visual.get("status", "missing"),
            "automatic_visual_report_sha256": automatic_visual_sha, "automatic_visual_findings": automatic_visual_findings,
            "automatic_visual_unresolved_count": len(automatic_visual_unresolved),
            "latex_compile_status": latex_compile, "delivery_mode": delivery_mode,
            "source": source, "candidate": pdf, "bilingual": bilingual, "evidence_sha256": evidence,
            "strict_delivery": False, "promotion_performed": False,
            "notes": ["中文可抽取只证明文本层存在；不证明可见翻译完整或语义正确。",
                      "ready_for_promotion_review 不替代既有 guarded cutover。"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--source-pdf", type=Path, required=True)
    parser.add_argument("--route", choices=ROUTES, required=True)
    parser.add_argument("--min-pages", type=int, default=5)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = assess(args.output_dir, args.source_pdf, args.route, min_pages=args.min_pages, max_pages=args.max_pages)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        print(text, end="")
    return 0 if result["status"] == "ready_for_promotion_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
