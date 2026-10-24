"""显式图片封面 + 电子正文的有界实验路线；逐段执行后核对来源再合成。"""
from __future__ import annotations
from stable_page_raster import stable_get_pixmap

import copy
import json
from pathlib import Path
from typing import Any, Callable

from assess_delivery import sha256, read_object, inspect_pdf, check_bilingual_sides


def cover_plan(pages: list[dict], *, max_pages: int = 5) -> dict | None:
    if not 2 <= max_pages <= 20:
        raise ValueError("--mixed-max-pages must be between 2 and 20")
    if not 2 <= len(pages) <= max_pages:
        return None
    if [p.get('page') for p in pages] != list(range(1, len(pages) + 1)):
        return None
    first = pages[0]
    if (first.get('decision') not in {'scanned', 'needs_review'}
        or first.get('full_page_image_coverage', 0) < .85
        or not 0 <= first.get('text_chars', 99999) < 120
        or first.get('span_count', 99999) > 8
        or first.get('image_count', 0) < 1):
        return None
    if any(p.get('decision') != 'digital' or p.get('confidence', 0) < .75
           or p.get('abnormal_char_rate', 1) > .05 for p in pages[1:]):
        return None
    return {'schema_version': 1, 'cover_pages': [1], 'body_pages': list(range(2, len(pages) + 1)),
            'page_count': len(pages), 'policy': 'explicit_image_cover_translate_v1',
            'cover_route': 'scanned_raster', 'body_route': 'pdf_backend',
            'strict_delivery': False, 'human_acceptance': 'pending'}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _page_signature(page) -> dict:
    import fitz
    import hashlib
    pix = stable_get_pixmap(page, matrix=fitz.Matrix(.5, .5), colorspace=fitz.csGRAY, alpha=False)
    return {'size': list(page.rect), 'rotation': page.rotation,
            'text': ''.join(page.get_text().split()),
            'pixels_sha256': hashlib.sha256(pix.samples).hexdigest()}


def verify_composition(candidate: Path, components: list[dict]) -> dict:
    """合成页须逐页等于声明的子候选；核对图像、文本、尺寸与旋转。"""
    import fitz
    rows = []
    with fitz.open(candidate) as merged:
        offset = 0
        for component in components:
            part = Path(component['translated_pdf'])
            if sha256(part) != component['candidate_sha256']:
                return {'status': 'blocking', 'reason': 'component_sha_changed'}
            with fitz.open(part) as document:
                if len(document) != len(component['source_pages']):
                    return {'status': 'blocking', 'reason': 'component_page_count'}
                for index, page in enumerate(document):
                    if offset >= len(merged):
                        return {'status': 'blocking', 'reason': 'merged_page_count'}
                    ok = _page_signature(page) == _page_signature(merged[offset])
                    rows.append({'page': offset + 1, 'component': component['name'],
                                 'component_page': index + 1, 'source_page': component['source_pages'][index],
                                 'status': 'ok' if ok else 'mismatch'})
                    offset += 1
        if offset != len(merged):
            return {'status': 'blocking', 'reason': 'merged_page_count'}
    return {'status': 'ok' if all(row['status'] == 'ok' for row in rows) else 'blocking', 'pages': rows}


