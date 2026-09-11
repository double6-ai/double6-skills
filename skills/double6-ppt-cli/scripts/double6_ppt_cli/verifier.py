from __future__ import annotations

import json
import posixpath
import re
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree
from PIL import Image, ImageChops, ImageFilter

from .common import (
    D6PPTError, SCHEMA_VERSION, load_run, read_json, resolve_run_path, save_run, set_status,
    sha256_file, utc_now, write_json,
)
from .doctor import find_soffice
from .officecli import OfficeCLI
from .package_diff import compare_parts
from .powerpoint import (
    _contact_sheet,
    detect_powerpoint_capability,
    is_portable_fallback_error,
    verify_with_powerpoint,
)
from .render_evidence import clear_render_manifest, load_current_render_manifest, record_render_manifest
from .visual_policy import resolve_visual_gate

VERIFY_TIERS = {"auto", "native", "portable"}
def _portable_claim(edit_probe: dict[str, Any] | None, render: dict[str, Any] | None) -> str:
    edit_status = (edit_probe or {}).get("status")
    render_status = (render or {}).get("status")
    edit_clause = {
        "pass": "OfficeCLI text-edit and object-move persistence probe passed",
        "not_automated": "OfficeCLI editability probe was not automated because no trusted object map was available",
    }.get(edit_status, "OfficeCLI editability probe did not pass")
    render_clause = (
        "LibreOffice page rendering completed"
        if render_status == "pass"
        else "portable page rendering was unavailable"
    )
    return (
        f"Portable tier: OOXML integrity and OfficeCLI validation passed; {edit_clause}; "
        f"{render_clause}. Microsoft PowerPoint native roundtrip was not performed."
    )


A_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main", "p": "http://schemas.openxmlformats.org/presentationml/2006/main"}


def _reusable_powerpoint_receipt(run: Path, pptx_sha: str) -> dict[str, Any] | None:
    receipt_path = run / "evidence" / "powerpoint_roundtrip" / "receipt.json"
    if not receipt_path.is_file():
        return None
    receipt = read_json(receipt_path)
    if receipt.get("status") != "pass" or receipt.get("source_pptx_sha256") != pptx_sha:
        return None
    roundtrip = resolve_run_path(run, str(receipt.get("roundtrip_pptx", "")))
    if not roundtrip.is_file():
        return None
    try:
        load_current_render_manifest(run, pptx_sha, expected_tier="native")
    except D6PPTError:
        return None
    reused = dict(receipt)
    reused["reused_for_same_pptx_sha"] = True
    return reused


