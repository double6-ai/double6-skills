"""有界结构流排入口：原生图层、完整段落、实际字形与来源映射。"""
from __future__ import annotations

import hashlib
import html
import json
import math
import unicodedata
from pathlib import Path

import fitz

from adaptive_paragraph_layout import pack_whole_items, pack_source_anchored_items
from cjk_justification import insert_source_htmlbox
from semantic_paragraph_flow import canonical_paragraph, plan_line_flow
from ink_preserving_copy import copy_text_with_true_ink
from actual_ink_change_mask import bind_saved_target
from native_line_spacing import glyphs


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def copy_pdf_region(page, document, index, clip, destination, *, precise_glyph_heights=False,
                    preserve_true_glyph_ink=False, rotation=0,
                    maximum_ink_bleed_pt=8., declared_font_aliases=()):
    """先删除裁区外文本；PDF的绘制clip不能保证抽取文本没有隐藏内容。"""
    if preserve_true_glyph_ink or precise_glyph_heights:
        return copy_text_with_true_ink(page,document,index,clip,destination,
            rotation=rotation,maximum_bleed_pt=maximum_ink_bleed_pt,
            declared_font_aliases=declared_font_aliases)
    if rotation:raise ValueError('asset_rotation_requires_declared_separate_route')
    clip, destination = fitz.Rect(clip), fitz.Rect(destination)
    if clip.is_empty or not (document[index].rect+(-.002,-.002,.002,.002)).contains(clip):
        raise ValueError('invalid_source_clip')
    clip = clip & document[index].rect
    links = document[index].get_links()
    with fitz.open() as clean:
        clean.insert_pdf(document, from_page=index, to_page=index)
        cp = clean[0]
        full = cp.rect
        for box in (fitz.Rect(0, 0, full.width, clip.y0),
                    fitz.Rect(0, clip.y1, full.width, full.height),
                    fitz.Rect(0, clip.y0, clip.x0, clip.y1),
                    fitz.Rect(clip.x1, clip.y0, full.width, clip.y1)):
            if not box.is_empty:
                cp.add_redact_annot(box, fill=False)
        cp.apply_redactions(images=0, graphics=1, text=0)
        cp = clean.reload_page(cp)
        cp.set_cropbox(clip)
        page.show_pdf_page(destination, clean, 0, keep_proportion=False)
    sx, sy = destination.width / clip.width, destination.height / clip.height
    for link in links:
        box = link['from'] & clip
        if not link.get('uri') or box.is_empty:
            continue
        target = fitz.Rect(destination.x0+(box.x0-clip.x0)*sx,
                           destination.y0+(box.y0-clip.y0)*sy,
                           destination.x0+(box.x1-clip.x0)*sx,
                           destination.y0+(box.y1-clip.y0)*sy)
        page.insert_link({'kind': fitz.LINK_URI, 'from': target, 'uri': link['uri']})


