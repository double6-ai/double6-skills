"""PDF原生删改：保留未选区域的文字和页面；使用外部AGPL-3.0 PyMuPDF引擎。"""
import io
import math
from collections import Counter

from PIL import Image, ImageChops
import engine


def backend():
    try:
        import pymupdf as fitz
    except ImportError as exc:
        raise engine.Rejected('缺少PDF原生处理依赖，请重新执行安装和验收。') from exc
    fitz.TOOLS.set_small_glyph_heights(True)
    fitz.TOOLS.mupdf_display_errors(False)
    fitz.TOOLS.mupdf_display_warnings(False)
    return fitz


def open_pdf(data, inspect_image_visibility=True):
    fitz = backend()
    try:
        doc = fitz.open(stream=data, filetype='pdf')
        if doc.is_encrypted or doc.needs_pass or doc.is_repaired:
            raise engine.Rejected('加密或需要修复的PDF不进入原生脱敏。')
        if doc.get_ocgs():
            raise engine.Rejected('PDF含可选图层，无法确认全部隐藏内容；原生路线停止。')
        if any(page.rotation and page.cropbox != page.mediabox for page in doc):
            raise engine.Rejected('PDF同时含裁剪框和旋转，当前原生坐标尚未验证，已停止；不自动图像化。')
        if any(page.first_widget for page in doc):
            raise engine.Rejected('PDF含表单/签名域，原生路线暂不安全处理；请明确选择图像化副本或先处理表单。')
        if inspect_image_visibility:
            import pdf_visibility
            for page in doc:
                pdf_visibility.validate(page)
                images=page.get_image_info(xrefs=True)
                if not images:continue
                if any(not image.get('xref')or image.get('has-mask')for image in images):
                    raise engine.Rejected('PDF含行内图片或图片遮罩，隐藏像素尚不能安全清理，原生路线停止。')
                # 原图中被裁剪、透明或后来遮盖的像素不应随新容器交付。
                bounds=page.rect * page.derotation_matrix
                if any(not bounds.contains(fitz.Rect(image['bbox'])) for image in images):
                    raise engine.Rejected('PDF图片超出可见页面，可能保留隐藏像素，原生路线停止。')
                if any(row[1] for row in page.get_images(full=True)):
                    raise engine.Rejected('PDF图片含透明遮罩，隐藏像素尚不能安全清理，原生路线停止。')
                bboxlog=page.get_bboxlog()
                for seq,(kind,bbox)in enumerate(bboxlog):
                    if kind!='fill-image':continue
                    rect=fitz.Rect(bbox)
                    if any(other_kind in {'fill-path','stroke-path','fill-image','fill-text','stroke-text'} and fitz.Rect(other).intersects(rect)for other_kind,other in bboxlog[seq+1:]):
                        raise engine.Rejected('PDF图片被后绘制对象遮住，可能保留隐藏像素，原生路线停止。')
        return doc
    except engine.Rejected:
        raise
    except Exception as exc:
        raise engine.Rejected('PDF原生结构无法安全读取。') from exc


def areas(plan, sizes):
    import formats
    return formats.pdf_boxes(plan, sizes)


def word_rows(page, boxes):
    fitz = backend()
    result = []
    for span in page.get_texttrace():
        for char in span['chars']:
            rect=fitz.Rect(char[3])
            if chr(char[0]).strip()and not any(rect.intersects(box)for box in boxes):
                result.append((char[0],*(round(x,1)for x in char[3])))
    return Counter(result)


