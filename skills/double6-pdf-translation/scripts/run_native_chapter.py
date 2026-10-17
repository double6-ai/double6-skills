"""显式候选路线：单栏原生连续章节识别、串行整段翻译和统一流排。"""
from __future__ import annotations
import argparse
import html
import json
import re
import threading
import time
import unicodedata
import urllib.request
from pathlib import Path

import fitz
import psutil

from adaptive_document_renderer import render_plan, sha
from hymt_compat_proxy import clean_plain_translation
from native_chapter_structure import prepare_chapter
from text_projection_protocol import decode, ProjectionError
from css_numbers import css_number


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def resources():
    provider = codex = 0
    for proc in psutil.process_iter(['name', 'exe', 'memory_info']):
        try:
            info = proc.info
            exe, name = info['exe'] or '', (info['name'] or '').lower()
            if info['memory_info'] is None:
                continue
            rss = info['memory_info'].rss
            if '.lmstudio/' in exe or '/LM Studio.app/' in exe:
                provider += rss
            if 'codex' in name or 'node_repl' in name:
                codex = max(codex, rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return {'provider_rss': provider, 'codex_max_rss': codex,
            'task_rss': psutil.Process().memory_info().rss,
            'swap': psutil.swap_memory().used, 'at': time.time()}


def translated_spans_html(spans):
    values = []
    for span in spans:
        if span['type'] == 'equation_inline':
            values.append(span['source_html'])
        elif span['type'] == 'text':
            values.append(html.escape(span['content']))
        else:
            raise ValueError('unsupported_translated_span')
    return ''.join(values)


def run(args):
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    from run_pdf_translation import discover_latex_source
    latex, route = discover_latex_source(args.input.resolve(), argparse.Namespace())
    write(out/'source_selection.json', route)
    if latex or route.get('identity_status') == 'ambiguous':
        raise ValueError('latex_first_or_ambiguous_source_requires_primary_route')
    before = resources()
    write(out/'preflight.json', {**before, 'runner_sha256': sha(__file__),
                               'source_parser_sha256': sha(Path(__file__).with_name('native_chapter_structure.py'))})
    if before['provider_rss'] > 40*1024**3 or before['codex_max_rss'] > 20*1024**3:
        raise ValueError('initial_memory_limit')
    structure = prepare_chapter(args.input, args.start_heading, args.end_heading)
    write(out/'structure.json', structure)
    units = []
    samples = []
    breached = []
    stop = threading.Event()
    def watch():
        while not stop.is_set():
            sample = resources()
            samples.append(sample)
            if (sample['provider_rss'] > 40*1024**3 or sample['codex_max_rss'] > 20*1024**3
                    or sample['task_rss'] > 4*1024**3 or sample['swap'] > before['swap']+256*1024**2):
                breached.append(sample)
                return
            stop.wait(10)
    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        for unit in structure['units']:
            if breached:
                raise ValueError('resource_watchdog_breach')
            prompt = ('把以下英文论文的一个完整段落逐句译为准确可读的简体中文，只输出译文。'
                      '保留程度、条件、否定、施受和因果关系，不增补信息。'
                      '所有PT占位符必须每个出现一次且按原顺序保留；人名保持英文。'
                      + ('术语表：'+args.glossary.read_text()+'\n' if args.glossary else '')
                      +unit['binding']['text'])
            payload = {'model': args.model, 'messages': [{'role': 'user', 'content': prompt}],
                       'temperature': .7, 'top_p': 1., 'top_k': -1,
                       'repetition_penalty': 1., 'max_tokens': 4096}
            rawdir = out/'raw_translation'/unit['id']
            rawdir.mkdir(parents=True)
            start = time.monotonic()
            for attempt in range(2):
                attempt_dir = rawdir/f'attempt-{attempt+1}'
                attempt_dir.mkdir()
                write(attempt_dir/'request.json', {'payload': payload, 'structure_sha256': sha(out/'structure.json')})
                request = urllib.request.Request('http://127.0.0.1:1234/v1/chat/completions',
                        data=json.dumps(payload, ensure_ascii=False).encode(), headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(request, timeout=120) as response:
                    raw = response.read(2*1024**2+1)
                (attempt_dir/'response.json').write_bytes(raw)
                if len(raw) > 2*1024**2 or breached:
                    raise ValueError('response_or_resource_limit')
                response = json.loads(raw)
                choice = response['choices'][0]
                if choice['finish_reason'] != 'stop' or response['model'] != args.model:
                    raise ValueError('incomplete_response_or_model_identity')
                projected = clean_plain_translation(choice['message']['content'])
                try:
                    spans = decode(projected, unit['binding'], allow_atom_reordering=True)
                    break
                except ProjectionError as error:
                    write(attempt_dir/'failure.json', {'error': str(error)})
                    if attempt:
                        raise
                    tokens = [v['token'] for v in unit['binding']['protected']]
                    payload['messages'][0]['content'] = prompt+'\n必须严格按此列表各保留一次：'+json.dumps(tokens)+'。不要在段末重复它们。'
            plain = ''.join(v['content'] for v in spans)
            if not re.search('[\u3400-\u9fff]', plain):
                raise ValueError('no_chinese_translation')
            row = {**unit, 'translation': plain, 'projected_translation': projected,
                   'decoded_spans': spans, 'usage': response.get('usage'),
                   'elapsed_seconds': time.monotonic()-start, 'raw_sha256': sha(attempt_dir/'response.json'),
                   'model_calls': attempt+1,
                   'protected_atom_reordering_requires_semantic_review':
                       [m.group() for m in re.finditer(r'\[\[PT_\d{4}\]\]', projected)] !=
                       [v['token'] for v in unit['binding']['protected']]}
            units.append(row)
            write(rawdir/'result.json', row)
            print(json.dumps({'unit': unit['id'], 'seconds': row['elapsed_seconds']}, ensure_ascii=False), flush=True)
        write(out/'translation.json', {'units': units, 'model': args.model})
        manifest = render_chapter(structure, units, args.font, args.bold_font, out, args.translated_heading)
        write(out/'manifest.json', manifest)
    finally:
        stop.set()
        watcher.join(2)
        write(out/'resources.json', {'samples': samples, 'breaches': breached, 'after': resources()})


def render_chapter(structure, units, font, bold_font, out, translated_heading=None):
    w, h = structure['page_size']
    frame = structure['source_frame']
    if translated_heading is None:
        source_heading = structure['start_heading']['text']
        if not re.search(r'\bIntroduction\s*$', source_heading, re.I):
            raise ValueError('translated_heading_required')
        translated_heading = re.sub(r'Introduction\s*$', '引言', source_heading, flags=re.I)
    heading = {'id': 'chapter-heading', 'kind': 'heading', 'role': 'heading',
               'html': '<p>'+html.escape(translated_heading)+'</p>', 'font': str(bold_font),
               'font_sha256': sha(bold_font), 'font_size': structure['start_heading']['font_size'],
               'lineheight': 1.2, 'width': frame[2]-frame[0], 'alignment': 'left',
               'expected': translated_heading, 'source_origins': [{'source_page': structure['start_heading']['page'],
                                                        'source_bbox': structure['start_heading']['bbox']}]}
    items = [heading]
    for unit in units:
        g = unit['source_geometry']
        alignment = g['alignment'] if g['alignment'] != 'unknown' else 'justify'
        content = translated_spans_html(unit['decoded_spans'])
        items.append({'id': unit['id'], 'kind': 'paragraph', 'role': 'body',
                      'html': f'<p style="text-align:{alignment};text-indent:{css_number(g["first_line_indent_pt"])}pt;margin-left:{css_number(max(0,-g["first_line_indent_pt"]))}pt">{content}</p>',
                      'font': str(font), 'font_sha256': sha(font), 'font_size': structure['body_font_size'], 'lineheight': 1.5,
                      'width': frame[2]-frame[0], 'alignment': alignment,
                      'expected': unit['translation'], 'source_origins': unit['source_origins'],
                      'source_geometry': g})
    plan = {'schema_version': 1, 'sources': [structure['source']], 'input_source':structure['source'],'items': items,
            'frames': [{'page': i+1, 'column': 0, 'bbox': frame} for i in range(5)],
            'templates': [{'width': w, 'height': h, 'regions': [], 'number_position': [w/2, h*.94]}],
            'gap': structure['source_paragraph_gap_pt'] if structure.get('source_paragraph_gap_pt') is not None else 8,
            'maximum_pages': 5}
    write(out/'plan.json', plan)
    manifest = render_plan(plan, out/'chapter.zh.pdf')
    norm = lambda text: ''.join(c for c in unicodedata.normalize('NFKC', text) if not c.isspace())
    checks = []
    with fitz.open(manifest['path']) as result:
        for row in manifest['placements']:
            page = result[row['page']-1]
            box = fitz.Rect(row['bbox'])
            glyphs = [(chr(c[0]), c[2], c[3], s['size']) for s in page.get_texttrace() for c in s['chars']
                      if box.contains(fitz.Point((c[3][0]+c[3][2])/2, (c[3][1]+c[3][3])/2))]
            actual = ''.join(g[0] for g in glyphs)
            if norm(actual) != norm(row['expected']):
                raise ValueError('visible_translation_mismatch:'+row['id'])
            checks.append({'id': row['id'], 'text_exact': True, 'one_frame': True,
                           'page': row['page'], 'glyph_count': len(glyphs)})
    manifest.update(actual_text_checks=checks, scope=structure['scope'],
                    source_pages=structure['selected_pages'], plan_sha256=sha(out/'plan.json'))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--start-heading', required=True)
    parser.add_argument('--end-heading', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--glossary', type=Path)
    parser.add_argument('--translated-heading')
    parser.add_argument('--font', required=True, type=Path)
    parser.add_argument('--bold-font', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    run(parser.parse_args())
