"""measure.py <template.pptx> <output.pptx> <plan.json> <outdir> -> metrics JSON (+ LO render)."""
import json, sys, zipfile, hashlib, subprocess, tempfile, shutil, re
from pathlib import Path
from lxml import etree
sys.path.insert(0, "/workspace/wt-pm6-template/skills/double6-ppt-cli/scripts")
from double6_ppt_cli.pm6_template.ooxml import Package, NS, cnvpr, iter_shapes, q, find_by_id, txbody_text
from double6_ppt_cli.pm6_template.style import fit_context
import fitz  # pymupdf

PT = 12700

def shapes_map(root):
    out = {}
    for e in iter_shapes(root.find("./p:cSld/p:spTree", NS)):
        c = cnvpr(e)
        if c is not None:
            out.setdefault(int(c.get("id")), []).append(e)
    return out

def package_diff(a, b):
    za, zb = zipfile.ZipFile(a), zipfile.ZipFile(b)
    ha = {n: hashlib.sha256(za.read(n)).hexdigest() for n in za.namelist() if not n.endswith("/")}
    hb = {n: hashlib.sha256(zb.read(n)).hexdigest() for n in zb.namelist() if not n.endswith("/")}
    def cls(n):
        for k in ("slideMasters/", "slideLayouts/", "theme/"):
            if k in n and not n.endswith(".rels"): return k.rstrip("/")
        return "other"
    res = {"identical": 0, "changed": [], "added": [], "removed": []}
    prot = {"slideMasters": [0, 0], "slideLayouts": [0, 0], "theme": [0, 0]}
    for n, h in ha.items():
        c = cls(n)
        if c in prot: prot[c][1] += 1
        if n in hb and hb[n] == h:
            res["identical"] += 1
            if c in prot: prot[c][0] += 1
        elif n in hb: res["changed"].append(n)
        else: res["removed"].append(n)
    res["added"] = [n for n in hb if n not in ha]
    res["protected_identical"] = {k: f"{v[0]}/{v[1]}" for k, v in prot.items()}
    return res

def render(pptx, outdir):
    prof = tempfile.mkdtemp(prefix="lo")
    subprocess.run(["soffice", f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(pptx)], capture_output=True, timeout=300)
    shutil.rmtree(prof, ignore_errors=True)
    return outdir / (Path(pptx).stem + ".pdf")

def find_hits(page, needle):
    needle = needle.strip()
    if not needle: return []
    return page.search_for(needle)

def contained(page, frame, text, slide_w_pt, page_w):
    """LO-measured containment: locate first and last line fragments of the slot text on the page."""
    k = page_w / slide_w_pt
    fx, fy, fw, fh = [v * k for v in frame]
    lines = [l for l in text.replace("\t", "").split("\n") if l.strip()]
    if not lines: return None
    def frag(s, last):
        s = s.strip()
        if re.search(r"[\u3000-\u9fff\uff00-\uffef]", s):
            return s[-4:] if last else s[:4]
        w = s.split()
        return " ".join(w[-2:]) if last else " ".join(w[:2])
    def best(needle):
        hits = find_hits(page, needle)
        if not hits: return None
        cx, cy = fx + fw / 2, fy + fh / 2
        return min(hits, key=lambda r: (max(0, fx - r.x0, r.x1 - fx - fw)) + abs((r.y0 + r.y1) / 2 - cy) * 0.2)
    top, bot = best(frag(lines[0], False)), best(frag(lines[-1], True))
    if top is None or bot is None: return {"found": False}
    tol = 6 * k
    over_bottom = max(0.0, bot.y1 - (fy + fh))
    over_top = max(0.0, fy - top.y0)
    over_right = max(0.0, max(top.x1, bot.x1) - (fx + fw))
    ok = over_bottom <= tol and over_top <= tol and over_right <= tol
    span = (max(bot.y1, fy + fh) - min(top.y0, fy))
    return {"found": True, "contained": ok, "overflow_pt": round((over_bottom + over_top) / k, 1), "overflow_ratio": round(span / fh - 1, 3) if fh else None,
            "over_right_pt": round(over_right / k, 1)}