def export(data, plan, _verify=True):
    import formats
    import pdf_visibility
    fitz = backend()
    plan=effective_plan(data,plan)
    sizes = formats.pdf_info(data)
    selected = areas(plan, sizes)
    try:
        with open_pdf(data) as doc:
            pdf_visibility.check_object_carriers(doc,clean=True)
            for index, page in enumerate(doc):
                # 注释中的附件/原词不移入正文；已存在的待应用涂黑标记不能直接删除。
                annotations = list(page.annots() or [])
                if any(a.type[0] == fitz.PDF_ANNOT_REDACT for a in annotations):
                    raise engine.Rejected('PDF已有未应用的涂黑标记，请先在原软件完成或移除后再检查。')
                for annot in annotations:
                    page.delete_annot(annot)
                for link in page.get_links():
                    page.delete_link(link)
                boxes = [fitz.Rect(*(n / 2 for n in box)) * page.derotation_matrix for box in selected.get(index + 1, [])]
                # 对不可见/半透明文字停止，避免把隐藏层变成普通可搜索正文。
                visible_bounds=page.rect * page.derotation_matrix
                for span in page.get_texttrace():
                    if any(chr(char[0]).strip() and not visible_bounds.contains(fitz.Rect(char[3]))for char in span['chars']):
                        raise engine.Rejected('PDF文字超出可见页面或裁剪边界，存在隐藏原文，原生路线停止。')
                    if span.get('type') == 3 or span.get('opacity', 1) < .999 or span.get('size',1)<.5 or (isinstance(span.get('color'),tuple) and all(c>=.99 for c in span['color']) and not pdf_visibility.white_text_visible(page,span)):
                        raise engine.Rejected('PDF含不可见或半透明文字，原生路线无法保证隐藏层清理，已停止。')
                covers=[(seq,fitz.Rect(rect))for seq,(kind,rect)in enumerate(page.get_bboxlog())if kind in {'fill-path','stroke-path','fill-image'}]
                for span in page.get_texttrace():
                    for char in span['chars']:
                        if chr(char[0]).strip() and any(seq>span.get('seqno',-1) and rect.intersects(fitz.Rect(char[3])) for seq,rect in covers):
                            raise engine.Rejected('PDF文字被后绘制的图形/图片遮住，存在可恢复的隐藏内容；原生路线停止。')
                pdf_visibility.redaction_graphics(page,boxes)
                for box in boxes:
                    page.add_redact_annot(box, fill=(0, 0, 0), cross_out=False)
                if boxes:
                    page.apply_redactions(images=2, graphics=1, text=0)
            # 新建容器，不保存增量历史，不导入链接、注释、书签和文档级脚本。
            fresh = fitz.open()
            fresh.insert_pdf(doc, links=False, annots=False, widgets=False)
            fresh.set_metadata({})
            output = fresh.tobytes(garbage=4, clean=True, deflate=True, no_new_id=True)
            fresh.close()
        if _verify:verify(output, plan, data)
        return output
    except engine.Rejected:
        raise
    except Exception as exc:
        raise engine.Rejected('PDF原生删改或复检未完成，未退回图像化。') from exc


