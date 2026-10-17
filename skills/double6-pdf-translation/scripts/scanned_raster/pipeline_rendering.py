# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pipeline rendering：从原入口拆出的同一实现。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *

def _source_text_boxes(region: dict[str, Any], *, use_destroke_boxes: bool = True) -> list[list[float]]:
    destroke_boxes = (region.get("destroke_boxes") or []) if use_destroke_boxes else []
    if destroke_boxes:
        return [
            [float(value) for value in bbox]
            for bbox in destroke_boxes
            if isinstance(bbox, list) and len(bbox) == 4
        ]
    boxes: list[list[float]] = []
    source_regions = region.get("source_regions") or []
    for source in source_regions:
        fragments = source.get("source_fragments") or []
        candidates = fragments or [source]
        for candidate in candidates:
            bbox = candidate.get("bbox")
            if isinstance(bbox, list) and len(bbox) == 4:
                boxes.append([float(value) for value in bbox])
    if boxes:
        return boxes
    source_bbox = region.get("source_bbox") or region.get("bbox")
    if isinstance(source_bbox, list) and len(source_bbox) == 4:
        box = [float(value) for value in source_bbox]
        # MinerU 段落框偶尔比 RapidOCR 最后一行略短；只接受紧邻该框的行证据。
        margin = float(region.get('source_line_height') or 12) * .5
        for line in region.get('source_line_evidence') or []:
            line_box = line.get('bbox') or []
            if len(line_box) == 4 and line_box[0] >= box[0] - margin and line_box[1] >= box[1] - margin and line_box[2] <= box[2] + margin and line_box[3] <= box[3] + margin:
                box = [min(box[0],line_box[0]),min(box[1],line_box[1]),max(box[2],line_box[2]),max(box[3],line_box[3])]
        return [box]
    return []

