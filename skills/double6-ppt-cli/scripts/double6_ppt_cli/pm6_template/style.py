"""Resolve the effective text geometry/style of a native text shape (placeholder + master inheritance).

Produces a JSON-serialisable *fit context* consumed by ``textfit``: box size, insets, autofit mode,
wrap mode and, per list level, font size / typefaces / margins / spacing / bullet.
"""
from __future__ import annotations

from typing import Any

from lxml import etree

from .ooxml import EMU_PER_PT, NS, Package, placeholder, q

TITLE_TYPES = {"title", "ctrTitle"}
BODY_LIKE = {"body", "subTitle", "obj", None}


def _ph_match(container: etree._Element, ph_type: str | None, ph_idx: str | None, by_type_only: bool) -> etree._Element | None:
    tree = container.find("./p:cSld/p:spTree", NS)
    if tree is None:
        return None
    norm = lambda t: "title" if t in TITLE_TYPES else ("body" if t in BODY_LIKE else t)  # noqa: E731
    candidates = []
    for sp in tree.iter(q("p", "sp")):
        ph = placeholder(sp)
        if ph is None:
            continue
        t, idx = ph
        if not by_type_only and ph_idx is not None and idx == ph_idx:
            return sp
        if norm(t) == norm(ph_type):
            candidates.append(sp)
    if by_type_only or ph_idx is None or ph_idx == "0":
        return candidates[0] if candidates else None
    return candidates[0] if candidates and ph_type not in BODY_LIKE else (candidates[0] if candidates else None)


def _xfrm(sp: etree._Element | None) -> tuple[int, int, int, int] | None:
    if sp is None:
        return None
    x = sp.find("./p:spPr/a:xfrm", NS)
    if x is None:
        x = sp.find("./p:xfrm", NS)
    if x is None:
        return None
    off, ext = x.find(q("a", "off")), x.find(q("a", "ext"))
    if off is None or ext is None:
        return None
    return int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))


def _group_scale(element: etree._Element) -> tuple[float, float, float, float]:
    """Accumulated (sx, sy, dx, dy) mapping child coords -> slide coords through grpSp ancestors."""
    sx = sy = 1.0
    dx = dy = 0.0
    chain = []
    parent = element.getparent()
    while parent is not None:
        if parent.tag == q("p", "grpSp"):
            chain.append(parent)
        parent = parent.getparent()
    for grp in reversed(chain):
        x = grp.find("./p:grpSpPr/a:xfrm", NS)
        if x is None:
            continue
        off, ext, choff, chext = (x.find(q("a", n)) for n in ("off", "ext", "chOff", "chExt"))
        if None in (off, ext, choff, chext):
            continue
        gx = float(int(ext.get("cx")) / max(1, int(chext.get("cx"))))
        gy = float(int(ext.get("cy")) / max(1, int(chext.get("cy"))))
        dx = dx + sx * (int(off.get("x")) - int(choff.get("x")) * gx)
        dy = dy + sy * (int(off.get("y")) - int(choff.get("y")) * gy)
        sx, sy = sx * gx, sy * gy
    return sx, sy, dx, dy


def _lvl(lst: etree._Element | None, level: int) -> etree._Element | None:
    if lst is None:
        return None
    return lst.find(q("a", f"lvl{level + 1}pPr"))


def _theme_fonts(pkg: Package, theme_part: str | None) -> dict[str, str]:
    fonts = {"+mj-lt": "", "+mn-lt": "", "+mj-ea": "", "+mn-ea": "", "hans_minor": "", "hans_major": ""}
    if not theme_part or theme_part not in pkg.entries:
        return fonts
    root = pkg.xml(theme_part)
    for kind, key in (("majorFont", "mj"), ("minorFont", "mn")):
        node = root.find(f".//a:fontScheme/a:{kind}", NS)
        if node is None:
            continue
        lat = node.find(q("a", "latin"))
        ea = node.find(q("a", "ea"))
        fonts[f"+{key}-lt"] = lat.get("typeface", "") if lat is not None else ""
        fonts[f"+{key}-ea"] = ea.get("typeface", "") if ea is not None else ""
        for f in node.findall(q("a", "font")):
            if f.get("script") == "Hans":
                fonts["hans_" + ("major" if key == "mj" else "minor")] = f.get("typeface", "")
    return fonts


def _resolve_face(face: str | None, theme: dict[str, str], is_ea: bool, major: bool) -> str:
    if face and face.startswith("+"):
        face = theme.get(face, "")
        if not face and is_ea:
            face = theme.get("hans_major" if major else "hans_minor", "")
    return face or ""


def _spacing(node: etree._Element | None, tag: str) -> tuple[str, float] | None:
    if node is None:
        return None
    sp = node.find(q("a", tag))
    if sp is None:
        return None
    pct = sp.find(q("a", "spcPct"))
    pts = sp.find(q("a", "spcPts"))
    if pct is not None:
        return ("pct", int(pct.get("val")) / 100000.0)
    if pts is not None:
        return ("pts", int(pts.get("val")) / 100.0)
    return None