def verify(data, plan, source):
    import formats
    fitz = backend()
    if source is None:
        raise engine.Rejected('PDF复检需要原件，才能检查框外页面及文字。')
    plan=effective_plan(source,plan)
    sizes = formats.pdf_info(source)
    selected = areas(plan, sizes)
    expected=export(source,plan,_verify=False)
    if data != expected:
        raise engine.Rejected('PDF实际副本与本工具按同一原件和计划重新生成的结果不一致，未接受外部覆盖或额外载体。')
    checks = {'deterministic_pdf_matches_source_plan': True, 'pdf_not_rasterized': True, 'selected_text_removed': True,
              'outside_text_positions_preserved': True, 'outside_page_pixels_preserved': True,
              'selected_regions_solid': True, 'pdf_hidden_objects_absent': True}
    try:
        with open_pdf(source) as before, open_pdf(data, inspect_image_visibility=False) as after:
            if len(before) != len(after):
                raise engine.Rejected('PDF页数发生变化。')
            import pdf_visibility
            pdf_visibility.check_used_xobjects(data)
            pdf_visibility.check_object_carriers(after)
            if after.embfile_count() or after.get_toc() or any(after.metadata.get(k) for k in ('title','author','subject','keywords','creator','producer')) or after.get_xml_metadata():
                checks['pdf_hidden_objects_absent'] = False
            for index, (original, page) in enumerate(zip(before, after)):
                if original.rect != page.rect or original.rotation != page.rotation:
                    raise engine.Rejected('PDF页面尺寸或旋转发生变化。')
                pixel_boxes = selected.get(index + 1, [])
                boxes = [fitz.Rect(*(n / 2 for n in b)) * original.derotation_matrix for b in pixel_boxes]
                if word_rows(original, boxes) != word_rows(page, boxes):
                    checks['outside_text_positions_preserved'] = False
                for span in page.get_texttrace():
                    for char in span['chars']:
                        if chr(char[0]).strip() and any(fitz.Rect(char[3]).intersects(b) for b in boxes):
                            checks['selected_text_removed'] = False
                used_images={image['xref']for image in page.get_image_info(xrefs=True)}
                if any(row[0]not in used_images for row in page.get_images(full=True)):
                    checks['pdf_hidden_objects_absent'] = False
                if page.first_annot or page.first_widget or page.get_links():
                    checks['pdf_hidden_objects_absent'] = False
                old = formats.pdf_image(source, index)
                new = formats.pdf_image(data, index)
                delta = ImageChops.difference(old, new)
                for box in pixel_boxes:
                    # 仅容许边缘的两像素抗锯齿差异；切到字形时框外变化会明确失败。
                    x0,y0,x1,y1=box
                    delta.paste((0,0,0),(max(0,x0-2),max(0,y0-2),min(new.width,x1+2),min(new.height,y1+2)))
                    inner=(x0+2,y0+2,x1-2,y1-2)
                    if inner[0] >= inner[2] or inner[1] >= inner[3] or new.crop(inner).getbbox() is not None:
                        checks['selected_regions_solid'] = False
                if delta.getbbox() is not None:
                    checks['outside_page_pixels_preserved'] = False
            keep = engine.keep_checked(plan.get('keep', []))
            if keep:
                all_text = '\n'.join(p.get_text() for p in after)
                checks['keep_phrases_preserved'] = all(x in all_text for x in keep)
        if not all(checks.values()):
            raise engine.Rejected('PDF原生复检未通过：可能切到字形、影响框外内容或存在隐藏对象；请扩大框选或检查格式，不自动图像化。')
        return {'checks': checks, 'not_checked': [] if keep else ['keep_phrases_preserved'],
                'effective_pages':plan.get('pages',[]),'output_sha256': engine.digest(data), 'scope': 'PDF原生删改；保留框外可搜索文字、位置和页面。仅核对已选区域及支持的隐藏载体。'}
    except engine.Rejected:
        raise
    except Exception as exc:
        raise engine.Rejected('PDF实际副本原生复检失败。') from exc


def snap_region(data,number,region):
    """在预览中对齐完整字符；仅返回范围，不返回原文。"""
    import formats
    sizes=formats.pdf_info(data)
    if type(number)is not int or not 1<=number<=len(sizes):raise engine.Rejected('PDF页码无效。')
    target=list(engine.rectangles([region],sizes[number-1])[0]);fitz=backend()
    with fitz.open(stream=data,filetype='pdf')as doc:
        page=doc[number-1];glyphs=[]
        for span in page.get_texttrace():
            for char in span['chars']:
                if chr(char[0]).strip():
                    r=fitz.Rect(char[3])*page.rotation_matrix;glyphs.append(fitz.Rect(*(v*2 for v in r)))
        if len(glyphs)>200000:raise engine.Rejected('PDF字形超出对齐范围。')
        for _ in range(64):
            previous=target[:];rect=fitz.Rect(target)
            for glyph in glyphs:
                if glyph.intersects(rect):target=[min(target[0],math.floor(glyph.x0)),min(target[1],math.floor(glyph.y0)),max(target[2],math.ceil(glyph.x1)),max(target[3],math.ceil(glyph.y1))]
            if target==previous:return list(engine.rectangles([target],sizes[number-1])[0])
    raise engine.Rejected('整字范围无法稳定对齐，请在预览调整框选。')


def effective_plan(data,plan):
    if not isinstance(plan.get('snap_to_text',False),bool):raise engine.Rejected('整字对齐选项必须为布尔值。')
    if plan.get('snap_to_text')is not True or plan.get('pdf_mode','preserve')!='preserve':return plan
    import formats
    original=areas(plan,formats.pdf_info(data))
    return {**plan,'snap_to_text':False,'pages':[{'page':number,'rectangles':[snap_region(data,number,list(region))for region in rows]}for number,rows in original.items()]}
