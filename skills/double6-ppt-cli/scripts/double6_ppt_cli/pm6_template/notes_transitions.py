"""Speaker notes and slide transitions for PM6 template fill (v4.8 plan semantics).

Plan fields per slide (same as v4.8 ``template_fill_pptx``):

* ``notes`` / ``speaker_notes``: string -> the slide's speaker notes become exactly this text (the
  existing notes part, its master and styling are kept and only the body text is rewritten; a notes
  part is created from the notes master when the template slide had none). ``"keep"`` keeps the
  template notes verbatim. Absent -> template sample notes are removed (v4.8 behaviour: sample notes
  are template residue).
* ``transition``: absent / ``"keep"`` keeps the template transition byte-for-byte (the roundtrip
  passes it through); ``"none"`` removes it; an effect name or ``{effect, effect_options, duration,
  advance_after}`` replaces it through the shared PPT Master ``pptx_transitions`` writer.
"""
from __future__ import annotations

import posixpath
import re
from copy import deepcopy
from typing import Any

from lxml import etree

from .ooxml import NS, Package, q, rels_name

NOTES_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
NOTES_CT = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
KEEP = "keep"


def _fillnative():
    from . import fillnative  # noqa: F401  (puts vendored scripts on sys.path)
    from .fillnative import transitions
    return transitions


def resolve_transition(item: dict[str, Any], default: str | None = KEEP, duration: float = 0.5):
    t = _fillnative()
    return t._resolve_slide_transition(item, default_effect=default, default_duration=duration)


def apply_transition(pkg: Package, part: str, item: dict[str, Any], default: str | None = KEEP,
                     duration: float = 0.5) -> dict[str, Any]:
    effect, options, dur, advance = resolve_transition(item, default, duration)
    if (effect in (None, KEEP)) and advance is None:
        return {"transition": "kept"}
    t = _fillnative()
    from pptx_transitions import parse_source_xml, serialize_source_xml  # vendored v6.7.0
    if part in pkg.dirty:
        pkg.save_part(part)
    source = pkg.entries[part]
    root = parse_source_xml(source)
    auto = t._set_slide_transition(root, effect=effect, effect_options=options, duration=dur, advance_after=advance)
    pkg.set_bytes(part, serialize_source_xml(root, source))
    return {"transition": effect or KEEP, "duration": dur, "advance_after": advance, "auto_advance": bool(auto)}


def _notes_part(pkg: Package, slide_part: str) -> tuple[str | None, str | None]:
    for rid, (rtype, target, _m) in pkg.rels(slide_part).items():
        if rtype == NOTES_REL:
            return rid, target
    return None, None


def _content_types(pkg: Package):
    return pkg.xml("[Content_Types].xml")


def _drop_override(pkg: Package, part: str) -> None:
    ct = _content_types(pkg)
    for o in ct.findall(f"{{{CT_NS}}}Override"):
        if o.get("PartName") == "/" + part:
            ct.remove(o)
            pkg.touch("[Content_Types].xml")


def _add_override(pkg: Package, part: str) -> None:
    ct = _content_types(pkg)
    if not any(o.get("PartName") == "/" + part for o in ct.findall(f"{{{CT_NS}}}Override")):
        etree.SubElement(ct, f"{{{CT_NS}}}Override", PartName="/" + part, ContentType=NOTES_CT)
        pkg.touch("[Content_Types].xml")


def _remove_rel(pkg: Package, owner: str, rid: str) -> None:
    rels = pkg.xml(rels_name(owner))
    for rel in rels.findall(q("pr", "Relationship")):
        if rel.get("Id") == rid:
            rels.remove(rel)
            pkg.touch(rels_name(owner))


def _referenced_elsewhere(pkg: Package, target: str, owner: str) -> bool:
    for name in list(pkg.entries):
        if not name.endswith(".rels") or name == rels_name(owner):
            continue
        src = name.replace("_rels/", "")[:-5]
        try:
            rels = pkg.rels(src)
        except Exception:
            continue
        if any(t == target and typ == NOTES_REL for typ, t, _m in rels.values()):
            return True
    return False


