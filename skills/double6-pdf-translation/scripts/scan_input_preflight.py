# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""扫描输入的有界事实预检；源图资格保持具名确认，绝不改写输入。"""
from pathlib import Path
import argparse
import hashlib
import json
import urllib.request
import fitz
from pdf_input_preflight import PreflightError, finding, inspect_pdf, raise_for_blocked

VERSION = '109-unpublished'


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def checked(value):
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'}:
        raise ValueError('exact_path_SHA_reference_required')
    path = Path(value['path'])
    if not path.is_file() or ref(path) != value:
        raise ValueError('parent_reference_changed:' + str(path))
    return path


def image_union_fraction(boxes, page):
    clipped = [fitz.Rect(b) & page for b in boxes]
    clipped = [b for b in clipped if not b.is_empty]
    xs = sorted({v for b in clipped for v in (b.x0, b.x1)})
    area = 0
    for a, b in zip(xs, xs[1:]):
        intervals = sorted((r.y0, r.y1) for r in clipped if r.x0 < b and r.x1 > a)
        end = -1e30
        for lo, hi in intervals:
            area += (b-a) * max(0, hi-max(lo, end))
            end = max(end, hi)
    return area / page.get_area() if page.get_area() else 0


def model_inventory(url, requested=None):
    result = {'url': url, 'requested_model': requested, 'generation_calls': 0,
              'automatic_load_or_fallback': False, 'models': []}
    if not url:
        result.update(status='not_configured', requested_status='UNKNOWN')
        return result
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            data = response.read(8*1024*1024+1)
        if len(data) > 8*1024*1024:
            raise ValueError('model_catalog_too_large')
        payload = json.loads(data)
        for row in payload.get('models', []):
            if row.get('type') != 'llm':
                continue
            result['models'].append({k: row.get(k) for k in
                ('key', 'selected_variant', 'variants', 'loaded_instances', 'format', 'quantization', 'size_bytes')})
        keys = [x['key'] for x in result['models']]
        aliases = [i.get('id') for x in result['models'] for i in x.get('loaded_instances') or []]
        variants = [v for x in result['models'] for v in x.get('variants') or []]
        result.update(status='observed', valid_load_keys=keys, loaded_instance_ids=aliases)
        result['requested_status'] = ('not_requested' if requested is None else
            'valid_load_key' if requested in keys else 'loaded_instance_id' if requested in aliases else
            'variant_is_not_load_key' if requested in variants else 'not_in_inventory')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update(status='unavailable', error=type(exc).__name__, requested_status='UNKNOWN')
    return result


