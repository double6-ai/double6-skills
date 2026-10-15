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


def _proto_text(p: etree._Element) -> str:
    out = []
    for node in p:
        if node.tag in (q("a", "r"), q("a", "fld")):
            t = node.find(q("a", "t"))
            out.append((t.text or "") if t is not None else "")
        elif node.tag == q("a", "br"):
            out.append("\v")
    return "".join(out)


MIN_KEEP = 2
# rPr attributes that do not change the look (proofing/editing state); ignored when deciding whether
# a paragraph really mixes formats.
NOISE_ATTRS = {"lang", "altLang", "dirty", "err", "noProof", "smtClean", "smtId", "bmk"}


def style_key(rpr: etree._Element | None) -> bytes:
    if rpr is None:
        return b""
    c = deepcopy(rpr)
    for a in NOISE_ATTRS:
        c.attrib.pop(a, None)
    return etree.tostring(c, method="c14n")  # shortest common prefix/suffix worth keeping with its own run style


def styled_runs(proto: etree._Element, line: str) -> list[tuple[etree._Element | None, str]] | None:
    """Mixed-format preservation: map ``line`` onto the prototype's runs.

    Unchanged text keeps the run it came from (bold lead-ins, coloured numbers, links); the edited
    middle inherits the style of the run where the edit starts. Returns None when the prototype has
    a single style (plain rewrite is equivalent) or contains breaks/fields.
    """
    runs = [n for n in proto if n.tag in RUN_TAGS]
    if not runs or any(n.tag != q("a", "r") for n in runs):
        return None
    pieces = []
    for r in runs:
        t = r.find(q("a", "t"))
        pieces.append((r.find(q("a", "rPr")), (t.text or "") if t is not None else ""))
    keys = {style_key(rp) for rp, _t in pieces}
    if len(keys) < 2:
        return None
    old = "".join(t for _rp, t in pieces)
    if "\v" in line:
        return None
    pre = 0
    while pre < min(len(old), len(line)) and old[pre] == line[pre]:
        pre += 1
    suf = 0
    while suf < min(len(old), len(line)) - pre and old[len(old) - 1 - suf] == line[len(line) - 1 - suf]:
        suf += 1
    if pre < MIN_KEEP and pre != len(old):
        pre = 0
    if suf < MIN_KEEP and suf != len(old):
        suf = 0
    owner = []  # run index per old char
    for i, (_rp, t) in enumerate(pieces):
        owner += [i] * len(t)
    out: list[tuple[int, str]] = []

    def push(idx: int, text: str) -> None:
        if not text:
            return
        if out and out[-1][0] == idx:
            out[-1] = (idx, out[-1][1] + text)
        else:
            out.append((idx, text))

    for c in range(pre):
        push(owner[c], old[c])
    middle = line[pre:len(line) - suf if suf else len(line)]
    if middle:
        anchor = pre if pre < len(old) - suf else max(pre - 1, 0)
        push(owner[anchor] if owner else 0, middle)
    for c in range(len(old) - suf, len(old)):
        push(owner[c], old[c])
    return [(deepcopy(pieces[i][0]) if pieces[i][0] is not None else None, text) for i, text in out]


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
            if ppr is None and lvl:
                ppr = etree.Element(q("a", "pPr"))
                p.insert(0, ppr)
            if ppr is not None:
                if lvl:
                    ppr.set("lvl", str(lvl))
                elif "lvl" in ppr.attrib:
                    del ppr.attrib["lvl"]
                if not len(ppr) and not ppr.attrib:
                    p.remove(ppr)
        end = p.find(q("a", "endParaRPr"))
        mixed = styled_runs(proto, line) if line != _proto_text(proto) else None
        if line == _proto_text(proto) and line:
            # unchanged paragraph: keep every run, break and field verbatim
            insert_at = list(p).index(end) if end is not None else len(p)
            for node in [n for n in proto if n.tag in RUN_TAGS]:
                p.insert(insert_at, deepcopy(node))
                insert_at += 1
            segments = []
        elif mixed:
            insert_at = list(p).index(end) if end is not None else len(p)
            for rp, seg in mixed:
                r = etree.Element(q("a", "r"))
                if rp is not None:
                    r.append(rp)
                etree.SubElement(r, q("a", "t")).text = seg
                p.insert(insert_at, r)
                insert_at += 1
            segments = []
        else:
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