def _set_body_text(root: etree._Element, text: str) -> bool:
    for sp in root.iter(q("p", "sp")):
        ph = sp.find("./p:nvSpPr/p:nvPr/p:ph", NS)
        if ph is None or ph.get("type") != "body":
            continue
        body = sp.find(q("p", "txBody"))
        paras = body.findall(q("a", "p"))
        proto_p = paras[0] if paras else etree.Element(q("a", "p"))
        proto_r = proto_p.find(q("a", "r"))
        for p in paras:
            body.remove(p)
        for line in text.split("\n"):
            p = etree.SubElement(body, q("a", "p"))
            ppr = proto_p.find(q("a", "pPr"))
            if ppr is not None:
                p.append(deepcopy(ppr))
            if line:
                r = etree.SubElement(p, q("a", "r"))
                if proto_r is not None and proto_r.find(q("a", "rPr")) is not None:
                    r.append(deepcopy(proto_r.find(q("a", "rPr"))))
                else:
                    etree.SubElement(r, q("a", "rPr"), lang="zh-CN")
                etree.SubElement(r, q("a", "t")).text = line
        return True
    return False


def _notes_master(pkg: Package) -> str | None:
    for _rid, (rtype, target, _m) in pkg.rels("ppt/presentation.xml").items():
        if rtype.endswith("/notesMaster"):
            return target
    return None


def apply_notes(pkg: Package, slide_part: str, slide_number: int, item: dict[str, Any]) -> dict[str, Any]:
    notes = item.get("notes", item.get("speaker_notes"))
    rid, target = _notes_part(pkg, slide_part)
    if isinstance(notes, str) and notes.strip() == KEEP:
        return {"notes": "kept" if target else "none"}
    if notes is None or not str(notes).strip():
        if not target:
            return {"notes": "none"}
        _remove_rel(pkg, slide_part, rid)
        if not _referenced_elsewhere(pkg, target, slide_part):
            pkg.remove(target)
            pkg.remove(rels_name(target))
            _drop_override(pkg, target)
        return {"notes": "removed_template_notes"}
    from .fillnative import notes as legacy_notes  # noqa: F401  (sys.path)
    from svg_to_pptx.pptx_package.notes import create_notes_slide_xml, markdown_to_plain_text
    plain = markdown_to_plain_text(str(notes).strip())
    if target and not _referenced_elsewhere(pkg, target, slide_part):
        root = pkg.xml(target)
        if _set_body_text(root, plain):
            # the notes slide's back-reference must point to this slide
            pkg.touch(target)
            return {"notes": "replaced", "part": target}
    if target:
        _remove_rel(pkg, slide_part, rid)
    n = 1
    while f"ppt/notesSlides/notesSlide{n}.xml" in pkg.entries:
        n += 1
    part = f"ppt/notesSlides/notesSlide{n}.xml"
    pkg.set_bytes(part, create_notes_slide_xml(n, plain).encode("utf-8"))
    master = _notes_master(pkg)
    rel_xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
               f'<Relationships xmlns="{NS["pr"]}">']
    if master:
        rel_xml.append(f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster" Target="{posixpath.relpath(master, "ppt/notesSlides")}"/>')
    rel_xml.append(f'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="{posixpath.relpath(slide_part, "ppt/notesSlides")}"/>')
    rel_xml.append("</Relationships>")
    pkg.set_bytes(rels_name(part), "".join(rel_xml).encode("utf-8"))
    srels_name = rels_name(slide_part)
    srels = pkg.xml(srels_name)
    used = {r.get("Id") for r in srels.findall(q("pr", "Relationship"))}
    k = 1
    while f"rId{k}" in used:
        k += 1
    etree.SubElement(srels, q("pr", "Relationship"), Id=f"rId{k}", Type=NOTES_REL,
                     Target=posixpath.relpath(part, posixpath.dirname(slide_part)))
    pkg.touch(srels_name)
    _add_override(pkg, part)
    return {"notes": "created", "part": part}
