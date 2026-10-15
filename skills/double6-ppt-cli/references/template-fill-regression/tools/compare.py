"""compare.py: measure every run, build stacked contact sheets and the comparison table."""
import json, sys, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, str(Path(__file__).parent))
import measure

EVAL = Path(__file__).resolve().parents[1]
import os
BACKENDS = os.environ.get("BACKENDS", "v48,pm6,pm6-svg").split(",")
LABEL = {"v48": "v4.8 Fill Native (现行)", "pm6": "v6.7 原型 native（推荐）", "pm6-svg": "v6.7 纯SVG路线+度量换行", "pm6-svg-restore": "v6.7 SVG+导出后恢复原生"}
FONT = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 18)

def pages(pdf, dpi=50):
    out = pdf.with_suffix("")
    for f in pdf.parent.glob(pdf.stem + "-*.png"): f.unlink()
    subprocess.run(["pdftoppm", "-png", "-r", str(dpi), str(pdf), str(pdf.parent / pdf.stem)], check=True)
    return sorted(pdf.parent.glob(pdf.stem + "-*.png"))

def sheet(rows, dest, title, width=300):
    imgs = [[Image.open(p).convert("RGB") for p in ps] for _, ps in rows]
    imgs = [[im.resize((width, int(im.height * width / im.width))) for im in r] for r in imgs]
    h = max((im.height for r in imgs for im in r), default=100)
    cols = max((len(r) for r in imgs), default=1)
    lw = 230
    S = Image.new("RGB", (lw + cols * (width + 6) + 10, 40 + len(rows) * (h + 10)), "white")
    d = ImageDraw.Draw(S); d.text((10, 8), title, fill="black", font=FONT)
    for ri, ((label, _), r) in enumerate(zip(rows, imgs)):
        y = 40 + ri * (h + 10)
        d.text((8, y + h // 2 - 20), label, fill="black", font=FONT)
        for ci, im in enumerate(r):
            x = lw + ci * (width + 6); S.paste(im, (x, y)); d.rectangle([x - 1, y - 1, x + im.width, y + im.height], outline="#888")
    S.save(dest)

def main(templates):
    out = EVAL / "results"; out.mkdir(exist_ok=True)
    table = []
    for t in templates:
        spec = json.load(open(EVAL / "specs" / f"{t}.json"))
        tpl = EVAL / "templates" / spec["template"]
        rows = []
        rdir = out / t; rdir.mkdir(exist_ok=True)
        tpdf = measure.render(tpl, rdir)
        rows.append(("模板原样", pages(tpdf)))
        for b in BACKENDS:
            run = EVAL / "runs" / t / b
            log = json.load(open(EVAL / "runs" / t / f"{b}_log.json"))
            pptx = run / "artifacts" / "template-filled.pptx"
            row = {"template": t, "backend": b, "status": log["status"]}
            if log["status"] == "ok" and pptx.exists():
                mdir = rdir / b
                m = measure.main(tpl, pptx, EVAL / "runs" / t / f"{b}_plan.json", mdir)
                rec = json.load(open(run / "evidence" / "template_apply_receipt.json"))
                pm6r = run / "artifacts" / "template-filled.pm6_receipt.json"
                pr = json.load(open(pm6r)) if pm6r.exists() else {}
                row.update({k: m[k] for k in ("id_preservation", "objects_expected", "objects_preserved", "slots_replaced", "slots_id_kept", "slots_single_txbody",
                                               "slots_pPr_kept", "slots_paragraphs_ok", "slots_placeholder_kept", "slots_placeholder_total", "new_shapes", "new_textboxes",
                                               "lo_found", "lo_contained", "lo_contained_ratio", "tables_native", "charts_native",
                                               "notes_expected", "notes_ok", "transitions_expected", "transitions_ok", "mixed_slots", "mixed_kept")})
                row["lo_overflow_max_ratio"] = max([o.get("overflow_ratio") or 0 for o in m["lo_overflow"]], default=0)
                row["pkg_protected_identical"] = m["package"]["protected_identical"]
                row["pkg_changed"], row["pkg_added"], row["pkg_removed"] = m["package"]["changed_count"], m["package"]["added_count"], m["package"]["removed_count"]
                row["officecli_validate"] = (rec.get("officecli_validate") or {}).get("data") or (rec.get("officecli_validate") or {}).get("message")
                row["nav_links"], row["nav_states"], row["images"] = len(rec.get("updated_navigation_links", [])), len(rec.get("updated_navigation_states", [])), len(rec.get("replaced_picture_objects", []))
                row["export_summary"], row["quality_gate"] = pr.get("export_summary"), pr.get("quality_gate")
                fits = [x.get("fit") for x in pr.get("text", [])]
                row["fit_decisions"] = {k: fits.count(k) for k in sorted(set(fits))}
                rows.append((LABEL[b], pages(mdir / "template-filled.pdf")))
            else:
                last = log["steps"][-1]["out"]
                row["error"] = (last.get("code"), str(last.get("message"))[:300])
                rows.append((LABEL[b] + "\n(失败)", []))
            table.append(row)
        sheet(rows, out / f"{t}_contact_sheet.png", f"{t} · {spec['template']} · LibreOffice 渲染对比")
    (out / "comparison.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    return table

if __name__ == "__main__":
    t = main(sys.argv[1:] or ["T1", "T2", "T3", "T4", "T5"])
    for r in t: print(json.dumps(r, ensure_ascii=False)[:600])
