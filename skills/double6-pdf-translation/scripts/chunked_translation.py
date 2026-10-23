# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-23：2.0.0-rc.9 新增（长文档分块翻译）；变更见Skill根目录MODIFICATIONS.md。
"""长文档分块：按页范围切成有界块，逐块走既有 candidate 路线，再按原页序合并（fail-closed）。

本模块只做三件纯文档工作，均由 ``paper_translation_workflow.py chunked-candidate`` 在有界任务
（``run_bounded``，操作名 ``chunk-plan`` / ``chunk-merge``）里调用，不调用模型、不联网：

* ``plan``：按冻结的分块合同（``CHUNKING_CONTRACT``）和预检逐页分类（``pdf_input_preflight.classify_page``）
  划分页范围；在每块页数上限内优先选“安全边界”（不在表格/公式/续表/续图/段落中途切开），
  不得已时记录跨块续接；写出每块源 PDF（逐 sha 登记）、原文目录/页码标签/内部链接，以及
  整份文档的术语上下文（与单份 candidate 相同的 ``prepare_source``/``write_glossary``/
  ``enrich_quality_artifacts``，供每块提示词共用，保证跨块术语一致）。
* ``merge``：核对每块产物 sha 与页数后按原页序拼接（主版式译文、QA 可读件），恢复原文目录、
  页码标签和跨块内部链接，逐页核对页面尺寸与图片指纹（无缺页、无重复页、无错位）。
* ``aggregate_quality``：合并综合质量，任何一块 fail 或合并核对失败即整份 fail；结论永远
  不好于最差的一块（fail > unverified > pass）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
# 冻结合同：FREEZE.chunking_contract 必须与此逐字相同（改变任何一项都需要重新冻结）。
CHUNKING_CONTRACT = {
    'protocol': 'page_range_chunks_v1',
    'max_document_pages': 500,
    # 单块页数上限：电子页实测约 17 s/页 + 固定开销（5 页 83 s），扫描页另加 OCR 约 8 s/页；
    # 都留出 120 s 单任务时限的余量。超时/超内存的块再二分，直到单页。
    'max_pages_per_chunk': {'digital_pdf': 4, 'scanned_ocr': 2},
    'boundary_policy': 'safe_page_boundary_v1',
    'boundary_search_pages': 1,
    # backend_timeout：后端在本任务时限内的内部超时（render_manifest.errors 记 error_type=timeout），
    # 同属时间预算耗尽，二分而不是指望重试命中缓存（实测见 references/chunked-translation.md）。
    'split_on_resource_stop': ['task_timeout', 'whole_job_deadline_exceeded', 'task_memory_limit', 'backend_timeout'],
    'retry_transient_failures': 1,
    'merge': 'ordered_page_concat_v1',
    'quality': 'worst_chunk_fail_closed_v1',
    'terminology': 'document_term_context_v1',
    'resume': 'sha_verified_chunk_reuse_v1',
    # 块从整份文档的参考文献区中间开始时，把区状态（整份源文上同一套标题判定）带入该块的残留检查。
    'reference_region': 'document_state_carry_in_v1',
    # 每次尝试结束后逐张 launch 回执做整树核实（恢复扫描：nonce / 本次进程组 / 已核验父链；查询失败的同用户
    # 进程记为归属未知，不当作已清理）；存活即回收并核实，核实不了即失败关闭并停止调度后续块（重任务并发 1）。
    'post_attempt_guard': 'launch_receipt_recovery_scan_v2',
    # 块完成并登记后删除的后端中间件（字体子集化临时 PDF，单块可达数百 MB；不被任何回执/门引用）。
    # 删除前在 CHUNK_PRUNED.json 登记文件名、字节数与 SHA-256。
    'prune_backend_temporaries': ['_backend_working/*/temp_subset_input_mono.pdf',
                                  '_backend_working/*/temp_subset_output_mono.pdf'],
}
QUALITY_ORDER = {'pass': 0, 'unverified': 1, 'fail': 2}
TERM_CONTEXT_PROTOCOL = 'document_term_context_v1'
PAGE_KIND_ROUTE = {'native_text': 'digital_pdf', 'scanned_image': 'scanned_ocr'}
_TERMINAL = re.compile(r'[.!?;:。！？；：…)\]}"”’》」』]\s*$')
_OPEN_MATH = re.compile(r'(?:[=+×·−<>≤≥∑∫]|(?<![A-Za-z])[-–])\s*$')
_CONTINUES_NEXT = re.compile(r'(?:continued on (?:the )?next page|continued overleaf|\(continued\)\s*$|续下页|（未完）|未完待续)', re.I)
_CONTINUED = re.compile(r'^\s*(?:(?:table|figure|fig\.)\s*[\w.\-]+\s*[:.(\[]?\s*\(?(?:continued|cont\.)|续表|续图|（续）|\(continued\))', re.I)
_SUBSET = re.compile(r'^[A-Z]{6}\+')


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def file_ref(path: Path | str) -> dict[str, str]:
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256_file(path)}


def write_json(path: Path, value: Any, *, new: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x' if new else 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


# ---------------------------------------------------------------- 边界信号
def _page_lines(page) -> list[tuple[float, float, float, str]]:
    """(y0, y1, x0, text)，按阅读顺序；去掉纯页码/罗马数字行。"""
    lines = []
    for block in page.get_text('dict').get('blocks', []):
        if block.get('type') != 0:
            continue
        for line in block.get('lines', []):
            text = ''.join(span.get('text', '') for span in line.get('spans', [])).strip()
            if text and not re.fullmatch(r'[\divxlcIVXLC\s\-–—.|/]+', text):
                lines.append((round(line['bbox'][1], 1), line['bbox'][3], line['bbox'][0], text))
    return sorted(lines)


def _running_key(text: str) -> str:
    return re.sub(r'\d+|[ivxlc]+\b', '#', text.lower()).strip()


def running_lines(pages: list[list[tuple[float, float, float, str]]], heights: list[float]) -> set[str]:
    """页眉页脚：出现在上下 12% 带、且（数字归一后）在 ≥ 30% 页面（至少 3 页）重复的行。"""
    counts: dict[str, int] = {}
    for lines, height in zip(pages, heights):
        keys = {_running_key(t) for y0, y1, _, t in lines if y1 < height * 0.12 or y0 > height * 0.88}
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    threshold = max(3, int(len(pages) * 0.3 + 0.999))
    return {key for key, n in counts.items() if n >= threshold}


def _body(lines, height, running) -> list[str]:
    return [t for y0, y1, _, t in lines
            if not ((y1 < height * 0.12 or y0 > height * 0.88) and _running_key(t) in running)
            and not (y1 < height * 0.04 or y0 > height * 0.96)]


def _tables(page) -> list[tuple[float, float]]:
    try:
        return [(t.bbox[1], t.bbox[3]) for t in page.find_tables().tables]
    except Exception:  # noqa: BLE001 - 表格探测失败按“未知”处理，不当作安全
        return [(-1.0, -1.0)]


def document_signals(document) -> list[dict[str, Any]]:
    pages = [_page_lines(page) for page in document]
    heights = [page.rect.height or 1 for page in document]
    running = running_lines(pages, heights)
    bodies = [_body(lines, h, running) for lines, h in zip(pages, heights)]
    tables = [_tables(page) for page in document]
    return [boundary_signals(bodies[i], bodies[i + 1], tables[i], tables[i + 1], heights[i], heights[i + 1], i)
            for i in range(len(pages) - 1)]


def boundary_signals(tail, head, tables_a, tables_b, h_a, h_b, page_index: int) -> dict[str, Any]:
    """第 page_index 页（0 起）与下一页之间的边界信号；任一 hard 信号为真即不宜在此切开。"""
    last, first = (tail[-1] if tail else ''), (head[0] if head else '')
    unknown_tables = (-1.0, -1.0) in tables_a or (-1.0, -1.0) in tables_b
    table_continues = unknown_tables or (any(y1 > h_a * 0.80 for _, y1 in tables_a)
                                         and any(0 <= y0 < h_b * 0.25 for y0, _ in tables_b))
    continued_caption = bool(first and _CONTINUED.search(first)) or bool(last and _CONTINUES_NEXT.search(last))
    formula_continues = bool(last and _OPEN_MATH.search(last))
    paragraph_continues = bool(last and first and not _TERMINAL.search(last))
    hard = {'table_continues': table_continues, 'continued_caption': continued_caption,
            'formula_continues': formula_continues}
    return {'after_page': page_index + 1, 'text_layer': bool(tail or head), **hard,
            'paragraph_continues': paragraph_continues,
            'hard_unsafe': any(hard.values()), 'safe': not any(hard.values()) and not paragraph_continues,
            'tail_text': last[-80:], 'head_text': first[:80],
            'tail_sha256': hashlib.sha256(last.encode()).hexdigest() if last else None,
            'head_sha256': hashlib.sha256(first.encode()).hexdigest() if first else None}


# ---------------------------------------------------------------- 划分
def page_routes(kinds: list[str], route: str) -> list[str]:
    """逐页路线。显式 digital_pdf / scanned_ocr：全部页同一路线（不合格页由该路线既有门拒绝）。
    per_chunk：原生文字页 → digital_pdf，扫描页 → scanned_ocr，稀疏/无文字层页并入相邻同路线段。"""
    if route in ('digital_pdf', 'scanned_ocr'):
        return [route] * len(kinds)
    if route != 'per_chunk':
        raise ValueError('unknown chunk route')
    routes: list[str | None] = [PAGE_KIND_ROUTE.get(kind) for kind in kinds]
    for index, value in enumerate(routes):
        if value is None and index > 0:
            routes[index] = routes[index - 1]
    for index in range(len(routes) - 1, -1, -1):
        if routes[index] is None:
            routes[index] = routes[index + 1] if index + 1 < len(routes) else 'scanned_ocr'
    return [str(value) for value in routes]


def plan_chunks(signals: list[dict[str, Any]], routes: list[str], contract: dict[str, Any]) -> list[dict[str, Any]]:
    """确定性划分：同一路线的连续页段内，每块不超过该路线页数上限；在上限往前 boundary_search_pages
    页内选最好的边界（先避开 hard 信号，再避开段落续接，再取最长）。返回 1 起的闭区间。"""
    count = len(routes)
    search = int(contract['boundary_search_pages'])
    chunks: list[dict[str, Any]] = []
    start = 1
    while start <= count:
        route = routes[start - 1]
        limit = int(contract['max_pages_per_chunk'][route])
        run_end = start
        while run_end < count and routes[run_end] == route:
            run_end += 1
        hard_end = min(start + limit - 1, run_end)
        if hard_end == run_end:
            end = hard_end
        else:
            candidates = list(range(max(start, hard_end - search), hard_end + 1))
            end = max(candidates, key=lambda e: (not signals[e - 1]['hard_unsafe'], signals[e - 1]['safe'], e))
        chunks.append({'id': f'c{len(chunks) + 1:03d}', 'start': start, 'end': end, 'route': route,
                       'pages': end - start + 1})
        start = end + 1
    for chunk in chunks:
        chunk['boundary_after'] = signals[chunk['end'] - 1] if chunk['end'] < count else None
    return chunks


def split_range(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    """资源停止后的二分：页数 > 1 的块按中点拆成两块（子块 id 追加 a/b），单页块不可再分。"""
    if chunk['pages'] <= 1:
        return []
    middle = chunk['start'] + chunk['pages'] // 2 - 1
    left = {'id': chunk['id'] + 'a', 'start': chunk['start'], 'end': middle, 'route': chunk['route'],
            'pages': middle - chunk['start'] + 1, 'split_from': chunk['id']}
    right = {'id': chunk['id'] + 'b', 'start': middle + 1, 'end': chunk['end'], 'route': chunk['route'],
             'pages': chunk['end'] - middle, 'split_from': chunk['id']}
    return [left, right]


def write_chunk_pdf(source, chunk: dict[str, Any], path: Path) -> dict[str, str]:
    import fitz
    path.parent.mkdir(parents=True, exist_ok=True)
    out = fitz.open()
    out.insert_pdf(source, from_page=chunk['start'] - 1, to_page=chunk['end'] - 1)
    out.save(str(path), garbage=3, deflate=True)
    out.close()
    return file_ref(path)


def source_navigation(document) -> dict[str, Any]:
    links = []
    for page in document:
        for link in page.get_links():
            target = link.get('page')
            if link.get('kind') in (1, 4) and isinstance(target, int) and target >= 0:
                to = link.get('to')
                links.append({'page': page.number + 1, 'from': [round(v, 3) for v in link['from']],
                              'target_page': target + 1,
                              'to': [round(to.x, 3), round(to.y, 3)] if to is not None else None})
    return {'toc': [row[:3] for row in document.get_toc()],
            'page_labels': document.get_page_labels() or [], 'internal_links': links}


def document_term_context(input_pdf: Path, workdir: Path) -> dict[str, Any]:
    """整份文档的术语/专名策略：与单份 candidate 相同的抽取函数，供每块提示词共用。"""
    from pdf_translation_artifacts import enrich_quality_artifacts, write_glossary
    from pdf_translation_latex_render import prepare_source
    workdir.mkdir(parents=True, exist_ok=True)
    manifest = prepare_source(input_pdf, workdir)
    glossary = write_glossary(workdir, manifest)
    enrich_quality_artifacts(workdir, manifest, glossary)
    def load(name: str) -> dict[str, Any]:
        path = workdir / name
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    return {'protocol': TERM_CONTEXT_PROTOCOL, 'input_ref': file_ref(input_pdf),
            'term_policy': {'terms': load('term_policy.json').get('terms', [])},
            'entity_map': {'entities': load('entity_map.json').get('entities', [])}}


def build_plan(input_pdf: Path, preflight_path: Path, route: str, output: Path) -> dict[str, Any]:
    import fitz
    preflight = json.loads(preflight_path.read_text(encoding='utf-8'))
    with fitz.open(input_pdf) as document:
        count = len(document)
        kinds = {row['page']: row['kind'] for row in preflight.get('pages', [])}
        if sorted(kinds) != list(range(1, count + 1)):
            raise ValueError('preflight page classification incomplete')
        kind_list = [kinds[p] for p in range(1, count + 1)]
        signals = document_signals(document)
        routes = page_routes(kind_list, route)
        chunks = plan_chunks(signals, routes, CHUNKING_CONTRACT)
        for chunk in chunks:
            chunk['source_ref'] = write_chunk_pdf(document, chunk, output / 'chunks' / f"{chunk['id']}.pdf")
            chunk['page_kinds'] = kind_list[chunk['start'] - 1:chunk['end']]
        navigation = source_navigation(document)
        from render_residue_check import reference_region_open_pages
        region_open = reference_region_open_pages(document)
        for chunk in chunks:
            chunk['reference_region_open_at_start'] = region_open[chunk['start'] - 1]
    context = document_term_context(input_pdf, output / 'document_terms')
    write_json(output / 'DOCUMENT_TERM_CONTEXT.json', context)
    plan = {'schema_version': SCHEMA_VERSION, 'contract': CHUNKING_CONTRACT, 'input_ref': file_ref(input_pdf),
            'preflight_ref': file_ref(preflight_path), 'route': route, 'page_count': count,
            'page_kinds': kind_list, 'page_routes': routes, 'boundaries': signals, 'chunks': chunks,
            'cross_chunk_continuations': [c['boundary_after'] for c in chunks
                                          if c['boundary_after'] and not c['boundary_after']['safe']],
            'navigation': navigation,
            'reference_region_open_at_page_start': region_open,
            'document_term_context_ref': file_ref(output / 'DOCUMENT_TERM_CONTEXT.json')}
    write_json(output / 'CHUNK_PLAN.json', plan)
    return plan


# ---------------------------------------------------------------- 合并
def _image_digests(page) -> list[str]:
    return sorted(row['digest'].hex() for row in page.get_image_info(hashes=True) if row.get('digest'))


def _target_fonts(document, target_language: str) -> list[str]:
    pattern = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]') if target_language == 'zh' else re.compile(r'[A-Za-z]{3}')
    fonts: dict[str, int] = {}
    for page in document:
        for block in page.get_text('dict').get('blocks', []):
            for line in block.get('lines', []):
                for span in line.get('spans', []):
                    if pattern.search(span.get('text', '')):
                        name = _SUBSET.sub('', span.get('font', ''))
                        fonts[name] = fonts.get(name, 0) + len(span['text'])
    return sorted(fonts, key=lambda n: -fonts[n])


def merge_outputs(plan: dict[str, Any], results: list[dict[str, Any]], output: Path, *, target_language: str,
                  input_pdf: Path) -> dict[str, Any]:
    """results 按页序：每项 {'chunk': {...}, 'outputs': {role: {'path','sha256'}}}。所有核对失败都记为
    merge issue（high），由调用方并入综合质量（fail-closed）。"""
    import fitz
    issues: list[dict[str, Any]] = []
    output.mkdir(parents=True, exist_ok=True)
    expected = 1
    for row in results:
        chunk = row['chunk']
        if chunk['start'] != expected:
            raise ValueError(f"chunk order/coverage broken at {chunk['id']}: starts {chunk['start']}, expected {expected}")
        expected = chunk['end'] + 1
        for role, ref in row['outputs'].items():
            if sha256_file(ref['path']) != ref['sha256']:
                raise ValueError(f"chunk {chunk['id']} output {role} changed after its receipt")
    if expected != plan['page_count'] + 1:
        raise ValueError('chunks do not cover the document exactly once')
    source = fitz.open(input_pdf)
    stem = Path(input_pdf).stem
    merged = fitz.open()
    per_chunk_fonts = {}
    for row in results:
        chunk = row['chunk']
        with fitz.open(row['outputs']['translated_pdf']['path']) as part:
            if len(part) != chunk['pages']:
                issues.append({'id': 'chunk_page_count_mismatch', 'severity': 'high', 'chunk': chunk['id'],
                               'pages': list(range(chunk['start'], chunk['end'] + 1)),
                               'message': f"chunk output has {len(part)} pages, expected {chunk['pages']}"})
            per_chunk_fonts[chunk['id']] = _target_fonts(part, target_language)
            merged.insert_pdf(part)
    page_checks = []
    # 每页图像指纹与该块实际送入后端的源（电子块 = 块 PDF；扫描块 = OCR 重建源）逐页一致：
    # 检出合并错位、漏页、重复页。页面尺寸/旋转与原文档逐页一致。
    backend_pages = []
    for row in results:
        ref = row.get('backend_input') or row['chunk']['source_ref']
        if sha256_file(ref['path']) != ref['sha256']:
            raise ValueError(f"chunk {row['chunk']['id']} backend input changed after its receipt")
        with fitz.open(ref['path']) as part:
            backend_pages += [_image_digests(page) for page in part]
    if len(merged) != len(source) or len(backend_pages) != len(source):
        issues.append({'id': 'merged_page_count_mismatch', 'severity': 'high',
                       'message': f'merged {len(merged)} pages, source {len(source)}'})
    else:
        for index in range(len(source)):
            s, m = source[index], merged[index]
            size_ok = abs(s.rect.width - m.rect.width) < 0.5 and abs(s.rect.height - m.rect.height) < 0.5
            src_img, out_img = backend_pages[index], _image_digests(m)
            image_ok = src_img == out_img
            page_checks.append({'page': index + 1, 'size_ok': size_ok, 'rotation_ok': s.rotation == m.rotation,
                                'source_images': len(src_img), 'image_identity_ok': image_ok})
        bad = [c['page'] for c in page_checks if not (c['size_ok'] and c['rotation_ok'] and c['image_identity_ok'])]
        if bad:
            issues.append({'id': 'merged_page_identity_mismatch', 'severity': 'high', 'pages': bad,
                           'message': 'merged page size/rotation/image fingerprint differs from the source page'})
    nav = plan['navigation']
    restored = {'cross_chunk': 0, 'within_chunk': 0, 'already_present': 0}
    if len(merged) == len(source):
        chunk_of = {}
        for row in results:
            for page in range(row['chunk']['start'], row['chunk']['end'] + 1):
                chunk_of[page] = row['chunk']['id']
        for link in nav['internal_links']:
            page = merged[link['page'] - 1]
            rect = fitz.Rect(link['from'])
            present = any(l.get('kind') in (1, 4) and l.get('page') == link['target_page'] - 1
                          and fitz.Rect(l['from']).intersects(rect) for l in page.get_links())
            if present:
                restored['already_present'] += 1
                continue
            entry = {'kind': fitz.LINK_GOTO, 'from': rect, 'page': link['target_page'] - 1}
            if link['to']:
                entry['to'] = fitz.Point(*link['to'])
            page.insert_link(entry)
            restored['cross_chunk' if chunk_of[link['page']] != chunk_of[link['target_page']] else 'within_chunk'] += 1
        if nav['toc']:
            merged.set_toc([row for row in nav['toc'] if 1 <= row[2] <= len(merged)])
        if nav['page_labels']:
            merged.set_page_labels(nav['page_labels'])
    mono_path = output / f'{stem}.chunked.{target_language}.mono.pdf'
    merged.save(str(mono_path), garbage=3, deflate=True)
    merged.close()
    if restored != {'cross_chunk': 0, 'within_chunk': 0, 'already_present': 0} or nav['internal_links']:
        # 以写出的文件为准核对：每条原文内部链接（页、目标页、位置）都在合并件里。
        with fitz.open(mono_path) as written:
            present = {(p.number + 1, l.get('page', -1) + 1) for p in written for l in p.get_links() if l.get('kind') in (1, 4)}
        missing = [l for l in nav['internal_links'] if (l['page'], l['target_page']) not in present]
        if missing:
            issues.append({'id': 'internal_links_not_restored', 'severity': 'high', 'missing': missing[:20],
                           'message': f"{len(missing)} of {len(nav['internal_links'])} source internal links missing in the merged PDF"})
    font_sets = {cid: fonts[:1] for cid, fonts in per_chunk_fonts.items() if fonts}
    primary = sorted({tuple(v) for v in font_sets.values()})
    if len(primary) > 1:
        issues.append({'id': 'chunk_target_font_inconsistent', 'severity': 'high',
                       'message': 'chunks use different primary target-language fonts', 'fonts': font_sets})
    outputs = {'translated_pdf': file_ref(mono_path)}
    if all('readable_repaired_pdf' in row['outputs'] for row in results):
        readable = fitz.open()
        bookmarks = []
        for row in results:
            with fitz.open(row['outputs']['readable_repaired_pdf']['path']) as part:
                bookmarks.append([1, f"{row['chunk']['id']} · source pages {row['chunk']['start']}–{row['chunk']['end']}",
                                  len(readable) + 1])
                readable.insert_pdf(part)
        readable.set_toc(bookmarks)
        readable_path = output / 'final_readable.pdf'
        readable.save(str(readable_path), garbage=3, deflate=True)
        readable.close()
        outputs['readable_repaired_pdf'] = file_ref(readable_path)
    chunk_texts = []
    for row in results:
        with fitz.open(row['chunk']['source_ref']['path']) as src, fitz.open(row['outputs']['translated_pdf']['path']) as out:
            chunk_texts.append({'chunk': row['chunk']['id'], 'source': ''.join(p.get_text() for p in src),
                                'translation': ''.join(p.get_text() for p in out)})
    source.close()
    report = {'schema_version': SCHEMA_VERSION, 'protocol': CHUNKING_CONTRACT['merge'], 'page_count': plan['page_count'],
              'chunk_order': [row['chunk']['id'] for row in results], 'outputs': outputs, 'page_checks': page_checks,
              'links': {'source_internal': len(nav['internal_links']), **restored},
              'toc_entries': len(nav['toc'] or []), 'page_labels': bool(nav['page_labels']),
              'target_fonts_by_chunk': per_chunk_fonts, 'issues': issues}
    context_ref = plan['document_term_context_ref']
    if sha256_file(context_ref['path']) != context_ref['sha256']:
        raise ValueError('document term context changed after planning')
    terminology = terminology_report(json.loads(Path(context_ref['path']).read_text(encoding='utf-8')), chunk_texts)
    qualities = []
    for row in results:
        ref = row.get('quality_ref')
        if ref and sha256_file(ref['path']) != ref['sha256']:
            raise ValueError(f"chunk {row['chunk']['id']} quality changed after its receipt")
        quality = json.loads(Path(ref['path']).read_text(encoding='utf-8')) if ref else None
        if quality is not None and row.get('quality_status') and row['quality_status'] != quality.get('status'):
            # 回执里的状态（例如 OCR 封顶为 unverified）比文件更严时以回执为准，绝不放宽。
            stricter = max((row['quality_status'], quality.get('status')), key=lambda s: QUALITY_ORDER.get(s, 99))
            quality = dict(quality, status=stricter)
        qualities.append({'chunk': row['chunk'], 'quality': quality})
    write_json(output / 'TERMINOLOGY_REPORT.json', terminology)
    quality = aggregate_quality(qualities, issues, terminology['issues'])
    quality.update(merge_manifest='MERGE_MANIFEST.json', terminology_report='TERMINOLOGY_REPORT.json',
                   chunk_count=len(results), page_count=plan['page_count'],
                   cross_chunk_continuations=plan.get('cross_chunk_continuations', []))
    write_json(output / 'comprehensive_quality.json', quality)
    report['quality_status'] = quality['status']
    return report


# ---------------------------------------------------------------- 质量
def _issue_pages(issue: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    row = {k: issue[k] for k in ('id', 'rule', 'severity', 'message', 'overall_residue_ratio') if k in issue}
    row.setdefault('id', issue.get('rule') or 'quality_issue')
    row['chunk'] = chunk['id']
    pages = issue.get('pages')
    if isinstance(pages, list):
        row['pages'] = [chunk['start'] - 1 + int(p) for p in pages if isinstance(p, int)]
    return row


def aggregate_quality(chunks: list[dict[str, Any]], merge_issues: list[dict[str, Any]],
                      terminology_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """chunks: [{'chunk':{...}, 'quality': comprehensive_quality dict or None}]。缺综合质量的块按 fail 计。"""
    statuses, issues, pending = [], [], []
    for row in chunks:
        quality = row.get('quality') or {}
        status = quality.get('status') if quality.get('status') in QUALITY_ORDER else 'fail'
        statuses.append(status)
        issues += [_issue_pages(i, row['chunk']) for i in quality.get('issues', []) if isinstance(i, dict)]
        if not quality:
            issues.append({'id': 'chunk_quality_missing', 'severity': 'high', 'chunk': row['chunk']['id']})
        for item in quality.get('pending', []) or []:
            if isinstance(item, dict):
                pending.append(dict(item, chunk=row['chunk']['id']))
    worst = max(statuses, key=QUALITY_ORDER.get) if statuses else 'fail'
    extra = list(merge_issues) + list(terminology_issues or [])
    issues += extra
    status = worst
    if any(i.get('severity') in ('high', 'critical', 'blocker') for i in extra):
        status = 'fail'
    elif status == 'pass' and pending:
        status = 'unverified'
    assert QUALITY_ORDER[status] >= QUALITY_ORDER[worst]
    return {'schema_version': SCHEMA_VERSION, 'status': status, 'quality_pass': status == 'pass',
            'worst_chunk_status': worst, 'chunk_statuses': {row['chunk']['id']: s for row, s in zip(chunks, statuses)},
            'issues': issues, 'pending': pending, 'strict_delivery': False, 'human_acceptance': 'pending',
            'promotion_performed': False, 'aggregation': CHUNKING_CONTRACT['quality']}


def terminology_report(context: dict[str, Any], chunk_texts: list[dict[str, Any]]) -> dict[str, Any]:
    """跨块术语：文档级策略里带译法的术语，在出现源术语的每一块译文里都应出现同一译法；
    不一致列为 high（fail-closed）。没有译法的候选术语只做出现统计（不作门）。"""
    issues, rows = [], []
    for term in context.get('term_policy', {}).get('terms', []):
        source = str(term.get('source_term') or '')
        target = str(term.get('translation') or '')
        if not source:
            continue
        seen = [row['chunk'] for row in chunk_texts if source.lower() in row['source'].lower()]
        missing = [row['chunk'] for row in chunk_texts if target and row['chunk'] in seen
                   and target not in row['translation']]
        rows.append({'source_term': source, 'translation': target or None, 'chunks_with_source': seen,
                     'chunks_missing_translation': missing})
        if missing and len(seen) > 1 and len(missing) < len(seen):
            issues.append({'id': 'chunk_terminology_inconsistent', 'severity': 'high', 'source_term': source,
                           'translation': target, 'chunks': missing,
                           'message': 'the frozen document term translation is used in some chunks but not in others'})
    return {'protocol': TERM_CONTEXT_PROTOCOL, 'terms': rows, 'issues': issues}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--preflight', type=Path, required=True)
    p.add_argument('--route', choices=('digital_pdf', 'scanned_ocr', 'per_chunk'), required=True)
    p.add_argument('--output', type=Path, required=True)
    m = sub.add_parser('merge')
    m.add_argument('--plan', type=Path, required=True)
    m.add_argument('--plan-sha256', required=True)
    m.add_argument('--results', type=Path, required=True)
    m.add_argument('--results-sha256', required=True)
    m.add_argument('--input', type=Path, required=True)
    m.add_argument('--target-language', choices=('zh', 'en'), required=True)
    m.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'plan':
        if args.output.exists():
            raise SystemExit('plan output must be new')
        plan = build_plan(args.input.resolve(), args.preflight.resolve(), args.route, args.output.resolve())
        print(json.dumps({'status': 'planned', 'chunks': len(plan['chunks'])}))
        return 0
    for path, digest in ((args.plan, args.plan_sha256), (args.results, args.results_sha256)):
        if sha256_file(path) != digest:
            raise SystemExit(f'{path} changed')
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    results = json.loads(args.results.read_text(encoding='utf-8'))
    if args.output.exists():
        raise SystemExit('merge output must be new')
    report = merge_outputs(plan, results, args.output.resolve(), target_language=args.target_language,
                           input_pdf=args.input.resolve())
    write_json(args.output / 'MERGE_MANIFEST.json', report)
    print(json.dumps({'status': 'merged', 'issues': len(report['issues'])}))
    return 0


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
