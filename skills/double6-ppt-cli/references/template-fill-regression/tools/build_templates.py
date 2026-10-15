"""Build the evaluation template corpus (T1..T5). Outputs templates/*.pptx + SOURCES.json."""
import json, shutil, subprocess, zipfile, hashlib, copy
from pathlib import Path
from pptx import Presentation
from pptx.util import Emu, Pt, Inches
from pptx.dml.color import RGBColor
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import MSO_AUTO_SIZE, PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from PIL import Image, ImageDraw
from lxml import etree

ROOT = Path(__file__).resolve().parents[1] / "templates"
SRC = ROOT / "src"
ROOT.mkdir(exist_ok=True)
sources = {}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def make_png(path, w, h, c1, c2, label):
    im = Image.new("RGB", (w, h), c1); d = ImageDraw.Draw(im)
    for i in range(0, w, 40): d.line([(i, 0), (i - h, h)], fill=c2, width=14)
    d.rectangle([w*0.1, h*0.35, w*0.9, h*0.65], fill=(255, 255, 255)); d.text((w*0.12, h*0.45), label, fill=c1)
    im.save(path)

def set_font(run, latin, ea=None, size=None, bold=None, color=None):
    f = run.font
    if latin: f.name = latin
    if size: f.size = Pt(size)
    if bold is not None: f.bold = bold
    if color: f.color.rgb = RGBColor.from_string(color)
    if ea:
        rPr = run._r.get_or_add_rPr()
        e = rPr.find(qn("a:ea"))
        if e is None: e = etree.SubElement(rPr, qn("a:ea"))
        e.set("typeface", ea)

def add_text(slide, name, x, y, w, h, paras, latin="Arial", ea=None, size=18, color="333333", bold=False,
             autosize=None, levels=None, bullet=False, align=None, anchor="t"):
    tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h)); tb.name = name
    tf = tb.text_frame; tf.word_wrap = True
    bp = tf._txBody.find(qn("a:bodyPr")); bp.set("anchor", anchor)
    for child in list(bp):
        if child.tag in (qn("a:spAutoFit"), qn("a:normAutofit"), qn("a:noAutofit")): bp.remove(child)
    if autosize == "norm": etree.SubElement(bp, qn("a:normAutofit"))
    elif autosize == "shape": tf.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
    for i, t in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        lvl = (levels or [0]*len(paras))[i]; p.level = lvl
        if align: p.alignment = align
        if bullet:
            pPr = p._p.get_or_add_pPr(); pPr.set("marL", str(285750 + lvl*342900)); pPr.set("indent", "-285750")
            bu = etree.SubElement(pPr, qn("a:buChar")); bu.set("char", "•")
        r = p.add_run(); r.text = t
        set_font(r, latin, ea, size - 2*lvl, bold, color)
    return tb

def rect(slide, name, x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE, text=None, **kw):
    s = slide.shapes.add_shape(shape, Emu(x), Emu(y), Emu(w), Emu(h)); s.name = name
    s.fill.solid(); s.fill.fore_color.rgb = RGBColor.from_string(fill); s.line.fill.background()
    if text is not None:
        tf = s.text_frame; tf.word_wrap = True; p = tf.paragraphs[0]; r = p.add_run(); r.text = text
        p.alignment = kw.get("align", PP_ALIGN.CENTER)
        set_font(r, kw.get("latin", "Arial"), kw.get("ea"), kw.get("size", 14), kw.get("bold", False), kw.get("color", "FFFFFF"))
    return s

def widen_layouts(prs, new_w):
    """Scale master/layout placeholder x-geometry from 4:3 to 16:9 (realistic widescreen master)."""
    old_w = prs.slide_width; k = new_w / old_w
    prs.slide_width = new_w
    for m in prs.slide_masters:
        for coll in [m.shapes] + [l.shapes for l in m.slide_layouts]:
            for s in coll:
                if s._element.find(qn("p:spPr")) is not None and s._element.find(qn("p:spPr")).find(qn("a:xfrm")) is not None:
                    s.left = int(s.left * k); s.width = int(s.width * k)