def prepare_html_item(item):
    """保留统一字号与行高；超出声明试排高度即失败，不缩字。"""
    width = float(item['width'])
    limit = float(item.get('measurement_height', 2048))
    if not 20 <= width <= 2000 or not 100 <= limit <= 4096:
        raise ValueError('measurement_bounds')
    font = Path(item['font'])
    if item.get('font_sha256') and sha(font) != item['font_sha256']:
        raise ValueError('font_identity_changed')
    size, lh = float(item['font_size']), float(item['lineheight'])
    inline_policy=item.get('inline_attachment_policy')
    if inline_policy is not None:
        from inline_attachment import POLICY_ID
        if inline_policy!=POLICY_ID:raise ValueError('unknown_inline_attachment_policy')
        if item.get('balanced_line_flow') is not True:raise ValueError('inline_attachment_requires_balanced_line_flow')
    source_styles=None
    if item.get('actual_style_ref') is not None:
        if item.get('balanced_line_flow') is not True:raise ValueError('source_style_requires_balanced_line_flow')
        record=item['actual_style_ref'];path=Path(record['path'])
        if path.stat().st_size>16*1024**2 or sha(path)!=record['sha256']:raise ValueError('actual_style_ref_identity_changed')
        binding=json.loads(path.read_text());pdf=binding['pdf']
        if sha(pdf['path'])!=pdf['sha256']:raise ValueError('actual_style_source_pdf_changed')
        source_styles=binding['glyphs']
    css = (f"@font-face{{font-family:PT;src:url('{font.name}')}}"
           f'body,p{{font-family:PT;font-size:{size}pt;margin:0;padding:0;'
           f'line-height:{lh};color:#000}}sub,sup{{font-size:75%}}')
    doc = fitz.open()
    try:
        page = doc.new_page(width=width, height=limit)
        if item.get('heading_parts'):
            parts = item['heading_parts']
            separator = item['separator']
            x, title_x = separator['relative_x'], separator['title_relative_x']
            if not 0 < x-3 < title_x < width:
                raise ValueError('heading_separator_geometry')
            spare, scale, evidence = insert_source_htmlbox(
                page, fitz.Rect(0, 0, x-3, limit), '<p>'+html.escape(parts['number'])+'</p>',
                css=css, archive=fitz.Archive(str(font.parent)), default_alignment='left')
            title_spare, title_scale, _ = insert_source_htmlbox(
                page, fitz.Rect(title_x, 0, width, limit), '<p>'+html.escape(parts['title'])+'</p>',
                css=css, archive=fitz.Archive(str(font.parent)), default_alignment='left')
            if title_spare < 0 or title_scale != 1:
                raise ValueError('heading_title_overflow')
            spare = min(spare, title_spare)
            baseline = page.get_texttrace()[0]['chars'][0][2][1]
            page.draw_line((x, baseline), (x, baseline-separator['source_line_height']),
                           color=separator['source']['color'], width=separator['width'])
            item = {**item, 'separator': {**separator, 'relative_baseline': baseline}}
        else:
            spare, scale, evidence = insert_source_htmlbox(
                page, page.rect, item['html'], css=css,
                archive=fitz.Archive(str(font.parent)),
                default_alignment=item.get('alignment', 'left'),
                balanced_line_flow={'font_size':size,'lineheight':lh,'maximum_added_spacing_em':.3,
                    'inline_attachment_policy':inline_policy,'source_glyph_styles':source_styles} if item.get('balanced_line_flow') is True else None)
        if spare < 0 or scale != 1:
            raise ValueError('paragraph_measurement_overflow')
        glyphs = [c for s in page.get_texttrace() for c in s['chars']]
        if not glyphs:
            raise ValueError('empty_rendered_paragraph')
        height = max(limit-spare, max(c[3][3] for c in glyphs)+.25)
        baselines=sorted({round(c[2][1],4)for c in glyphs})
        grouped=None
        if item.get('line_group_policy')=='body_with_verified_small_scripts':
            styled=[(span['size'],c)for span in page.get_texttrace()for c in span['chars']]
            baselines=sorted({round(c[2][1],4)for fs,c in styled if abs(fs-size)<.001})
            if not baselines:raise ValueError('script_body_baselines_missing')
            grouped={y:[]for y in baselines}
            for fs,c in styled:
                y=min(baselines,key=lambda v:abs(c[2][1]-v))
                if abs(fs-size)>=.001 and (abs(fs/size-.75)>.001 or abs(c[2][1]-y)>size*.5):
                    raise ValueError('script_line_binding_ambiguous')
                if abs(fs-size)<.001 and abs(c[2][1]-y)>.001:
                    raise ValueError('script_body_line_binding_ambiguous')
                grouped[y].append(c)
        line_records=[];text_offset=0
        for y in baselines:
            chars=grouped[y]if grouped is not None else [c for c in glyphs if abs(c[2][1]-y)<.001]
            text_offset+=sum(len(unicodedata.normalize('NFKC',chr(c[0])))for c in chars if not chr(c[0]).isspace())
            line_records.append({'baseline':y,'ink_top':min(c[3][1]for c in chars),
                                 'ink_bottom':max(c[3][3]for c in chars),'text_end_offset':text_offset})
        for i,line in enumerate(line_records):
            if i and line_records[i-1]['ink_bottom']>line['ink_top']+.001:
                # 上下标等混合基线不作为可拆印刷行；整段路线仍可用。
                line_records=[];break
            line['clip_top']=0 if i==0 else (line_records[i-1]['ink_bottom']+line['ink_top'])/2
            line['clip_bottom']=height if i==len(line_records)-1 else (line['ink_bottom']+line_records[i+1]['ink_top'])/2
        # new_page stores finite-precision dimensions; the requested fractional
        # width may be a few ulps larger than the actual MediaBox.
        if height > page.rect.height:
            raise ValueError('paragraph_measurement_overflow')
        page.set_cropbox(fitz.Rect(0, 0, min(width, page.rect.width), height))
        return doc, {**item, 'height': height, 'fit_scale': 1.,
                     'font_sha256': sha(font), 'actual_justification': evidence,'line_records':line_records}
    except BaseException:
        doc.close()
        raise


