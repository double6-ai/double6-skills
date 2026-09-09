from __future__ import annotations

import os
import pwd
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw

from .common import D6PPTError, SCHEMA_VERSION, sha256_file, utc_now, write_json
if TYPE_CHECKING:
    from .officecli import OfficeCLI


POWERPOINT_APP = Path("/Applications/Microsoft PowerPoint.app")
POWERPOINT_CONTAINER_RELATIVE = Path("Library/Containers/com.microsoft.Powerpoint/Data/tmp/d6ppt")


PDF_SCRIPT = r'''
on run argv
    set inputPath to item 1 of argv
    set outputPath to item 2 of argv
    set appWasRunning to application "Microsoft PowerPoint" is running
    set openedPresentation to missing value
    try
        with timeout of 600 seconds
            tell application "Microsoft PowerPoint"
                if (count of presentations) is not 0 then error "powerpoint_busy"
                activate
                open POSIX file inputPath
                repeat 240 times
                    if (count of presentations) > 0 then exit repeat
                    delay 0.25
                end repeat
                if (count of presentations) is 0 then error "presentation_did_not_open"
                set openedPresentation to active presentation
                save openedPresentation in POSIX file outputPath as save as PDF
                close openedPresentation saving no
                set openedPresentation to missing value
                if not appWasRunning then quit
            end tell
        end timeout
    on error errorMessage number errorNumber
        try
            tell application "Microsoft PowerPoint"
                if openedPresentation is not missing value then close openedPresentation saving no
                if not appWasRunning and (count of presentations) is 0 then quit
            end tell
        end try
        error errorMessage number errorNumber
    end try
end run
'''


def _system_user_home() -> Path:
    """Resolve the login account home without trusting an isolated HOME."""
    return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()