def master_rect(prs, name, x, y, w, h, color):
    tmp = prs.slides.add_slide(prs.slide_layouts[6])
    sh = tmp.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h); sh.name = name
    sh.fill.solid(); sh.fill.fore_color.rgb = RGBColor.from_string(color); sh.line.fill.background()
    el = sh._element; m = prs.slide_masters[0]
    m.shapes._spTree.insert(2, el)  # behind placeholders
    # drop temp slide
    sldIdLst = prs.slides._sldIdLst; rId = sldIdLst[-1].rId; prs.part.drop_rel(rId); sldIdLst.remove(sldIdLst[-1])

def set_geom(shape, x, y, w, h):
    shape.left, shape.top, shape.width, shape.height = Emu(x), Emu(y), Emu(w), Emu(h)

def hyperlink_to(shape, target_slide):
    shape.click_action.target_slide = target_slide

# ---------------- T3: zh corporate with nav tabs, table, chart, image ----------------
def build_t3():
    prs = Presentation(); widen_layouts(prs, Inches(13.333)); prs.slide_height = Inches(7.5)
    W, H = prs.slide_width, prs.slide_height
    # master branding: footer bar + logo text on master (layout inheritance)
    m = prs.slide_masters[0]
    master_rect(prs, "Master Footer Bar", 0, H - Emu(380000), W, Emu(380000), "0B3D6E")
    for ph in m.placeholders:
        for p in ph.text_frame.paragraphs:
            for r in p.runs: set_font(r, "Arial", "Microsoft YaHei")
    lay_title = prs.slide_layouts[0]; lay_tonly = prs.slide_layouts[5]; lay_blank = prs.slide_layouts[6]
    YA = dict(latin="Arial", ea="Microsoft YaHei")
    img = SRC / "t3_photo.png"; make_png(img, 1200, 800, (11, 61, 110), (40, 110, 170), "SAMPLE PHOTO")
    tabs = ["项目背景", "解决方案", "经营数据", "实施计划"]
    slides = {}
    # 1 cover (title layout placeholders, inherits)
    s = prs.slides.add_slide(lay_title); slides[1] = s
    s.shapes.title.text = "在此输入演示文稿主标题"; s.shapes.title.name = "封面标题"
    s.placeholders[1].text = "副标题：一句话说明汇报主题与受众"; s.placeholders[1].name = "封面副标题"
    add_text(s, "汇报人信息", 800000, H - 1300000, 6000000, 500000, ["汇报人：姓名 ｜ 部门 ｜ 2026年10月"], size=16, color="FFFFFF", **YA)
    blk = rect(s, "封面色块", 0, H - 1500000, W, 1120000, "0B3D6E"); s.shapes._spTree.remove(blk._element); s.shapes._spTree.insert(2, blk._element)
    # 2 agenda: multi-paragraph list
    s = prs.slides.add_slide(lay_tonly); slides[2] = s
    s.shapes.title.text = "目录"; s.shapes.title.name = "目录标题"
    add_text(s, "目录列表", 1200000, 1700000, 7000000, 4000000,
             ["01  项目背景与目标", "02  整体解决方案", "03  经营数据回顾", "04  下一步实施计划"], size=24, color="0B3D6E", **YA)
    pics = s.shapes.add_picture(str(img), W - Emu(4300000), Emu(1700000), Emu(3600000), Emu(2400000)); pics.name = "目录配图"
    # content slides with nav tabs
    def nav(s, active):
        x0 = 600000
        shapes = []
        for i, t in enumerate(tabs):
            on = i == active
            sh = rect(s, f"导航-{t}", x0 + i * 1900000, 250000, 1800000, 420000, "0B3D6E" if on else "D9E2EC",
                      shape=MSO_SHAPE.ROUNDED_RECTANGLE, text=t, size=14, bold=on, color="FFFFFF" if on else "0B3D6E", **YA)
            shapes.append(sh)
        return shapes
    navs = {}
    # 3 背景: title + multi-level bullets + image
    s = prs.slides.add_slide(lay_tonly); slides[3] = s; navs[3] = nav(s, 0)
    s.shapes.title.text = "页面标题：一句话概括本页核心观点"; s.shapes.title.name = "正文标题"
    set_geom(s.shapes.title, 600000, 800000, W - 1200000, 900000)
    add_text(s, "正文要点", 600000, 1900000, 6600000, 4300000,
             ["要点一：在此填写关键背景信息", "补充说明文字，控制在两行以内", "要点二：在此填写业务痛点", "补充说明文字",
              "要点三：在此填写项目目标"], levels=[0, 1, 0, 1, 0], bullet=True, size=20, color="333333", autosize="norm", **YA)
    p = s.shapes.add_picture(str(img), Emu(7600000), Emu(1900000), Emu(4200000), Emu(2800000)); p.name = "背景配图"
    add_text(s, "图片说明", 7600000, 4800000, 4200000, 400000, ["图：示意图片说明"], size=12, color="888888", **YA)
    # 4 方案: three columns cards
    s = prs.slides.add_slide(lay_tonly); slides[4] = s; navs[4] = nav(s, 1)
    s.shapes.title.text = "解决方案总览"; s.shapes.title.name = "正文标题"; set_geom(s.shapes.title, 600000, 800000, W - 1200000, 900000)
    for i in range(3):
        x = 600000 + i * 4050000
        rect(s, f"卡片底{i+1}", x, 1950000, 3800000, 3900000, "F2F5F9")
        rect(s, f"卡片序号{i+1}", x + 200000, 2100000, 600000, 600000, "0B3D6E", shape=MSO_SHAPE.OVAL, text=f"0{i+1}", size=16, bold=True, **YA)
        add_text(s, f"卡片标题{i+1}", x + 200000, 2850000, 3400000, 500000, [f"能力模块{i+1}"], size=20, bold=True, color="0B3D6E", **YA)
        add_text(s, f"卡片正文{i+1}", x + 200000, 3400000, 3400000, 2300000, ["在此描述该模块的核心能力。", "第二段补充说明。"], size=16, color="555555", **YA)
    # 5 数据: table + chart
    s = prs.slides.add_slide(lay_tonly); slides[5] = s; navs[5] = nav(s, 2)
    s.shapes.title.text = "经营数据回顾"; s.shapes.title.name = "正文标题"; set_geom(s.shapes.title, 600000, 800000, W - 1200000, 900000)
    rows = [["指标", "2024", "2025", "同比"], ["营业收入（亿元）", "0.0", "0.0", "0%"], ["毛利率", "0%", "0%", "0pt"], ["客户数", "0", "0", "0%"]]
    gf = s.shapes.add_table(4, 4, Emu(600000), Emu(1950000), Emu(5800000), Emu(2400000)); gf.name = "数据表格"
    for r, row in enumerate(rows):
        for c, v in enumerate(row):
            cell = gf.table.cell(r, c); cell.text = v
            for pr in cell.text_frame.paragraphs:
                for rr in pr.runs: set_font(rr, "Arial", "Microsoft YaHei", 14, r == 0)
    cd = CategoryChartData(); cd.categories = ["Q1", "Q2", "Q3", "Q4"]; cd.add_series("收入", (1, 2, 3, 4)); cd.add_series("利润", (0.5, 1, 1.5, 2))
    ch = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Emu(6800000), Emu(1950000), Emu(5800000), Emu(3600000), cd); ch.name = "季度图表"
    ch.chart.has_legend = True; ch.chart.legend.position = XL_LEGEND_POSITION.BOTTOM; ch.chart.legend.include_in_layout = False
    add_text(s, "数据结论", 600000, 4600000, 5800000, 1200000, ["结论：在此填写数据解读。"], size=16, color="333333", **YA)
    # 6 计划: timeline
    s = prs.slides.add_slide(lay_tonly); slides[6] = s; navs[6] = nav(s, 3)
    s.shapes.title.text = "下一步实施计划"; s.shapes.title.name = "正文标题"; set_geom(s.shapes.title, 600000, 800000, W - 1200000, 900000)
    rect(s, "时间轴线", 600000, 3300000, W - 1200000, 60000, "0B3D6E")
    for i in range(4):
        x = 900000 + i * 3000000
        rect(s, f"节点{i+1}", x, 3180000, 300000, 300000, "F5A623", shape=MSO_SHAPE.OVAL)
        add_text(s, f"节点标题{i+1}", x - 300000, 2400000, 2600000, 600000, [f"阶段{i+1}：名称"], size=18, bold=True, color="0B3D6E", **YA)
        add_text(s, f"节点说明{i+1}", x - 300000, 3700000, 2600000, 1500000, ["关键任务说明", "交付物"], size=14, color="555555", **YA)
    # 7 closing
    s = prs.slides.add_slide(lay_blank); slides[7] = s
    rect(s, "结束底色", 0, 0, W, H, "0B3D6E")
    add_text(s, "结束语", 0, 2700000, W, 1200000, ["谢谢！"], size=48, bold=True, color="FFFFFF", align=PP_ALIGN.CENTER, **YA)
    add_text(s, "联系方式", 0, 4000000, W, 600000, ["联系人：姓名 ｜ 邮箱：name@example.com"], size=16, color="D9E2EC", align=PP_ALIGN.CENTER, **YA)
    # nav hyperlinks: tab i -> section slide
    target = {0: slides[3], 1: slides[4], 2: slides[5], 3: slides[6]}
    for sl, shapes in navs.items():
        for i, sh in enumerate(shapes): hyperlink_to(sh, target[i])
    out = ROOT / "T3-zh-corp-nav.pptx"; prs.save(out)
    sources["T3-zh-corp-nav.pptx"] = {"origin": "built with python-pptx (tools/build_templates.py) on python-pptx default master widened to 16:9", "license": "CC0-1.0 (authored for this eval); python-pptx default template MIT", "features": ["layout placeholders (title/subtitle inherited)", "master footer bar", "nav tabs with slide-jump hyperlinks + active state", "multi-level bullets w/ normAutofit", "pictures", "native table", "native chart", "CJK (Microsoft YaHei, absent -> fallback)"]}