def main(template, output, plan_path, outdir):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    plan = json.load(open(plan_path))
    tpl, out = Package.open(Path(template)), Package.open(Path(output))
    tparts, oparts = tpl.slide_parts(), out.slide_parts()
    removed = {(d["plan_slide"], d["source_object_id"]) for d in plan.get("object_dispositions", []) if d["disposition"] == "remove_sample"}
    sw, sh = out.slide_size()
    pdf = render(output, outdir)
    doc = fitz.open(pdf) if pdf.exists() else None
    m = {"slides": len(oparts), "plan_slides": len(plan["slides"]), "objects_expected": 0, "objects_preserved": 0, "objects_lost": [],
         "slots_replaced": 0, "slots_id_kept": 0, "slots_single_txbody": 0, "slots_pPr_kept": 0, "slots_paragraphs_ok": 0, "slots_placeholder_kept": 0,
         "slots_placeholder_total": 0, "new_shapes": 0, "new_textboxes": 0, "lo_found": 0, "lo_contained": 0, "lo_overflow": [], "tables_native": 0, "charts_native": 0}
    for i, (item, opart) in enumerate(zip(plan["slides"], oparts), 1):
        tpart = tparts[item["source_slide"] - 1]
        tmap, omap = shapes_map(tpl.xml(tpart)), shapes_map(out.xml(opart))
        for sid, els in tmap.items():
            e = els[0]
            soid = f"s{item['source_slide']:02d}:"
            if any(r[0] == i and r[1].startswith(soid) and r[1].endswith(f":{sid}") for r in removed):
                continue
            m["objects_expected"] += 1
            o = omap.get(sid)
            if o and o[0].tag == e.tag and cnvpr(o[0]).get("name") == cnvpr(e).get("name"):
                m["objects_preserved"] += 1
            else:
                m["objects_lost"].append(f"p{i}:id{sid}:{cnvpr(e).get('name')}")
        new_ids = [sid for sid in omap if sid not in tmap]
        m["new_shapes"] += len(new_ids)
        m["new_textboxes"] += sum(1 for sid in new_ids if omap[sid][0].tag == q("p", "sp") and omap[sid][0].find(q("p", "txBody")) is not None)
        page = doc[i - 1] if doc and i - 1 < len(doc) else None
        for rep in item.get("replacements", []):
            sid = int(rep["slot_id"].split("_sh")[1])
            if rep.get("text") == rep.get("old_text"): continue
            m["slots_replaced"] += 1
            te = tmap[sid][0]
            if te.find("./p:nvSpPr/p:nvPr/p:ph", NS) is not None: m["slots_placeholder_total"] += 1
            o = [x for x in omap.get(sid, []) if x.tag == q("p", "sp")]
            if o:
                m["slots_id_kept"] += 1
                body = o[0].find(q("p", "txBody"))
                if body is not None:
                    m["slots_single_txbody"] += 1
                    paras = body.findall(q("a", "p"))
                    if len(paras) == len(str(rep["text"]).split("\n")): m["slots_paragraphs_ok"] += 1
                    tp = [etree_s(p.find(q("a", "pPr"))) for p in te.findall("./p:txBody/a:p", NS)]
                    op = [etree_s(p.find(q("a", "pPr"))) for p in paras]
                    if all(x in tp for x in op): m["slots_pPr_kept"] += 1
                if o[0].find("./p:nvSpPr/p:nvPr/p:ph", NS) is not None: m["slots_placeholder_kept"] += 1
            ctx = fit_context(tpl, tpart, te)
            if page is not None and ctx:
                b = ctx["box"]
                r = contained(page, (b["x_pt"], b["y_pt"], b["w_pt"], b["h_pt"]), str(rep["text"]), sw / PT, page.rect.width)
                if r and r.get("found"):
                    m["lo_found"] += 1
                    if r["contained"]: m["lo_contained"] += 1
                    else: m["lo_overflow"].append({"plan_slide": i, "slot": rep["slot_id"], **r})
        for e in iter_shapes(out.xml(opart)):
            if e.tag == q("p", "graphicFrame"):
                if e.find(".//a:tbl", NS) is not None: m["tables_native"] += 1
                if e.xpath(".//c:chart", namespaces=NS): m["charts_native"] += 1
    # notes / transitions / mixed runs / protected parts
    m.update({"notes_expected": 0, "notes_ok": 0, "transitions_expected": 0, "transitions_ok": 0, "mixed_slots": 0, "mixed_kept": 0})
    def notes_text(pkg, part):
        for _r, (typ, tgt, _m) in pkg.rels(part).items():
            if typ.endswith("/notesSlide") and tgt in pkg.entries:
                return "".join(pkg.xml(tgt).xpath(".//p:sp[.//p:ph[@type='body']]//a:t/text()", namespaces=NS))
        return ""
    def trans(pkg, part):
        t = pkg.xml(part).xpath(".//p:transition", namespaces=NS)
        return [c.tag.split("}")[1] for c in t[0]] if t else []
    for i, (item, opart) in enumerate(zip(plan["slides"], oparts), 1):
        tpart = tparts[item["source_slide"] - 1]
        if "notes" in item:
            m["notes_expected"] += 1
            if notes_text(out, opart).strip() == str(item["notes"]).strip(): m["notes_ok"] += 1
        tt = trans(tpl, tpart)
        if "transition" in item or tt:
            m["transitions_expected"] += 1
            want = item.get("transition", {}).get("effect") if isinstance(item.get("transition"), dict) else None
            got = trans(out, opart)
            if (want and want in got) or (not want and got[:1] == tt[:1]): m["transitions_ok"] += 1
        omap = shapes_map(out.xml(opart))
        for rep in item.get("replacements", []):
            sid = int(rep["slot_id"].split("_sh")[1])
            te = shapes_map(tpl.xml(tpart)).get(sid, [None])[0]
            if te is None: continue
            from double6_ppt_cli.pm6_template.txbody import style_key
            def styles(e):
                return [ {style_key(r.find(q("a","rPr"))) for r in p.findall(q("a","r"))} for p in e.findall("./p:txBody/a:p", NS)]
            ts = styles(te)
            if any(len(x) > 1 for x in ts):
                m["mixed_slots"] += 1
                o = [x for x in omap.get(sid, []) if x.tag == q("p", "sp")]
                if o and any(len(x) > 1 for x in styles(o[0])): m["mixed_kept"] += 1
    m["id_preservation"] = round(m["objects_preserved"] / max(1, m["objects_expected"]), 4)
    m["lo_contained_ratio"] = round(m["lo_contained"] / max(1, m["lo_found"]), 4)
    m["package"] = package_diff(template, output)
    m["package"]["changed_count"] = len(m["package"]["changed"]); m["package"]["added_count"] = len(m["package"]["added"]); m["package"]["removed_count"] = len(m["package"]["removed"])
    (outdir / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))
    return m

def etree_s(x):
    """Namespace/attribute-order independent canonical form."""
    if x is None:
        return ()
    return (x.tag, tuple(sorted(x.attrib.items())), tuple(etree_s(c) for c in x))

if __name__ == "__main__":
    r = main(*sys.argv[1:5])
    print(json.dumps({k: v for k, v in r.items() if k not in ("objects_lost", "lo_overflow", "package")}, ensure_ascii=False))