def run_mixed_cover(input_pdf: Path, output_dir: Path, route: dict, args: Any, *,
                    body_runner: Callable, cover_runner: Callable | None = None) -> dict:
    import fitz
    from .pipeline import run_scanned_translation
    from build_bilingual_pdf import bilingual_direction, build_manifest
    cover_runner = cover_runner or run_scanned_translation
    plan = cover_plan(route.get('pages', []), max_pages=getattr(args, 'mixed_max_pages', 5))
    if (not plan or route.get('document_route') != 'mixed_cover_digital'
        or route.get('dispatch_allowed') is not True or route.get('mixed_cover_plan') != plan
        or route.get('latex_source', {}).get('status') in {'ambiguous', 'expected_but_missing', 'verified_match'}
        or getattr(args, 'mixed_cover_mode', 'off') != 'translate'):
        raise ValueError('mixed cover requires the explicit, verified narrow route')
    if getattr(args, 'pages', None):
        raise ValueError('mixed cover requires a physical PDF subset; --pages cannot obscure page mapping')
    if any((output_dir / name).exists() for name in ['mixed_parts', 'mixed_manifest.json', 'render_manifest.json']):
        raise ValueError('mixed cover requires a fresh output attempt')
    output_dir.mkdir(parents=True, exist_ok=True)
    source_sha = sha256(input_pdf)
    if route.get('input_sha256') != source_sha:
        raise ValueError('mixed source SHA mismatch')
    manifest = {'schema_version': 1, 'document_route': 'mixed_cover_digital', 'status': 'running',
                'input_pdf': str(input_pdf), 'input_sha256': source_sha, 'plan': plan,
                'components': [], 'outputs': {}, 'strict_delivery': False, 'human_visual_accepted': False}
    manifest_path = output_dir / 'mixed_manifest.json'
    render_path = output_dir / 'render_manifest.json'
    _write(manifest_path, manifest)
    try:
        with fitz.open(input_pdf) as source:
            if len(source) != plan['page_count'] or source.needs_pass:
                raise ValueError('mixed input page count or encryption changed')
            for name, pages in [('cover', plan['cover_pages']), ('body', plan['body_pages'])]:
                part_dir = output_dir / 'mixed_parts' / name
                part_dir.mkdir(parents=True)
                subset = part_dir / 'input.pdf'
                with fitz.open() as part:
                    part.insert_pdf(source, from_page=pages[0]-1, to_page=pages[-1]-1)
                    part.save(subset)
                child_args = copy.deepcopy(args)
                child_args.input_pdf = str(subset)
                child_args.output_dir = str(part_dir / 'run')
                child_args.pages = None
                child_args.mixed_cover_mode = 'off'
                child_args.source_override = None
                # 子流水线各自的质量合同要求双语；保留它们作为中间证据。
                child_args.dual = True
                child_args.bilingual_layout = 'en-left-zh-right'
                if name == 'cover':
                    child_args.scanned_max_pages = 1
                    child_args.scanned_page_profile = 'image_cover'
                    cover_page = {**route['pages'][0], 'decision': 'scanned',
                                  'original_decision': route['pages'][0]['decision']}
                    child_route = {**route, 'input_pdf': str(subset), 'input_sha256': sha256(subset),
                                   'document_route': 'scanned_raster', 'intended_render_source': 'scanned_raster',
                                   'pages': [cover_page], 'raster_candidate_pages': [1], 'mixed_cover_plan': None,
                                   'mixed_reason': None, 'notes': ['explicit image-cover policy; original page 1']}
                    _write(Path(child_args.output_dir) / 'route_manifest.json', child_route)
                    child = cover_runner(subset, Path(child_args.output_dir), child_route, child_args)
                else:
                    child = body_runner(child_args)
                child_render_path = Path(child_args.output_dir) / 'render_manifest.json'
                child_render = read_object(child_render_path)
                expected = plan[f'{name}_route']
                if (child.get('status') not in {'ok', 'partial'} or child_render.get('status') not in {'ok', 'partial'}
                    or child_render.get('actual_render_source') != expected):
                    raise ValueError(f'{name} child route or quality blocked')
                child_route = read_object(Path(child_args.output_dir) / 'route_manifest.json')
                if child_route.get('input_sha256') != sha256(subset) or child_route.get('document_route') != expected:
                    raise ValueError(f'{name} child input identity mismatch')
                gate = read_object(Path(child_args.output_dir) / 'scan_quality_gate.json') if name == 'cover' else child_render.get('validation', {}).get('gates', {})
                if (gate.get('status') not in {'ok', 'partial'}
                    or any(g.get('status') in {'blocking', 'error'} for g in gate.get('gates', []))
                    or any(g.get('severity') in {'blocking', 'error', 'high'} for g in gate.get('issues', []))):
                    raise ValueError(f'{name} child quality evidence missing or blocked')
                outputs = child_render.get('outputs', {})
                raw = outputs.get('translated_pdf') or outputs.get('mono_pdf')
                candidate = Path(raw) if raw else None
                if candidate and not candidate.is_absolute():
                    candidate = Path(child_args.output_dir) / candidate
                pdf = inspect_pdf(candidate, 20)
                if pdf.get('status') != 'ok' or pdf.get('page_count') != len(pages) or not pdf.get('cjk_count'):
                    raise ValueError(f'{name} child PDF missing, page mapping changed or Chinese layer absent')
                with fitz.open(subset) as original, fitz.open(candidate) as translated:
                    if any(list(a.rect) != list(b.rect) or a.rotation != b.rotation for a,b in zip(original, translated)):
                        raise ValueError(f'{name} child page geometry changed')
                manifest['components'].append({'name': name, 'source_pages': pages, 'route': expected,
                    'source_pdf': str(subset), 'source_sha256': sha256(subset), 'translated_pdf': str(candidate),
                    'candidate_sha256': pdf['sha256'], 'render_manifest': str(child_render_path),
                    'render_manifest_sha256': sha256(child_render_path), 'quality_status': gate['status'],
                    'quality_evidence_sha256': {filename: sha256(Path(child_args.output_dir)/filename)
                        for filename in ('quality_report.md', 'qa_checks.json', 'scan_quality_gate.json')
                        if (Path(child_args.output_dir)/filename).is_file()},
                    'delivery_mode': child_render.get('delivery_mode'), 'human_acceptance_inherited': False})
                _write(manifest_path, manifest)
            mono = output_dir / 'translated_mixed.pdf'
            with fitz.open() as merged:
                for component in manifest['components']:
                    with fitz.open(component['translated_pdf']) as child_pdf:
                        merged.insert_pdf(child_pdf)
                merged.set_metadata(source.metadata)
                merged.set_toc(source.get_toc())
                # 分段会丢失跨段内部跳转；按原始整本文档页号重建内部链接。
                for index, original in enumerate(source):
                    for link in merged[index].get_links():
                        if link['kind'] == fitz.LINK_GOTO:
                            merged[index].delete_link(link)
                    for link in original.get_links():
                        if link['kind'] == fitz.LINK_GOTO:
                            merged[index].insert_link({k:v for k,v in link.items() if k not in {'xref','id'}})
                merged.save(mono)
        composition = verify_composition(mono, manifest['components'])
        if composition['status'] != 'ok':
            raise ValueError('mixed composition differs from declared child pages')
        dual = None
        side_check = None
        if getattr(args, 'dual', True) and getattr(args, 'bilingual_layout', 'en-left-zh-right') != 'off':
            target = output_dir / 'bilingual_mixed.pdf'
            bilingual = build_manifest(input_pdf, mono, target,
                                       direction=bilingual_direction('en', 'zh', basis='route_contract_scanned_raster_en_to_zh'))
            _write(output_dir / 'bilingual_pdf_manifest.json', bilingual)
            if bilingual.get('status') != 'ok':
                raise ValueError('mixed bilingual build failed')
            side_check = check_bilingual_sides(input_pdf, mono, target, max_pages=20)
            if side_check['status'] != 'ok':
                raise ValueError('mixed bilingual sides inconsistent')
            dual = target
        if sha256(input_pdf) != source_sha:
            raise ValueError('mixed input changed during execution')
        manifest.update(status='partial', actual_render_source='mixed_cover_digital',
                        composition_verification=composition, bilingual_verification=side_check,
                        candidate_sha256=sha256(mono),
                        outputs={'translated_pdf': str(mono), 'standard_bilingual_pdf': str(dual) if dual else None},
                        delivery_mode=('fast_full_translation_draft' if any(c['delivery_mode'] == 'fast_full_translation_draft' for c in manifest['components'])
                                       else 'experimental_mixed_candidate_pending_review'),
                        review_required=['semantic_review', 'full_page_sweep', 'targeted_region_audit', 'human_acceptance'])
        _write(manifest_path, manifest)
        _write(render_path, manifest)
        return {**manifest, 'mixed_manifest': str(manifest_path), 'render_manifest': str(render_path)}
    except Exception as exc:
        manifest.update(status='blocking', actual_render_source=None, outputs={},
                        error_type=type(exc).__name__, reason=str(exc))
        _write(manifest_path, manifest)
        _write(render_path, manifest)
        raise