# ---------------- T4: en QBR ----------------
def build_t4():
    prs = Presentation(); widen_layouts(prs, Inches(13.333)); prs.slide_height = Inches(7.5)
    W, H = prs.slide_width, prs.slide_height
    m = prs.slide_masters[0]
    master_rect(prs, "Master Accent", 0, 0, Emu(160000), H, "E4572E")
    for ph in m.placeholders:
        for p in ph.text_frame.paragraphs:
            for r in p.runs: set_font(r, "Calibri")
    C = dict(latin="Calibri")
    img = SRC / "t4_photo.png"; make_png(img, 1600, 900, (30, 41, 59), (228, 87, 46), "PRODUCT IMAGE")
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Quarterly Business Review"; s.shapes.title.name = "Title 1"
    s.placeholders[1].text = "Q3 FY2026 · Regional Sales Organization"; s.placeholders[1].name = "Subtitle 2"
    # 2 exec summary: layout body placeholder, multi-level bullets (inherited formatting)
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Executive summary"; s.shapes.title.name = "Title 1"
    body = s.placeholders[1]; body.name = "Content Placeholder 2"
    tf = body.text_frame
    items = [("Revenue headline goes here", 0), ("Supporting detail for the headline", 1), ("Second key message", 0),
             ("Supporting detail", 1), ("Third key message", 0)]
    for i, (t, l) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph(); p.text = t; p.level = l
    # 3 KPI cards
    s = prs.slides.add_slide(prs.slide_layouts[5]); s.shapes.title.text = "Key metrics at a glance"; s.shapes.title.name = "Title 1"
    for i in range(4):
        x = 700000 + i * 3000000
        rect(s, f"KPI Card {i+1}", x, 1900000, 2700000, 2600000, "F1F5F9")
        add_text(s, f"KPI Value {i+1}", x + 150000, 2100000, 2400000, 900000, ["$0.0M"], size=40, bold=True, color="E4572E", **C)
        add_text(s, f"KPI Label {i+1}", x + 150000, 3050000, 2400000, 1300000, ["Metric label", "vs. prior quarter"], size=16, color="475569", **C)
    # 4 chart + commentary
    s = prs.slides.add_slide(prs.slide_layouts[5]); s.shapes.title.text = "Revenue trend by region"; s.shapes.title.name = "Title 1"
    cd = CategoryChartData(); cd.categories = ["Q4 FY25", "Q1 FY26", "Q2 FY26", "Q3 FY26"]
    cd.add_series("North", (10, 11, 12, 13)); cd.add_series("South", (8, 9, 9, 10)); cd.add_series("West", (6, 7, 8, 9))
    ch = s.shapes.add_chart(XL_CHART_TYPE.LINE_MARKERS, Emu(600000), Emu(1700000), Emu(7400000), Emu(4600000), cd); ch.name = "Revenue Chart"
    ch.chart.has_legend = True; ch.chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    add_text(s, "Chart Commentary", 8300000, 1700000, 3900000, 4600000,
             ["What happened", "Commentary sentence one.", "Why it matters", "Commentary sentence two."], levels=[0, 1, 0, 1], bullet=True, size=18, color="1E293B", autosize="norm", **C)
    # 5 table
    s = prs.slides.add_slide(prs.slide_layouts[5]); s.shapes.title.text = "Pipeline by stage"; s.shapes.title.name = "Title 1"
    rows = [["Stage", "Deals", "Value", "Win rate", "Owner"]] + [[f"Stage {i}", "0", "$0", "0%", "Name"] for i in range(1, 5)]
    gf = s.shapes.add_table(5, 5, Emu(700000), Emu(1800000), Emu(11400000), Emu(3500000)); gf.name = "Pipeline Table"
    for r, row in enumerate(rows):
        for c, v in enumerate(row): gf.table.cell(r, c).text = v
    # 6 image + caption + section-like tabs (English nav)
    s = prs.slides.add_slide(prs.slide_layouts[5]); s.shapes.title.text = "Product spotlight"; s.shapes.title.name = "Title 1"
    p = s.shapes.add_picture(str(img), Emu(700000), Emu(1700000), Emu(6400000), Emu(3600000)); p.name = "Spotlight Image"
    add_text(s, "Spotlight Body", 7500000, 1700000, 4700000, 3600000,
             ["Product name", "Short description of the product and why customers buy it.", "Proof point or customer quote."], size=18, color="1E293B", **C)
    # 7 closing
    s = prs.slides.add_slide(prs.slide_layouts[0]); s.shapes.title.text = "Thank you"; s.shapes.title.name = "Title 1"
    s.placeholders[1].text = "Questions & discussion"; s.placeholders[1].name = "Subtitle 2"
    out = ROOT / "T4-en-qbr.pptx"; prs.save(out)
    sources["T4-en-qbr.pptx"] = {"origin": "built with python-pptx (tools/build_templates.py)", "license": "CC0-1.0 (authored for this eval); python-pptx default template MIT", "features": ["body placeholder with inherited list levels (no local rPr)", "KPI cards", "line chart", "5x5 table", "picture", "Calibri (Carlito metric-compatible)"]}