def _snapshot(path: Path) -> dict[str, Any]:
    texts: list[str] = []
    notes: list[str] = []
    identities: list[str] = []
    placeholders: list[str] = []
    counts = Counter()
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise D6PPTError(f"Corrupt ZIP member: {bad}", "corrupt_pptx")
        names = set(archive.namelist())
        for required in ("[Content_Types].xml", "ppt/presentation.xml"):
            if required not in names:
                raise D6PPTError(f"Missing required OOXML part: {required}", "corrupt_pptx")
        if "ppt/_rels/presentation.xml.rels" not in names:
            raise D6PPTError("Missing presentation relationships", "corrupt_pptx")
        presentation = etree.fromstring(archive.read("ppt/presentation.xml"))
        relationships = etree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
        rel_targets = {
            rel.get("Id"): posixpath.normpath(posixpath.join("ppt", rel.get("Target", "")))
            for rel in relationships
            if rel.get("Id") and rel.get("Target")
        }
        logical_by_part: dict[str, int] = {}
        for logical_index, slide_id in enumerate(
            presentation.xpath(
                "//p:sldIdLst/p:sldId",
                namespaces={
                    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
                    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
                },
            ),
            start=1,
        ):
            rel_id = slide_id.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_targets.get(rel_id)
            if target and target.startswith("ppt/slides/"):
                logical_by_part[target] = logical_index
        if not logical_by_part:
            raise D6PPTError("PPTX has no logical slide order", "corrupt_pptx")
        for name in sorted(names):
            if not name.endswith(".xml"):
                continue
            try:
                root = etree.fromstring(archive.read(name))
            except etree.XMLSyntaxError as exc:
                raise D6PPTError(f"Invalid XML part: {name}", "corrupt_pptx") from exc
            if name in logical_by_part:
                slide_number = logical_by_part[name]
                for shape in root.xpath(".//p:sp", namespaces=A_NS):
                    value = "".join(shape.xpath(".//a:t/text()", namespaces=A_NS)).strip()
                    if value:
                        texts.append(value)
                for identity in root.xpath(".//p:cNvPr", namespaces=A_NS):
                    identities.append(
                        f"slide:{slide_number}:id:{identity.get('id')}:name:{identity.get('name') or ''}"
                    )
                for placeholder in root.xpath(".//p:sp/p:nvSpPr/p:nvPr/p:ph", namespaces=A_NS):
                    placeholders.append(f"ph:{slide_number}:{placeholder.get('type') or 'body'}")
                counts["shapes"] += len(root.xpath(".//p:sp", namespaces=A_NS))
                counts["groups"] += len(root.xpath(".//p:grpSp", namespaces=A_NS))
                counts["connectors"] += len(root.xpath(".//p:cxnSp", namespaces=A_NS))
                counts["tables"] += len(root.xpath(".//a:tbl", namespaces=A_NS))
                counts["charts"] += len(root.xpath(".//*[local-name()='chart']"))
            elif name.startswith("ppt/notesSlides/notesSlide"):
                for shape in root.xpath(".//p:sp", namespaces=A_NS):
                    value = "".join(shape.xpath(".//a:t/text()", namespaces=A_NS)).strip()
                    if value:
                        notes.append(value)
    return {
        "texts": texts, "notes": notes, "identities": sorted(identities), "placeholders": sorted(placeholders),
        "counts": dict(counts), "sha256": sha256_file(path),
    }


def _move_value(value: str) -> str | None:
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(pt|cm|mm|in|emu)\s*", value or "")
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    delta = {"pt": 1.0, "cm": 0.0352778, "mm": 0.352778, "in": 1 / 72, "emu": 12700}[unit]
    if unit == "emu":
        return f"{int(round(number + delta))}emu"
    return f"{number + delta:.6f}{unit}"


