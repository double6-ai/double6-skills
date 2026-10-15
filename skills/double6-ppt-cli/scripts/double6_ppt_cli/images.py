"""Royalty-free image sourcing, credit metadata and deterministic image treatments.

Images are authored into ``authoring/project/images/`` and referenced from SVG as
``<image href="../images/<name>.jpg" .../>``. Every image there must have an entry in
``images/credits.json`` (source, creator, license, landing page, sha256, treatments);
``compile`` refuses uncredited images and ``finalize`` ships the credits with the deck.

Sources:
- ``openverse``: Openverse API (WordPress Foundation) restricted to licenses that allow
  commercial use and modification (CC0, PDM, CC BY, CC BY-SA). Attribution is recorded
  and must be shown when the license requires it (CC BY*).
- ``url`` / ``file``: caller-supplied image plus explicit license metadata (e.g. an Unsplash
  or Pexels photo under their own free licenses).
- ``placeholder``: generated abstract artwork (gradient / duotone noise) recorded as
  ``placeholder: true`` so delivery lists it for replacement.
"""
from __future__ import annotations

import hashlib
import io
import json
import random
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .common import D6PPTError, load_run, utc_now

OPENVERSE_API = "https://api.openverse.org/v1/images/"
ALLOWED_LICENSES = {"cc0", "pdm", "by", "by-sa"}
USER_AGENT = "double6-ppt-cli (+https://github.com/double6-ai/double6-skills)"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
ATTRIBUTION_REQUIRED = {"by", "by-sa"}


def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only, checked below
        return resp.read()


def search_openverse(query: str, count: int = 12, min_width: int = 1200, orientation: str | None = "wide") -> list[dict[str, Any]]:
    params = {"q": query, "license_type": "commercial,modification", "page_size": str(max(1, min(count * 2, 20))),
              "mature": "false"}
    if orientation:
        params["aspect_ratio"] = orientation
    data = json.loads(_get(OPENVERSE_API + "?" + urllib.parse.urlencode(params)))
    out = []
    for item in data.get("results", []):
        lic = str(item.get("license", "")).lower()
        if lic not in ALLOWED_LICENSES or (item.get("width") or 0) < min_width:
            continue
        out.append({
            "openverse_id": item.get("id"), "title": item.get("title"), "creator": item.get("creator"),
            "license": lic, "license_version": item.get("license_version"), "license_url": item.get("license_url"),
            "landing_url": item.get("foreign_landing_url"), "url": item.get("url"), "width": item.get("width"),
            "height": item.get("height"), "provider": item.get("source") or item.get("provider"),
            "attribution": item.get("attribution"),
        })
        if len(out) >= count:
            break
    return out


def openverse_detail(image_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f-]{36}", image_id or ""):
        raise D6PPTError("Invalid Openverse id", "invalid_image_source")
    item = json.loads(_get(f"{OPENVERSE_API}{image_id}/"))
    lic = str(item.get("license", "")).lower()
    if lic not in ALLOWED_LICENSES:
        raise D6PPTError(f"Openverse image license '{lic}' does not allow commercial use with modification", "image_license_refused")
    return item


# ----------------------------------------------------------------------------- treatments

def _hex(c: str) -> tuple[int, int, int]:
    c = c.strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", c):
        raise D6PPTError(f"Invalid colour: {c}", "invalid_image_treatment")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def parse_treatments(spec: str | None) -> list[tuple[str, str]]:
    """``cover=1280x720;focus=0.5,0.35;duotone=#16181C,#B08D57;tint=#000000@0.35;blur=4;round=24;circle;grayscale``"""
    out = []
    for part in [p.strip() for p in (spec or "").split(";") if p.strip()]:
        key, _, value = part.partition("=")
        key = key.strip().lower()
        if key not in {"cover", "focus", "duotone", "tint", "blur", "round", "circle", "grayscale", "brightness", "contrast", "fade"}:
            raise D6PPTError(f"Unknown image treatment: {key}", "invalid_image_treatment")
        out.append((key, value.strip()))
    return out


