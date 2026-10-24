"""虚构的正常办公和攻击样例。只在测试里生成，不提交 PDF。"""
import pymupdf as fitz

SECRET = "13800006661"
KEEP = "整理活动反馈"
SIDE = "DELETEME"

def office_samples():
    samples = []

    def add(name, cohort, doc, box, note):
        raw = doc.tobytes()
        doc.close()
        samples.append({
            "name": name,
            "group": "office" if cohort == "normal" else "attack",
            "cohort_hint": cohort,
            "params": {"note": note},
            "raw": raw,
            "box": box,
            "keep": KEEP,
            "run_export": True,
        })

    def base():
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
        page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
        page.insert_text((20, 180), SECRET, fontname="helv", fontsize=14)
        return doc, page

    def side(page):
        rect = page.search_for(SIDE)[0]
        return [(rect.x0 - 1) * 2, (rect.y0 - 1) * 2, (rect.x1 + 1) * 2, (rect.y1 + 1) * 2]

    doc, page = base()
    page.add_highlight_annot(page.search_for(KEEP)[0]).update()
    add("正常-黄色高亮在保留句", "normal", doc, side(page), "高亮不压号码")

    doc, page = base()
    page.add_highlight_annot(page.search_for(SECRET)[0]).update()
    add("正常-黄色高亮压在号码上", "normal", doc, side(page), "半透明高亮，号码仍可读")

    doc, page = base()
    page.add_underline_annot(page.search_for(KEEP)[0]).update()
    add("正常-下划线", "normal", doc, side(page), "下划线在保留句")

    doc, page = base()
    page.add_strikeout_annot(page.search_for("旧句") if False else page.search_for(SIDE)[0]).update()
    add("正常-删除线在被选词上", "normal", doc, side(page), "删除线画在选区上")

    doc, page = base()
    page.add_squiggly_annot(page.search_for(KEEP)[0]).update()
    add("正常-波浪线", "normal", doc, side(page), "波浪线在保留句")

    doc, page = base()
    note = page.add_text_annot(fitz.Point(330, 48), "请再核对活动名称")
    note.update()
    add("正常-页边便签", "normal", doc, side(page), "便签不压号码")

    doc, page = base()
    page.add_stamp_annot(fitz.Rect(250, 30, 370, 110), stamp=0).update()
    add("正常-空白处审批图章", "normal", doc, side(page), "图章不压号码")

    doc, page = base()
    found = page.search_for(SECRET)[0]
    page.add_stamp_annot(fitz.Rect(found.x0 - 4, found.y0 - 6, found.x1 + 8, found.y1 + 8), stamp=0).update()
    add("正常-图章压住号码", "attack", doc, side(page), "看这个图章有没有真的把字涂平")

    doc, page = base()
    ink = page.add_ink_annot([[(300, 200), (340, 230), (360, 190), (380, 240)]])
    ink.set_border(width=1.4)
    ink.update()
    add("正常-页边手写签名", "normal", doc, side(page), "墨迹不压号码")

    doc, page = base()
    found = page.search_for(KEEP)[0]
    circle = page.add_circle_annot(fitz.Rect(found.x0 - 4, found.y0 - 4, found.x1 + 6, found.y1 + 4))
    circle.set_colors(stroke=(0.8, 0.1, 0.1))
    circle.set_border(width=1.2)
    circle.update()
    add("正常-红圈圈注", "normal", doc, side(page), "只描边，字仍可读")

    doc, page = base()
    found = page.search_for(SECRET)[0]
    box = fitz.Rect(found.x0 - 3, found.y0 - 3, found.x1 + 3, found.y1 + 3)
    annot = page.add_rect_annot(box)
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_border(width=0)
    annot.update()
    add("正常-用户黑框盖住号码", "reveal", doc, side(page), "用户自己画的不透明黑框")

    doc, page = base()
    page.add_highlight_annot(page.search_for(KEEP)[0]).update()
    page.add_underline_annot(page.search_for(SIDE)[0]).update()
    page.add_text_annot(fitz.Point(320, 50), "已阅").update()
    add("正常-高亮下划线便签同时在", "normal", doc, side(page), "普通办公组合")

    # 老漏洞
    for opacity in (0.25, 0.45, 0.7, 0.85, 0.95, 0.99):
        doc, page = base()
        found = page.search_for(SECRET)[0]
        annot = page.add_rect_annot(fitz.Rect(found.x0 - 4, found.y0 - 4, found.x1 + 4, found.y1 + 4))
        annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
        annot.set_opacity(opacity)
        annot.set_border(width=0)
        annot.update()
        add(f"攻击-黑方块透明度{opacity}", "attack", doc, side(page), "测半透明还读不读得出来")

    for level in (0.9, 0.96, 0.985, 0.99):
        doc = fitz.open()
        page = doc.new_page(width=400, height=300)
        page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
        page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
        page.insert_text((20, 180), SECRET, fontname="helv", fontsize=14, color=(level, level, level))
        found = page.search_for(SECRET)
        rect = found[0] if found else fitz.Rect(18, 164, 200, 186)
        annot = page.add_rect_annot(fitz.Rect(rect.x0 - 3, rect.y0 - 3, rect.x1 + 3, rect.y1 + 3))
        annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
        annot.set_border(width=0)
        annot.update()
        other = page.search_for(SIDE)[0]
        box = [(other.x0 - 1) * 2, (other.y0 - 1) * 2, (other.x1 + 1) * 2, (other.y1 + 1) * 2]
        raw = doc.tobytes()
        doc.close()
        samples.append({
            "name": f"攻击-黑方块盖住灰度{level}的号码",
            "group": "attack",
            "cohort_hint": "reveal",
            "params": {"gray": level},
            "raw": raw,
            "box": box,
            "keep": KEEP,
            "run_export": True,
        })

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 210), SECRET, fontname="helv", fontsize=1)
    tiny = page.search_for(SECRET)
    rect = tiny[-1] if tiny else fitz.Rect(18, 204, 90, 214)
    annot = page.add_rect_annot(fitz.Rect(rect.x0 - 2, rect.y0 - 2, rect.x1 + 12, rect.y1 + 3))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_border(width=0)
    annot.update()
    add("攻击-黑方块盖住1点号码", "reveal", doc, side(page), "贴边小字")

    doc, page = base()
    found = page.search_for(SECRET)[0]
    # 矢量描出来的数字，没有文字层
    shape = page.new_shape()
    x = found.x0
    for _ in SECRET:
        shape.draw_line(fitz.Point(x, found.y0 + 28), fitz.Point(x + 4, found.y0 + 40))
        shape.draw_line(fitz.Point(x + 4, found.y0 + 40), fitz.Point(x + 8, found.y0 + 28))
        x += 10
    shape.finish(color=(0, 0, 0), width=1.2)
    shape.commit()
    cover = fitz.Rect(found.x0 - 2, found.y0 + 24, found.x1 + 2, found.y0 + 44)
    annot = page.add_rect_annot(cover)
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_border(width=0)
    annot.update()
    add("攻击-黑方块盖住矢量笔画", "reveal", doc, side(page), "没有文字层")

    doc, page = base()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 90, 16), 0)
    pix.set_rect(pix.irect, (255, 255, 255))
    pix.set_rect(fitz.IRect(4, 4, 86, 12), (0, 0, 0))
    page.insert_image(fitz.Rect(20, 220, 130, 244), pixmap=pix)
    annot = page.add_rect_annot(fitz.Rect(16, 214, 136, 250))
    annot.set_colors(stroke=(0, 0, 0), fill=(0, 0, 0))
    annot.set_border(width=0)
    annot.update()
    add("攻击-黑方块盖住图片", "reveal", doc, side(page), "图片没有文字层")

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), SECRET, fontname="helv", fontsize=14, render_mode=3)
    add("攻击-只有不可见文字层", "attack", doc, side(page), "文字层有号码，画面上没有")

    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((20, 40), KEEP, fontname="china-s", fontsize=14)
    page.insert_text((20, 90), SIDE, fontname="helv", fontsize=14)
    page.insert_text((20, 180), SECRET, fontname="helv", fontsize=14, render_mode=3)
    found = page.search_for(SECRET)
    rect = found[0] if found else fitz.Rect(18, 164, 160, 186)
    annot = page.add_rect_annot(fitz.Rect(rect.x0 - 2, rect.y0 - 2, rect.x1 + 2, rect.y1 + 2))
    annot.set_colors(stroke=(1, 1, 1), fill=(1, 1, 1))
    annot.set_border(width=0)
    annot.update()
    add("攻击-白方块盖住不可见文字层", "attack", doc, side(page), "文字层和渲染不一致")

    doc, page = base()
    found = page.search_for(SECRET)[0]
    annot = page.add_rect_annot(fitz.Rect(found.x0 - 3, found.y0 - 3, found.x1 + 3, found.y1 + 3))
    annot.set_colors(stroke=(1, 1, 1), fill=(0.45, 0.45, 0.45))
    annot.set_border(width=6)
    annot.update()
    raw = doc.tobytes()
    doc.close()
    forged = fitz.open(stream=raw, filetype="pdf")
    forged.xref_set_key(forged[0].first_annot.xref, "Subtype", "/Highlight")
    raw = forged.tobytes()
    forged.close()
    other_box = side_from_raw(raw)
    samples.append({
        "name": "攻击-灰底白边伪造高亮",
        "group": "attack",
        "cohort_hint": "reveal",
        "params": {"subtype": "/Highlight", "gray": 0.45, "border": 6},
        "raw": raw,
        "box": other_box,
        "keep": KEEP,
        "run_export": True,
    })
    return samples



def side_from_raw(raw):
    with fitz.open(stream=raw, filetype="pdf") as doc:
        rect = doc[0].search_for(SIDE)[0]
    return [(rect.x0 - 1) * 2, (rect.y0 - 1) * 2, (rect.x1 + 1) * 2, (rect.y1 + 1) * 2]