# ---------------- T1: Velis (CC0, real PowerPoint-authored master) ----------------
def potx_to_pptx(src, dst):
    with zipfile.ZipFile(src) as zi, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            data = zi.read(it.filename)
            if it.filename == "[Content_Types].xml":
                data = data.replace(b"application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
                                    b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml")
            zo.writestr(it, data)

def fill_layout_slide(prs, layout_name, texts):
    lay = next(l for l in prs.slide_layouts if l.name == layout_name)
    s = prs.slides.add_slide(lay)
    if isinstance(texts, dict):
        byidx = {p.placeholder_format.idx: p for p in s.placeholders}
        pairs = [(byidx[k], v) for k, v in texts.items()]
    else:
        pairs = list(zip(sorted(s.placeholders, key=lambda p: p.placeholder_format.idx), texts))
    for ph, t in pairs:
        if t is None: continue
        if isinstance(t, list):
            tf = ph.text_frame
            for i, (txt, lvl) in enumerate(t):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph(); p.text = txt; p.level = lvl
        else:
            ph.text = t
    return s

def build_t1():
    tmp = SRC / "velis.pptx"; potx_to_pptx(SRC / "velis.potx", tmp)
    prs = Presentation(tmp)
    names = [l.name for l in prs.slide_layouts]
    print("velis layouts:", names)
    json.dump(names, open(SRC / "velis_layouts.json", "w"))
    plan = []
    def find(*cands):
        for c in cands:
            for n in names:
                if c.lower() in n.lower(): return n
        return names[0]
    fill_layout_slide(prs, find("Presentation Title"), ["Presentation title", "Subtitle · Author · Venue"])
    fill_layout_slide(prs, find("Title and Content"), {0: "Slide title", 13: "Optional one-line lead-in", 17: [("First point with some explanation", 0), ("Sub point", 1), ("Second point", 0), ("Sub point", 1), ("Third point", 0)]})
    fill_layout_slide(prs, find("Two Columns"), {0: "Comparison title", 13: "Two options compared side by side", 1: [("Left column point", 0), ("Left detail", 1)], 17: [("Right column point", 0), ("Right detail", 1)]})
    fill_layout_slide(prs, find("Section Title"), {0: "Section heading", 14: "Section subtitle", 15: [("Section description", 0)]})
    fill_layout_slide(prs, find("Title and Content"), {0: "Another content slide", 13: "Lead-in", 17: [("Point A", 0), ("Point B", 0), ("Point C", 0)]})
    fill_layout_slide(prs, find("Close"), {0: "Thank you", 11: "Speaker Name", 12: "contact@example.org"})
    out = ROOT / "T1-en-velis.pptx"; prs.save(out)
    sources["T1-en-velis.pptx"] = {"origin": "https://github.com/lrkrol/powerpoint/raw/master/lrk-slides-velis.potx (Laurens R. Krol), potx->pptx content-type switch; sample slides added from its layouts via python-pptx", "license": "CC0-1.0 (stated in repo README)", "source_sha256": sha(SRC / "velis.potx"), "features": ["real PowerPoint-authored masters/layouts (2 masters)", "all text in inherited placeholders", "multi-level bullets"]}

# ---------------- T2: LibreOffice Focus (MPL-2.0) converted ----------------
def build_t2():
    otp = Path("/usr/lib/libreoffice/share/template/common/presnt/Grey_Elegant.otp")
    out_dir = SRC / "lo"; out_dir.mkdir(exist_ok=True)
    shutil.copy(otp, out_dir / "Grey_Elegant.odp")
    subprocess.run(["soffice", "--headless", "--convert-to", "pptx", "--outdir", str(out_dir), str(out_dir / "Grey_Elegant.odp")], check=True, capture_output=True, timeout=180)
    prs = Presentation(out_dir / "Grey_Elegant.pptx")
    sample = {
        0: ["年度工作汇报模板", "部门名称 ｜ 汇报人 ｜ 日期"],
        1: ["目录", "第一部分  年度回顾\n第二部分  重点项目\n第三部分  问题与改进\n第四部分  明年计划"],
        2: ["年度回顾", "在此输入本部分的概要说明。\n第二段：补充关键背景。"],
        3: ["重点项目一", "要点一", "要点二", "要点三"],
        4: ["组织与团队", "说明一", "说明二", "说明三", "说明四", "说明五", "说明六"],
        5: ["四大举措", "举措一说明", "举措二说明", "举措三说明", "举措四说明"],
        6: ["协同关系", "在此描述各模块之间的协同关系。"],
        7: ["问题与改进", "问题一", "问题二", "问题三"],
        8: ["图片页", "图片说明文字"],
    }
    for i, sl in enumerate(prs.slides):
        phs = [sh for sh in sl.shapes if sh.is_placeholder and sh.placeholder_format.type not in (13, 15, 16)]
        for ph, t in zip(phs, sample.get(i, [])):
            if not ph.has_text_frame: continue
            tf = ph.text_frame
            for j, line in enumerate(t.split("\n")):
                para = tf.paragraphs[0] if j == 0 else tf.add_paragraph(); para.text = line
    sl = prs.slides[2]
    gf = sl.shapes.add_table(3, 3, Emu(prs.slide_width // 2), Emu(int(prs.slide_height * 0.55)), Emu(prs.slide_width // 2 - 500000), Emu(1100000)); gf.name = "风险表"
    for r, row in enumerate([["事项", "影响", "负责人"], ["示例事项", "高", "姓名"], ["示例事项", "中", "姓名"]]):
        for c, v in enumerate(row): gf.table.cell(r, c).text = v
    out = ROOT / "T2-zh-lo-grey.pptx"; prs.save(out)
    sources["T2-zh-lo-grey.pptx"] = {"origin": "LibreOffice bundled Impress template Grey_Elegant.otp (/usr/lib/libreoffice/share/template/common/presnt), converted to PPTX by soffice 24.x; Chinese sample text written into its own placeholders via python-pptx; one table added", "license": "MPL-2.0 (LibreOffice core extras/source/templates)", "source_sha256": sha(otp), "features": ["LO-exported master/layout XML (non-PowerPoint dialect)", "9 layouts with placeholders", "decorative LO shapes (numbered circles)", "CJK in placeholders", "multi-paragraph placeholder", "table"]}

def build_t5():
    src = Path("/workspace/ppt-test/cases/c3/template.pptx"); out = ROOT / "T5-en-case3-tech.pptx"; shutil.copy(src, out)
    sources["T5-en-case3-tech.pptx"] = {"origin": "existing double6 eval case3 template (/workspace/ppt-test/cases/c3/template.pptx), python-pptx built", "license": "CC0-1.0 (authored in-house for eval)", "source_sha256": sha(src), "features": ["multi-paragraph columns", "agenda list", "free-floating text boxes"]}

def sanitize_chart_ids(path):
    """python-pptx can emit negative c:axId/c:crossAx values (invalid UInt32); make them positive."""
    import re
    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(path) as zi, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zi.infolist():
            data = zi.read(it.filename)
            if it.filename.startswith("ppt/charts/") and it.filename.endswith(".xml"):
                data = re.sub(rb'(<c:(?:axId|crossAx) val=")-(\d+)', rb"\1\2", data)
            zo.writestr(it, data)
    tmp.replace(path)

if __name__ == "__main__":
    build_t1(); build_t2(); build_t3(); build_t4(); build_t5()
    for f in ROOT.glob("T*.pptx"): sanitize_chart_ids(f)
    for k, v in sources.items(): v["sha256"] = sha(ROOT / k)
    json.dump(sources, open(ROOT / "SOURCES.json", "w"), ensure_ascii=False, indent=2)
    print(json.dumps(sources, ensure_ascii=False, indent=1))
