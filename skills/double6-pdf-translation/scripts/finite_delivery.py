"""按具体三页用户接受复制有限交付；保留原机器质量状态，不授 strict。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

import fitz
from cutover.scoped import check_scoped_preflight

PROTOCOL = "finite_pdf_delivery_v1"
ACCEPTANCE_SCOPE = "specific_PDF_full_three_page_finite_acceptance"
MAX_JSON_BYTES = 4 * 1024 * 1024


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("finite_json_missing_or_over_budget")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("finite_json_object_required")
    return value


def _ref(path):
    return {"path": str(Path(path).absolute()), "sha256": _sha(path)}


def _bound(reference):
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
        raise ValueError("finite_reference_invalid")
    if _sha(reference["path"]) != reference.get("sha256"):
        raise ValueError("finite_reference_identity_changed:" + reference["path"])
    return reference


def _same_identity(reference, expected, aliases=()):
    _bound(reference)
    choices = [expected, *aliases]
    if not any(reference == item for item in choices):
        raise ValueError("finite_unregistered_same_byte_alias")


def _pages(reference, expected_pages):
    _bound(reference)
    with fitz.open(reference["path"]) as document:
        if expected_pages != list(range(1, len(document) + 1)) or len(document) != 3:
            raise ValueError("finite_complete_three_page_scope_mismatch")


def _quality(item):
    """只接受用户回执绑定的两种既有独立报告形状。"""
    quality_ref = _bound(item["scope_evidence_ref"])
    quality = _json(quality_ref["path"])
    source = item["source_pdf_ref"]
    original = item.get("same_byte_original_candidate_ref")
    aliases = [original] if original else []
    for alias in aliases:
        _bound(alias)
        if alias["sha256"] != item["sha256"]:
            raise ValueError("finite_original_alias_sha_mismatch")
    target = {"path": item["path"], "sha256": item["sha256"]}
    expected_technical = item["accepted_technical_boundaries"]
    # A source report may refer to the same source at its original, frozen path.
    qa_source = quality["source"]
    _bound(qa_source)
    if qa_source["sha256"] != source["sha256"]:
        raise ValueError("finite_quality_source_changed")
    for key in ("issues", "pending", "pending_current_declared_quality", "blocking_findings",
                "body_errors", "style_errors", "action_errors", "visibility_errors"):
        if quality.get(key):
            raise ValueError("finite_unaccepted_quality_finding:" + key)
    if "finite_quality" in quality:
        _same_identity(quality["actual_pdf"], target, aliases)
        if quality["finite_quality"].get("pass") is not True:
            raise ValueError("finite_quality_not_pass")
        for key in ("complete20_groups_and7_edits", "visual_science_elements_and_page_starts", "links"):
            if not isinstance(quality["finite_quality"].get(key), str) or not quality["finite_quality"][key]:
                raise ValueError("finite_complete_review_description_missing:" + key)
        if quality.get("strict_and_unknown") != expected_technical:
            raise ValueError("finite_technical_boundaries_not_accepted")
        if not quality.get("reviewer_thread_id"):
            raise ValueError("finite_independent_reviewer_missing")
        for key in ("controlled_run", "current_final_identity", "current_HTTP"):
            if quality.get(key, {}).get("pass") is not True:
                raise ValueError("finite_actual_evidence_not_pass:" + key)
        pages = quality.get("page_checks", [])
        if [p.get("page") for p in pages] != [1, 2, 3]:
            raise ValueError("finite_quality_page_scope_mismatch")
        for page in pages:
            if (page.get("capture_status") != "succeeded"
                    or page.get("current_pdf_ref_matches") is not True
                    or page.get("current_complete_text_equal_prior") is not True):
                raise ValueError("finite_actual_page_unverified")
        actions = quality.get("actions", [])
        if not actions or any(a.get("actual_host_pass") is not True for a in actions):
            raise ValueError("finite_action_host_not_pass")
        standards = quality.get("standards", [])
    else:
        _same_identity(quality["target"], target, aliases)
        if (quality.get("quality_pass") is not True
                or quality.get("scope", {}).get("complete_source_and_target_pages") != [1, 2, 3]
                or not quality.get("components")
                or any(v != "pass" for v in quality["components"].values())):
            raise ValueError("finite_whole_quality_not_pass")
        if quality.get("technical_unknowns_and_scope_limits") != expected_technical:
            raise ValueError("finite_technical_boundaries_not_accepted")
        if (not quality.get("reviewer_id")
                or quality["reviewer_id"] == quality.get("producer_id")):
            raise ValueError("finite_independent_reviewer_missing")
        standards = quality.get("standard_refs", [])
    if not standards:
        raise ValueError("finite_standards_missing")
    for standard in standards:
        _bound(standard)
    return {"ref": quality_ref, "standard_refs": standards,
            "source_identity_map": {"accepted_source_ref": source,
                                    "review_source_ref": qa_source,
                                    "same_byte_sha256": source["sha256"]},
            "target_identity_map": {"accepted_target_ref": target,
                                    "explicit_accepted_original_aliases": aliases},
            "accepted_technical_boundaries": expected_technical}


def preflight_finite(packet_path, acceptance_path):
    result = {"status": "blocked", "blockers": [], "finite": True, "strict_delivery": False,
              "promotion_performed": False, "published": False}
    try:
        packet = _json(packet_path)
        acceptance = _json(acceptance_path)
        if packet.get("protocol") != PROTOCOL:
            raise ValueError("finite_protocol_missing")
        if (acceptance.get("status") != "accepted"
                or acceptance.get("scope_type") != ACCEPTANCE_SCOPE
                or acceptance.get("direct_user_authorization") is not True
                or acceptance.get("human_acceptance") is not True
                or acceptance.get("human_user_acceptance") is not True
                or acceptance.get("acceptance_role") != "human_user"
                or acceptance.get("strict_delivery") is not False
                or not acceptance.get("authorization_source")):
            raise ValueError("finite_specific_user_acceptance_missing")
        accepted = acceptance.get("artifacts", [])
        accepted_by_id = {a["id"]: a for a in accepted}
        if len(accepted_by_id) != len(accepted):
            raise ValueError("finite_duplicate_accepted_ids")
        artifacts = packet.get("artifacts", [])
        ids = [a["id"] for a in artifacts]
        if not 1 <= len(ids) <= 2 or len(set(ids)) != len(ids) or not set(ids) <= set(accepted_by_id):
            raise ValueError("finite_acceptance_scope_mismatch")
        # A subset references the original user receipt; it does not create new acceptance.
        projection = {**acceptance, "artifacts": [accepted_by_id[i] for i in ids]}
        scoped = check_scoped_preflight(packet, projection)
        if scoped["blockers"]:
            result["blockers"] += scoped["blockers"]
            return result
        originals = packet.get("original_comprehensive_quality_refs", {})
        if set(originals) != set(ids):
            raise ValueError("finite_original_comprehensive_scope_mismatch")
        reviews, machine = {}, {}
        for artifact in artifacts:
            if not artifact["id"] or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in artifact["id"]):
                raise ValueError("finite_unsafe_artifact_id")
            item = accepted_by_id[artifact["id"]]
            if ({"path": artifact["path"], "sha256": artifact["sha256"]}
                    != {"path": item["path"], "sha256": item["sha256"]}):
                raise ValueError("finite_accepted_path_or_sha_changed")
            if (item.get("whole_source_and_target_scope") is not True
                    or item.get("human_accepted") is not True
                    or item.get("finite_quality_pass") is not True
                    or item.get("strict_delivery") is not False):
                raise ValueError("finite_artifact_acceptance_incomplete")
            _pages(item["source_pdf_ref"], item["accepted_source_pages"])
            _pages(artifact, item["accepted_target_pages"])
            reviews[artifact["id"]] = _quality(item)
            comp_ref = _bound(originals[artifact["id"]])
            comp = _json(comp_ref["path"])
            _same_identity(comp["target"], {"path": item["path"], "sha256": item["sha256"]},
                           [item["same_byte_original_candidate_ref"]])
            if comp.get("source", {}).get("sha256") != item["source_pdf_ref"]["sha256"]:
                raise ValueError("finite_original_comprehensive_source_changed")
            _bound(comp["source"])
            if comp.get("issues") or comp.get("status") not in {"pass", "unverified"}:
                raise ValueError("finite_original_comprehensive_unaccepted_failure")
            # The existing Digital report has this packaging gap. Its independent
            # accepted full review closes finite delivery, while the U stays U.
            if comp.get("pending", []) not in ([], [{"rule": "complete_independent_quality_packet_required"}]):
                raise ValueError("finite_original_comprehensive_unaccepted_unknown")
            machine[artifact["id"]] = {"ref": comp_ref, "original_report": comp}
        result.update(status="ready_for_delivery", finite_quality_pass=True,
                      human_acceptance=True, artifacts=artifacts, finite_reviews=reviews,
                      original_machine_quality=machine, packet_ref=_ref(packet_path),
                      acceptance_ref=_ref(acceptance_path), scope="only listed accepted three-page PDF identities")
    except (KeyError, ValueError, TypeError, OSError, fitz.FileDataError) as exc:
        result["blockers"].append(str(exc))
    return result


def deliver_finite(packet_path, acceptance_path, output):
    result = preflight_finite(packet_path, acceptance_path)
    if result["blockers"]:
        return result
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    copies = []
    for item in result["artifacts"]:
        identity = item["id"]
        if not identity or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in identity):
            raise ValueError("finite_unsafe_artifact_id")
        if _sha(item["path"]) != item["sha256"]:
            raise ValueError("finite_artifact_changed_before_copy")
        target = output / (identity + ".pdf")
        shutil.copyfile(item["path"], target)
        if _sha(target) != item["sha256"] or _sha(item["path"]) != item["sha256"]:
            raise ValueError("finite_copy_identity_changed")
        copies.append({"id": identity, "accepted_original_ref": item, **_ref(target)})
    # Recheck all authoritative inputs after copying; failed work is never receipted as delivered.
    final = preflight_finite(packet_path, acceptance_path)
    if (final["blockers"] or final["packet_ref"] != result["packet_ref"]
            or final["acceptance_ref"] != result["acceptance_ref"]):
        raise ValueError("finite_evidence_changed_during_delivery")
    result.update(status="delivered", artifacts=copies,
                  delivered_at=datetime.now(timezone.utc).isoformat())
    with (output / "DELIVERY_RECEIPT.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result