def apply_treatments(img: Image.Image, treatments: list[tuple[str, str]]) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    focus = (0.5, 0.5)
    for key, value in treatments:
        if key == "focus":
            fx, fy = (float(v) for v in value.split(","))
            focus = (min(max(fx, 0), 1), min(max(fy, 0), 1))
    alpha = None
    for key, value in treatments:
        if key == "cover":
            w, h = (int(v) for v in value.lower().split("x"))
            img = ImageOps.fit(img, (w, h), Image.LANCZOS, centering=focus)
        elif key == "grayscale":
            img = ImageOps.grayscale(img).convert("RGB")
        elif key == "duotone":
            dark, light = (_hex(v) for v in value.split(","))
            img = ImageOps.colorize(ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1), dark, light)
        elif key == "tint":
            colour, _, amount = value.partition("@")
            layer = Image.new("RGB", img.size, _hex(colour))
            img = Image.blend(img, layer, float(amount or 0.3))
        elif key == "brightness":
            from PIL import ImageEnhance
            img = ImageEnhance.Brightness(img).enhance(float(value))
        elif key == "contrast":
            from PIL import ImageEnhance
            img = ImageEnhance.Contrast(img).enhance(float(value))
        elif key == "blur":
            img = img.filter(ImageFilter.GaussianBlur(float(value)))
        elif key == "fade":  # side=amount, e.g. left@0.9 : gradient to transparent towards a side
            side, _, amount = value.partition("@")
            grad = Image.linear_gradient("L").resize(img.size)
            grad = {"top": grad, "bottom": grad.rotate(180), "left": grad.rotate(90, expand=False).resize(img.size),
                    "right": grad.rotate(-90, expand=False).resize(img.size)}.get(side, grad)
            a = ImageChops.multiply(grad, Image.new("L", img.size, int(255 * float(amount or 1))))
            a = ImageOps.invert(a)
            alpha = a if alpha is None else ImageChops.multiply(alpha, a)
        elif key in {"round", "circle"}:
            mask = Image.new("L", img.size, 0)
            d = ImageDraw.Draw(mask)
            if key == "circle":
                d.ellipse((0, 0, img.size[0] - 1, img.size[1] - 1), fill=255)
            else:
                d.rounded_rectangle((0, 0, img.size[0] - 1, img.size[1] - 1), radius=int(value or 24), fill=255)
            alpha = mask if alpha is None else ImageChops.multiply(alpha, mask)
    if alpha is not None:
        img = img.convert("RGBA")
        img.putalpha(alpha)
    return img


