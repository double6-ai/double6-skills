"""Native txBody rewriting: keep the frame, bodyPr, lstStyle and paragraph/run formatting prototypes."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from lxml import etree

from .ooxml import NS, q
from .textfit import map_levels

RUN_TAGS = {q("a", "r"), q("a", "br"), q("a", "fld")}
AUTOFIT_TAGS = {q("a", "normAutofit"), q("a", "spAutoFit"), q("a", "noAutofit")}


def _para_level(p: etree._Element) -> int:
    ppr = p.find(q("a", "pPr"))
    return int(ppr.get("lvl", "0")) if ppr is not None else 0


def _proto_for(protos: list[etree._Element], index: int, lvl: int, explicit: bool) -> etree._Element:
    if explicit:
        same = [p for p in protos if _para_level(p) == lvl]
        if same:
            return same[0]
    return protos[min(index, len(protos) - 1)]


def _run_rpr(proto: etree._Element) -> etree._Element | None:
    r = proto.find("./a:r/a:rPr", NS)
    if r is not None:
        return deepcopy(r)
    end = proto.find(q("a", "endParaRPr"))
    if end is not None:
        rpr = etree.Element(q("a", "rPr"))
        for k, v in end.attrib.items():
            rpr.set(k, v)
        for child in end:
            rpr.append(deepcopy(child))
        return rpr
    return None


def set_text(txbody: etree._Element, text: str, ctx_levels: list[int] | None = None, *, size_scale: float | None = None,
             resolved_sizes: dict[int, float] | None = None, levels: list[int] | None = None) -> int:
    """Replace paragraphs of ``txbody`` with ``text`` (``\\n`` = paragraph, leading ``\\t`` = list level).

    Returns the number of paragraphs written. Shape identity, bodyPr and lstStyle are untouched.
    """
    protos = [deepcopy(p) for p in txbody.findall(q("a", "p"))]
    if not protos:
        protos = [etree.Element(q("a", "p"))]
    for p in txbody.findall(q("a", "p")):
        txbody.remove(p)
    ctx = {"template_paragraph_levels": ctx_levels or [_para_level(p) for p in protos]}
    raw_lines = text.split("\n")
    explicit_mode = (levels is not None and len(levels) == len(raw_lines)) or any(r.startswith("\t") for r in raw_lines)
    for index, (lvl, line) in enumerate(map_levels(ctx, text, levels)):
        explicit = explicit_mode
        proto = _proto_for(protos, index, lvl, explicit)
        p = deepcopy(proto)
        rpr = _run_rpr(proto)
        for child in list(p):
            if child.tag in RUN_TAGS:
                p.remove(child)
        ppr = p.find(q("a", "pPr"))
        if explicit:
            if ppr is None:
                ppr = etree.Element(q("a", "pPr"))
                p.insert(0, ppr)
            if lvl:
                ppr.set("lvl", str(lvl))
            elif "lvl" in ppr.attrib:
                del ppr.attrib["lvl"]
        end = p.find(q("a", "endParaRPr"))
        segments = line.split("\v")
        insert_at = list(p).index(end) if end is not None else len(p)
        for s_index, seg in enumerate(segments):
            if s_index:
                br = etree.Element(q("a", "br"))
                if rpr is not None:
                    br.append(deepcopy(rpr))
                p.insert(insert_at, br)
                insert_at += 1
            if seg == "":
                continue
            r = etree.Element(q("a", "r"))
            if rpr is not None:
                r.append(deepcopy(rpr))
            t = etree.SubElement(r, q("a", "t"))
            t.text = seg
            p.insert(insert_at, r)
            insert_at += 1
        if size_scale is not None and resolved_sizes:
            base = resolved_sizes.get(lvl) or resolved_sizes.get(0) or 18.0
            sz = str(int(round(base * size_scale * 100)))
            for node in p.xpath("./a:r/a:rPr | ./a:br/a:rPr | ./a:endParaRPr", namespaces=NS):
                node.set("sz", sz)
            for r in p.findall(q("a", "r")):
                if r.find(q("a", "rPr")) is None:
                    rp = etree.Element(q("a", "rPr"))
                    rp.set("sz", sz)
                    r.insert(0, rp)
        txbody.append(p)
    return len(raw_lines)


def apply_fit(element: etree._Element, report: dict[str, Any]) -> None:
    """Translate a ``textfit.fit`` decision into native bodyPr state (wrap/autofit kept native)."""
    body = element.find("./p:txBody/a:bodyPr", NS)
    if body is None:
        return
    status = report.get("status")
    if status == "autofit" or (report.get("autofit_mode") == "norm"):
        for child in list(body):
            if child.tag in AUTOFIT_TAGS:
                body.remove(child)
        norm = etree.Element(q("a", "normAutofit"))
        if report.get("font_scale", 1.0) < 0.999:
            norm.set("fontScale", str(int(round(report["font_scale"] * 100000))))
        if report.get("ln_spc_reduction", 0.0) > 0:
            norm.set("lnSpcReduction", str(int(round(report["ln_spc_reduction"] * 100000))))
        _insert_autofit(body, norm)
    elif status == "grow" and report.get("new_h_pt"):
        ext = element.find("./p:spPr/a:xfrm/a:ext", NS)
        if ext is not None:
            ext.set("cy", str(int(round(report["new_h_pt"] * 12700))))


def _insert_autofit(body: etree._Element, node: etree._Element) -> None:
    # CT_TextBodyProperties order: prstTxWarp?, (autofit)?, scene3d?, sp3d?, flatTx?, extLst?
    warp = body.find(q("a", "prstTxWarp"))
    if warp is not None:
        warp.addnext(node)
    else:
        body.insert(0, node)
