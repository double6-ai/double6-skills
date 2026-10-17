"""单个已审源完整paragraph的真实native warming，供共享有界job调用。"""
from pathlib import Path
import argparse,json
from pdf_source_cache import SourceCache,source_cache,bound_json,file_ref,write_new,GroupProjectionCache
from independent_latex import service_identity
from paper_translation_workflow import validate_freeze
import hymt_compat_proxy as proxy


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--context-sha256',required=True)
    parser.add_argument('--coverage',type=Path)
    parser.add_argument('--coverage-sha256')
    parser.add_argument('--request-key')
    parser.add_argument('--group-id')
    parser.add_argument('--trace',type=Path,required=True)
    args=parser.parse_args()
    context_ref={'path':str(args.context.resolve()),'sha256':args.context_sha256}
    coverage_ref={'path':str(args.coverage.resolve()),'sha256':args.coverage_sha256} if args.coverage else None
    cache=source_cache(context_ref,'write');context=cache.context
    freeze=bound_json(context['freeze_ref'])
    validate_freeze(freeze,Path(context['input_ref']['path']),'digital_pdf',context['model'])
    service_identity(context['model_fingerprint_ref']['path'],context['model'],context['endpoint'])
    if isinstance(cache,GroupProjectionCache):
        if not args.group_id or args.request_key or args.coverage: raise ValueError('exact whole-group stage arguments required')
        args.trace.mkdir(parents=True,exist_ok=False)
        if cache._entry(args.group_id).exists(): raise ValueError('fresh group response required')
        group=cache.groups[args.group_id]
        if all(c['immutable'] for c in group['components']):
            cache.preserve_group(args.group_id)
            write_new(args.trace/'WARM_RESULT.json',{'status':'protected_source_identity','group_id':args.group_id,
                'actual_provider_calls':0,'entry_ref':file_ref(cache._entry(args.group_id)),'human_accepted':False})
            return
        from lmstudio_native import native_payload,post_native
        from uuid import uuid4
        request=cache.group_request(args.group_id);events=[];bodies=[]
        payload=native_payload(context['model'],request['system_control'],request['source_literal'])
        write_new(args.trace/'REQUEST.json',{'context_ref':context_ref,'source_ledger_ref':context['source_ledger_ref'],
                                           'group_id':args.group_id,'request':request,'payload':payload})
        def event(row):
            events.append(row)
            with (args.trace/'transport.jsonl').open('a') as file: file.write(json.dumps(row)+'\n')
        response=post_native(base_url=context['endpoint'],model=context['model'],system=request['system_control'],
                             source=request['source_literal'],attempt_callback=event,response_callback=bodies.append)
        if len(bodies)!=1: raise ValueError('one actual whole-group HTTP body required')
        raw=args.trace/('RAW_NATIVE_CALL_'+uuid4().hex+'.json')
        write_new(raw,{'context_ref':context_ref,'request':request,'payload':payload,'response':response,
            'response_body':bodies[0],'events':events,'endpoint':context['endpoint'].rstrip('/').removesuffix('/v1')+'/api/v1/chat'})
        cache.store_group(args.group_id,response,file_ref(raw))
        write_new(args.trace/'WARM_RESULT.json',{'status':'whole_group_response_candidate','group_id':args.group_id,
            'entry_ref':file_ref(cache._entry(args.group_id)),'raw_ref':file_ref(raw),'actual_provider_calls':1,
            'actual_usage':response['stats'],'semantic_accepted':False,'human_accepted':False})
        return
    if not args.request_key or not coverage_ref: raise ValueError('legacy request coverage required')
    rows=[json.loads(line) for line in cache.collection.read_text().splitlines()]
    matches=[row['request'] for row in rows if row['request']['key']==args.request_key and not row['request']['retry']]
    if not matches or any(row!=matches[0] for row in matches):raise ValueError('unknown or conflicting complete-source request')
    request=matches[0];cache.verify_request(request);cache.verify_coverage(coverage_ref,request)
    if (cache.directory/(request['key']+'.json')).exists():raise ValueError('warming requires new actual source response; no old response reuse')
    cfg=proxy.ProxyConfig(model=context['model'],upstream_base_url=context['endpoint'],transport='lmstudio_native_chat_v1',
        trace_dir=str(args.trace),source_cache_context_ref=context_ref,source_cache_mode='write',source_cache_coverage_ref=coverage_ref)
    output=proxy._request_plain_translation(request['source_literal'],cfg,request['policy_prompt'])
    proxy.validate_source_output(cfg,request['source_literal'],output)
    if cfg.stats.get('actual_provider_calls')!=1:raise ValueError('one actual complete-source request required')
    write_new(args.trace/'WARM_RESULT.json',{'status':'source_response_candidate','request_key':request['key'],
        'context_ref':context_ref,'coverage_ref':coverage_ref,'cache_entry_ref':file_ref(cache.directory/(request['key']+'.json')),
        'actual_provider_calls':1,'stats':cfg.stats,'semantic_accepted':False,'human_accepted':False})


if __name__=='__main__':main()
