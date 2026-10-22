# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""pdf translation runtime：从原入口拆出的同一实现。"""
from __future__ import annotations
from run_pdf_translation_context import *

def bind_final_group_artifact(args, output_dir, manifest, invocation_ref):
    """最后保存后的实际身份；复用写时门证据，rawgraph/physical未知分开保留。"""
    import fitz
    import hashlib
    from pdf_source_cache import bound_json,file_ref
    from pdf_group_source_style import source_font_inventory
    from pdf_glyph_paint_evidence import parse_tounicode
    context=bound_json({'path':str(args.source_cache_context.resolve()),'sha256':args.source_cache_context_sha256})
    if not context.get('source_style_contract_ref'):return
    invocation=bound_json(invocation_ref);run_id=invocation['render_id']
    proof_path=Path(context['collection_file']).parent/'writer'/run_id/'FINAL_SAVED_WRITER_RECONCILIATION.jsonl'
    if not proof_path.is_file():raise ValueError('final artifact current saved writer evidence missing')
    proofs=[json.loads(line)for line in proof_path.read_text().splitlines()if json.loads(line).get('render_id')==run_id]
    if len(proofs)!=1:raise ValueError('final artifact current writer identity ambiguous')
    proof=proofs[0]
    actual_manifest=json.loads((output_dir/'render_manifest.json').read_text())
    target=actual_manifest.get('outputs',{}).get('translated_pdf')
    if not target:raise ValueError('final artifact missing actual PDF')
    final_ref=file_ref(target);report={'render_id':run_id,'final_pdf_ref':final_ref,'writer_evidence_ref':file_ref(proof_path),
        'writer_saved_pdf_ref':proof['saved_pdf_ref'],'context_ref':invocation['context_ref'],'pages':[],
        'physical_glyphs_unknown':proof['physical_glyphs_unknown'],'strict_quality_pass':False}
    with fitz.open(args.input_pdf)as source,fitz.open(target)as doc:
        before=source_font_inventory(source);after=source_font_inventory(doc,False)
        report['source_raw_font_graph_exact']=all(after['fonts'].get(x)==r for x,r in before['fonts'].items())
        report['source_font_key_values_equal']=all(set(source.xref_get_keys(x))==set(doc.xref_get_keys(x))
            and all(source.xref_get_key(x,k)==doc.xref_get_key(x,k)for k in source.xref_get_keys(x))for x in before['fonts'])
        if not report['source_font_key_values_equal']:raise ValueError('final source font semantic dictionary changed')
        for page in proof['pages']:
            stream=page['stream_ref'];n=stream['page_number'];contents=doc[n].get_contents()
            if contents!=[stream['stream_xref']] or hashlib.sha256(doc.xref_stream(contents[0])).hexdigest()!=stream['decoded_stream_sha256']:
                raise ValueError('final artifact actual committed content stream changed')
            maps={};fonts={}
            for glyph in page['final_actual_glyphs']:
                x=glyph['final_font_xref']
                if x not in fonts:fonts[x]=hashlib.sha256(doc.extract_font(x)[3]).hexdigest()
                if fonts[x]!=glyph['final_font_program_sha256']:raise ValueError('final artifact actual font program changed')
                if glyph['source_binding'].get('origin')=='reviewed_complete_target_natural_span':
                    if x not in maps:
                        kind,value=doc.xref_get_key(x,'ToUnicode')
                        if kind!='xref':raise ValueError('final natural ToUnicode missing')
                        maps[x]=parse_tounicode(doc.xref_stream(int(value.split()[0])))
                    if maps[x].get(bytes.fromhex(glyph['encoded_hex']))!=glyph['actual_transform_evidence']['actual_ToUnicode']:
                        raise ValueError('final natural actual ToUnicode changed')
            report['pages'].append({'page':n+1,'actual_stream_ref':stream['stream_xref'],
                'decoded_stream_sha256':stream['decoded_stream_sha256'],'actual_font_programs_equal':True,'actual_natural_unicode_equal':True})
    if file_ref(target)!=final_ref:raise ValueError('final artifact changed during identity binding')
    report['raw_font_graph_boundary']='raw dictionary serialization differs' if not report['source_raw_font_graph_exact'] else None
    path=output_dir/'FINAL_ARTIFACT_IDENTITY.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    manifest['final_artifact_identity_ref']=file_ref(path)

def run(args: argparse.Namespace) -> dict[str, Any]:
    from pdf_translation_paths import default_output_dir
    from pdf_translation_render import _run_render
    review = getattr(args, "quality_review", None)
    digest = getattr(args, "quality_review_sha256", None)
    if bool(review) != bool(digest):
        raise ValueError("quality_review_and_frozen_sha_required_together")
    if not getattr(args, 'route_only', False):
        if getattr(args, 'source_cache_mode', None) in {'read', 'collect'} and getattr(args, 'source_cache_context', None):
            from pdf_source_cache import bound_json
            frozen = bound_json({'path': str(args.source_cache_context.resolve()),
                                 'sha256': args.source_cache_context_sha256})
            args.model = args.model or frozen.get('model')
            args.base_url = args.base_url or frozen.get('endpoint')
        if not getattr(args, 'model', None) or not getattr(args, 'base_url', None):
            raise ValueError('new_translation_requires_explicit_model_and_base_url')
    invocation_ref=None
    if getattr(args,'source_cache_mode',None)=='read':
        from pdf_source_cache import GROUP_PROTOCOLS,bound_json,begin_group_render
        context_ref={'path':str(args.source_cache_context.resolve()),'sha256':args.source_cache_context_sha256}
        if bound_json(context_ref).get('protocol') in GROUP_PROTOCOLS:
            source=Path(args.input_pdf).expanduser().resolve()
            output=Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir(source).resolve()
            invocation_ref=begin_group_render(context_ref,source,output,getattr(args,'pages',None))
            args.source_cache_render_id=bound_json(invocation_ref)['render_id']
    manifest = _run_render(args)
    if invocation_ref:
        manifest['source_cache_render_invocation_ref']=invocation_ref
        for filename in ('render_manifest.json','backend_run_manifest.json'):
            path=output/filename
            if path.is_file():
                value=json.loads(path.read_text());value['source_cache_render_invocation_ref']=invocation_ref
                path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    if bool(getattr(args, "route_only", False)):
        return manifest
    if getattr(args, "source_cache_mode", None) == "collect":
        if manifest.get("status") != "source_only_collected" or manifest.get("candidate_generated") is not False or manifest.get("actual_provider_calls") != 0:
            raise ValueError("source-only result failed no-generation/no-PDF boundary")
        return manifest
    from qa_pipeline import attach_pipeline_quality
    source = Path(args.input_pdf).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else default_output_dir(source).resolve()
    from pdf_translation_render import load_document_term_context
    # 分块翻译：块从整份文档的参考文献区中间开始时，带入区状态（上下文文件已按 SHA-256 绑定）。
    chunk_context = load_document_term_context(args) or {}
    result=attach_pipeline_quality(manifest, source=source, output_dir=output_dir,
        review_ref={"path": str(Path(review).resolve()), "sha256": digest} if review else None,
        target_language=getattr(args, "target_language", "zh") or "zh",
        region_open_at_start=chunk_context.get("reference_region_open_at_start") is True)
    if invocation_ref:bind_final_group_artifact(args,output_dir,result,invocation_ref)
    return result


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