def inspect_input(source, *, max_pages=2, source_review=None, reuse_contract=None,
                  model=None, catalog_url=None, fresh=False):
    source = Path(source).resolve()
    if source_review and reuse_contract or fresh and reuse_contract:
        raise ValueError('fresh_review_and_frozen_replay_are_distinct_routes')
    if not 1 <= max_pages <= 20:
        raise PreflightError('page_limit_exceeded', f'--max-pages 必须在 1–20 之间（当前 {max_pages}）。', max_pages=max_pages)
    # 结构化预检：加密、截断/损坏、页数超限各自给出独立错误码，不再合并为一个含糊错误。
    facts = inspect_pdf(source, max_pages=max_pages, require_digital=False, target_language='zh')
    if any(f['code'] == 'page_limit_exceeded' for f in facts['findings']):
        for f in facts['findings']:
            if f['code'] == 'page_limit_exceeded':
                f['message'] = (f"PDF 共 {facts['page_count']} 页，超过扫描预检 --max-pages {max_pages}（默认 2，最大 20）。"
                                '电子 PDF 请改用 candidate --route digital_pdf（完整 1–5 页）。')
    raise_for_blocked(facts)
    sr = ref(source)
    blockers, todos, pages = [], [], []
    with fitz.open(source) as doc:
        count = len(doc)
        for index, page in enumerate(doc):
            visible = hidden = 0
            for span in page.get_texttrace():
                n = len(span['chars'])
                if span.get('type') == 3 or span.get('opacity', 1) == 0:
                    hidden += n
                else:
                    visible += n
            images = page.get_image_info()
            if len(images) > 10000 or visible+hidden > 100000:
                raise ValueError('page_complexity_limit')
            pages.append({'page': index+1, 'media_box_pt': list(page.mediabox),
                'crop_box_pt': list(page.cropbox), 'rect_pt': list(page.rect), 'rotation': page.rotation,
                'visible_render_mode_glyphs': visible, 'hidden_render_mode_glyphs': hidden,
                'visibility_limit': 'render mode/opacity only; occlusion and semantic OCR accuracy UNKNOWN',
                'image_count': len(images), 'image_union_coverage': image_union_fraction([x['bbox'] for x in images], page.rect),
                'largest_image_bbox_coverage': max([fitz.Rect(x['bbox']).get_area()/page.rect.get_area() for x in images]+[0])})
    qualification = {'complete_work': 'UNKNOWN', 'handwriting': 'UNKNOWN',
        'automatic_semantic_or_handwriting_detection': False, 'source_image_review_required': True}
    if reuse_contract:
        from scan_structure_proposal import reused_preparation_inputs
        cp = checked(reuse_contract)
        explicit = {k: None for k in ('ocr', 'groups', 'roles', 'font', 'ink', 'raw_targets', 'targets', 'review')}
        reused_preparation_inputs(source, cp, explicit)
        qualification.update(scope='inherited_exact_frozen_preparation_only',
            preparation_ref=ref(cp), source_image_review_required=False,
            note='No new qualification signoff; existing bound source/group/role evidence remains required. This does not automatically prove complete work or handwriting.')
    elif source_review:
        rp = checked(source_review)
        review = json.loads(rp.read_text())
        if review.get('source') != sr or not review.get('reviewer') or not review.get('source_image_evidence_ref'):
            raise ValueError('source_review_not_bound_to_source_image')
        checked(review['source_image_evidence_ref'])
        qualification.update(complete_work=review.get('complete_work', 'UNKNOWN'),
            handwriting=review.get('script_kind', 'UNKNOWN'), review_ref=ref(rp), source_image_review_required=False)
        if review.get('complete_work') is not True:
            blockers.append('complete_work_not_confirmed')
        if review.get('script_kind') not in ('printed', 'printed_with_protected_signature'):
            blockers.append('handwritten_or_unknown_requires_supported_source_decision')
    else:
        todos += ['confirm_complete_work_from_source_image', 'confirm_printed_handwritten_or_mixed_from_source_image']
    hidden_total = sum(p['hidden_render_mode_glyphs'] for p in pages)
    visible_total = sum(p['visible_render_mode_glyphs'] for p in pages)
    if hidden_total:
        todos.append('hidden_OCR_present: review original layer and explicitly choose a route; no automatic stripping or rewrapping')
        if fresh:
            blockers.append('hidden_OCR_requires_explicit_route_decision')
    if fresh and any(p['visible_render_mode_glyphs'] >= 30 or p['largest_image_bbox_coverage'] < .85 for p in pages):
        blockers.append('outside_finite_image_scan_input_profile')
    inventory = ({'status': 'not_required', 'requested_model': model,
                  'requested_status': 'not_checked_frozen_replay', 'network_probes': 0,
                  'reason': 'cache-only replay uses frozen targets; no current model needed'}
                 if reuse_contract else model_inventory(catalog_url, model))
    model_problem = inventory['status'] != 'observed' or inventory['requested_status'] not in ('valid_load_key', 'loaded_instance_id')
    if fresh and (not model or model_problem):
        blockers.append('fresh_translation_model_must_be_explicit_and_available')
    elif model_problem and model and not reuse_contract:
        todos.append('model_not_verified_but_not_required_for_frozen_replay')
    if fresh and not source_review:
        blockers.append('source_image_qualification_unconfirmed')
    kinds = {p['page']: p['kind'] for p in facts['pages']}
    digital_route = {'all_pages_native_text': bool(kinds) and all(k == 'native_text' for k in kinds.values()),
                     'page_kinds': kinds,
                     'note': 'heuristic only; candidate --route digital_pdf re-checks every page with route_pdf'}
    if digital_route['all_pages_native_text'] and not reuse_contract and not source_review:
        todos.append('all_pages_have_native_text_layer: if this is a digital PDF (1–5 pages), use candidate --route digital_pdf instead of scan preparation')
    return {'schema_version': 1, 'development_revision': VERSION,
        'status': 'blocked' if blockers else 'needs_source_review' if not reuse_contract and not source_review else 'ready_for_declared_route',
        'source': sr, 'page_count': count, 'pages': pages, 'qualification': qualification,
        'route': 'fresh_scan_preparation' if fresh else 'frozen_replay' if reuse_contract else 'facts_only',
        'blockers': blockers, 'todos': todos, 'model_inventory': inventory,
        'model_required': fresh, 'input_modified': False, 'physical_scale_policy': 'preserve_input_media_and_crop_boxes',
        'new_OCR_MT_calls': 0, 'human_acceptance': False, 'strict_delivery': False,
        'error_code': None, 'findings': facts['findings'], 'source_language': facts['source_language'],
        'digital_route': digital_route, 'code_ref': ref(__file__)}


