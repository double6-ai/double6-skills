#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""Apply source-bound complete paragraph edits to a PDF at fixed scale."""
from __future__ import annotations
import argparse, hashlib, json, re, sys
from html.parser import HTMLParser
from pathlib import Path

import fitz

ROOT = __import__("runtime_paths").workspace_root()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cjk_justification import insert_source_htmlbox  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\xa0", " ")
    text = re.sub(r"-\s*\n\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]
    def handle_data(self, data): self.parts.append(data)


def plain(markup: str) -> str:
    p=Plain(); p.feed(markup); return "".join(p.parts)


def image_hashes(doc):
    return sorted(hashlib.sha256(doc.extract_image(row[0])["image"]).hexdigest()
                  for row in doc[0].get_images(full=True))


def links(doc):
    rows=[]
    for x in doc[0].get_links():
        if x.get('kind')!=fitz.LINK_URI or not x.get('uri'): raise ValueError('only_explicit_uri_actions_supported')
        rows.append((x['kind'],x['uri'],tuple(round(v,3) for v in x['from'])))
    return sorted(rows)


def apply(manifest_path: Path, output_path: Path, report_path: Path) -> dict:
    m=json.loads(manifest_path.read_text()); src=Path(m["source_pdf"]); base=Path(m["base_pdf"])
    if m.get("schema") != "reviewed_pdf_paragraphs@1": raise ValueError("unsupported_manifest_schema")
    if sha(src)!=m["source_sha256"]: raise ValueError("source_sha_mismatch")
    if sha(base)!=m["base_sha256"]: raise ValueError("base_sha_mismatch")
    source=fitz.open(src); doc=fitz.open(base)
    if len(source)!=1 or len(doc)!=1 or m["page"]!=1: raise ValueError("single_page_scope_only")
    sp, page=source[m["page"]-1], doc[m["page"]-1]
    if tuple(round(v,2) for v in sp.rect)!=tuple(round(v,2) for v in page.rect): raise ValueError("page_geometry_mismatch")
    before_links=links(doc); before_images=image_hashes(doc)
    baseline_fonts={f[0] for f in page.get_fonts(full=True)}
    seen=[]; out_seen=[]; clear_rects=[fitz.Rect(u['base_bbox']) for u in m['units']]; output_rects=[]
    for u in m["units"]:
        for field in ("source_text","base_text","target_text","target_markup"):
            if not isinstance(u.get(field),str) or not u[field]: raise ValueError("incomplete_unit:"+u.get("id","?"))
        for field in ("source_text_sha256","base_text_sha256","target_text_sha256"):
            target={"source_text_sha256":"source_text","base_text_sha256":"base_text","target_text_sha256":"target_text"}[field]
        if hashlib.sha256(u[target].encode()).hexdigest()!=u[field]: raise ValueError("unit_text_sha_mismatch:"+u["id"])
        glyph_text=u.get("target_glyph_text",u["target_text"])
        if u.get("target_glyph_sha256") and hashlib.sha256(glyph_text.encode()).hexdigest()!=u["target_glyph_sha256"]: raise ValueError("target_glyph_sha_mismatch:"+u["id"])
        if norm(plain(u["target_markup"]))!=norm(glyph_text): raise ValueError("target_markup_incomplete:"+u["id"])
        sr=fitz.Rect(u["source_bbox"]); br=fitz.Rect(u["base_bbox"]); out=fitz.Rect(u["output_bbox"])
        if not sp.rect.contains(sr) or not page.rect.contains(br) or not page.rect.contains(out): raise ValueError("bbox_outside_page:"+u["id"])
        if norm(sp.get_textbox(sr))!=norm(u["source_text"]): raise ValueError("source_unit_incomplete_or_changed:"+u["id"])
        if norm(page.get_textbox(br))!=norm(u["base_text"]): raise ValueError("base_unit_incomplete_or_changed:"+u["id"])
        if any(br.intersects(old) for old in seen): raise ValueError("overlapping_clear_regions")
        if any(out.intersects(old) for old in out_seen): raise ValueError("overlapping_output_regions")
        for info in page.get_image_info(xrefs=True):
            if out.intersects(fitz.Rect(info['bbox'])): raise ValueError("output_overlaps_page_image:"+u["id"])
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    sr=fitz.Rect(span["bbox"])
                    if out.intersects(sr) and not any(c.contains(sr) for c in clear_rects): raise ValueError("output_overlaps_unowned_text:"+u["id"])
        seen.append(br); out_seen.append(out); output_rects.append(out)
    for u in m["units"]: page.add_redact_annot(fitz.Rect(u["base_bbox"]), fill=(1,1,1), cross_out=False)
    page.apply_redactions(images=0, graphics=0, text=0)
    for u in m["units"]:
        box=fitz.Rect(u["output_bbox"]); style=u["style"]
        if style["renderer"]=="source_crop":
            source_box=fitz.Rect(u['source_bbox'])
            if abs(source_box.width-box.width)>.01 or abs(source_box.height-box.height)>.01: raise ValueError('source_crop_requires_scale_one')
            page.show_pdf_page(box,source,m['page']-1,clip=source_box,overlay=True,keep_proportion=False)
            evidence={"source_bound_clip":list(source_box),"scale":1}
        elif style["renderer"]=="text":
            origin=style.get('origin')
            if not isinstance(origin,list) or len(origin)!=2: raise ValueError('text_renderer_requires_source_bound_baseline')
            page.insert_text(tuple(origin), u["target_text"], fontname=style.get("fontname","helv"),
                fontsize=float(style["font_size"]), color=style.get("color",[0,0,0]))
            drawn=[fitz.Rect(ch[3]) for span in page.get_texttrace() for ch in span['chars'] if box.intersects(fitz.Rect(ch[3]))]
            if not drawn or any(not box.contains(r) for r in drawn): raise ValueError("fixed_scale_text_overflow:"+u["id"])
            evidence={"baseline_origin":origin,"scale":1,"drawn_bbox_union":list(fitz.Rect(min(r.x0 for r in drawn),min(r.y0 for r in drawn),max(r.x1 for r in drawn),max(r.y1 for r in drawn)))}
        elif style["renderer"]=="story":
            bindings=style["font_bindings"]; files={k:Path(v["path"]) for k,v in bindings.items()}
            for key,p in files.items():
                if not p.is_file() or sha(p)!=bindings[key]["sha256"]: raise ValueError("font_binding_changed:"+key)
            if len({p.parent for p in files.values()})!=1: raise ValueError("font_binding_archive_must_be_single_directory")
            css=(f"@font-face{{font-family:CJK;src:url('{files['CJK'].name}')}}"
                 f"@font-face{{font-family:Latin;src:url('{files['Latin'].name}')}}"
                 + (f"@font-face{{font-family:CJKBold;src:url('{files['CJKBold'].name}')}}" if 'CJKBold' in files else "")
                 + f"body,p{{font-family:{style.get('font_family','CJK')};font-size:{style['font_size']}pt;line-height:{style['line_height']};"
                 f"margin:0;padding:0;color:#000;text-align:{style['alignment']}}}"
                 ".latin{font-family:Latin;font-style:italic}")
            spare,scale,evidence=insert_source_htmlbox(page,box,u["target_markup"],css=css,
                archive=fitz.Archive(str(next(iter(files.values())).parent)),default_alignment=style["alignment"])
            if spare<0 or scale!=1: raise ValueError("fixed_scale_story_overflow:"+u["id"])
        else: raise ValueError("unknown_renderer")
        u["render_evidence"]={"scale":1,"result":evidence}
    from owned_font_unicode import bind_owned_font_unicode
    def key(value): return re.sub(r'[^a-z0-9]','',value.lower())
    used={}
    for span in page.get_texttrace():
        if not any(fitz.Rect(span['bbox']).intersects(r) for r in output_rects): continue
        mapping=used.setdefault(key(span['font']),{})
        for ch in span['chars']:
            code,gid=ch[:2]; char=chr(code)
            if gid in mapping and mapping[gid]!=char: raise ValueError('ambiguous_actual_cid_unicode_mapping')
            mapping[gid]=char
    font_records=page.get_fonts(full=True); owned={f[0] for f in font_records}-baseline_fonts
    if any(u['style']['renderer']=='story' for u in m['units']) and not owned: raise ValueError('no_new_story_owned_font_xrefs')
    cmaps=[]
    for f in font_records:
        if f[0] not in owned: continue
        mapping=used.get(key(f[3]))
        if not mapping: raise ValueError('owned_story_font_missing_actual_trace_map')
        cmaps.append(bind_owned_font_unicode(doc,f[0],mapping,owned_font_xrefs=owned))
    if links(doc)!=before_links: raise ValueError("link_actions_changed")
    if image_hashes(doc)!=before_images: raise ValueError("embedded_image_identity_changed")
    output_path.parent.mkdir(parents=True,exist_ok=True); doc.save(output_path,garbage=4,deflate=True)
    doc.close();source.close()
    check=fitz.open(output_path)
    for u in m["units"]:
        wanted=u.get("target_glyph_text",u["target_text"]); rect=fitz.Rect(u["output_bbox"]); pieces=[]
        for span in check[m["page"]-1].get_texttrace():
            for ch in span["chars"]:
                if rect.intersects(fitz.Rect(ch[3])): pieces.append(chr(ch[0]))
        actual="".join(pieces)
        if norm(actual)!=norm(wanted): raise ValueError("saved_text_verification_failed:"+u["id"]+":"+repr(actual[:200]))
    if links(check)!=before_links or image_hashes(check)!=before_images: raise ValueError("saved_protection_verification_failed")
    report={"schema":"reviewed_pdf_paragraphs_report@1","status":"ok","input_source_sha256":m["source_sha256"],
        "input_base_sha256":m["base_sha256"],"output_pdf":str(output_path),"output_sha256":sha(output_path),
        "units":[{"id":u["id"],"source_text_sha256":u["source_text_sha256"],"target_text_sha256":u["target_text_sha256"],"scale":1} for u in m["units"]],
        "image_sha256":before_images,"links_preserved":len(before_links),"owned_font_cmaps":cmaps}
    report_path.parent.mkdir(parents=True,exist_ok=True); report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    check.close(); return report


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("manifest",type=Path);p.add_argument("output",type=Path);p.add_argument("report",type=Path);a=p.parse_args()
    print(json.dumps(apply(a.manifest,a.output,a.report),ensure_ascii=False))
