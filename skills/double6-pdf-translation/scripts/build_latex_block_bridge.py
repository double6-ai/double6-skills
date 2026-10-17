"""把历史 Markdown block 经可逆文本投影接到最终 TeX；不替代 PDF/语义验收。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

import prepare_paper_source as prepare
import build_latex_traceability as trace_api
from assess_delivery import sha256


def compact(text: str) -> str:
    return ''.join(text.split())


def project_ranges(raw: str, spans: list[list[int]]) -> dict:
    start_tag, end_tag = '\ue000', '\ue001'
    if start_tag in raw or end_tag in raw:
        raise ValueError('projection marker already present in source')
    baseline = prepare.read_latex_text(raw)
    projected, absent = [], []
    for start,end in spans:
        if not 0 <= start < end <= len(raw):
            raise ValueError('invalid projection span')
        marked = raw[:start]+start_tag+raw[start:end]+end_tag+raw[end:]
        rendered = prepare.read_latex_text(marked)
        if compact(rendered.replace(start_tag,'').replace(end_tag,'')) != compact(baseline):
            raise ValueError('annotation changed the text projection')
        if rendered.count(start_tag) == rendered.count(end_tag) == 1:
            a,z = rendered.index(start_tag),rendered.index(end_tag)
            if a >= z:
                raise ValueError('projection reversed source boundaries')
            projected.append([len(compact(rendered[:a])),len(compact(rendered[:z].replace(start_tag,'')))])
        elif not (start_tag in rendered or end_tag in rendered):
            absent.append([start,end])
        else:
            raise ValueError('partial projection boundary was removed')
    return {'ranges':projected,'removed_by_legacy_parser':absent}


def block_ranges(text: str, blocks: list[dict]) -> list[dict]:
    if compact(text) != compact(''.join(b['text'] for b in blocks)):
        raise ValueError('blocks do not reproduce the source projection')
    if len({b['block_id'] for b in blocks}) != len(blocks):
        raise ValueError('duplicate block identity')
    cursor, result = 0, []
    for block in blocks:
        end = cursor+len(compact(block['text']))
        result.append({**block,'projection_range':[cursor,end]})
        cursor = end
    return result


def contributing_ids(projections: dict[str, dict], span: list[int]) -> list[str]:
    return [identity for identity, record in projections.items()
            if any(a < span[1] and z > span[0] for a,z in record['ranges'])]


def heading_commands(text: str) -> list[str]:
    return re.findall(r'\\(title|section|subsection|subsubsection|paragraph)\*?\s*\{',prepare.strip_latex_comments(text))


def ordered_heading_bindings(rows: list[dict], source_fragments: dict[str,str], target_fragments: dict[str,str]) -> None:
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        if row['element_type']=='heading' and len(row['source_segment_ids'])==1 and len(row['target_block_ids'])>1:
            groups.setdefault((tuple(row['source_segment_ids']),tuple(row['target_block_ids'])),[]).append(row)
    for (identities,targets),group in groups.items():
        source_commands = heading_commands(source_fragments[identities[0]])
        target_commands = heading_commands(target_fragments[identities[0]])
        if len(group)!=len(targets) or len(source_commands)!=len(group) or source_commands!=target_commands:
            continue
        for row,target,command in zip(group,targets,source_commands,strict=True):
            row['target_block_ids']=[target]
            row['binding_method']='same_segment_preserved_heading_commands_in_source_order'
            row['heading_command']=command


def abstract_label(raw: str) -> str | None:
    preamble = prepare.strip_latex_comments(raw).split(r'\begin{document}',1)[0]
    # 不执行 TeX 条件或任意宏；有条件的声明留待专门审校。
    if re.search(r'\\(?:if[A-Za-z@]*|else|fi)\b',preamble):
        return None
    labels = re.findall(r'\\renewcommand\*?\s*\{\s*\\abstractname\s*\}\s*\{([^{}\\]+)\}',preamble)
    return labels[0].strip() if len(labels)==1 and labels[0].strip() else None


def build(run_dir: Path, trace_path: Path, *, max_pages: int=20) -> dict[str,Any]:
    import fitz
    run_dir,trace_path=run_dir.resolve(),trace_path.resolve()
    if not 1<=max_pages<=20:
        raise ValueError('1–20 page budget required')
    frozen={str(p.resolve()):sha256(p) for p in [Path(__file__),Path(prepare.__file__),Path(trace_api.__file__),trace_path]}
    def read(path:Path)->str:
        if not path.is_file() or path.is_symlink() or path.stat().st_size>8*1024**2:
            raise ValueError('bounded regular input required')
        path=path.resolve()
        digest=sha256(path)
        if str(path) in frozen and frozen[str(path)]!=digest:
            raise ValueError('previously frozen bridge input changed')
        frozen[str(path)]=digest
        return path.read_text(encoding='utf-8')
    trace=json.loads(read(trace_path))
    if Path(trace['run_dir']).resolve()!=run_dir or trace['status']!='trace_reconstructed_pdf_review_pending':
        raise ValueError('trace identity or status mismatch')
    for name,digest in trace['evidence_sha256'].items():
        if sha256(Path(name))!=digest:
            raise ValueError('stale upstream trace evidence')
        if name in frozen and frozen[name]!=digest:
            raise ValueError('conflicting frozen evidence identity')
        frozen[name]=digest
    manifest=json.loads(read(run_dir/'source_manifest.json'))
    if manifest.get('input_type')!='latex':
        raise ValueError('LaTeX source manifest required')
    input_path=Path(manifest['input']).resolve()
    names={r['file'] for r in trace['segments'] if Path(r['file']).name==input_path.name}
    if len(names)!=1 or not 1<=len(trace['segments'])<=512 or not 1<=len(manifest['blocks'])<=400:
        raise ValueError('one unambiguous main file and bounded segment/block inventory required')
    main=Path(names.pop())
    if main.is_absolute() or '..' in main.parts:
        raise ValueError('unsafe main source path')
    source=read(input_path)
    source_copy=read(run_dir/'latex_direct/paper_source'/main)
    target=read(run_dir/'latex_direct/paper_cn'/main)
    if max(len(source),len(source_copy),len(target))>2*1024**2:
        raise ValueError('main TeX exceeds2MiB projection budget')
    source_text,target_text=prepare.read_latex_text(source),prepare.read_latex_text(target)
    source_blocks=block_ranges(source_text,manifest['blocks'])
    target_blocks=block_ranges(target_text,prepare.build_blocks(target_text))
    source_projections,target_projections,source_fragments,target_fragments={},{},{},{}
    segment_lookup={r['id']:r for r in trace['segments']}
    for row in trace['segments']:
        if row['file']!=str(main):
            continue
        a,z=row['source_range'];source_fragments[row['id']]=source_copy[a:z]
        sa,sz,method=trace_api.unique_span(source,source_fragments[row['id']])
        source_projections[row['id']]={**project_ranges(source,[[sa,sz]]),'input_source_range':[sa,sz],'input_source_match':method}
        target_projections[row['id']]=project_ranges(target,row['final_target_ranges'])
        target_fragments[row['id']]='\n'.join(target[a:z] for a,z in row['final_target_ranges'])
    for block in target_blocks:
        block['segment_ids']=contributing_ids(target_projections,block['projection_range'])
    rows=[]
    for block in source_blocks:
        identities=contributing_ids(source_projections,block['projection_range'])
        candidates=[t['block_id'] for t in target_blocks if set(identities)&set(t['segment_ids']) and t['element_type']==block['element_type']]
        rows.append({'block_id':block['block_id'],'source_text':block['text'],'element_type':block['element_type'],
                     'source_projection_range':block['projection_range'],'source_segment_ids':identities,
                     'target_block_ids':candidates,'binding_method':'segment_overlap_and_block_role'})
    ordered_heading_bindings(rows,source_fragments,target_fragments)
    label=abstract_label(target)
    abstract_source=[r for r in rows if not r['source_segment_ids'] and r['source_text']=='## Abstract']
    abstract_target=[r for r in target_blocks if not r['segment_ids'] and r['text']=='## Abstract']
    if (label and len(abstract_source)==len(abstract_target)==1
        and source.count(r'\begin{abstract}')==target.count(r'\begin{abstract}')==1):
        row=abstract_source[0];row['target_block_ids']=[abstract_target[0]['block_id']]
        row['binding_method']='unique_abstract_environment_and_literal_preamble_label'
        row['template_target_text']='## '+label
    ownership:dict[str,list[str]]={}
    for row in rows:
        for identity in row['target_block_ids']:ownership.setdefault(identity,[]).append(row['block_id'])
    lookup={r['block_id']:r for r in target_blocks}
    pdf=Path(json.loads(read(run_dir/'render_manifest.json'))['outputs']['translated_pdf'])
    if sha256(pdf)!=trace['candidate_sha256']:
        raise ValueError('current PDF changed')
    with fitz.open(pdf) as doc:
        if not 1<=len(doc)<=max_pages:raise ValueError('PDF exceeds page budget')
        pages=[''.join(chr(c[0]) for span in page.get_texttrace() if span['type']!=3 for c in span['chars'] if 0x4e00<=c[0]<=0x9fff) for page in doc]
        streams=trace_api.build_pdf_streams(doc)
    for row in rows:
        row['ambiguous_target_blocks']=[i for i in row['target_block_ids'] if len(ownership[i])!=1]
        row['mapping_status']='mapped_to_final_tex' if row['target_block_ids'] and not row['ambiguous_target_blocks'] else 'needs_review'
        row['target_text']=row.get('template_target_text') or '\n\n'.join(lookup[i]['text'] for i in row['target_block_ids'])
        row['target_origin']='final_tex_plain_projection_not_extracted_pdf_block'
        row['pdf_locator']=trace_api.pdf_anchors(row['target_text'],pages,streams)
        row['segment_trace_refs']=[{'id':i,'source_range':segment_lookup[i]['source_range'],'final_target_ranges':segment_lookup[i]['final_target_ranges']} for i in row['source_segment_ids']]
    if any(sha256(Path(name))!=digest for name,digest in frozen.items()):
        raise ValueError('bridge evidence changed during execution')
    unmapped=[r['block_id'] for r in rows if r['mapping_status']!='mapped_to_final_tex']
    return {'schema_version':1,'status':'mapped_to_final_tex_pdf_review_pending' if not unmapped else 'partial_bridge',
            'run_dir':str(run_dir),'trace':str(trace_path),'source_sha256':trace['source_sha256'],'candidate_sha256':trace['candidate_sha256'],
            'evidence_sha256':frozen,'source_block_count':len(rows),'mapped_block_count':len(rows)-len(unmapped),
            'unmapped_block_ids':unmapped,'orphan_target_block_ids':[r['block_id'] for r in target_blocks if r['block_id'] not in ownership],
            'segments_not_in_legacy_block_projection':[identity for identity,r in source_projections.items() if not r['ranges']],
            'source_segment_projection':source_projections,'target_segment_projection':target_projections,'blocks':rows,
            'scope':'Legacy Markdown blocks only. Floats/captions, protected source content, current-parser gaps, PDF geometry, numbers/formulas and semantic fidelity require separate audits.',
            'quality_reports_modified':False,'model_calls':0,'semantic_accepted':False,'visual_accepted':False,'human_accepted':False,'strict_promoted':False}


def validate_for_quality(path: Path, manifest: dict, render_manifest: dict) -> dict:
    """重放桥接并绑定 QA 的当前输入；成功只表示 TeX 对应关系可复现。"""
    path=path.resolve()
    if not path.is_file() or path.stat().st_size>16*1024**2:
        raise ValueError('bounded bridge report required')
    digest=sha256(path)
    record=json.loads(path.read_text(encoding='utf-8'))
    if render_manifest.get('actual_render_source')!='latex_direct':
        raise ValueError('bridge requires current LaTeX route')
    run=Path(record['run_dir']).resolve()
    current_manifest=json.loads((run/'source_manifest.json').read_text(encoding='utf-8'))
    if any(manifest.get(key)!=current_manifest.get(key) for key in ('input','input_type','blocks')):
        raise ValueError('bridge source manifest differs from quality input')
    pdf=Path(render_manifest['outputs']['translated_pdf']).resolve()
    current_pdf=Path(json.loads((run/'render_manifest.json').read_text())['outputs']['translated_pdf']).resolve()
    if pdf!=current_pdf or sha256(pdf)!=record['candidate_sha256']:
        raise ValueError('bridge PDF differs from quality input')
    rebuilt=build(run,Path(record['trace']))
    if rebuilt!=record or sha256(path)!=digest:
        raise ValueError('bridge cannot be reproduced from current evidence')
    if record['status']!='mapped_to_final_tex_pdf_review_pending' or record['orphan_target_block_ids']:
        raise ValueError('bridge is incomplete')
    return record


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir',type=Path);parser.add_argument('--trace',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--max-pages',type=int,default=20)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    result=build(args.run_dir,args.trace,max_pages=args.max_pages)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(json.dumps({k:result[k] for k in ['status','source_block_count','mapped_block_count','unmapped_block_ids','orphan_target_block_ids']},ensure_ascii=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