def text_layers(pkg: Package, slide_part: str, element: etree._Element) -> dict[str, Any]:
    """Return the ordered inheritance layers for a text-bearing sp (shape first, defaults last)."""
    layout, master, theme_part = pkg.chain(slide_part)
    ph = placeholder(element)
    layout_sp = master_sp = None
    if ph is not None and layout:
        layout_sp = _ph_match(pkg.xml(layout), ph[0], ph[1], by_type_only=False)
    if ph is not None and master:
        mtype = layout_sp is not None and placeholder(layout_sp)[0] or ph[0]
        master_sp = _ph_match(pkg.xml(master), mtype, None, by_type_only=True)
    eff_type = ph[0] if ph else None
    if ph is not None and eff_type is None and layout_sp is not None:
        eff_type = placeholder(layout_sp)[0]
    style_name = None
    if master:
        if ph is None:
            style_name = "otherStyle"
        elif eff_type in TITLE_TYPES:
            style_name = "titleStyle"
        elif eff_type in BODY_LIKE:
            style_name = "bodyStyle"
        else:
            style_name = "otherStyle"
    master_style = pkg.xml(master).find(f"./p:txStyles/p:{style_name}", NS) if master and style_name else None
    default_style = pkg.xml("ppt/presentation.xml").find("./p:defaultTextStyle", NS)
    lst = lambda sp: sp.find("./p:txBody/a:lstStyle", NS) if sp is not None else None  # noqa: E731
    lists = [lst(element), lst(layout_sp), lst(master_sp), master_style]
    if ph is None:
        lists.append(default_style)
    return {
        "layout_sp": layout_sp, "master_sp": master_sp, "lists": lists,
        "theme": _theme_fonts(pkg, theme_part), "is_title": eff_type in TITLE_TYPES, "ph": ph,
    }


def level_props(layers: dict[str, Any], level: int, p: etree._Element | None = None, run_rpr: etree._Element | None = None) -> dict[str, Any]:
    nodes = []
    if p is not None:
        nodes.append(p.find(q("a", "pPr")))
    nodes += [_lvl(lst, level) for lst in layers["lists"]]
    props: dict[str, Any] = {"sz": None, "marL": None, "indent": None, "lnSpc": None, "spcBef": None, "spcAft": None,
                             "latin": None, "ea": None, "bold": None, "bullet": None, "algn": None}
    rprs = ([run_rpr] if run_rpr is not None else []) + [n.find(q("a", "defRPr")) if n is not None else None for n in nodes]
    for r in rprs:
        if r is None:
            continue
        if props["sz"] is None and r.get("sz"):
            props["sz"] = int(r.get("sz")) / 100.0
        if props["bold"] is None and r.get("b") is not None:
            props["bold"] = r.get("b") in ("1", "true")
        for key in ("latin", "ea"):
            node = r.find(q("a", key))
            if props[key] is None and node is not None and node.get("typeface"):
                props[key] = node.get("typeface")
    for n in nodes:
        if n is None:
            continue
        for key in ("marL", "indent"):
            if props[key] is None and n.get(key) is not None:
                props[key] = int(n.get(key)) / EMU_PER_PT
        if props["algn"] is None and n.get("algn"):
            props["algn"] = n.get("algn")
        for key in ("lnSpc", "spcBef", "spcAft"):
            if props[key] is None:
                props[key] = _spacing(n, key)
        if props["bullet"] is None:
            if n.find(q("a", "buNone")) is not None:
                props["bullet"] = False
            elif n.find(q("a", "buChar")) is not None or n.find(q("a", "buAutoNum")) is not None:
                props["bullet"] = True
    theme = layers["theme"]
    major = layers["is_title"]
    props["latin"] = _resolve_face(props["latin"] or ("+mj-lt" if major else "+mn-lt"), theme, False, major)
    props["ea"] = _resolve_face(props["ea"] or ("+mj-ea" if major else "+mn-ea"), theme, True, major)
    props["sz"] = props["sz"] or 18.0
    props["marL"] = props["marL"] or 0.0
    props["indent"] = props["indent"] or 0.0
    props["bullet"] = bool(props["bullet"])
    props["bold"] = bool(props["bold"])
    return props