def blocked_report(source, exc):
    """预检失败也输出与正常报告同形的结构化 JSON，而不是原始 traceback。"""
    source = Path(source)
    try:
        sr = ref(source)
    except OSError:
        sr = {'path': str(source.resolve()), 'sha256': None}
    if isinstance(exc, PreflightError):
        findings = getattr(exc, 'result', {}).get('findings') or [exc.finding]
        code = exc.code
    else:
        code = 'invalid_preflight_request'
        findings = [finding(code, f'{type(exc).__name__}: {exc}'[:500])]
    facts = getattr(exc, 'result', {}) if isinstance(exc, PreflightError) else {}
    return {'schema_version': 1, 'development_revision': VERSION, 'status': 'blocked',
        'source': sr, 'page_count': facts.get('page_count'), 'pages': [], 'qualification': {},
        'route': 'facts_only', 'blockers': [code], 'todos': [], 'model_inventory': {'status': 'not_checked'},
        'model_required': False, 'input_modified': False, 'physical_scale_policy': 'preserve_input_media_and_crop_boxes',
        'new_OCR_MT_calls': 0, 'human_acceptance': False, 'strict_delivery': False,
        'error_code': code, 'findings': findings, 'source_language': facts.get('source_language'),
        'code_ref': ref(__file__)}


def load_run_config(path):
    config = json.loads(Path(path).read_text())
    allowed = {'schema_version', 'mode', 'preparation_ref', 'max_pages', 'model', 'model_catalog_url'}
    if not isinstance(config, dict) or set(config)-allowed or config.get('schema_version') != 1 or config.get('mode') not in ('reprepare', 'rebuild'):
        raise ValueError('unsupported_reviewed_scan_config')
    cp = checked(config['preparation_ref'])
    if type(config.get('max_pages', 2)) is not int or not 1 <= config.get('max_pages', 2) <= 20:
        raise ValueError('invalid_config_page_scope')
    contract = json.loads(cp.read_text())
    source = checked(contract['source_pdf_ref'])
    # Validate all old source/target/font/code/materialization parents before any output or heavy job.
    from scan_structure_proposal import reused_preparation_inputs
    explicit = {k: None for k in ('ocr', 'groups', 'roles', 'font', 'ink', 'raw_targets', 'targets', 'review')}
    reused_preparation_inputs(source, cp, explicit)
    return config, source, cp


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--max-pages', type=int, default=2)
    p.add_argument('--source-review', type=Path)
    p.add_argument('--reuse-contract', type=Path)
    p.add_argument('--model')
    p.add_argument('--catalog-url', default=None)
    p.add_argument('--fresh', action='store_true')
    a = p.parse_args(argv)
    try:
        result = inspect_input(a.input, max_pages=a.max_pages,
            source_review=ref(a.source_review) if a.source_review else None,
            reuse_contract=ref(a.reuse_contract) if a.reuse_contract else None,
            model=a.model, catalog_url=a.catalog_url, fresh=a.fresh)
    except (PreflightError, OSError) as exc:
        result = blocked_report(a.input, exc)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'status': result['status'], 'error_code': result.get('error_code'), 'page_count': result['page_count'],
                      'blockers': result['blockers'], 'warnings': [x['code'] for x in result.get('findings', []) if x['severity'] == 'warning'],
                      'output': str(a.output.resolve())}, ensure_ascii=False))
    return 2 if result['blockers'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
