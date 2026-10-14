"""Minimal OOXML package helpers for the PM6 template-fill prototype (no vendor imports)."""
from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from typing import Iterable

from lxml import etree

PML = "http://schemas.openxmlformats.org/presentationml/2006/main"
AML = "http://schemas.openxmlformats.org/drawingml/2006/main"
RML = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CML = "http://schemas.openxmlformats.org/drawingml/2006/chart"
NS = {"p": PML, "a": AML, "r": RML, "pr": PKG_REL, "c": CML}
EMU_PER_PT = 12700


def q(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


def rels_name(part: str) -> str:
    return posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")


class Package:
    """In-memory PPTX: raw entries plus a parsed-XML cache. Only touched parts are re-serialized."""

    def __init__(self, entries: dict[str, bytes]):
        self.entries = entries
        self._xml: dict[str, etree._Element] = {}
        self.dirty: set[str] = set()

    @classmethod
    def open(cls, path: Path) -> "Package":
        with zipfile.ZipFile(path) as archive:
            return cls({i.filename: archive.read(i.filename) for i in archive.infolist() if not i.is_dir()})

    def xml(self, part: str) -> etree._Element:
        if part not in self._xml:
            self._xml[part] = etree.fromstring(self.entries[part])
        return self._xml[part]

    def touch(self, part: str) -> None:
        self.dirty.add(part)

    def rels(self, part: str) -> dict[str, tuple[str, str, str | None]]:
        name = rels_name(part)
        if name not in self.entries:
            return {}
        out = {}
        for rel in self.xml(name).findall(q("pr", "Relationship")):
            target = rel.get("Target") or ""
            mode = rel.get("TargetMode")
            resolved = target if mode == "External" else posixpath.normpath(posixpath.join(posixpath.dirname(part), target))
            out[rel.get("Id")] = (rel.get("Type") or "", resolved, mode)
        return out

    def rel_target(self, part: str, suffix: str) -> str | None:
        for typ, target, _mode in self.rels(part).values():
            if typ.endswith("/" + suffix):
                return target
        return None

    def slide_parts(self) -> list[str]:
        pres = self.xml("ppt/presentation.xml")
        rels = self.rels("ppt/presentation.xml")
        return [rels[rid][1] for rid in pres.xpath("./p:sldIdLst/p:sldId/@r:id", namespaces=NS)]

    def slide_size(self) -> tuple[int, int]:
        sz = self.xml("ppt/presentation.xml").find(q("p", "sldSz"))
        return int(sz.get("cx")), int(sz.get("cy"))

    def chain(self, slide_part: str) -> tuple[str | None, str | None, str | None]:
        layout = self.rel_target(slide_part, "slideLayout")
        master = self.rel_target(layout, "slideMaster") if layout else None
        theme = self.rel_target(master, "theme") if master else None
        return layout, master, theme

    def save(self, path: Path) -> None:
        for part in self.dirty:
            self.entries[part] = etree.tostring(self._xml[part], xml_declaration=True, encoding="UTF-8", standalone=True)
        self.dirty.clear()
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            # keep [Content_Types].xml first for picky consumers
            names = sorted(self.entries, key=lambda n: (n != "[Content_Types].xml",))
            for name in names:
                archive.writestr(name, self.entries[name])


def cnvpr(element: etree._Element) -> etree._Element | None:
    for path in ("./p:nvSpPr/p:cNvPr", "./p:nvPicPr/p:cNvPr", "./p:nvGraphicFramePr/p:cNvPr",
                 "./p:nvGrpSpPr/p:cNvPr", "./p:nvCxnSpPr/p:cNvPr"):
        found = element.xpath(path, namespaces=NS)
        if found:
            return found[0]
    return None


SHAPE_TAGS = {q("p", t) for t in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp")}


def iter_shapes(tree: etree._Element) -> Iterable[etree._Element]:
    for element in tree.iter():
        if element.tag in SHAPE_TAGS:
            yield element


def find_by_id(slide_root: etree._Element, shape_id: int) -> list[etree._Element]:
    out = []
    for element in iter_shapes(slide_root):
        c = cnvpr(element)
        if c is not None and c.get("id") == str(shape_id):
            out.append(element)
    return out


def placeholder(element: etree._Element) -> tuple[str | None, str | None] | None:
    ph = element.xpath("./p:nvSpPr/p:nvPr/p:ph | ./p:nvPicPr/p:nvPr/p:ph | ./p:nvGraphicFramePr/p:nvPr/p:ph", namespaces=NS)
    if not ph:
        return None
    return ph[0].get("type"), ph[0].get("idx")


def paragraph_text(p: etree._Element) -> str:
    out = []
    for node in p:
        if node.tag in (q("a", "r"), q("a", "fld")):
            t = node.find(q("a", "t"))
            out.append(t.text or "" if t is not None else "")
        elif node.tag == q("a", "br"):
            out.append("\v")
    return "".join(out)


def txbody_text(element: etree._Element) -> str:
    body = element.find(q("p", "txBody"))
    if body is None:
        return ""
    return "\n".join(paragraph_text(p) for p in body.findall(q("a", "p")))
