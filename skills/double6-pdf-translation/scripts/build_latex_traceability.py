"""只读重建 LaTeX 分段、精确返修与最终 TeX/PDF 定位证据；不签发质量验收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from assess_delivery import sha256


def single_occurrence(text: str, needle: str) -> int:
    """包括重叠匹配；str.count 会漏掉 aaa 中第二个 aa。"""
    start = text.find(needle) if needle else -1
    return start if start >= 0 and text.find(needle, start + 1) < 0 else -1


def unique_span(text: str, needle: str) -> tuple[int, int, str]:
    if not needle or not needle.strip():
        raise ValueError("empty trace fragment")
    start = single_occurrence(text, needle)
    if start >= 0:
        return start, start + len(needle), "exact"
    # 仅忽略空白，不去标点、命令、数字或实词；返回原文件坐标。
    positions = [i for i, c in enumerate(text) if not c.isspace()]
    normalized = "".join(text[i] for i in positions)
    query = "".join(needle.split())
    start = single_occurrence(normalized, query)
    if start < 0:
        raise ValueError("missing or ambiguous trace fragment")
    return positions[start], positions[start + len(query) - 1] + 1, "whitespace_only"


def patch_intervals(text: str, spans: list[dict], before: str, after: str, patch_id: str) -> tuple[str, list[dict]]:
    start = single_occurrence(text, before)
    if start < 0:
        raise ValueError("repair must have exactly one literal match")
    end = start + len(before)
    delta = len(after) - len(before)
    output, touched = [], {patch_id}
    for span in spans:
        a, z = span["start"], span["end"]
        if z <= start:
            output.append(dict(span))
        elif a >= end:
            output.append({**span, "start": a + delta, "end": z + delta})
        else:
            touched.update(span["ids"])
            if a < start:
                output.append({**span, "end": start})
            if z > end:
                output.append({**span, "start": start + len(after), "end": z + delta})
    if after:
        output.append({"start": start, "end": start + len(after), "ids": sorted(touched)})
    return text[:start] + after + text[end:], sorted(output, key=lambda x: (x["start"], x["end"]))


def ranges_for(spans: list[dict], identity: str) -> list[list[int]]:
    ranges = sorted([s["start"], s["end"]] for s in spans if identity in s["ids"])
    merged: list[list[int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def build_pdf_streams(document: Any) -> list[dict]:
    """按字号/左右栏给出候选阅读序；用于定位，不能代替版面审校。"""
    lanes: dict[float, list[tuple]] = {}
    for page_index, page in enumerate(document):
        for span in page.get_texttrace():
            if span['type'] == 3:
                continue
            size = round(span['size'], 1)
            for c in span['chars']:
                if not 0x4e00 <= c[0] <= 0x9fff:
                    continue
                box = list(c[3])
                column = int((box[0] + box[2]) / 2 >= page.rect.width / 2)
                lanes.setdefault(size, []).append((page_index + 1, column, round(c[2][1], 1), c[2][0], chr(c[0]), box))
    streams = []
    for size, chars in sorted(lanes.items()):
        chars.sort(key=lambda c: c[:4])
        streams.append({'font_size':size, 'text':''.join(c[4] for c in chars),
                        'positions':[{'page':c[0],'column':c[1],'bbox':c[5]} for c in chars]})
    return streams


def pdf_anchors(text: str, pages: list[str], flow_streams: list[dict] | None = None) -> dict:
    # 这些只是中文可绘制文本定位，不证明数字、外文、公式、遮挡或完整句意。
    uncommented = re.sub(r"(?<!\\)%[^\n]*", "", text)
    runs = list(dict.fromkeys(re.findall(r"[\u4e00-\u9fff]+", uncommented)))
    hits = []
    for run in runs:
        hit = {"text":run, "pages":[i + 1 for i,page in enumerate(pages) if run in page],
               "occurrences":sum(page.count(run) for page in pages), 'flow_candidates':[]}
        if not hit['pages']:
            for stream in flow_streams or []:
                start = stream['text'].find(run)
                if start < 0 or single_occurrence(stream['text'],run) < 0:
                    continue
                points = stream['positions'][start:start+len(run)]
                matched_pages = sorted({p['page'] for p in points})
                if matched_pages[-1] - matched_pages[0] > 1:
                    continue
                hit['flow_candidates'].append({'font_size':stream['font_size'],'pages':matched_pages,
                                               'characters':points,'method':'exact_cjk_run_in_font_column_projection'})
        hits.append(hit)
    return {"scope": "painted_cjk_runs_only", "runs": hits,
            "missing": [h["text"] for h in hits if not h["pages"] and not h['flow_candidates']],
            "flow_review_required": [h['text'] for h in hits if h['flow_candidates']],
            "unique_anchor_pages": sorted({p for h in hits if h["occurrences"] == 1 and len(h["text"]) >= 4 for p in h["pages"]}),
            "ambiguous_short_runs": sum(h["occurrences"] > 1 for h in hits)}


def audit_source_units(source: str, nodes: list[Any], source_spans: list[list[int]]) -> list[dict]:
    if ''.join(node.text for node in nodes) != source:
        raise ValueError('source parser changed characters; no offset mapping available')
    covered = bytearray(len(source))
    for start,end in source_spans:
        if not 0 <= start <= end <= len(source):
            raise ValueError('source trace range outside file')
        covered[start:end] = bytes([1]) * (end-start)
    rows, cursor = [], 0
    for node in nodes:
        if node.segment_id:
            gaps = ''.join(' ' if covered[cursor+i] else c for i,c in enumerate(node.text))
            rows.append({'source_range':[cursor,cursor+len(node.text)], 'parser_segment_id':node.segment_id,
                         'uncovered_text':gaps.strip(), 'uncovered_latin_text':bool(re.search('[A-Za-z]',gaps)),
                         'scope':'current parser translatable units only; protected source content excluded'})
        cursor += len(node.text)
    return rows


def build(run_dir: Path, *, max_pages: int = 20) -> dict[str, Any]:
    import fitz
    run_dir = run_dir.resolve()
    if not 1 <= max_pages <= 20:
        raise ValueError("1–20 page budget required")
    frozen: dict[str, str] = {str(Path(__file__).resolve()): sha256(Path(__file__))}
    vendor = Path(__file__).resolve().parents[1] / 'vendor/pdf2zh_skill'
    sys.path.insert(0,str(vendor))
    from pdf2zh_skill import latex_ops
    if not Path(latex_ops.__file__).resolve().is_relative_to(vendor):
        raise ValueError('source parser is not the frozen vendored implementation')
    for implementation in (vendor/'pdf2zh_skill').rglob('*.py'):
        frozen[str(implementation)] = sha256(implementation)
    def read(path: Path) -> str:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 8 * 1024**2:
            raise ValueError("bounded regular evidence file required")
        digest = sha256(path)
        if str(path) in frozen and frozen[str(path)] != digest:
            raise ValueError("evidence changed while reading")
        frozen[str(path)] = digest
        return path.read_text(encoding="utf-8")
    def tex(root: Path, relative: str) -> Path:
        rel = Path(relative)
        path = root / rel
        if rel.is_absolute() or ".." in rel.parts or rel.suffix != ".tex" or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe TeX identity")
        return path
    history, seen = [], set()
    current = run_dir
    while (current / "latex_recovery_receipt.json").is_file():
        if current in seen or len(seen) >= 12:
            raise ValueError("cyclic or unbounded recovery history")
        seen.add(current)
        receipt = json.loads(read(current / "latex_recovery_receipt.json"))
        if receipt.get("status") != "render_recovered_pending_quality_review" or receipt.get("original_unchanged") is not True:
            raise ValueError("unfinished or changed recovery history")
        previous = Path(receipt["source_run"]).resolve()
        history.append((current, previous, receipt))
        current = previous
    base = current
    sources = json.loads(read(run_dir / "route_manifest.json"))
    if sources.get("document_route") != "latex_direct" or sources.get("dispatch_allowed") is not True:
        raise ValueError("verified LaTeX route required")
    source_pdf = Path(sources["input_pdf"])
    frozen[str(source_pdf)] = sha256(source_pdf)
    if frozen[str(source_pdf)] != sources["input_sha256"]:
        raise ValueError("source PDF changed")
    with fitz.open(source_pdf) as source_document:
        if not 1 <= len(source_document) <= max_pages:
            raise ValueError("source PDF exceeds page budget")
    render = json.loads(read(run_dir / "render_manifest.json"))
    pdf = Path(render["outputs"]["translated_pdf"])
    cn, initial = run_dir / "latex_direct/paper_cn", base / "latex_direct/paper_cn"
    if not pdf.resolve().is_relative_to(cn.resolve()):
        raise ValueError("PDF must be the current project output")
    frozen[str(pdf)] = sha256(pdf)
    if history and history[0][2].get('compiled_pdf', {}).get('sha256') != frozen[str(pdf)]:
        raise ValueError('compiled PDF receipt does not match current PDF')
    seg_name, translated_name = "segments_English.jsonl", "translations_reviewed_中文.jsonl"
    segments = [json.loads(line) for line in read(cn / seg_name).splitlines() if line.strip()]
    translated_rows = [json.loads(line) for line in read(cn / translated_name).splitlines() if line.strip()]
    if not 1 <= len(segments) <= 2000 or len({r['id'] for r in segments}) != len(segments):
        raise ValueError("bounded unique source segments required")
    translations = {r['id']: r['translation'] for r in translated_rows}
    if len(translations) != len(translated_rows) or set(translations) != {r['id'] for r in segments}:
        raise ValueError("translation identity mismatch")
    for name in [seg_name, translated_name]:
        if read(initial / name) != read(cn / name):
            raise ValueError("segment history changed; explicit migration required")
    files = sorted({r['file'] for r in segments} | {e['path'] for _, _, h in history for e in h.get('tex_repairs', [])})
    if len(files) > 32:
        raise ValueError("at most32 TeX files per trace")
    states, origin_rows, repair_rows = {}, [], []
    for name in files:
        source = read(tex(run_dir / 'latex_direct/paper_source', name))
        original_source = read(tex(base / 'latex_direct/paper_source', name))
        if source != original_source:
            raise ValueError("source TeX changed across recovery")
        target = read(tex(initial, name))
        spans = []
        for segment in [r for r in segments if r['file'] == name]:
            sa, sz, sm = unique_span(source, segment['text'])
            ta, tz, tm = unique_span(target, translations[segment['id']])
            spans.append({'start':ta,'end':tz,'ids':[segment['id']]})
            origin_rows.append({'id':segment['id'],'file':name,'source_range':[sa,sz],'source_match':sm,
                                'initial_target_range':[ta,tz],'initial_target_match':tm})
        states[name] = (target, spans)
    for step, (directory, previous, receipt) in enumerate(reversed(history), 1):
        edits = {e['path']:e for e in receipt.get('tex_repairs', [])}
        if len(edits) != len(receipt.get('tex_repairs', [])):
            raise ValueError("duplicate repaired file")
        for name in files:
            text, spans = states[name]
            before_path, after_path = tex(previous/'latex_direct/paper_cn',name), tex(directory/'latex_direct/paper_cn',name)
            before = read(before_path)
            if before != text or receipt['source_files_sha256'].get('latex_direct/paper_cn/'+name) != sha256(before_path):
                raise ValueError("broken recovery predecessor identity")
            if name in edits:
                edit = edits[name]
                if edit['before_sha256'] != sha256(before_path):
                    raise ValueError("stale repair before SHA")
                for number, patch in enumerate(edit['replacements'], 1):
                    if not patch.get('reason') or not patch.get('source_evidence'):
                        raise ValueError("repair lacks review reason/evidence")
                    identity = f'repair-{step:02d}-{name}-{number:03d}'
                    text, spans = patch_intervals(text, spans, patch['before'], patch['after'], identity)
                    repair_rows.append({'id':identity,'file':name,'receipt':str(directory/'latex_recovery_receipt.json'),
                                        'source_evidence':patch['source_evidence'],'reason':patch['reason'],
                                        'before':patch['before'],'after':patch['after']})
                if hashlib.sha256(text.encode()).hexdigest() != edit['after_sha256']:
                    raise ValueError("replayed repair differs from after SHA")
            if read(after_path) != text:
                raise ValueError("unrecorded target TeX change")
            states[name] = text, spans
    with fitz.open(pdf) as document:
        if not 1 <= len(document) <= max_pages:
            raise ValueError("PDF exceeds page budget")
        pages = [''.join(chr(c[0]) for span in page.get_texttrace() if span['type'] != 3
                         for c in span['chars'] if 0x4e00 <= c[0] <= 0x9fff) for page in document]
        flow_streams = build_pdf_streams(document)
    for row in origin_rows + repair_rows:
        text, spans = states[row['file']]
        ranges = ranges_for(spans, row['id'])
        row['final_target_ranges'] = ranges
        row['final_target_fragments'] = [text[a:z] for a,z in ranges]
        row['pdf_locator'] = pdf_anchors('\n'.join(row['final_target_fragments']), pages, flow_streams)
        row['target_deleted'] = not ranges
    source_units = []
    for name in files:
        source = read(tex(run_dir/'latex_direct/paper_source',name))
        source_spans = [r['source_range'] for r in origin_rows if r['file']==name]
        for row in [r for r in repair_rows if r['file']==name]:
            a = single_occurrence(source,row['before'])
            if a >= 0:
                row['literal_source_range'] = [a,a+len(row['before'])]
                source_spans.append(row['literal_source_range'])
            else:
                row['literal_source_range'] = None
                row['source_link_note'] = 'Controller repair of translated/layout text; see predecessor segments and review evidence, not a literal source match.'
        for row in audit_source_units(source,latex_ops.split_nodes(source),source_spans):
            row['file'] = name
            row['id'] = f"{name}::source-span-{row['source_range'][0]}-{row['source_range'][1]}"
            source_units.append(row)
    if any(sha256(Path(path)) != digest for path,digest in frozen.items()):
        raise ValueError("evidence changed during trace reconstruction")
    return {'schema_version':1,'status':'trace_reconstructed_pdf_review_pending','run_dir':str(run_dir),'base_run':str(base),
            'source_sha256':sources['input_sha256'],'candidate_sha256':sha256(pdf),'evidence_sha256':frozen,
            'recovery_steps':len(history),'segment_count':len(origin_rows),'repair_count':len(repair_rows),
            'segments':origin_rows,'repairs':repair_rows,'unlocated_cjk_segments':[r['id'] for r in origin_rows if r['pdf_locator']['missing']],
            'current_parser_source_units':source_units,
            'source_units_with_unmapped_latin_text':[r['id'] for r in source_units if r['uncovered_latin_text']],
            'segments_without_unique_pdf_anchor':[r['id'] for r in origin_rows if not r['pdf_locator']['unique_anchor_pages']],
            'scope':'Historical segments and recorded exact TeX repairs; CJK page anchors only. Not complete source coverage, block-local alignment, semantic, visual or human acceptance.',
            'model_calls':0,'semantic_accepted':False,'visual_accepted':False,'human_accepted':False,'strict_promoted':False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-pages',type=int,default=20)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = build(args.run_dir,max_pages=args.max_pages)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({k:result[k] for k in ['status','segment_count','repair_count','unlocated_cjk_segments','segments_without_unique_pdf_anchor']},ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