def body_props(element: etree._Element, layers: dict[str, Any]) -> dict[str, Any]:
    chain = [element, layers["layout_sp"], layers["master_sp"]]
    bodies = [sp.find("./p:txBody/a:bodyPr", NS) if sp is not None else None for sp in chain]
    out: dict[str, Any] = {"lIns": None, "tIns": None, "rIns": None, "bIns": None, "wrap": None, "anchor": None, "autofit": None, "vert": None}
    for b in bodies:
        if b is None:
            continue
        for key in ("lIns", "tIns", "rIns", "bIns", "wrap", "anchor", "vert"):
            if out[key] is None and b.get(key) is not None:
                out[key] = b.get(key)
        if out["autofit"] is None:
            if b.find(q("a", "normAutofit")) is not None:
                out["autofit"] = "norm"
            elif b.find(q("a", "spAutoFit")) is not None:
                out["autofit"] = "shape"
            elif b.find(q("a", "noAutofit")) is not None:
                out["autofit"] = "none"
    defaults = {"lIns": 91440, "tIns": 45720, "rIns": 91440, "bIns": 45720}
    for key, value in defaults.items():
        out[key] = int(out[key]) / EMU_PER_PT if out[key] is not None else value / EMU_PER_PT
    out["wrap"] = out["wrap"] or "square"
    out["autofit"] = out["autofit"] or "none"
    return out


def _obstacle_limit(element: etree._Element, box: tuple[int, int, int, int], slide_w: int) -> tuple[float | None, list[str]]:
    """Height (EMU) available before the first sibling shape that sits inside the lower part of this frame.

    Text that grows down into a card/callout overlaps it in PowerPoint even when the frame itself is
    large enough (verified on PowerPoint 16), so such shapes cap the usable height.
    """
    parent = element.getparent()
    if parent is None or etree.QName(parent).localname != "spTree":
        return None, []
    x, y, cx, cy = box
    limit, names = None, []
    for sib in parent:
        if sib is element or etree.QName(sib).localname not in ("sp", "pic", "graphicFrame", "grpSp", "cxnSp"):
            continue
        b = _xfrm(sib)
        if b is None and etree.QName(sib).localname == "grpSp":
            g = sib.find("./p:grpSpPr/a:xfrm", NS)
            if g is not None and g.find(q("a", "off")) is not None:
                o, e = g.find(q("a", "off")), g.find(q("a", "ext"))
                b = (int(o.get("x")), int(o.get("y")), int(e.get("cx")), int(e.get("cy")))
        if b is None or (slide_w and b[2] >= 0.9 * slide_w):
            continue
        bx, by, bcx, bcy = b
        overlap_w = min(x + cx, bx + bcx) - max(x, bx)
        if overlap_w <= 0.1 * cx:
            continue
        if y + 0.2 * cy < by < y + cy:
            if limit is None or by - y < limit:
                limit = by - y
            c = sib.find(".//p:cNvPr", NS)
            names.append(c.get("name") if c is not None else etree.QName(sib).localname)
    return limit, names


def fit_context(pkg: Package, slide_part: str, element: etree._Element, *, txbody: etree._Element | None = None) -> dict[str, Any] | None:
    """Fit context for a p:sp text frame (or a table cell when txbody is given: geometry left to caller)."""
    layers = text_layers(pkg, slide_part, element)
    box = _xfrm(element) or _xfrm(layers["layout_sp"]) or _xfrm(layers["master_sp"])
    if box is None:
        return None
    sx, sy, dx, dy = _group_scale(element)
    x, y, cx, cy = box
    body = txbody if txbody is not None else element.find(q("p", "txBody"))
    if body is None:
        return None
    paragraphs = body.findall(q("a", "p"))
    levels = []
    for p in paragraphs or [None]:
        ppr = p.find(q("a", "pPr")) if p is not None else None
        levels.append(int(ppr.get("lvl", "0")) if ppr is not None else 0)
    level_set = sorted(set(levels) | {0, 1, 2})
    per_level = {}
    for lvl in level_set:
        proto = next((p for p, l in zip(paragraphs, levels) if l == lvl), None)
        run = proto.find("./a:r/a:rPr", NS) if proto is not None else None
        if run is None and proto is not None:
            run = proto.find(q("a", "endParaRPr"))
        per_level[str(lvl)] = level_props(layers, lvl, proto, run)
    slide_w, slide_h = pkg.slide_size()
    limit, obstacles = (None, []) if txbody is not None else _obstacle_limit(element, (x, y, cx, cy), slide_w)
    usable_cy = min(cy, limit) if limit is not None else cy
    return {
        "box": {"x_pt": (dx + x * sx) / EMU_PER_PT, "y_pt": (dy + y * sy) / EMU_PER_PT,
                "w_pt": cx * sx / EMU_PER_PT, "h_pt": usable_cy * sy / EMU_PER_PT, "frame_h_pt": cy * sy / EMU_PER_PT},
        "obstacles": obstacles,
        "slide": {"w_pt": slide_w / EMU_PER_PT, "h_pt": slide_h / EMU_PER_PT},
        "body": body_props(element, layers),
        "levels": per_level,
        "template_paragraph_levels": levels,
        "placeholder": list(layers["ph"]) if layers["ph"] else None,
        "is_title": bool(layers.get("is_title")),
    }