def _destroke_page_image(
    image: Any,
    regions: list[dict[str, Any]],
    *,
    page_width: float,
    page_height: float,
    protected_boxes: list[list[float]] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Replace OCR line boxes with locally fitted paper colour and grain."""
    import cv2
    import numpy as np
    from PIL import Image

    rgb = np.asarray(image.convert("RGB"), dtype=np.float32).copy()
    scale_x = image.width / max(page_width, 1.0)
    scale_y = image.height / max(page_height, 1.0)
    region_pixels: dict[str, int] = {}
    region_background_modes: dict[str, list[str]] = {}
    for region in regions:
        region_pixel_count = 0
        for bbox in _source_text_boxes(region):
            raw_x0 = int(math.floor(bbox[0] * scale_x))
            raw_y0 = int(math.floor(bbox[1] * scale_y))
            raw_x1 = int(math.ceil(bbox[2] * scale_x))
            raw_y1 = int(math.ceil(bbox[3] * scale_y))
            source_height = max(1, raw_y1 - raw_y0)
            pad_x = max(6, int(round(source_height * 0.22)))
            pad_y = max(3, int(round(source_height * 0.09)))
            x0 = max(0, raw_x0 - pad_x)
            y0 = max(0, raw_y0 - pad_y)
            x1 = min(image.width, raw_x1 + pad_x)
            y1 = min(image.height, raw_y1 + pad_y)
            if x1 <= x0 or y1 <= y0:
                continue
            box_height = y1 - y0
            margin = max(12, min(48, int(round(box_height * 0.65))))
            ox0, oy0 = max(0, x0 - margin), max(0, y0 - margin)
            ox1, oy1 = min(image.width, x1 + margin), min(image.height, y1 + margin)
            outer = rgb[oy0:oy1, ox0:ox1]
            luma = 0.2126 * outer[:, :, 0] + 0.7152 * outer[:, :, 1] + 0.0722 * outer[:, :, 2]
            yy, xx = np.mgrid[oy0:oy1, ox0:ox1]
            ring = np.ones(luma.shape, dtype=bool)
            ring[y0 - oy0 : y1 - oy0, x0 - ox0 : x1 - ox0] = False
            cover = region.get('render_surface') == 'cover_title'
            if cover:
                # 封面局部背景可能很暗；按局部众数附近取样，禁止从整页亮色图案填补。
                local = luma[ring]
                if local.size < 32:
                    raise ValueError('cover background ring insufficient')
                median = float(np.median(local))
                ring &= np.abs(luma-median) <= 30
            else:
                ring &= luma >= 185.0
            sample_y = yy[ring]
            sample_x = xx[ring]
            sample_rgb = outer[ring]
            if sample_rgb.shape[0] < 32:
                if cover:
                    raise ValueError('cover background samples insufficient')
                bright = rgb[(0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]) >= 185.0]
                if bright.shape[0] < 32:
                    continue
                sample_rgb = bright[:: max(1, bright.shape[0] // 2000)]
                sample_x = np.full(sample_rgb.shape[0], (x0 + x1) / 2.0)
                sample_y = np.full(sample_rgb.shape[0], (y0 + y1) / 2.0)
            stride = max(1, sample_rgb.shape[0] // 5000)
            sample_rgb = sample_rgb[::stride]
            sample_x = sample_x[::stride]
            sample_y = sample_y[::stride]
            design = np.column_stack(
                (
                    np.ones(sample_rgb.shape[0]),
                    sample_x / max(1.0, float(image.width)),
                    sample_y / max(1.0, float(image.height)),
                )
            )
            coefficients = np.linalg.lstsq(design, sample_rgb, rcond=None)[0]
            fill_y, fill_x = np.mgrid[y0:y1, x0:x1]
            fill_design = np.stack(
                (
                    np.ones(fill_x.shape),
                    fill_x / max(1.0, float(image.width)),
                    fill_y / max(1.0, float(image.height)),
                ),
                axis=-1,
            )
            fitted = fill_design @ coefficients
            residual = sample_rgb - design @ coefficients
            # 白纸周围的英文抗锯齿灰边不能作为纸色拟合样本。
            # 只有相邻环带主要是无色饱和白纸时，才重建同色白纸并关闭造粒。
            neutral_white = (np.min(sample_rgb, axis=1) >= 252.0) & (
                np.max(sample_rgb, axis=1) - np.min(sample_rgb, axis=1) <= 2.0
            )
            white_paper = not cover and float(np.mean(neutral_white)) >= 0.75
            if white_paper:
                paper_rgb = np.percentile(sample_rgb[neutral_white], 90, axis=0)
                fitted[:] = paper_rgb
            mode = "verified_white_paper" if white_paper else "local_plane_with_grain"
            modes = region_background_modes.setdefault(str(region.get("region_id") or ""), [])
            if mode not in modes:
                modes.append(mode)
            if cover:
                fit_rmse = float(np.sqrt(np.mean(residual**2)))
                region['cover_background_fit_rmse'] = max(float(region.get('cover_background_fit_rmse', 0)), round(fit_rmse, 3))
                if fit_rmse > 15:
                    raise ValueError('cover background is too complex for local planar reconstruction')
            grain_std = 0.0 if cover or white_paper else float(np.clip(np.std(residual), 0.8, 4.5))
            seed = int((x0 * 73856093) ^ (y0 * 19349663) ^ (x1 * 83492791) ^ y1) & 0xFFFFFFFF
            rng = np.random.default_rng(seed)
            grain = rng.normal(0.0, grain_std, size=fill_x.shape).astype(np.float32)
            grain = cv2.GaussianBlur(grain, (0, 0), sigmaX=0.45)
            fitted += grain[:, :, None] * np.array([1.0, 0.86, 0.72], dtype=np.float32)
            alpha = np.zeros(fill_x.shape, dtype=np.uint8)
            inset_y = min(max(1, int(round(pad_y * 0.35))), max(1, alpha.shape[0] // 3))
            inset_x = min(max(1, int(round(pad_x * 0.35))), max(1, alpha.shape[1] // 3))
            alpha[inset_y : alpha.shape[0] - inset_y, inset_x : alpha.shape[1] - inset_x] = 255
            alpha = cv2.GaussianBlur(
                alpha,
                (0, 0),
                sigmaX=max(1.0, min(pad_x, pad_y) * 0.55),
            ).astype(np.float32) / 255.0
            # 原字框内部必须完全去字；羽化只作用于外围纸面，避免大框尾行留下浅字。
            alpha[max(0,raw_y0-y0):min(y1-y0,raw_y1-y0), max(0,raw_x0-x0):min(x1-x0,raw_x1-x0)] = 1.0
            # 外围羽化也不得触碰公式、表格等受保护区域。
            for protected in protected_boxes or []:
                px0,py0=int(math.floor(protected[0]*scale_x)),int(math.floor(protected[1]*scale_y))
                px1,py1=int(math.ceil(protected[2]*scale_x)),int(math.ceil(protected[3]*scale_y))
                if px1>x0 and px0<x1 and py1>y0 and py0<y1:
                    alpha[max(0,py0-y0):min(y1-y0,py1-y0),max(0,px0-x0):min(x1-x0,px1-x0)] = 0.0
            alpha = alpha[:, :, None]
            rgb[y0:y1, x0:x1] = (
                np.clip(fitted, 0, 255) * alpha + rgb[y0:y1, x0:x1] * (1.0 - alpha)
            )
            region_pixel_count += int((x1 - x0) * (y1 - y0))
        region_id = str(region.get("region_id") or "")
        region_pixels[region_id] = region_pixel_count
    total_pixels = sum(region_pixels.values())
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)), {
        "strategy": "source_line_texture_synthesis",
        "mask_pixels": total_pixels,
        "page_pixel_ratio": round(total_pixels / max(1, image.width * image.height), 8),
        "region_mask_pixels": region_pixels,
        "region_background_modes": region_background_modes,
    }

def _render_text_style(
    region: dict[str, Any], text: str, *, page_width: float
) -> tuple[str, dict[str, Any]]:
    if region.get("frontmatter_alignment_policy") == "sparse_report_author_fields_centered_v1":
        return text, {"paragraph_style": "centered_report_field", "align": 1, "lineheight": 1.18, "first_line_indent_em": 0}
    if region.get("structured_name_column") == "common":
        return text, {"paragraph_style": "common_name_field", "align": 0, "lineheight": 1.18, "first_line_indent_em": 0}
    if region.get('layout_role') == 'cover_title':
        return text, {'paragraph_style':'cover_title','align':0,'lineheight':1.15,'first_line_indent_em':0}
    if region.get('layout_role') == 'paragraph_title':
        return text, {'paragraph_style':'paragraph_title','align':0,'lineheight':1.05,'first_line_indent_em':0}
    if region.get('layout_role') == 'doc_title':
        lines = region.get('source_line_evidence') or []
        centered = bool(lines) and all(
            isinstance(line.get('bbox'), list) and len(line['bbox']) == 4
            and abs((line['bbox'][0] + line['bbox'][2])/2 - page_width/2) <= page_width*.04
            for line in lines
        )
        return text, {'paragraph_style':'document_title','align':1 if centered else 0,
                      'lineheight':1.1,'first_line_indent_em':0}
    source = " ".join(
        str(region.get("paragraph_source_text") or region.get("ocr_text") or "").split()
    )
    heading = str(region.get("layout_role") or "") == "chapter_heading" or bool(
        re.fullmatch(r"(?:CHAPTER|BOOK|PART)\s+[IVXLCDM\d. -]+", source, flags=re.IGNORECASE)
    )
    if heading:
        return text, {
            "paragraph_style": "chapter_heading",
            "align": 1,
            "lineheight": 1.0,
            "first_line_indent_em": 0,
        }
    if re.match(
        r"(?i)^[\"'‘’“”|i ]*(?:Applicant|Assignee|Title|Serial No\.|Filed|Examiner|Group Art Unit|Attorney Docket No\.|Sir)\s*:",
        source,
    ):
        return text, {
            "paragraph_style": "structured_field",
            "align": 0,
            "lineheight": 1.0,
            "first_line_indent_em": 0,
        }
    band_index = int(region.get("paragraph_band_index") or 0)
    starts_quote = bool(re.match(r'^["“‘]', source))
    bbox = region.get("source_bbox") or region.get("bbox") or [0.0, 0.0, page_width, 0.0]
    left_edge = float(bbox[0])
    if band_index > 0:
        style = "paragraph_continuation_band"
        indent = 0
    elif starts_quote:
        style = "dialogue"
        indent = 0 if left_edge > page_width * 0.095 else 1
    elif str(region.get("paragraph_boundary_reason") or "") == "heading_boundary" and left_edge > page_width * 0.30:
        style = "illustrated_opening"
        indent = 0
    else:
        style = "body_paragraph"
        indent = 2
    if len(text) <= 8:
        indent = 0
        if style == "body_paragraph":
            style = "compact_inline"
    lineheight = (
        1.18
        if str(region.get("engine") or "") == "mineru"
        and isinstance(region.get("source_line_height"), (int, float))
        else 1.28
    )
    source_lines = region.get('source_line_evidence') or region.get('source_regions') or []
    if len(source_lines) >= 3:
        measured = infer_paragraph_geometry(source_lines,
            frame=region.get('source_bbox') or region.get('bbox'),
            font_size=float(region.get('source_line_height') or 12)*.78,
            continuation=band_index>0)
        region['source_formatting'] = measured
        if measured['confidence'] == 'high' and measured['alignment'] in {'left','justify','right','center'}:
            source_step = measured.get('baseline_step_pt')
            if source_step:
                lineheight = max(1.05, min(3., source_step / measured['font_size_pt']))
            indent_pt = float(measured.get('first_line_indent_pt') or 0)
            return text, {'paragraph_style':style,'align':{'left':0,'center':1,'right':2,'justify':3}[measured['alignment']],
                          'lineheight':lineheight,'first_line_indent_em':indent_pt/measured['font_size_pt'],
                          'first_line_indent_pt':indent_pt,'formatting_evidence':measured['reason']}
    return text, {
        "paragraph_style": style,
        "align": 0,
        "lineheight": lineheight,
        "first_line_indent_em": indent,
    }

def _sample_background_color(
    image: Any,
    rect: Any,
    *,
    page_width: float,
    page_height: float,
) -> tuple[float, float, float]:
    """Estimate the local light paper colour around a text rectangle."""
    scale_x = image.width / max(page_width, 1.0)
    scale_y = image.height / max(page_height, 1.0)
    x0 = max(0, int(float(rect.x0) * scale_x))
    y0 = max(0, int(float(rect.y0) * scale_y))
    x1 = min(image.width, max(x0 + 1, int(math.ceil(float(rect.x1) * scale_x))))
    y1 = min(image.height, max(y0 + 1, int(math.ceil(float(rect.y1) * scale_y))))
    margin = max(4, int(round((y1 - y0) * 0.35)))
    ox0, oy0 = max(0, x0 - margin), max(0, y0 - margin)
    ox1, oy1 = min(image.width, x1 + margin), min(image.height, y1 + margin)
    pixels: list[tuple[int, int, int]] = []
    step = max(1, int(math.sqrt(max(1, (ox1 - ox0) * (oy1 - oy0) // 4000))))
    source = image.load()
    for py in range(oy0, oy1, step):
        for px in range(ox0, ox1, step):
            if x0 <= px < x1 and y0 <= py < y1:
                continue
            red, green, blue = source[px, py][:3]
            luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            if luma >= 155:
                pixels.append((red, green, blue))
    if not pixels:
        return (1.0, 1.0, 1.0)
    return tuple(float(statistics.median(channel)) / 255.0 for channel in zip(*pixels, strict=True))

def _readable_scanned_block(region, rect, page_rect, page_regions):
    """小标题和缺行高证据的长单行正文仅在相邻块前扩高，不改变去字框。"""
    import fitz
    role = region.get('layout_role')
    line_height = region.get('source_line_height')
    source = str(region.get('normalized_text') or region.get('ocr_text') or '')
    if role == 'doc_title' and isinstance(line_height, (float, int)):
        font_size = max(14., min(30., line_height * 1.05))
        policy = 'document_title_source_geometry'
    elif role == 'paragraph_title':
        font_size = max(12., min(24., float(line_height or rect.height) * 1.05))
        policy = 'paragraph_title_source_geometry'
    elif (role == 'text' and not line_height and not region.get('frontmatter_alignment_policy')
          and not region.get('structured_name_column') and len(source.split()) >= 8
          and '\n' not in source and 8 <= rect.height <= 35 and rect.width >= 12 * rect.height):
        font_size = max(12., min(30., rect.height * .9))
        policy = 'single_line_prose_source_geometry'
    else:
        return rect, None, None
    bottom = page_rect.y1 - 8
    for other in page_regions:
        box = other.get('original_layout_bbox') or other.get('bbox')
        if other is region or not isinstance(box, list) or len(box) != 4:
            continue
        b = fitz.Rect(box)
        if b.x0 < rect.x1 and b.x1 > rect.x0 and b.y0 > rect.y0:
            bottom = min(bottom, b.y0 - 3)
    desired = max(rect.y1, rect.y0 + font_size * 1.8)
    return fitz.Rect(rect.x0, rect.y0, rect.x1, min(desired, bottom)), font_size, policy

def _render_translated_pdf(
    input_pdf: Path,
    output_pdf: Path,
    regions: list[dict[str, Any]],
    *,
    dpi: int,
    source_ink_protection: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from scanned_raster.pipeline_fonts import _embedded_cjk_font, _insert_fitted_textbox, _insert_invisible_search_text, _verify_embedded_font
    from scanned_raster.pipeline_translation import _clip_rect_against_protected
    import fitz

    uniform_policies = validate_uniform_typography(input_pdf, regions)
    source = fitz.open(input_pdf)
    ink_assets = source_ink_protection or []
    if len(ink_assets)>64:
        raise ValueError('source_ink_protection_limit')
    for asset in ink_assets:
        number=asset.get('page');box=asset.get('bbox')
        if not isinstance(number,int) or isinstance(number,bool) or not 1<=number<=len(source) or not isinstance(box,list) or len(box)!=4 or not asset.get('source_evidence'):
            raise ValueError('source_ink_protection_evidence_required')
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box) or not (0<=box[0]<box[2]<=source[number-1].rect.width and 0<=box[1]<box[3]<=source[number-1].rect.height):
            raise ValueError('source_ink_protection_geometry')
    target = fitz.open()
    font_alias, font_buffer, font_metadata = _embedded_cjk_font()
    font_metrics = fitz.Font(fontbuffer=font_buffer)
    destroke_pages: list[dict[str, Any]] = []
    try:
        regions_by_page: dict[int, list[dict[str, Any]]] = {}
        for region in regions:
            regions_by_page.setdefault(int(region["page"]), []).append(region)
        for index, source_page in enumerate(source, start=1):
            from PIL import Image

            page = target.new_page(width=source_page.rect.width, height=source_page.rect.height)
            page.insert_font(fontname=font_alias, fontbuffer=font_buffer)
            pixmap = stable_get_pixmap(source_page, matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
            page_png = pixmap.tobytes("png")
            page_image = Image.open(BytesIO(page_png)).convert("RGB")
            page_regions = regions_by_page.get(index, [])
            protected_rects = [
                fitz.Rect(*[float(value) for value in item["bbox"]]) & page.rect
                for item in page_regions
                if item.get("status") in {"protected", "skipped_with_reason", "failed"}
                and isinstance(item.get("bbox"), list)
            ]
            committed_regions: list[dict[str, Any]] = []
            for region in page_regions:
                if region.get("status") != "translated" or not region.get("in_destroke_mask"):
                    continue
                # 去字区域可能扩到 OCR 印刷行边缘；重渲染仍沿用原排版框，
                # 避免从已渲染区域恢复时把遮罩扩张当作更大的排版空间。
                layout_bbox = region.get("name_column_layout_bbox") or region.get("original_layout_bbox") or region["bbox"]
                rect = fitz.Rect(*[float(value) for value in layout_bbox]) & page.rect
                source_mask_bbox = region.get("source_bbox") or region.get("bbox")
                source_mask_rect = fitz.Rect(
                    *[float(value) for value in source_mask_bbox]
                ) & page.rect
                original_source_boxes = _source_text_boxes(region, use_destroke_boxes=False)
                for source_box in original_source_boxes:
                    source_mask_rect |= fitz.Rect(source_box)
                source_mask_rect &= page.rect
                if any(abs(a-b) > .01 for a,b in zip(source_mask_rect, region['bbox'])):
                    region.setdefault('original_layout_bbox', list(region['bbox']))
                    region['source_geometry_expansion'] = {'policy': 'union_original_block_and_nearby_source_line_evidence', 'source_boxes': original_source_boxes}
                    region['bbox'] = [float(value) for value in source_mask_rect]
                    region['polygon'] = [[source_mask_rect.x0,source_mask_rect.y0],[source_mask_rect.x1,source_mask_rect.y0],[source_mask_rect.x1,source_mask_rect.y1],[source_mask_rect.x0,source_mask_rect.y1]]
                source_text = " ".join(
                    str(region.get("paragraph_source_text") or region.get("ocr_text") or "").split()
                )
                heading = str(region.get("layout_role") or "") == "chapter_heading" or bool(
                    re.fullmatch(
                        r"(?:CHAPTER|BOOK|PART)\s+[IVXLCDM\d. -]+",
                        source_text,
                        flags=re.IGNORECASE,
                    )
                )
                if heading:
                    source_height = max(1.0, rect.height)
                    rect = fitz.Rect(
                        max(0.0, page.rect.width * 0.27),
                        max(0.0, rect.y0 - source_height * 0.12),
                        min(page.rect.width, page.rect.width * 0.73),
                        min(page.rect.height, rect.y1 + source_height * 0.42),
                    )
                uniform_policy = uniform_policies.get(region["region_id"])
                if uniform_policy is None:
                    rect, readable_size, readable_policy = _readable_scanned_block(region, rect, page.rect, page_regions)
                else:
                    readable_size = float(uniform_policy["font_size_pt"])
                    readable_policy = "declared_same_class_typography"
                rect, clipped_by = _clip_rect_against_protected(rect, protected_rects)
                source_mask_rect, mask_clipped_by = _clip_rect_against_protected(
                    source_mask_rect,
                    protected_rects,
                )
                destroke_boxes: list[list[float]] = []
                destroke_clipped_by: list[list[float]] = []
                for source_box in original_source_boxes:
                    safe_box, box_clipped_by = _clip_rect_against_protected(
                        fitz.Rect(*source_box) & page.rect,
                        protected_rects,
                    )
                    if not safe_box.is_empty and safe_box.width >= 2 and safe_box.height >= 2:
                        destroke_boxes.append([float(value) for value in safe_box])
                    destroke_clipped_by.extend(box_clipped_by)
                if (
                    rect.is_empty
                    or rect.width < 2
                    or rect.height < 2
                    or source_mask_rect.is_empty
                    or not destroke_boxes
                ):
                    region.update(status="failed", skip_reason="invalid_render_bbox", in_destroke_mask=False)
                    continue
                region["render_bbox"] = [float(value) for value in rect]
                region["destroke_boxes"] = destroke_boxes
                region["mask_geometry"] = {
                    "type": "polygon",
                    "points": [
                        [float(source_mask_rect.x0), float(source_mask_rect.y0)],
                        [float(source_mask_rect.x1), float(source_mask_rect.y0)],
                        [float(source_mask_rect.x1), float(source_mask_rect.y1)],
                        [float(source_mask_rect.x0), float(source_mask_rect.y1)],
                    ],
                }
                all_clipped_by = clipped_by + mask_clipped_by + destroke_clipped_by
                if all_clipped_by:
                    region["mask_clip_reason"] = "protected_region_intersection"
                    region["mask_clipped_by"] = all_clipped_by
                text, style = _render_text_style(
                    region,
                    str(region.get("translation") or ""),
                    page_width=float(source_page.rect.width),
                )
                if uniform_policy is not None:
                    style["lineheight"] = float(uniform_policy["baseline_step_pt"]) / float(uniform_policy["font_size_pt"])
                    region["declared_baseline_step_pt"] = float(uniform_policy["baseline_step_pt"])
                region.update(
                    paragraph_style=style["paragraph_style"],
                    line_break_policy="measured_cjk_with_protected_math_atoms_v1",
                    text_alignment={0:"left",1:"center",2:"right",3:"justify"}[int(style["align"])],
                    first_line_indent_em=float(style["first_line_indent_em"]),
                    first_line_indent_pt=float(style.get("first_line_indent_pt",0)),
                    lineheight=float(style["lineheight"]),
                )
                source_line_height = region.get("source_line_height")
                if readable_size is not None:
                    initial_font_size = minimum_font_size = readable_size
                    region['font_size_source'] = readable_policy
                elif heading:
                    initial_font_size = max(20.0, min(30.0, float(source_line_height or rect.height) * 0.90))
                    minimum_font_size = 18.0
                    region["font_size_source"] = "chapter_heading_source_line_height"
                elif isinstance(source_line_height, (int, float)):
                    if str(region.get("engine") or "") == "mineru":
                        initial_font_size = max(12.0, min(34.0, float(source_line_height) * 0.78))
                        minimum_font_size = max(8.0, min(12.0, float(source_line_height) * 0.50))
                        region["font_size_source"] = "rapidocr_geometry_for_mineru_block"
                    else:
                        initial_font_size = max(12.0, min(30.0, float(source_line_height) * 0.78))
                        minimum_font_size = 10.0
                        region["font_size_source"] = "rapidocr_source_line_height"
                else:
                    initial_font_size = max(5.5, min(12.0, rect.height * 0.55))
                    minimum_font_size = 5.5
                    region["font_size_source"] = "render_bbox_height"
                text_color = (0.,0.,0.)
                if region.get('render_surface') == 'cover_title':
                    from PIL import ImageStat
                    sample = page_image.crop((int(rect.x0*dpi/72),int(rect.y0*dpi/72),int(rect.x1*dpi/72),int(rect.y1*dpi/72))).convert('L')
                    if ImageStat.Stat(sample).median[0] < 128:
                        text_color = (.96,.96,.96)
                    region['text_color'] = list(text_color)
                region["initial_font_size"] = round(initial_font_size, 2)
                font_size, result = _insert_fitted_textbox(
                    page,
                    rect,
                    text,
                    font_alias=font_alias,
                    initial_font_size=initial_font_size,
                    font_metrics=font_metrics,
                    minimum_font_size=minimum_font_size,
                    paint_background=False,
                    text_color=text_color,
                    align=int(style["align"]),
                    lineheight=float(style["lineheight"]),
                    first_line_indent_pt=float(style.get("first_line_indent_pt",0)),
                    first_line_indent_em=float(style.get("first_line_indent_em",0)) if "first_line_indent_pt" not in style else 0,
                    baseline_step_pt=float(uniform_policy["baseline_step_pt"]) if uniform_policy is not None else None,
                )
                if result < 0 and readable_size is None and (minimum_font_size > 5.5 or float(style["lineheight"]) > 1.05):
                    font_size, result = _insert_fitted_textbox(
                        page,
                        rect,
                        text,
                        font_alias=font_alias,
                        initial_font_size=min(initial_font_size, 10.0),
                        minimum_font_size=5.5,
                        font_metrics=font_metrics if (int(style["align"])==3 or style.get("first_line_indent_pt") or style.get("first_line_indent_em") or re.search(r"[A-Za-z]\u0304", text)) else None,
                        paint_background=False,
                        text_color=text_color,
                        align=int(style["align"]),
                        lineheight=min(float(style["lineheight"]), 1.05),
                        first_line_indent_pt=float(style.get("first_line_indent_pt",0)),
                        first_line_indent_em=float(style.get("first_line_indent_em",0)) if "first_line_indent_pt" not in style else 0,
                    )
                    if result >= 0:
                        region["font_size_source"] = f"{region.get('font_size_source')}:overflow_rescue"
                region["font_size"] = round(font_size, 2)
                if "first_line_indent_pt" not in style:
                    region["first_line_indent_pt"] = float(style.get("first_line_indent_em", 0)) * font_size
                if result < 0:
                    region["overflow"] = True
                    region["in_destroke_mask"] = False
                    region["writeback_status"] = "preserved_source_due_overflow"
                else:
                    region["writeback_status"] = "translated_text_committed"
                    committed_regions.append(region)
            for region in page_regions:
                search_text = str(region.get("search_layer_translation") or "").strip()
                if region.get("status") != "protected" or not search_text:
                    continue
                raw_bbox = region.get("bbox")
                if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
                    region.update(search_layer_status="failed", search_layer_error="invalid_bbox")
                    continue
                search_rect = fitz.Rect(*[float(value) for value in raw_bbox]) & page.rect
                font_size, result = _insert_invisible_search_text(
                    page,
                    search_rect,
                    search_text,
                    font_alias=font_alias,
                )
                region["search_layer_bbox"] = [float(value) for value in search_rect]
                region["search_layer_font_size"] = font_size
                if result < 0:
                    region.update(search_layer_status="overflow", search_layer_error="text_did_not_fit")
                else:
                    region.update(
                        search_layer_status="committed_invisible",
                        writeback_status="protected_source_with_search_layer",
                    )
            destroked_image, destroke = _destroke_page_image(
                page_image,
                committed_regions,
                page_width=float(source_page.rect.width),
                page_height=float(source_page.rect.height),
                protected_boxes=[list(rect) for rect in protected_rects]+[asset['bbox'] for asset in ink_assets if asset['page']==index],
            )
            for region in committed_regions:
                mask_pixels = int(
                    (destroke.get("region_mask_pixels") or {}).get(str(region.get("region_id") or ""), 0)
                )
                region["destroke_strategy"] = str(destroke["strategy"])
                region["destroke_mask_pixels"] = mask_pixels
                modes = destroke.get("region_background_modes", {}).get(str(region.get("region_id") or ""), [])
                region["background_fill_strategy"] = (
                    "source_verified_white_paper" if modes == ["verified_white_paper"]
                    else "source_line_texture_synthesis"
                )
            destroke_pages.append({"page": index, **destroke})
            output_png = BytesIO()
            destroked_image.save(output_png, format="PNG")
            # 光栅尺寸取整后仍绑定完整源页矩形，避免keep_proportion产生隐含居中偏移。
            page.insert_image(page.rect, stream=output_png.getvalue(), overlay=False, keep_proportion=False)
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        target.subset_fonts(verbose=False)
        target.save(output_pdf, garbage=4, deflate=True)
    finally:
        target.close()
        source.close()
    verification = _verify_embedded_font(output_pdf, alias=font_alias)
    if not verification["embedded"]:
        raise RuntimeError("embedded_cjk_font_verification_failed")
    return {
        **font_metadata,
        **verification,
        "subset_requested": True,
        "destroke": {"strategy": "source_line_texture_synthesis", "pages": destroke_pages},
    }


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