def resolve_powerpoint_staging_root(*, create: bool = True) -> Path:
    container_root = (_system_user_home() / POWERPOINT_CONTAINER_RELATIVE).resolve()
    configured = os.environ.get("POWERPOINT_STAGING_ROOT")
    root = Path(configured).expanduser().resolve() if configured else container_root
    try:
        root.relative_to(container_root)
    except ValueError as exc:
        raise D6PPTError(
            "POWERPOINT_STAGING_ROOT must stay inside the real PowerPoint container",
            "powerpoint_staging_root_invalid",
        ) from exc
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def validate_powerpoint_path(path: Path, staging_root: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = staging_root.expanduser().resolve()
    lowered = "/" + "/".join(part.lower() for part in resolved.parts) + "/"
    if "/process/tmp/opencode/diag/" in lowered:
        raise D6PPTError(
            "Diagnostic cleanroom files must never be opened by PowerPoint",
            "powerpoint_diag_path_forbidden",
        )
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise D6PPTError(
            "PowerPoint may only open files staged in the real PowerPoint container",
            "powerpoint_path_outside_staging",
        ) from exc
    return resolved


def find_powerpoint() -> Path | None:
    return POWERPOINT_APP if POWERPOINT_APP.exists() else None


def detect_powerpoint_capability() -> dict[str, Any]:
    """Report whether the native PowerPoint gate can be attempted on this host."""
    app = find_powerpoint()
    osascript = shutil.which("osascript")
    reasons: list[str] = []
    if app is None:
        reasons.append("Microsoft PowerPoint.app is not installed")
    if not osascript:
        reasons.append("osascript is unavailable")
    return {
        "available": not reasons,
        "app": str(app) if app else None,
        "osascript": osascript,
        "reason": "; ".join(reasons) if reasons else None,
    }


def is_portable_fallback_error(exc: D6PPTError) -> bool:
    """True when a native PowerPoint attempt should degrade to the portable tier."""
    if exc.code in {
        "powerpoint_missing",
        "powerpoint_automation_missing",
        "powerpoint_accessibility_denied",
    }:
        return True
    message = str(exc)
    details = exc.details if isinstance(exc.details, dict) else {}
    blob = " ".join(str(value) for value in (message, details.get("message", ""), details.get("stderr", ""), details.get("stdout", "")))
    return "-1719" in blob or "不允许辅助访问" in blob or "not allowed assistive" in blob.lower()


def _run_osascript(script: str, args: list[str], timeout: int = 240) -> subprocess.CompletedProcess[str]:
    if not shutil.which("osascript"):
        raise D6PPTError("osascript is unavailable", "powerpoint_automation_missing")
    proc = subprocess.run(
        ["osascript", "-", *args],
        input=script,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    blob = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    if proc.returncode != 0 and ("-1719" in blob or "不允许辅助访问" in blob):
        raise D6PPTError(
            (proc.stderr or proc.stdout or "PowerPoint automation was denied assistive access").strip(),
            "powerpoint_accessibility_denied",
            {"stdout": proc.stdout, "stderr": proc.stderr, "returncode": proc.returncode},
        )
    return proc


def _candidate(rows: list[dict[str, Any]]) -> tuple[int, str, str, str] | None:
    for row in rows:
        path = str(row.get("path") or "")
        match = re.match(r"/slide\[(\d+)\]/", path)
        fmt = row.get("format") or {}
        name = fmt.get("name") if isinstance(fmt, dict) else None
        text = str(row.get("text") or "").strip()
        if match and name and text and row.get("type") in {"title", "shape", "textbox", "placeholder"}:
            return int(match.group(1)), str(name), text, str(name)
    return None


def _contact_sheet(pages: list[Path], output: Path) -> None:
    opened = [Image.open(path).convert("RGB") for path in pages]
    try:
        thumb_w = 400
        thumbs = []
        for image in opened:
            ratio = thumb_w / image.width
            thumbs.append(image.resize((thumb_w, max(1, int(image.height * ratio)))))
        cols = 3
        rows = (len(thumbs) + cols - 1) // cols
        cell_h = max(image.height for image in thumbs) + 36
        sheet = Image.new("RGB", (cols * thumb_w, rows * cell_h), "white")
        draw = ImageDraw.Draw(sheet)
        for index, image in enumerate(thumbs):
            x = (index % cols) * thumb_w
            y = (index // cols) * cell_h
            sheet.paste(image, (x, y))
            draw.text((x + 8, y + image.height + 8), f"Slide {index + 1}", fill="black")
        output.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(output)
    finally:
        for image in opened:
            image.close()


def _rasterize_powerpoint_pdf(pdf: Path, output_dir: Path, contact_sheet: Path) -> dict[str, Any]:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        raise D6PPTError("pdftoppm is required for PowerPoint page rendering", "pdf_renderer_missing")
    prefix = output_dir / "slide"
    proc = subprocess.run(
        [pdftoppm, "-png", "-r", "120", str(pdf), str(prefix)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    pages = sorted(output_dir.glob("slide-*.png"), key=lambda path: int(path.stem.split("-")[-1]))
    if proc.returncode != 0 or not pages:
        raise D6PPTError(proc.stderr or "PowerPoint PDF rasterization failed", "pdf_render_failed")
    _contact_sheet(pages, contact_sheet)
    return {"pdf": str(pdf), "pages": [str(path) for path in pages], "contact_sheet": str(contact_sheet)}


def render_with_powerpoint(pptx: Path, output_dir: Path, contact_sheet: Path) -> dict[str, Any]:
    if not find_powerpoint():
        raise D6PPTError("Microsoft PowerPoint is required", "powerpoint_missing")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    staging_root = resolve_powerpoint_staging_root()
    token = uuid.uuid4().hex[:8]
    staging_dir = staging_root / f"render-{token}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    staged = validate_powerpoint_path(staging_dir / "input.pptx", staging_root)
    sandbox_pdf = validate_powerpoint_path(staging_dir / "render.pdf", staging_root)
    pdf = output_dir / "powerpoint-render.pdf"
    shutil.copy2(pptx, staged)
    try:
        proc = _run_osascript(PDF_SCRIPT, [str(staged), str(sandbox_pdf)], timeout=660)
        if proc.returncode != 0 or not sandbox_pdf.is_file():
            message = proc.stderr or proc.stdout or "PowerPoint PDF export failed"
            code = "powerpoint_busy" if "powerpoint_busy" in message else "powerpoint_render_failed"
            raise D6PPTError(message.strip(), code)
        shutil.copy2(sandbox_pdf, pdf)
    finally:
        staged.unlink(missing_ok=True)
        sandbox_pdf.unlink(missing_ok=True)
        shutil.rmtree(staging_dir, ignore_errors=True)
    return _rasterize_powerpoint_pdf(pdf, output_dir, contact_sheet)


def verify_with_powerpoint(pptx: Path, run: Path, client: OfficeCLI) -> dict[str, Any]:
    if not find_powerpoint():
        raise D6PPTError("Microsoft PowerPoint is required", "powerpoint_missing")
    query = client.run(["query", str(pptx), "*"])
    data = query.get("data", {})
    rows = data.get("results", []) if isinstance(data, dict) else []
    candidate = _candidate(rows)
    roundtrip_dir = run / "evidence" / "powerpoint_roundtrip"
    roundtrip_dir.mkdir(parents=True, exist_ok=True)
    output = roundtrip_dir / "roundtrip-edit-probe.pptx"
    if output.exists():
        output.unlink()
    render_dir = run / "evidence" / "powerpoint_render"
    if render_dir.exists():
        shutil.rmtree(render_dir)
    render_dir.mkdir(parents=True, exist_ok=True)
    pdf = render_dir / "powerpoint-render.pdf"
    if candidate:
        slide, text_name, original_text, move_name = candidate
        replacement = f"{original_text} [D6 edit probe]"
        perform = "true"
    else:
        slide, text_name, replacement, move_name, perform = 1, "", "", "", "false"
    probe_script = Path(__file__).with_name("powerpoint_roundtrip_probe.applescript")
    if not probe_script.is_file():
        raise D6PPTError("Bundled PowerPoint roundtrip probe is missing", "powerpoint_automation_missing")
    staging_root = resolve_powerpoint_staging_root()
    staging_dir = staging_root / f"verify-{uuid.uuid4().hex[:8]}"
    staging_dir.mkdir(parents=True, exist_ok=False)
    staged_input = validate_powerpoint_path(staging_dir / "input.pptx", staging_root)
    staged_roundtrip = validate_powerpoint_path(staging_dir / "roundtrip-edit-probe.pptx", staging_root)
    staged_pdf = validate_powerpoint_path(staging_dir / "powerpoint-render.pdf", staging_root)
    shutil.copy2(pptx, staged_input)
    try:
        proc = _run_osascript(
            probe_script.read_text(encoding="utf-8"),
            [
                str(staged_input), str(staged_roundtrip), str(slide), text_name,
                replacement, move_name, "1", perform, str(staged_pdf),
            ],
            timeout=900,
        )
        result = (proc.stdout or proc.stderr).strip()
        if "powerpoint_busy" in result or "unsafe_preexisting_presentations" in result:
            raise D6PPTError("PowerPoint has another presentation open", "powerpoint_busy")
        if proc.returncode != 0 or not result.startswith("status=passed"):
            raise D6PPTError(result or "PowerPoint batch verification failed", "powerpoint_roundtrip_failed")
        if not staged_roundtrip.is_file() or not staged_pdf.is_file():
            raise D6PPTError("PowerPoint batch did not create all required outputs", "powerpoint_batch_output_missing")
        shutil.copy2(staged_roundtrip, output)
        shutil.copy2(staged_pdf, pdf)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
    render = _rasterize_powerpoint_pdf(pdf, render_dir, run / "review" / "contact_sheet.png")
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": "pass",
        "application": "Microsoft PowerPoint",
        "source_pptx_sha256": sha256_file(pptx),
        "roundtrip_pptx": str(output.relative_to(run)),
        "roundtrip_pptx_sha256": sha256_file(output),
        "edit_probe_performed": candidate is not None,
        "batch_session_count": 1,
        "powerpoint_input_policy": "real_container_staging_only",
        "staging_root": str(staging_root),
        "operation_result": result,
        "probe_script_sha256": sha256_file(probe_script),
        "render": render,
    }
    write_json(roundtrip_dir / "receipt.json", receipt)
    return receipt