def _render_libreoffice(pptx: Path, output: Path, soffice: Path) -> list[Path]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    pdf_dir = output / "pdf"
    profile = output / "profile"
    pdf_dir.mkdir(exist_ok=True); profile.mkdir(exist_ok=True)
    command = [
        str(soffice), f"-env:UserInstallation={profile.as_uri()}", "--headless",
        "--convert-to", "pdf", "--outdir", str(pdf_dir), str(pptx),
    ]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=300)
    pdf = pdf_dir / f"{pptx.stem}.pdf"
    if proc.returncode != 0 or not pdf.is_file():
        raise D6PPTError("LibreOffice PDF render failed", "libreoffice_render_failed", {"command": command, "stdout": proc.stdout, "stderr": proc.stderr})
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise D6PPTError("pdftoppm is required for LibreOffice visual comparison", "pdf_renderer_missing")
    prefix = output / "slide"
    proc = subprocess.run([pdftoppm, "-png", "-r", "96", str(pdf), str(prefix)], capture_output=True, text=True, timeout=300)
    pages = sorted(output.glob("slide-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
    if proc.returncode != 0 or not pages:
        raise D6PPTError("PDF rasterization failed", "pdf_render_failed", {"stdout": proc.stdout, "stderr": proc.stderr})
    return pages


def _visual_compare(before_pages: list[Path], after_pages: list[Path]) -> dict[str, Any]:
    if len(before_pages) != len(after_pages):
        return {"status": "fail", "before_page_count": len(before_pages), "after_page_count": len(after_pages), "pages": []}
    metrics = []
    for page_number, (before_path, after_path) in enumerate(zip(before_pages, after_pages), 1):
        before = Image.open(before_path).convert("RGB")
        after = Image.open(after_path).convert("RGB")
        if before.size != after.size:
            metrics.append({"page": page_number, "status": "fail", "reason": "canvas_size_changed", "before_size": before.size, "after_size": after.size})
            continue
        diff = ImageChops.difference(before, after)
        histogram = diff.histogram()
        samples = before.width * before.height * 3
        rms = (sum((index % 256) ** 2 * count for index, count in enumerate(histogram)) / samples) ** 0.5
        changed_fraction = sum(count for index, count in enumerate(histogram) if index % 256 != 0) / samples
        before_small = before.convert("L").resize((320, 180)).filter(ImageFilter.GaussianBlur(1))
        after_small = after.convert("L").resize((320, 180)).filter(ImageFilter.GaussianBlur(1))
        small_hist = ImageChops.difference(before_small, after_small).histogram()
        perceptual_rms = (sum(index * index * count for index, count in enumerate(small_hist)) / (320 * 180)) ** 0.5
        def dhash(image: Image.Image) -> list[bool]:
            pixels = list(image.convert("L").resize((33, 32)).getdata())
            return [pixels[y * 33 + x] > pixels[y * 33 + x + 1] for y in range(32) for x in range(32)]
        left_hash, right_hash = dhash(before), dhash(after)
        dhash_distance = sum(a != b for a, b in zip(left_hash, right_hash)) / len(left_hash)
        page_status = "pass" if perceptual_rms <= 12.0 and dhash_distance <= 0.05 else "fail"
        metrics.append({
            "page": page_number, "status": page_status,
            "perceptual_rms": round(perceptual_rms, 6), "dhash_distance": round(dhash_distance, 8),
            "full_resolution_rms_informational": round(rms, 6),
            "full_resolution_changed_fraction_informational": round(changed_fraction, 8),
        })
    status = "pass" if metrics and all(item["status"] == "pass" for item in metrics) else "fail"
    return {
        "status": status, "before_page_count": len(before_pages), "after_page_count": len(after_pages),
        "thresholds": {"perceptual_rms_max": 12.0, "dhash_distance_max": 0.05}, "pages": metrics,
        "claim_boundary": "Blurred low-resolution RMS and dHash discount antialias-only rewrites. Passing permits inheritance of the accepted source visual review; larger structural deltas require manual review and block delivery.",
    }


def _edit_probe(client: OfficeCLI, pptx: Path, object_map: dict[str, Any] | None) -> dict[str, Any]:
    if not object_map:
        return {"status": "not_automated", "reason": "No trusted object map; require review/editability_receipt.json."}
    query = client.run(["query", str(pptx), "*"])
    query_data = query.get("data", {})
    results = query_data.get("results", []) if isinstance(query_data, dict) else []
    paths_by_name = {
        (row.get("format") or {}).get("name"): row.get("path")
        for row in results if (row.get("format") or {}).get("name") and row.get("path")
    }
    title_paths = {
        int(row["path"].split("/slide[")[1].split("]", 1)[0]): row["path"]
        for row in results if row.get("type") == "title" and row.get("path", "").startswith("/slide[")
    }
    candidates = []
    for item in object_map.get("objects", []):
        if not item.get("editable"):
            continue
        rebound = paths_by_name.get(item.get("drawingml_name"))
        if not rebound and item.get("placeholder") == "title":
            rebound = title_paths.get(int(item["slide"]))
        if rebound:
            candidates.append((item, rebound))
    for item, rebound_path in candidates:
        if "/group[" in rebound_path:
            continue
        got = client.run(["get", str(pptx), rebound_path])
        data = got.get("data", {})
        if isinstance(data, dict) and isinstance(data.get("results"), list) and len(data["results"]) == 1:
            data = data["results"][0]
        if not isinstance(data, dict):
            continue
        text = data.get("text")
        x = (data.get("format") or {}).get("x")
        moved = _move_value(str(x)) if x else None
        if text and moved:
            client.set_property(pptx, rebound_path, "text", f"{text} [D6 edit probe]")
            client.set_property(pptx, rebound_path, "x", moved)
            client.save(pptx)
            client.close(pptx)
            try:
                post_edit_validation = client.validate(pptx)
                post_edit_validation_status = "pass"
            except D6PPTError as exc:
                if exc.code != "officecli_failed":
                    raise
                post_edit_validation = {
                    "status": "warn",
                    "error_code": exc.code,
                    "message": str(exc),
                    "receipt": exc.details,
                }
                post_edit_validation_status = "warn"
            return {
                "status": "pass", "source_id": item["source_id"],
                "path_before_roundtrip": item["officecli_path"], "path_after_roundtrip": rebound_path,
                "text_edited": True, "object_moved": True,
                "post_edit_officecli_validation_status": post_edit_validation_status,
                "post_edit_officecli_validation": post_edit_validation,
            }
    return {"status": "fail", "reason": "No top-level editable text object with readable x coordinate."}


def _optional_libreoffice(
    run: Path,
    pptx: Path,
    before: dict[str, Any],
    client: OfficeCLI,
    object_map: dict[str, Any] | None,
) -> dict[str, Any]:
    soffice = find_soffice()
    if not soffice:
        raise D6PPTError("LibreOffice compatibility was requested but LibreOffice is unavailable", "libreoffice_missing")
    roundtrip_dir = run / "evidence" / "libreoffice_roundtrip"
    roundtrip_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="d6ppt-lo-") as temp:
        temp_path = Path(temp)
        incoming = temp_path / "input"
        outgoing = temp_path / "output"
        profile = temp_path / "profile"
        incoming.mkdir(); outgoing.mkdir(); profile.mkdir()
        staged = incoming / "roundtrip_source.pptx"
        shutil.copy2(pptx, staged)
        command = [
            str(soffice), f"-env:UserInstallation={profile.as_uri()}", "--headless",
            "--convert-to", "pptx", "--outdir", str(outgoing), str(staged),
        ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=300)
        converted = outgoing / "roundtrip_source.pptx"
        if proc.returncode != 0 or not converted.is_file():
            receipt = {"status": "fail", "command": command, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
            write_json(roundtrip_dir / "receipt.json", receipt)
            raise D6PPTError("LibreOffice roundtrip failed", "libreoffice_roundtrip_failed")
        roundtrip = roundtrip_dir / "roundtrip.pptx"
        shutil.copy2(converted, roundtrip)
    after = _snapshot(roundtrip)
    text_ok = Counter(before["texts"]) == Counter(after["texts"])
    notes_ok = Counter(before["notes"]) == Counter(after["notes"])
    if object_map:
        expected_named = {
            item["drawingml_name"] for item in object_map.get("objects", []) if not item.get("placeholder")
        }
        expected_placeholders = {
            f"ph:{item['slide']}:{item['placeholder']}" for item in object_map.get("objects", []) if item.get("placeholder")
        }
        identities_ok = expected_named.issubset(set(after["identities"])) and expected_placeholders.issubset(set(after["placeholders"]))
    else:
        identities_ok = True
    try:
        roundtrip_validate = client.validate(roundtrip)
        roundtrip_schema_status = "pass"
    except D6PPTError as exc:
        if exc.code != "officecli_failed":
            raise
        details = exc.details if isinstance(exc.details, dict) else {}
        stdout = details.get("stdout", "")
        try:
            validation_payload = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            validation_payload = {"raw_stdout": stdout}
        roundtrip_validate = {
            "success": False,
            "status": "warn",
            "error_code": exc.code,
            "message": str(exc),
            "validation_payload": validation_payload,
            "receipt": details,
            "claim_boundary": (
                "This warning applies to the LibreOffice-rewritten copy, not the delivered source artifact. "
                "Functional reopen, content, identity, edit, and visual gates must still pass."
            ),
        }
        roundtrip_schema_status = "warn"
    before_pages = _render_libreoffice(pptx, roundtrip_dir / "render_before", soffice)
    after_pages = _render_libreoffice(roundtrip, roundtrip_dir / "render_after", soffice)
    visual_roundtrip = _visual_compare(before_pages, after_pages)
    probe = roundtrip_dir / "edit_probe.pptx"
    shutil.copy2(roundtrip, probe)
    edit_probe = _edit_probe(client, probe, object_map)
    # LibreOffice Save As commonly renumbers DrawingML IDs and may drop custom
    # cNvPr names. Content + visual preservation is the honest compatibility bar;
    # identity drift alone should not hard-fail an otherwise healthy roundtrip.
    core_ok = text_ok and notes_ok and visual_roundtrip["status"] == "pass"
    edit_ok = edit_probe.get("status") in {"pass", "not_automated"}
    if core_ok and edit_ok and identities_ok:
        status = "pass"
    elif core_ok and edit_ok:
        status = "pass_with_warnings"
    else:
        status = "fail"
    receipt = {
        "schema_version": SCHEMA_VERSION, "created_at": utc_now(), "status": status,
        "source_pptx_sha256": before["sha256"], "roundtrip_pptx": str(roundtrip.relative_to(run)),
        "roundtrip_pptx_sha256": after["sha256"],
        "text_preserved": text_ok, "notes_preserved": notes_ok, "object_identities_preserved": identities_ok,
        "identity_claim_boundary": (
            "LibreOffice may renumber DrawingML IDs or drop custom names; identity drift is a warning "
            "when text/notes/visual/edit-probe still pass."
        ) if core_ok and edit_ok and not identities_ok else None,
        "before_counts": before["counts"], "after_counts": after["counts"], "edit_probe": edit_probe,
        "libreoffice_visual_comparison": visual_roundtrip,
        "libreoffice_roundtrip_officecli_validation": roundtrip_validate,
        "package_diff": compare_parts(pptx, roundtrip),
    }
    write_json(roundtrip_dir / "receipt.json", receipt)
    return receipt


def _resolve_verify_tier(
    requested: str,
    capability: dict[str, Any],
    reusable: dict[str, Any] | None,
) -> str:
    if requested not in VERIFY_TIERS:
        raise D6PPTError("verify tier must be auto, native, or portable", "invalid_verify_tier")
    if requested == "native":
        return "native"
    if requested == "portable":
        return "portable"
    if reusable is not None:
        return "native"
    return "native" if capability.get("available") else "portable"


def _portable_render(run: Path, pptx: Path) -> dict[str, Any]:
    pptx_sha = sha256_file(pptx)
    try:
        existing = load_current_render_manifest(run, pptx_sha, expected_tier="portable")
        page_rel = [str(item["path"]) for item in existing.get("pages", [])]
        return {
            "status": "pass",
            "application": existing.get("renderer") or "LibreOffice",
            "fact_source": existing.get("fact_source") or "libreoffice_portable",
            "page_count": len(page_rel),
            "pages": page_rel,
            "pdf": str(existing["pdf"]["path"]),
            "contact_sheet": str(existing["contact_sheet"]["path"]),
            "reused_existing_manifest": True,
            "claim_boundary": "Portable tier page rasterization uses LibreOffice, not Microsoft PowerPoint.",
        }
    except D6PPTError:
        pass
    soffice = find_soffice()
    pdftoppm = shutil.which("pdftoppm")
    if not soffice or not pdftoppm:
        clear_render_manifest(run)
        return {
            "status": "not_available",
            "soffice": str(soffice) if soffice else None,
            "pdftoppm": pdftoppm,
            "claim_boundary": "No LibreOffice/pdftoppm on this host; portable visual pages are unavailable.",
        }
    output = run / "evidence" / "portable_render"
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    pages = _render_libreoffice(pptx, output, soffice)
    contact = run / "review" / "contact_sheet-portable.png"
    _contact_sheet(pages, contact)
    pdf = next(output.glob("*.pdf"), None) or next((output / "pdf").glob("*.pdf"), None)
    if pdf is None:
        clear_render_manifest(run)
        raise D6PPTError("LibreOffice render did not produce a PDF", "render_bundle_incomplete")
    record_render_manifest(
        run,
        pptx,
        verification_tier="portable",
        renderer="LibreOffice",
        fact_source="libreoffice_portable",
        pdf=pdf,
        pages=pages,
        contact_sheet=contact,
    )
    return {
        "status": "pass",
        "application": "LibreOffice",
        "fact_source": "libreoffice_portable",
        "page_count": len(pages),
        "pages": [str(path.relative_to(run)) for path in pages],
        "pdf": str(pdf.relative_to(run)) if pdf else None,
        "contact_sheet": str(contact.relative_to(run)),
        "claim_boundary": "Portable tier page rasterization uses LibreOffice, not Microsoft PowerPoint.",
    }


def _portable_editability(client: OfficeCLI, pptx: Path, run: Path, object_map: dict[str, Any] | None) -> dict[str, Any]:
    probe = run / "evidence" / "portable_editability"
    probe.mkdir(parents=True, exist_ok=True)
    working = probe / "edit-probe.pptx"
    shutil.copy2(pptx, working)
    result = _edit_probe(client, working, object_map)
    write_json(probe / "receipt.json", result)
    return result


def verify_run(
    run: Path,
    runtime_dir: Path | None = None,
    *,
    compatibility: str = "none",
    tier: str = "auto",
) -> dict[str, Any]:
    run = run.resolve()
    manifest = load_run(run)
    pptx = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
    pptx_sha = sha256_file(pptx)
    findings_path = run / "evidence" / "findings.json"
    if not findings_path.is_file() or read_json(findings_path).get("pptx_sha256") != pptx_sha:
        raise D6PPTError("Current PPTX must be inspected after its last change", "inspection_stale")
    findings = read_json(findings_path)
    before = _snapshot(pptx)
    client = OfficeCLI(runtime_dir, run / "logs")
    office_validate = client.validate(pptx)
    map_rel = manifest["artifacts"].get("object_path_map")
    object_map = read_json(resolve_run_path(run, map_rel)) if map_rel else None
    capability = detect_powerpoint_capability()
    reusable = _reusable_powerpoint_receipt(run, pptx_sha)
    requested_tier = tier
    if requested_tier == "auto" and manifest.get("verification_preference") in {"native", "portable"}:
        requested_tier = manifest["verification_preference"]
    resolved_tier = _resolve_verify_tier(requested_tier, capability, reusable)
    powerpoint: dict[str, Any] | None = None
    portable_fallback_reason: dict[str, Any] | None = None
    if resolved_tier == "native":
        powerpoint = reusable
        if powerpoint is None:
            try:
                powerpoint = verify_with_powerpoint(pptx, run, client)
            except D6PPTError as exc:
                if requested_tier == "native" or not is_portable_fallback_error(exc):
                    set_status(run, manifest, "blocked", "verify_powerpoint", {"code": exc.code, "message": str(exc)})
                    raise
                resolved_tier = "portable"
                portable_fallback_reason = {"code": exc.code, "message": str(exc)}
    notes_ok = counts_ok = identities_ok = True
    powerpoint_roundtrip: Path | None = None
    if powerpoint is not None:
        powerpoint_roundtrip = resolve_run_path(run, powerpoint["roundtrip_pptx"])
        after = _snapshot(powerpoint_roundtrip)
        notes_ok = Counter(before["notes"]) == Counter(after["notes"])
        counts_ok = before["counts"] == after["counts"]
        identities_ok = set(before["identities"]).issubset(set(after["identities"]))
    portable_render = None
    edit_probe = None
    if resolved_tier == "portable":
        # Produce portable visual pages before the visual gate so review/waiver can bind them.
        portable_render = _portable_render(run, pptx)
        edit_probe = _portable_editability(client, pptx, run, object_map)
        manifest.setdefault("artifacts", {})
        if portable_render and portable_render.get("status") == "pass":
            manifest["artifacts"]["portable_render"] = "evidence/portable_render"
            if portable_render.get("contact_sheet"):
                manifest["artifacts"]["contact_sheet"] = portable_render["contact_sheet"]
        if edit_probe:
            manifest["artifacts"]["portable_editability_receipt"] = "evidence/portable_editability/receipt.json"
        manifest["artifacts"]["verification_tier"] = resolved_tier
        manifest["powerpoint_status"] = "skipped_portable_tier"
    else:
        manifest.setdefault("artifacts", {})["verification_tier"] = "native"
        manifest["powerpoint_status"] = "native_render_ready"
    render_manifest_path = run / "evidence" / "render_manifest.json"
    if render_manifest_path.is_file():
        manifest["artifacts"]["render_manifest"] = "evidence/render_manifest.json"
    else:
        manifest["artifacts"].pop("render_manifest", None)
    save_run(run, manifest)
    try:
        visual_gate, visual_receipt = resolve_visual_gate(run, pptx_sha)
    except D6PPTError as exc:
        if exc.code == "visual_review_decision_required" and portable_render:
            details = dict(exc.details or {})
            details["portable_render"] = {
                "status": portable_render.get("status"),
                "page_count": portable_render.get("page_count"),
                "contact_sheet": portable_render.get("contact_sheet"),
            }
            raise D6PPTError(str(exc), exc.code, details) from exc
        raise
    libreoffice = None
    if compatibility == "libreoffice":
        libreoffice = _optional_libreoffice(run, pptx, before, client, object_map)
    elif compatibility != "none":
        raise D6PPTError("compatibility must be none or libreoffice", "invalid_compatibility_target")
    warning_count = int(findings.get("warning_count", 0))
    blocking_count = int(findings.get("blocking_count", findings.get("finding_count", 0)))
    render_manifest = None
    try:
        render_manifest = load_current_render_manifest(run, pptx_sha, expected_tier=resolved_tier)
    except D6PPTError:
        render_manifest = None
    contact_sheet_ready = render_manifest is not None
    if resolved_tier == "native":
        render_gate = "pass" if contact_sheet_ready else "fail"
        powerpoint_gates = {
            "powerpoint_roundtrip": "pass" if powerpoint and powerpoint.get("status") == "pass" else "fail",
            "powerpoint_notes_preserved": "pass" if notes_ok else "fail",
            "powerpoint_object_counts_preserved": "pass" if counts_ok else "fail",
            "powerpoint_object_identities_preserved": "pass" if identities_ok else "fail",
            "powerpoint_second_text_edit_and_object_move": "pass" if (
                ("text_persisted=true" in (powerpoint or {}).get("operation_result", "")
                 or "title_persisted=true" in (powerpoint or {}).get("operation_result", ""))
                and "move_persisted=true" in (powerpoint or {}).get("operation_result", "")
            ) else "fail",
        }
    else:
        render_gate = "pass" if portable_render and portable_render.get("status") == "pass" else "not_available"
        edit_status = (edit_probe or {}).get("status")
        powerpoint_gates = {
            "powerpoint_roundtrip": "skipped_portable_tier",
            "portable_full_page_render": render_gate,
            "officecli_edit_probe": "pass" if edit_status == "pass" else ("warn" if edit_status == "not_automated" else "fail"),
        }
    gates = {
        "ooxml_package": "pass",
        "officecli_validate": "pass" if office_validate.get("success", office_validate.get("ok", True)) else "fail",
        "full_page_render": render_gate,
        "automated_blocking_findings_closed": "pass" if blocking_count == 0 else "fail",
        "automated_warning_findings": "warn" if warning_count else "pass",
        "visual_review": visual_gate,
        **powerpoint_gates,
        "unreplayed_patches": "pass" if not manifest.get("unreplayed_patches") else "fail",
        "libreoffice_compatibility": libreoffice["status"] if libreoffice else "not_requested",
        "verification_tier": "pass",
    }
    failed = [name for name, status in gates.items() if status == "fail"]
    warnings = [name for name, status in gates.items() if status in {"warn", "skipped_with_user_ack", "not_available"}]
    if resolved_tier == "portable":
        warnings.append("verification_tier=portable")
    status = "fail" if failed else ("pass_with_warnings" if warnings else "pass")
    powerpoint_status = "verified" if resolved_tier == "native" else "skipped_portable_tier"
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": status,
        "source_pptx_sha256": pptx_sha,
        "before_counts": before["counts"],
        "verification_tier": resolved_tier,
        "requested_verification_tier": requested_tier,
        "powerpoint_capability": capability,
        "powerpoint_fallback_reason": portable_fallback_reason,
        "powerpoint_status": powerpoint_status,
        "powerpoint_receipt": (
            "evidence/powerpoint_roundtrip/receipt.json" if resolved_tier == "native" else None
        ),
        "powerpoint_roundtrip": powerpoint,
        "powerpoint_package_diff": (
            compare_parts(pptx, powerpoint_roundtrip) if powerpoint_roundtrip else None
        ),
        "portable_render": portable_render,
        "officecli_edit_probe": edit_probe,
        "visual_receipt": visual_receipt,
        "libreoffice_compatibility": libreoffice,
        "gates": gates,
        "render_manifest": "evidence/render_manifest.json" if render_manifest else None,
        "render_manifest_sha256": sha256_file(run / "evidence" / "render_manifest.json") if render_manifest else None,
        "tier_result": (
            f"tier=native · PowerPoint roundtrip=pass · visual={visual_gate}"
            if resolved_tier == "native" else
            f"tier=portable · PowerPoint roundtrip=not run · edit_probe={(edit_probe or {}).get('status', 'missing')} · render={(portable_render or {}).get('status', 'missing')} · visual={visual_gate}"
        ),
        "compatibility_claim": (
            (
                "Validated as a native editable PPTX in Microsoft PowerPoint with Save As/reopen, "
                "persistent text edit and object movement."
                if resolved_tier == "native"
                else _portable_claim(edit_probe, portable_render)
            )
            + (" Visual quality was not assessed by a vision-capable model." if visual_gate == "skipped_with_user_ack" else "")
        ),
    }
    write_json(run / "evidence" / "verification_receipt.json", receipt)
    manifest["artifacts"].update({
        "verification_receipt": "evidence/verification_receipt.json",
        "verification_tier": resolved_tier,
    })
    if resolved_tier == "native":
        manifest["artifacts"].update({
            "powerpoint_receipt": "evidence/powerpoint_roundtrip/receipt.json",
            "powerpoint_render": "evidence/powerpoint_render",
            "render_manifest": "evidence/render_manifest.json",
        })
        manifest["powerpoint_status"] = "verified"
    else:
        manifest["artifacts"].pop("powerpoint_receipt", None)
        manifest["artifacts"].pop("powerpoint_render", None)
        if portable_render and portable_render.get("status") == "pass":
            manifest["artifacts"]["portable_render"] = "evidence/portable_render"
            manifest["artifacts"]["render_manifest"] = "evidence/render_manifest.json"
        if edit_probe:
            manifest["artifacts"]["portable_editability_receipt"] = "evidence/portable_editability/receipt.json"
        manifest["powerpoint_status"] = "skipped_portable_tier"
    set_status(run, manifest, "blocked" if failed else ("verified_with_warnings" if warnings else "verified"), "verify", gates)
    return receipt
