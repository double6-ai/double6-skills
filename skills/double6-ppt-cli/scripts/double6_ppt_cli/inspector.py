from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from .common import D6PPTError, SCHEMA_VERSION, load_run, resolve_run_path, set_status, sha256_file, utc_now, write_json
from .officecli import OfficeCLI
from .template_workflow import build_pptx_profile


PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
RML = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
PKG_NS = {"p": PML, "r": RML, "pr": PKG_REL, "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _data(payload: dict[str, Any]) -> Any:
    return payload.get("data", payload)


def _normalize_issues(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _data(payload)
    raw = data.get("issues", []) if isinstance(data, dict) else []
    result = []
    for index, issue in enumerate(raw, 1):
        message = str(issue.get("message", ""))
        category = "layout" if re.search(r"overflow|overlap|contrast|outside|clip", message, re.I) else "structure"
        result.append({
            "finding_id": f"officecli-{issue.get('id') or index}",
            "source_tool": "officecli",
            "severity": "error" if issue.get("severity") in (2, "error", "high") else "warning",
            "category": category,
            "object": {"officecli_path": issue.get("path")},
            "source_id": None,
            "message": message,
            "evidence": issue,
            "suggested_route": "source_repair",
        })
    return result


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = _data(payload)
    return data.get("results", []) if isinstance(data, dict) and isinstance(data.get("results"), list) else []


def _path_identity(path: str | None) -> tuple[str | None, int | None]:
    match = re.fullmatch(r"/slide\[\d+\](?:/group\[@id=\d+\])*/(shape|textbox|equation|connector|picture|group|chart|table)\[@id=(\d+)\]", str(path or ""))
    return (match.group(1), int(match.group(2))) if match else (None, None)


def _capture_html_preview(_client: OfficeCLI, _pptx: Path, _screenshot: Path) -> dict[str, Any]:
    # Chrome-based OfficeCLI preview is intentionally disabled. On macOS its
    # isolated profile can trigger Keychain dialogs, while PowerPoint is already
    # the required rendering fact source later in the workflow.
    return {
        "status": "deferred_to_powerpoint",
        "fact_source": "powerpoint_required",
        "reason": "chrome_preview_disabled_to_avoid_keychain_prompts",
    }


def _finding(
    code: str,
    row: dict[str, Any],
    message: str,
    *,
    severity: str = "warning",
    category: str = "template_residue",
    operation: str | None = None,
    property_name: str | None = None,
    replacement: str | None = None,
    deterministic: bool = False,
) -> dict[str, Any]:
    path = row.get("path")
    object_type, drawingml_id = _path_identity(path)
    text = str(row.get("text") or "")
    result = {
        "finding_id": f"d6-{code}-{hashlib.sha256((str(path) + text).encode()).hexdigest()[:10]}",
        "source_tool": "double6-ppt-cli",
        "severity": severity,
        "category": category,
        "object": {
            "officecli_path": path,
            "object_type": object_type or row.get("type"),
            "drawingml_id": drawingml_id,
        },
        "source_id": None,
        "message": message,
        "evidence": {"text": text, "format": row.get("format"), "name": (row.get("format") or {}).get("name")},
        "suggested_route": "bounded_patch" if deterministic else "manual_review",
        "deterministic": deterministic,
    }
    if operation:
        result["suggested_operation"] = operation
    if property_name:
        result["suggested_property"] = property_name
    if replacement is not None:
        result["suggested_value"] = replacement
    return result


def _font_size(row: dict[str, Any]) -> float | None:
    fmt = row.get("format") or {}
    for key in ("size", "fontSize", "fontsize"):
        value = fmt.get(key) if isinstance(fmt, dict) else None
        if value is None:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", str(value))
        if match:
            return float(match.group())
    effective = fmt.get("effective") if isinstance(fmt, dict) else None
    if isinstance(effective, dict) and effective.get("size") is not None:
        match = re.search(r"-?\d+(?:\.\d+)?", str(effective["size"]))
        return float(match.group()) if match else None
    return None


def _generic_findings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    rows_by_slide: dict[int, list[dict[str, Any]]] = {}
    navigation_values = {"导航一": "背景", "导航二": "个体", "导航三": "团队", "导航四": "机制", "导航五": "行动"}
    navigation_labels = set(navigation_values.values()) | {"觉醒", "涌现"}
    for row in rows:
        path = str(row.get("path") or "")
        text = str(row.get("text") or "")
        if not path.startswith("/slide["):
            continue
        slide_match = re.match(r"/slide\[(\d+)\]", path)
        if slide_match:
            rows_by_slide.setdefault(int(slide_match.group(1)), []).append(row)
        if re.search(r"Designed\s+by\s+sjq", text, re.I):
            finding = _finding("template-attribution", row, "Visible template author trace remains; resolve template license before removal or preserve attribution in delivery notes")
            finding["license_review_required"] = True
            findings.append(finding)
        if re.search(r"导航[一二三四五]", text):
            findings.append(_finding(
                "template-navigation", row, "Template navigation label was not mapped to deck sections",
                severity="error", property_name="text", replacement=navigation_values.get(text.strip()), deterministic=True,
            ))
        if re.search(r"【.*】|（示例）|\(示例\)|图表占位区|内容页标题", text):
            findings.append(_finding("template-placeholder", row, "Template placeholder or sample label remains", severity="error", operation="remove_leaf", deterministic=True))
        if re.search(r"U_IR|P_f|g_thres|Kriging|AK-IR|N_MCS|N_IS|逆可靠度|97\.7%|Φ\(2\)", text, re.I):
            findings.append(_finding("template-formula", row, "Template formula or source-domain sample content remains", severity="error", operation="remove_leaf", deterministic=True))
        elif re.search(r"组织竞争力公式|^\s*(分子|分母|乘除关系)：", text, re.I):
            finding = _finding(
                "formula-like-business-content", row,
                "Formula-like business content is present; without an exact template identity match it is semantic content and must not be auto-deleted",
                severity="warning", category="content",
            )
            finding["requires_user_confirmation"] = True
            findings.append(finding)
        if "87×" in text:
            findings.append(_finding("numeric-87x", row, "88% minus 1% is 87 percentage points, not 87 times", severity="error", category="data", property_name="text", replacement=text.replace("87×", "87 个百分点"), deterministic=True))
        if re.search(r"\b87\s*pp\b", text, re.I):
            findings.append(_finding(
                "numeric-87pp", row, "Use the locked Chinese percentage-point expression",
                severity="error", category="data", property_name="text",
                replacement=re.sub(r"\b87\s*pp\b", "87 个百分点", text, flags=re.I), deterministic=True,
            ))
        if "87 个百分点" in text and (size := _font_size(row)) is not None and size > 32:
            findings.append(_finding(
                "numeric-display-capacity", row,
                f"Locked percentage-point display is {size:g}pt in a compact metric slot and wraps in PowerPoint",
                severity="error", category="layout", property_name="size", replacement="32pt", deterministic=True,
            ))
        size = _font_size(row)
        if size is not None and 0 < size < 12 and text.strip():
            findings.append(_finding("small-font", row, f"Visible text is only {size:g}pt", category="layout"))
        name = str((row.get("format") or {}).get("name") or "")
        if row.get("type") == "picture" and re.search(r"公式|equation|formula", name, re.I):
            finding = _finding(
                "template-formula-picture", row,
                "Formula-like picture is present; if inherited from the template it requires explicit confirmation before deletion",
                severity="error", category="template_residue",
            )
            finding["requires_user_confirmation"] = True
            finding["suggested_operation"] = "remove_leaf"
            findings.append(finding)
    for slide, slide_rows in sorted(rows_by_slide.items()):
        digit_labels = [
            row for row in slide_rows
            if re.fullmatch(r"[1-9]", str(row.get("text") or "").strip())
        ]
        group_count = sum(row.get("type") == "group" for row in slide_rows)
        if len(digit_labels) >= 5 and group_count >= 4:
            findings.append({
                "finding_id": f"d6-directory-skeleton-{slide}",
                "source_tool": "double6-ppt-cli", "severity": "error", "category": "template_residue",
                "object": {"slide": slide}, "source_id": None,
                "message": f"Slide {slide} still has a directory-like numbered skeleton ({len(digit_labels)} numbered blocks)",
                "evidence": {"numbered_leaf_count": len(digit_labels), "group_count": group_count},
                "suggested_route": "manual_review", "deterministic": False,
            })
    selected_by_slide: dict[int, str] = {}
    for slide, slide_rows in sorted(rows_by_slide.items()):
        nav_rows = [row for row in slide_rows if str(row.get("text") or "").strip() in navigation_labels]
        if len(nav_rows) < 4:
            continue
        selected = []
        for row in nav_rows:
            color = str((row.get("format") or {}).get("color") or "").strip().lower()
            if color in {"background1", "background 1", "#ffffff", "ffffff", "white"}:
                selected.append(str(row.get("text") or "").strip())
        if len(selected) == 1:
            selected_by_slide[slide] = selected[0]
    if len(selected_by_slide) >= 4:
        counts: dict[str, list[int]] = {}
        for slide, label in selected_by_slide.items():
            counts.setdefault(label, []).append(slide)
        dominant_label, dominant_slides = max(counts.items(), key=lambda item: len(item[1]))
        if len(dominant_slides) >= 4 and len(dominant_slides) / len(selected_by_slide) >= 0.75:
            findings.append({
                "finding_id": f"d6-navigation-selection-static-{hashlib.sha256((dominant_label + str(dominant_slides)).encode()).hexdigest()[:10]}",
                "source_tool": "double6-ppt-cli", "severity": "warning", "category": "navigation",
                "object": {"slides": dominant_slides}, "source_id": None,
                "message": f"Navigation selected state remains on {dominant_label} across {len(dominant_slides)} slides; confirm the intended section mapping before changing styles",
                "evidence": {"selected_label": dominant_label, "slides": dominant_slides, "navigated_slide_count": len(selected_by_slide)},
                "suggested_route": "manual_review", "deterministic": False,
                "requires_user_confirmation": True,
            })
    return findings


def _package_hygiene_findings(pptx: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(pptx) as archive:
        names = set(archive.namelist())
        required = {"ppt/presentation.xml", "ppt/_rels/presentation.xml.rels"}
        if not required.issubset(names):
            return []
        presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
        relationships = etree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
        targets = {
            str(rel.get("Id")): posixpath.normpath(posixpath.join("ppt", str(rel.get("Target") or "")))
            for rel in relationships.xpath("./pr:Relationship", namespaces=PKG_NS)
            if rel.get("Id") and rel.get("Target") and rel.get("TargetMode") != "External"
        }
        logical = {
            targets.get(str(rel_id), "")
            for rel_id in presentation.xpath("./p:sldIdLst/p:sldId/@r:id", namespaces=PKG_NS)
        }
        nonlogical = sorted(
            name for name in names
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name) and name not in logical
        )
        if not nonlogical:
            return []
        sample_parts: list[dict[str, Any]] = []
        for part in nonlogical:
            root = etree.fromstring(archive.read(part))
            text = " ".join(root.xpath(".//a:t/text()", namespaces=PKG_NS))
            markers = sorted(set(re.findall(
                r"【[^】]+】|导航[一二三四五]|（示例）|\(示例\)|图表占位区|U_IR|P_f|g_thres|Kriging|AK-IR|逆可靠度",
                text,
                re.I,
            )))
            if markers:
                sample_parts.append({"part": part, "markers": markers[:12]})
    is_sample = bool(sample_parts)
    return [{
        "finding_id": "d6-package-orphan-template-sample-slides" if is_sample else "d6-package-nonlogical-slides",
        "source_tool": "double6-ppt-cli",
        "severity": "error" if is_sample else "warning",
        "category": "package_hygiene",
        "object": {"package": True},
        "source_id": None,
        "message": (
            f"Package contains {len(nonlogical)} nonlogical slide parts with template sample content"
            if is_sample else
            f"Package contains {len(nonlogical)} nonlogical slide parts; confirm whether they belong to a custom show"
        ),
        "evidence": {"nonlogical_slide_parts": nonlogical, "sample_parts": sample_parts},
        "suggested_route": "package_clean" if is_sample else "manual_review",
        "deterministic": is_sample,
        "suggested_command": "d6ppt package-clean --run <run>" if is_sample else None,
    }]


def _template_findings(run: Path, manifest: dict[str, Any], pptx: Path, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    profile_rel = manifest.get("artifacts", {}).get("template_profile")
    if not profile_rel:
        return findings
    profile_path = resolve_run_path(run, profile_rel)
    if not profile_path.is_file():
        return findings
    from .common import read_json

    template_profile = read_json(profile_path)
    output_profile = build_pptx_profile(pptx)
    write_json(run / "artifacts" / "current_pptx_profile.json", output_profile)
    profile_rel = manifest.get("artifacts", {}).get("template_profile")
    if profile_rel:
        from .common import read_json
        template_profile = read_json(resolve_run_path(run, profile_rel))
        for key in ("masters", "layouts", "themes"):
            expected = template_profile.get("counts", {}).get(key)
            actual = output_profile.get("counts", {}).get(key)
            if expected != actual:
                findings.append({
                    "finding_id": f"d6-template-{key}-drift",
                    "source_tool": "double6-ppt-cli", "severity": "error", "category": "structure",
                    "object": {"deck": True}, "source_id": None,
                    "message": f"Template {key} count drifted from {expected} to {actual}",
                    "evidence": {"expected": expected, "actual": actual},
                    "suggested_route": "manual_review", "deterministic": False,
                })
    template_media_counts: dict[str, int] = {}
    template_media_names: dict[str, set[str]] = {}
    template_media_roles: dict[str, set[str]] = {}
    for obj in template_profile.get("objects", []):
        digest = obj.get("media_sha256")
        if not digest:
            continue
        template_media_counts[digest] = template_media_counts.get(digest, 0) + 1
        template_media_names.setdefault(digest, set()).add(str(obj.get("drawingml_name") or ""))
        template_media_roles.setdefault(digest, set()).add(str(obj.get("role") or "unknown"))
    template_media = set(template_media_counts)
    for obj in output_profile.get("objects", []):
        if obj.get("object_type") == "picture" and obj.get("media_sha256") in template_media:
            digest = obj["media_sha256"]
            names = template_media_names.get(digest, set())
            if template_media_counts.get(digest, 0) >= 3 or any(re.search(r"logo|校徽|学校|背景", name, re.I) for name in names):
                continue
            fake_row = {
                "path": obj["officecli_path"], "type": "picture", "text": "",
                "format": {**obj["geometry"], "name": obj.get("drawingml_name")},
            }
            finding = _finding(
                "template-formula-media" if "sample_formula_media" in template_media_roles.get(digest, set()) else "template-media-reuse",
                fake_row,
                (
                    "Formula media is byte-identical to a template sample; explicit confirmation is required before deletion"
                    if "sample_formula_media" in template_media_roles.get(digest, set()) else
                    "Picture is byte-identical to template media; confirm that it is meaningful rather than sample imagery"
                ),
                severity="error" if "sample_formula_media" in template_media_roles.get(digest, set()) else "warning",
                category="template_residue" if "sample_formula_media" in template_media_roles.get(digest, set()) else "visual",
                operation="remove_leaf" if "sample_formula_media" in template_media_roles.get(digest, set()) else None,
            )
            finding["requires_user_confirmation"] = True
            finding["evidence"]["media_sha256"] = obj["media_sha256"]
            findings.append(finding)
    def slide_signatures(profile: dict[str, Any]) -> dict[int, set[tuple[Any, ...]]]:
        result: dict[int, set[tuple[Any, ...]]] = {}
        for obj in profile.get("objects", []):
            if obj.get("object_type") in {"group", "connector"}:
                continue
            geo = obj.get("geometry") or {}
            signature = (
                obj.get("object_type"), obj.get("drawingml_name"),
                geo.get("x_emu"), geo.get("y_emu"), geo.get("width_emu"), geo.get("height_emu"),
            )
            result.setdefault(int(obj["source_template_slide"]), set()).add(signature)
        return result
    template_signatures = slide_signatures(template_profile)
    output_signatures = slide_signatures(output_profile)
    inferred: dict[int, int] = {}
    for output_slide, output_set in output_signatures.items():
        best_slide, best_score = None, 0.0
        for source_slide, source_set in template_signatures.items():
            if not source_set:
                continue
            score = len(output_set & source_set) / len(source_set)
            if score > best_score:
                best_slide, best_score = source_slide, score
        if best_slide is not None and best_score >= 0.6:
            inferred[output_slide] = best_slide
    inferred_counts: dict[int, int] = {}
    for source_slide in inferred.values():
        inferred_counts[source_slide] = inferred_counts.get(source_slide, 0) + 1
    for source_slide, count in sorted(inferred_counts.items()):
        if count > 2:
            findings.append({
                "finding_id": f"d6-inferred-template-slide-overuse-{source_slide}",
                "source_tool": "double6-ppt-cli", "severity": "warning", "category": "layout",
                "object": {"source_template_slide": source_slide}, "source_id": None,
                "message": f"Template source slide {source_slide} appears to be reused {count} times",
                "evidence": {"reuse_count": count, "inferred_output_slides": [slide for slide, source in inferred.items() if source == source_slide]},
                "suggested_route": "manual_review", "deterministic": False,
            })
    if output_signatures:
        boundary_slides = {min(output_signatures), max(output_signatures)}
        template_objects = {
            (int(obj["source_template_slide"]), int(obj["drawingml_id"])): obj
            for obj in template_profile.get("objects", [])
        }
        for output_obj in output_profile.get("objects", []):
            output_slide = int(output_obj["source_template_slide"])
            source_slide = inferred.get(output_slide)
            if output_slide not in boundary_slides or source_slide is None or not output_obj.get("text"):
                continue
            source_obj = template_objects.get((source_slide, int(output_obj["drawingml_id"])))
            if not source_obj or not source_obj.get("text"):
                continue
            source_length = len(str(source_obj["normalized_text"]))
            output_length = len(str(output_obj["normalized_text"]))
            if output_length > max(10, int(source_length * 1.5)) and output_length >= source_length + 5:
                findings.append({
                    "finding_id": f"d6-template-boundary-capacity-{output_slide}-{output_obj['drawingml_id']}",
                    "source_tool": "double6-ppt-cli", "severity": "warning", "category": "layout",
                    "object": {"officecli_path": output_obj["officecli_path"], "drawingml_id": output_obj["drawingml_id"]},
                    "source_id": output_obj.get("source_object_id"),
                    "message": f"Boundary slide text is {output_length} characters versus template slot sample {source_length}; confirm title/ending capacity visually",
                    "evidence": {"output_length": output_length, "template_sample_length": source_length, "source_template_slide": source_slide},
                    "suggested_route": "manual_review", "deterministic": False,
                })
    plan_rel = manifest.get("artifacts", {}).get("template_plan")
    if plan_rel:
        plan_path = Path(plan_rel)
        if not plan_path.is_absolute():
            plan_path = resolve_run_path(run, plan_rel)
        if plan_path.is_file():
            plan = read_json(plan_path)
            counts: dict[int, int] = {}
            for slide in plan.get("slides", []):
                source_slide = int(slide.get("source_slide", 0))
                counts[source_slide] = counts.get(source_slide, 0) + 1
            for source_slide, count in sorted(counts.items()):
                if count > 2:
                    findings.append({
                        "finding_id": f"d6-template-slide-overuse-{source_slide}",
                        "source_tool": "double6-ppt-cli",
                        "severity": "warning",
                        "category": "layout",
                        "object": {"source_template_slide": source_slide},
                        "source_id": None,
                        "message": f"Template source slide {source_slide} is reused {count} times",
                        "evidence": {"reuse_count": count},
                        "suggested_route": "manual_review",
                        "deterministic": False,
                    })
    return findings


def inspect_run(run: Path, runtime_dir: Path | None = None) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    current_rel = manifest.get("artifacts", {}).get("current_pptx")
    if not current_rel:
        raise D6PPTError("Run has no current PPTX", "pptx_missing")
    pptx = resolve_run_path(run, current_rel)
    if not pptx.is_file():
        raise D6PPTError("Current PPTX is missing", "pptx_missing")
    client = OfficeCLI(runtime_dir, run / "logs")
    results = {}
    for mode in ("outline", "stats", "issues"):
        results[mode] = client.view(pptx, mode)
        clean = {k: v for k, v in results[mode].items() if k != "_receipt"}
        write_json(run / "evidence" / f"officecli_{mode}.json", clean)
    results["validate"] = client.validate(pptx)
    write_json(run / "evidence" / "officecli_validate.json", {k: v for k, v in results["validate"].items() if k != "_receipt"})
    screenshot = run / "review" / "contact_sheet.png"
    preview_receipt = _capture_html_preview(client, pptx, screenshot)
    write_json(run / "evidence" / "officecli_preview.json", preview_receipt)
    query = client.run(["query", str(pptx), "*"])
    clean_query = {k: v for k, v in query.items() if k != "_receipt"}
    write_json(run / "evidence" / "officecli_query_all.json", clean_query)
    rows = _rows(query)
    findings = _normalize_issues(results["issues"])
    findings.extend(_generic_findings(rows))
    findings.extend(_template_findings(run, manifest, pptx, rows))
    findings.extend(_package_hygiene_findings(pptx))
    output_profile = build_pptx_profile(pptx)
    contract_record = manifest.get("content_contract")
    if isinstance(contract_record, dict) and contract_record.get("copied_path"):
        from .common import read_json
        contract_path = resolve_run_path(run, contract_record["copied_path"])
        if sha256_file(contract_path) != contract_record.get("sha256"):
            raise D6PPTError("Content contract is stale", "stale_content_contract")
        contract = read_json(contract_path)
        expected_slides = contract.get("expected_slide_count")
        actual_slides = output_profile.get("counts", {}).get("slides")
        if isinstance(expected_slides, int) and actual_slides != expected_slides:
            findings.append({
                "finding_id": "d6-content-contract-slide-count",
                "source_tool": "double6-ppt-cli", "severity": "error", "category": "structure",
                "object": {"deck": True}, "source_id": None,
                "message": f"Content contract requires {expected_slides} slides but PPTX contains {actual_slides}",
                "evidence": {"expected_slide_count": expected_slides, "actual_slide_count": actual_slides},
                "suggested_route": "manual_review", "deterministic": False,
            })
        deck_text = "\n".join(str(row.get("text") or "") for row in rows)
        for claim in contract.get("numeric_claims", []):
            claim_id = str(claim.get("claim_id") or "numeric")
            for operand in claim.get("operands", []):
                if str(operand) not in deck_text:
                    findings.append({
                        "finding_id": f"d6-{claim_id}-operand-{hashlib.sha256(str(operand).encode()).hexdigest()[:8]}",
                        "source_tool": "double6-ppt-cli", "severity": "error", "category": "data",
                        "object": {"deck": True}, "source_id": None,
                        "message": f"Required numeric operand is missing: {operand}",
                        "evidence": {"claim_id": claim_id, "operand": operand},
                        "suggested_route": "manual_review", "deterministic": False,
                    })
            expected = str(claim.get("expected") or "")
            if expected and expected not in deck_text:
                findings.append({
                    "finding_id": f"d6-{claim_id}-expected-display",
                    "source_tool": "double6-ppt-cli", "severity": "error", "category": "data",
                    "object": {"deck": True}, "source_id": None,
                    "message": f"Required numeric relation display is missing: {expected}",
                    "evidence": {"claim_id": claim_id, "expected": expected},
                    "suggested_route": "manual_review", "deterministic": False,
                })
    canvas = output_profile.get("canvas", {})
    canvas_area = (canvas.get("width_emu") or 0) * (canvas.get("height_emu") or 0)
    if canvas_area:
        by_slide: dict[int, list[dict[str, Any]]] = {}
        for obj in output_profile.get("objects", []):
            by_slide.setdefault(int(obj["source_template_slide"]), []).append(obj)
        for slide, objects in sorted(by_slide.items()):
            occupied = 0
            text_length = 0
            for obj in objects:
                text_length += len(str(obj.get("text") or ""))
                if obj.get("object_type") in {"group", "connector"}:
                    continue
                geo = obj.get("geometry") or {}
                width, height = geo.get("width_emu"), geo.get("height_emu")
                if width and height and width * height < canvas_area * 0.85:
                    occupied += min(width * height, canvas_area)
            ratio = min(1.0, occupied / canvas_area)
            if text_length >= 20 and ratio < 0.10:
                findings.append({
                    "finding_id": f"d6-extreme-blank-balance-{slide}",
                    "source_tool": "double6-ppt-cli", "severity": "warning", "category": "layout",
                    "object": {"slide": slide}, "source_id": None,
                    "message": f"Slide {slide} has extreme blank balance (estimated occupied area {ratio:.1%})",
                    "evidence": {"estimated_occupied_ratio": round(ratio, 4), "text_length": text_length},
                    "suggested_route": "manual_review", "deterministic": False,
                })
    deduplicated = []
    seen = set()
    for finding in findings:
        key = finding["finding_id"]
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(finding)
    findings = deduplicated
    map_path = run / "artifacts" / "object_path_map.json"
    if map_path.is_file():
        from .common import read_json
        path_to_source = {item["officecli_path"]: item["source_id"] for item in read_json(map_path).get("objects", [])}
        for finding in findings:
            finding["source_id"] = path_to_source.get(finding["object"].get("officecli_path"))
    elif manifest["mode"] in {"postflight", "template-fill"}:
        inspection_objects = []
        for index, row in enumerate(rows, 1):
            if not row.get("path"):
                continue
            inspection_objects.append({
                "inspection_id": f"inspection-{sha256_file(pptx)[:8]}-{index:04d}",
                "officecli_path": row["path"], "type": row.get("type"),
                "text": row.get("text"), "format": row.get("format"),
                "trusted_source_map": False,
            })
        write_json(run / "artifacts" / "inspection_map.json", {
            "schema_version": SCHEMA_VERSION, "created_at": utc_now(),
            "pptx_sha256": sha256_file(pptx), "trusted_source_map": False,
            "objects": inspection_objects,
        })
        manifest["artifacts"]["inspection_map"] = "artifacts/inspection_map.json"
    payload = {
        "schema_version": SCHEMA_VERSION, "created_at": utc_now(), "pptx_sha256": sha256_file(pptx),
        "finding_count": len(findings),
        "blocking_count": sum(item.get("severity") == "error" for item in findings),
        "warning_count": sum(item.get("severity") != "error" for item in findings),
        "preview_status": preview_receipt["status"],
        "findings": findings,
        "claim_boundary": "issues=0, validate=pass, or a non-empty preview cannot close the visual gate.",
    }
    write_json(run / "evidence" / "findings.json", payload)
    manifest["artifacts"].update({
        "findings": "evidence/findings.json", "contact_sheet": "review/contact_sheet.png",
        "current_pptx_profile": "artifacts/current_pptx_profile.json",
        "inspected_pptx_sha256": sha256_file(pptx),
    })
    status = "repair_needed" if payload["blocking_count"] else "inspected"
    set_status(run, manifest, status, "inspect", {"finding_count": len(findings)})
    return payload
