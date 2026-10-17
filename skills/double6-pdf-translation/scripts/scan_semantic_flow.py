"""显式扫描段落按完整译文试排一次，再沿源片段框分配完整行。"""
from pathlib import Path
import json
import fitz
from semantic_paragraph_flow import plan_line_flow


def prepare_scan_flows(contract, rows, font, insert_textbox, bound, output):
    evidence = contract.get('scan_semantic_flow_ref')
    if evidence is None:
        return {}, [], []
    spec = json.loads(bound(evidence).read_text())
    assert spec['source'] == contract['source_pdf_ref'], 'scan_flow_source_identity'
    by_id = {r['region_id']: r for r in rows}
    mapping, banks, reports = {}, [], []
    for group in spec['groups']:
        members = [by_id[k] for k in group['region_ids']]
        assert len(members) >= 2 and group.get('boundary_evidence'), 'scan_flow_verified_boundary_required'
        assert all(r['trial_source_policy']['source_role'] == 'body' for r in members), 'scan_flow_body_only'
        pages = [r['page'] for r in members]
        blanks = {b['page']: b for b in spec.get('blank_source_pages', [])}
        for a, b in zip(pages, pages[1:]):
            for n in range(a + 1, b):
                assert n in blanks, 'scan_flow_unverified_page_gap'
                bound(blanks[n]['image_ref'])
                assert blanks[n].get('review_ref'), 'scan_flow_blank_review_required'
                bound(blanks[n]['review_ref'])
        policy = contract['typography']['body']
        size, step = policy['font_size_pt'], policy['baseline_step_pt']
        width = min(r['original_layout_bbox'][2] - r['original_layout_bbox'][0] for r in members)
        bank = fitz.open()
        page = bank.new_page(width=width, height=3000)
        metrics = fitz.Font(fontfile=str(font))
        page.insert_font(fontname='PTFlow', fontbuffer=bytes(metrics.buffer))
        fs, spare = insert_textbox(page, page.rect, group['target_text'], font_alias='PTFlow',
            initial_font_size=size, minimum_font_size=size, font_metrics=metrics,
            align=0, first_line_indent_pt=members[0].get('chinese_uniform_body_indent_pt', 0),
            lineheight=step / size, baseline_step_pt=step, paint_background=False)
        assert spare >= 0 and fs == size, 'scan_flow_bank_overflow'
        glyphs = [dict(codepoint=c[0], origin=list(c[2]), bbox=list(c[3]), size=s['size'])
                  for s in page.get_texttrace() for c in s['chars']]
        text = ''.join(chr(c['codepoint']) for c in glyphs)
        assert ''.join(text.split()) == ''.join(group['target_text'].split()), 'scan_flow_bank_text_changed'
        first = min(c['origin'][1] for c in glyphs)
        frames = [dict(id=r['region_id'], source_page=r['page'], column=r['trial_source_policy']['source_column'],
                       bbox=r['original_layout_bbox'], first_baseline=r['original_layout_bbox'][1] + first)
                  for r in members]
        places = plan_line_flow(glyphs, frames, width=width, font_size=size, lineheight=step / size,
                                minimum_fragment_lines=1)
        assert len(places) == len(members), 'scan_flow_unconsumed_source_fragment'
        for r, place in zip(members, places):
            r['translation'] = ''.join(chr(c['codepoint']) for c in place['glyphs'])
            r['semantic_line_flow'] = dict(group_id=group['id'], line_range=place['line_range'],
                complete_target=group['target_text'], first_line_indent_pt=members[0].get('chinese_uniform_body_indent_pt', 0),
                source_page=r['page'], fit_scale=1.)
            assert r['region_id'] not in mapping, 'scan_flow_duplicate_region'
            mapping[r['region_id']] = (bank, place, size)
        bank_path = Path(output) / ('flow_bank_' + group['id'] + '.pdf')
        bank.save(bank_path, garbage=4, deflate=True)
        banks.append(bank)
        reports.append(dict(group_id=group['id'], source_pages=pages, complete_target=group['target_text'],
                            bank=str(bank_path), placements=places, width=width, font_size_pt=size,
                            baseline_step_pt=step, input_adaptation='explicit reviewed fragments and blank scan page identities'))
    return mapping, banks, reports