def render_plan(plan, output):
    """结构已冻结的候选入口；模板区域、来源、文本和字体均显式声明。"""
    item_limit = plan.get('maximum_items', 100)
    if (plan.get('schema_version') != 1 or not isinstance(item_limit, int)
            or not 1 <= item_limit <= 200 or not 1 <= len(plan['items']) <= item_limit):
        raise ValueError('plan_schema_or_item_limit')
    maximum_pages = plan.get('maximum_pages', 10)
    if not isinstance(maximum_pages, int) or not 1 <= maximum_pages <= 10:
        raise ValueError('output_page_limit')
    if not plan.get('templates') or len(plan['templates']) > 10:
        raise ValueError('template_limit_or_missing')
    for frame in plan['frames']:
        if not isinstance(frame['page'], int) or not 1 <= frame['page'] <= maximum_pages:
            raise ValueError('frame_page_limit')
        template = plan['templates'][min(frame['page']-1,len(plan['templates'])-1)]
        if not all(math.isfinite(v) for v in frame['bbox']):
            raise ValueError('nonfinite_frame')
        box = fitz.Rect(frame['bbox'])
        if box.is_empty or not fitz.Rect(0,0,template['width'],template['height']).contains(box):
            raise ValueError('frame_outside_page')
    output = Path(output)
    if output.exists():
        raise ValueError('output_already_exists')
    for source in plan['sources']:
        if Path(source['path']).stat().st_size > 128*1024**2:
            raise ValueError('source_file_limit')
        if sha(source['path']) != source['sha256']:
            raise ValueError('source_identity_changed')
    frozen_sources = {str(Path(s['path']).resolve()) for s in plan['sources']}
    source_uri_actions = None
    if plan.get('source_uri_action_policy') is not None:
        if plan['source_uri_action_policy'] != 'unique_source_uri_full_actions_and_names':
            raise ValueError('unknown_source_uri_action_policy')
        from raw_link_actions import capture_page_link_actions
        original = plan.get('input_source', {})
        if original not in plan['sources']:
            raise ValueError('unfrozen_source_uri_actions')
        source_uri_actions = {}
        with fitz.open(original['path']) as source_document:
            if len(source_document) > 10:
                raise ValueError('source_uri_action_page_limit')
            for source_page in range(len(source_document)):
                for record in capture_page_link_actions(source_document, source_page):
                    fields = record['fields']
                    if fields['kind'] != fitz.LINK_URI:
                        raise ValueError('source_uri_action_policy_requires_uri_only')
                    uri = fields['uri']
                    if uri in source_uri_actions:
                        raise ValueError('source_uri_occurrence_requires_named_mapping')
                    source_uri_actions[uri] = record
                    if len(source_uri_actions) > 2000:
                        raise ValueError('source_uri_action_annotation_limit')

    used_sources = [region['path'] for template in plan['templates']
                    for region in template.get('regions', [])]
    used_sources.extend(item['source'] for item in plan['items'] if item.get('kind') == 'asset')
    if any(str(Path(path).resolve()) not in frozen_sources for path in used_sources):
        raise ValueError('unfrozen_source_region')
    ids = [v['id'] for v in plan['items']]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate_logical_id')
    policy=plan.get('layout_policy','whole_paragraph')
    with fitz.open() as bank, fitz.open() as result:
        prepared = []
        planned_unit_texts = {}
        copied_unit_texts = {}
        for item in plan['items']:
            if item['kind'] == 'asset':
                if policy=='verified_multiframe':raise ValueError('verified_flow_text_only')
                prepared.append(item)
                continue
            if not item.get('font_sha256'):
                raise ValueError('unfrozen_font_identity')
            temp, row = prepare_html_item(item)
            try:
                normalize_text = lambda value: ''.join(
                    c for c in unicodedata.normalize('NFKC', value) if not c.isspace())
                prepared_text = normalize_text(''.join(
                    chr(c[0]) for span in temp[0].get_texttrace() for c in span['chars']))
                if item.get('expected_text') is not None and prepared_text != normalize_text(item['expected_text']):
                    raise ValueError('prepared_unit_text_incomplete:' + item['id'])
                planned_unit_texts[item['id']] = prepared_text
                copied_unit_texts[item['id']] = []
                if policy=='verified_multiframe':
                    if item['kind']=='asset':raise ValueError('verified_flow_text_only')
                    fragments=item.get('verified_fragments',[])
                    canonical=canonical_paragraph(fragments,item.get('expected_text',''))
                    if canonical['id']!=item['id']:raise ValueError('flow_logical_id_changed')
                    indices=item.get('frame_indices',[])
                    if not indices or len(set(indices))!=len(indices) or any(not isinstance(i,int)or i<0 or i>=len(plan['frames']) for i in indices):
                        raise ValueError('flow_frame_indices')
                    frames=[plan['frames'][i] for i in indices]
                    sources_by_id={f['id']:f for f in fragments}
                    for frame in frames:
                        fragment=sources_by_id.get(frame.get('source_fragment_id'))
                        if fragment is None or frame['source_page']!=fragment['source_page']:
                            raise ValueError('flow_frame_source_binding')
                        if abs(frame['first_baseline']-fragment['source_baseline'])>.01:
                            raise ValueError('flow_source_baseline_changed')
                    if frames[0]['source_fragment_id']!=fragments[0]['id']:
                        raise ValueError('flow_paragraph_start_moved')
                    gs=[{'unicode':c[0],'gid':c[1],'size':s['size'],'origin':list(c[2]),'bbox':list(c[3])}
                        for s in temp[0].get_texttrace() for c in s['chars']]
                    norm=lambda v: ''.join(c for c in unicodedata.normalize('NFKC',v) if not c.isspace())
                    if norm(''.join(chr(c['unicode']) for c in gs))!=norm(item['expected_text']):
                        raise ValueError('flow_visible_translation_changed')
                    row['flow_placements']=plan_line_flow(gs,frames,width=temp[0].rect.width,
                        font_size=item['font_size'],lineheight=item['lineheight'],
                        minimum_fragment_lines=plan.get('minimum_fragment_lines',2))
                row['bank_page'] = len(bank)
                bank.insert_pdf(temp)
            finally:
                temp.close()
            prepared.append(row)
        if policy=='source_anchored':
            placements=pack_source_anchored_items(prepared,plan['frames'],
                maximum_drift_pt=plan.get('maximum_drift_pt',54),maximum_frames=20,
                minimum_fragment_lines=plan.get('minimum_fragment_lines',2),
                preserve_complete_source_page=plan.get('preserve_complete_source_page',False))
        elif policy=='whole_paragraph':
            placements = pack_whole_items(prepared, plan['frames'],
                                          gap=plan.get('gap', 8), maximum_frames=20)
        elif policy=='verified_multiframe':
            placements=[]
            for row in prepared:
                if 'flow_placements' not in row:raise ValueError('verified_flow_text_only')
                placements.extend({**{k:v for k,v in row.items() if k!='flow_placements'},**p,
                    'bbox':p['destination'],'paragraph_parts':len(row['flow_placements'])}
                    for p in row['flow_placements'])
        else:raise ValueError('unknown_layout_policy')
        page_count = max(v['page'] for v in placements)
        if policy=='verified_multiframe':page_count=max(page_count,max(f['page'] for f in plan['frames']))
        if page_count > plan.get('maximum_pages', 10):
            raise ValueError('output_page_limit')
        templates = plan['templates']
        for i in range(page_count):
            template = templates[min(i, len(templates)-1)]
            page = result.new_page(width=template['width'], height=template['height'])
            for region in template.get('regions', []):
                with fitz.open(region['path']) as source:
                    copy_pdf_region(page, source, region.get('page_index', 0),
                                    region['clip'], region.get('destination', region['clip']))
            if template.get('number_position'):
                page.insert_text(template['number_position'], str(i+1), fontsize=9)
        true_ink_copies=[]
        for placement_index,row in enumerate(placements):
            page = result[row['page']-1]
            if row['kind'] == 'asset':
                with fitz.open(row['source']) as source:
                    copy_pdf_region(page, source, row['source_page_index'],
                                    row['native_clip'], row['bbox'])
            else:
                before_copy_count = len(glyphs(page))
                ink_copy=copy_pdf_region(page, bank, row['bank_page'],
                                row.get('bank_clip',[0, 0, row['width'], row['height']]), row['bbox'],
                                precise_glyph_heights=policy in ('source_anchored','verified_multiframe'),
                                preserve_true_glyph_ink=True,
                                maximum_ink_bleed_pt=plan.get('maximum_ink_bleed_pt',8.),
                                declared_font_aliases=row.get('declared_font_aliases',()))
                added = glyphs(page)[before_copy_count:]
                copied_unit_texts[row['id']].extend(chr(c['unicode']) for c in added)
                true_ink_copies.append({'placement_index':placement_index,'copy':ink_copy})
        for unit_id, expected_text in planned_unit_texts.items():
            actual_text = normalize_text(''.join(copied_unit_texts[unit_id]))
            if actual_text != expected_text:
                raise ValueError('rendered_unit_text_incomplete:' + unit_id)

        saved_link_records = {}
        if source_uri_actions is not None:
            import copy
            from raw_link_actions import restore_raw_link_actions
            # 释放最后一次复制持有的页引用，再刷新新增注释的页缓存。
            del page
            counts = {}
            for target_page in range(len(result)):
                records = []
                # 插入注释后刷新页缓存，按实际新建链接核对和恢复原动作。
                linked_page = result[target_page]
                linked_page = result.reload_page(linked_page)
                for target_link in linked_page.get_links():
                    uri = target_link.get('uri')
                    if target_link['kind'] != fitz.LINK_URI or uri not in source_uri_actions:
                        raise ValueError('target_uri_not_bound_to_frozen_source')
                    source_record = source_uri_actions[uri]
                    counts[uri] = counts.get(uri, 0) + 1
                    if source_record['fields'].get('id') and counts[uri] > 1:
                        raise ValueError('named_source_uri_split_requires_identity_policy')
                    record = copy.deepcopy(source_record)
                    record['candidate_xref'] = target_link['xref']
                    record['expected_fields'] = {**target_link, 'from': list(target_link['from'])}
                    records.append(record)
                saved_link_records[target_page] = records
                del linked_page
            if set(counts) != set(source_uri_actions):
                raise ValueError('source_uri_action_omitted')
            for records in saved_link_records.values():
                restore_raw_link_actions(result, records)
        expected_saved_pages=[glyphs(result[i]) for i in range(len(result))]
        # 完全相同的字体流合并；保留完整字体程序和原GID，不做字体子集。
        output.parent.mkdir(parents=True, exist_ok=True)
        result.save(output, garbage=4, deflate=True)
        with fitz.open(output) as saved:
            if len(saved)!=len(expected_saved_pages):raise ValueError('saved_render_page_count_changed')
            for i,expected in enumerate(expected_saved_pages):
                bind_saved_target(glyphs(saved[i]),expected,[])
                if source_uri_actions is not None:
                    from raw_link_actions import verify_saved_link_actions
                    verify_saved_link_actions(saved, i, saved_link_records[i])


    return {'status': 'adaptive_candidate', 'path': str(output), 'sha256': sha(output),
            'pages': page_count, 'placements': placements, 'true_ink_copies':true_ink_copies, 'quality_pass': False,
            'saved_full_native_partition_verified':True,
            'saved_complete_unit_text_verified':True,
            'complete_unit_text_count':len(planned_unit_texts),
            'saved_source_uri_actions_verified':source_uri_actions is not None,
            'source_uri_action_count':len(source_uri_actions or {}),
            'actual_pixel_visibility_proved':False, 'human_acceptance': False, 'strict_delivery': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    manifest = render_plan(json.loads(args.plan.read_text()), args.output)
    manifest['plan'] = {'path': str(args.plan.resolve()), 'sha256': sha(args.plan)}
    args.output.with_suffix('.manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