def placeholder_image(size: tuple[int, int], colours: list[str], style: str = "gradient", seed: int = 7) -> Image.Image:
    w, h = size
    a, b = _hex(colours[0]), _hex(colours[1] if len(colours) > 1 else colours[0])
    grad = Image.linear_gradient("L").rotate(-35, expand=True).resize((w, h))
    img = ImageOps.colorize(grad, a, b)
    rnd = random.Random(seed)
    d = ImageDraw.Draw(img, "RGBA")
    if style in {"gradient", "orbs"}:
        for _ in range(6):
            r = rnd.randint(min(w, h) // 6, min(w, h) // 2)
            x, y = rnd.randint(-r, w), rnd.randint(-r, h)
            d.ellipse((x, y, x + 2 * r, y + 2 * r), fill=(255, 255, 255, rnd.randint(10, 28)))
        img = img.filter(ImageFilter.GaussianBlur(min(w, h) / 40))
    if style in {"grain", "gradient", "orbs"}:
        noise = Image.effect_noise((w, h), 18).convert("L")
        img = Image.blend(img, ImageOps.colorize(noise, a, b), 0.08)
    return img


# ----------------------------------------------------------------------------- run integration

def _project(run: Path) -> Path:
    load_run(run)
    return run / "authoring" / "project"


def credits_path(project: Path) -> Path:
    return project / "images" / "credits.json"


def read_credits(project: Path) -> dict[str, Any]:
    path = credits_path(project)
    if not path.is_file():
        return {"schema": "d6ppt.image_credits.v1", "images": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def add_image(run: Path, name: str, *, openverse_id: str | None = None, url: str | None = None, file: Path | None = None,
              placeholder: str | None = None, colours: list[str] | None = None, size: str = "1600x900",
              license: str | None = None, creator: str | None = None, source_url: str | None = None,
              license_url: str | None = None, treatments: str | None = None) -> dict[str, Any]:
    run = run.resolve()
    project = _project(run)
    if not NAME_RE.fullmatch(name or ""):
        raise D6PPTError("Image name must be lowercase [a-z0-9_-]", "invalid_image_name")
    chosen = [x for x in (openverse_id, url, file, placeholder) if x]
    if len(chosen) != 1:
        raise D6PPTError("Choose exactly one of --openverse-id, --url, --file, --placeholder", "invalid_image_source")
    record: dict[str, Any] = {"name": name, "added_at": utc_now(), "placeholder": False}
    if openverse_id:
        item = openverse_detail(openverse_id)
        raw = _get(item["url"])
        record.update(source="openverse", openverse_id=openverse_id, title=item.get("title"), creator=item.get("creator"),
                      license=str(item.get("license")).lower(), license_version=item.get("license_version"),
                      license_url=item.get("license_url"), landing_url=item.get("foreign_landing_url"),
                      provider=item.get("source"), attribution=item.get("attribution"))
    elif url or file:
        if not license or not source_url:
            raise D6PPTError("--url/--file require --license and --source-url (and --creator when known)", "image_credit_missing")
        if url and not url.startswith("https://"):
            raise D6PPTError("Only https image URLs are accepted", "invalid_image_source")
        raw = _get(url) if url else Path(file).read_bytes()
        record.update(source="url" if url else "file", creator=creator, license=license, license_url=license_url,
                      landing_url=source_url)
    else:
        w, h = (int(v) for v in size.lower().split("x"))
        buf = io.BytesIO()
        placeholder_image((w, h), colours or ["#1F3A5F", "#3C7A78"], placeholder).save(buf, "PNG")
        raw = buf.getvalue()
        record.update(source="generated", placeholder=True, license="generated", creator="double6-ppt-cli",
                      note="Generated placeholder artwork — replace with a real photo before external use")
    record["original_sha256"] = hashlib.sha256(raw).hexdigest()
    treat = parse_treatments(treatments)
    img = apply_treatments(Image.open(io.BytesIO(raw)), treat)
    images = project / "images"
    images.mkdir(parents=True, exist_ok=True)
    for old in images.glob(f"{name}.*"):
        if old.name != "credits.json":
            old.unlink()
    if img.mode == "RGBA":
        target = images / f"{name}.png"
        img.save(target, "PNG", optimize=True)
    else:
        if max(img.size) > 2400:
            img.thumbnail((2400, 2400))
        target = images / f"{name}.jpg"
        img.save(target, "JPEG", quality=86, optimize=True, progressive=True)
    record.update(file=f"images/{target.name}", width=img.size[0], height=img.size[1], treatments=treatments or "",
                  sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                  attribution_required=record.get("license") in ATTRIBUTION_REQUIRED)
    credits = read_credits(project)
    credits["images"][target.name] = record
    credits_path(project).write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


IMAGE_HREF = re.compile(r'<image\b[^>]*?\b(?:xlink:)?href="([^"]+)"')


def check_image_credits(project: Path) -> dict[str, Any]:
    """Every project image referenced by an SVG must exist and carry a credit record."""
    credits = read_credits(project).get("images", {})
    missing, absent, placeholders, used = [], [], [], []
    for svg in sorted((project / "svg_output").glob("*.svg")):
        for href in IMAGE_HREF.findall(svg.read_text(encoding="utf-8")):
            if href.startswith("data:"):
                continue
            name = Path(href).name
            used.append(name)
            if not (project / "images" / name).is_file():
                absent.append(f"{svg.name}:{href}")
            elif name not in credits:
                missing.append(f"{svg.name}:{href}")
            elif credits[name].get("placeholder"):
                placeholders.append(name)
    if absent or missing:
        raise D6PPTError(
            "Images referenced by the deck must exist under authoring/project/images and be credited in images/credits.json",
            "image_credit_missing", {"missing_file": absent, "missing_credit": missing,
                                     "next_step": "Use `d6ppt image-add` to import images with license metadata."})
    return {"used": sorted(set(used)), "placeholders": sorted(set(placeholders))}


def credits_markdown(project: Path, used: list[str] | None = None) -> str:
    credits = read_credits(project).get("images", {})
    lines = ["# Image credits", ""]
    for name, rec in sorted(credits.items()):
        if used is not None and name not in used:
            continue
        if rec.get("placeholder"):
            lines.append(f"- `{name}` — generated placeholder (replace before external use)")
            continue
        lic = rec.get("license", "")
        ver = f" {rec['license_version']}" if rec.get("license_version") else ""
        lines.append(f"- `{name}` — \"{rec.get('title') or name}\" by {rec.get('creator') or 'unknown'}, "
                     f"{lic.upper()}{ver} ({rec.get('license_url') or ''}), source: {rec.get('landing_url') or ''}")
    return "\n".join(lines) + "\n"
