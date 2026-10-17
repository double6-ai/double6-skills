# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：流式身份校验与有界内存维护；详见MODIFICATIONS.md。
"""当前attempt PDF完整源请求缓存；收集阶段没有译文，render不调用provider。"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import copy
import threading

_SOURCE_PARAGRAPH_INDEX = None
_SOURCE_PARAGRAPH_LOCK = threading.RLock()


def release_source_parsing_cache():
    """翻译阶段结束后释放可重算解析对象；后续访问仍按SHA重新核验。"""
    global _SOURCE_PARAGRAPH_INDEX
    import gc
    import pdf_source_groups
    with _SOURCE_PARAGRAPH_LOCK:
        _SOURCE_PARAGRAPH_INDEX = None
    with pdf_source_groups._COMPILED_SOURCE_LOCK:
        pdf_source_groups._COMPILED_SOURCE = None
    import sys
    revision = sys.modules.get('pdf_group_editorial_revision')
    if revision is not None:
        with revision._VERIFY_LOCK:
            revision._VERIFIED_CONTRACTS.clear()
    gc.collect()

PROTOCOL='pdf_source_bound_cache_v1'
CONTRACT={'protocol':PROTOCOL,'backend_translation_cache':'bypass','render_provider_calls':0,'collection_no_pdf':True,'unit_scope':'complete_source_semantic_units'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def file_ref(path):
    path=Path(path)
    with path.open('rb') as stream:
        sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path':str(path.resolve()),'sha256':sha256}


def bound_json(ref):
    if set(ref)!={'path','sha256'} or file_ref(ref['path'])!=ref:
        raise ValueError('source cache reference changed')
    return json.loads(Path(ref['path']).read_text())


def write_new(path,value):
    with Path(path).open('x',encoding='utf-8') as file:
        json.dump(value,file,ensure_ascii=False,indent=2)


def skip_non_source_health_probe(settings):
    import os
    mode=os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_MODE')
    if not mode:return False
    if mode not in {'collect','read'}:raise ValueError('unsupported backend cache mode')
    ref={'path':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT'],
         'sha256':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT_SHA']}
    cache=source_cache(ref,mode)
    if (settings.translate_engine_settings.openai_model!=cache.context['model']
        or not settings.translation.ignore_cache):
        raise ValueError('source cache health control model/cache identity changed')
    with (cache.collection.parent/'NON_SOURCE_HEALTH_CONTROLS.jsonl').open('a') as file:
        file.write(json.dumps({'context_ref':ref,'mode':mode,'role':'backend initialization health probe',
                              'action':'skipped non-source generation','actual_provider_calls':0})+'\n')
    return True


class SourceCache:
    protocol = PROTOCOL
    extra_context_fields = set()
    optional_context_fields = set()
    def __init__(self,context_ref,mode):
        from independent_latex import reject_symlink_ancestors
        if mode not in {'collect','write','read'}:raise ValueError('unknown source cache mode')
        self.context_ref=context_ref;self.mode=mode;self.context=bound_json(context_ref)
        required={'protocol','freeze_ref','input_ref','scope_ref','model_fingerprint_ref','implementation_refs',
                  'policy_ref','model','endpoint','parameters','transport','transport_contract','cache_directory','collection_file','editorial_revisions'}
        present=set(self.context); mandatory=required | self.extra_context_fields
        if (not mandatory.issubset(present) or present-mandatory-self.optional_context_fields
                or self.context['protocol']!=self.protocol):
            raise ValueError('incomplete source cache context')
        if self.context['transport']!='lmstudio_native_chat_v1':raise ValueError('native source cache transport required')
        from lmstudio_native import PARAMETERS,CONTRACT_ID,TRANSPORT
        fp=bound_json(self.context['model_fingerprint_ref'])
        if self.context['transport_contract']!=TRANSPORT or fp.get('transport_contract')!=TRANSPORT or fp.get('api_contract')!=CONTRACT_ID or self.context['parameters']!=PARAMETERS or fp.get('generation_parameters')!=PARAMETERS or fp.get('model_id')!=self.context['model'] or fp.get('endpoint')!=self.context['endpoint']:
            raise ValueError('source cache native model/generation fingerprint mismatch')
        for name in ('freeze_ref','input_ref','scope_ref','model_fingerprint_ref','policy_ref'):
            item=self.context[name]
            if file_ref(item['path'])!=item:raise ValueError('source cache context dependency changed:'+name)
        for item in self.context['implementation_refs']:
            if file_ref(item['path'])!=item:raise ValueError('source cache implementation changed')
        self.directory=reject_symlink_ancestors(self.context['cache_directory']).resolve()
        self.collection=reject_symlink_ancestors(self.context['collection_file']).resolve()
        if self.mode!='read':self.directory.mkdir(parents=True,exist_ok=True)
        self.identity=digest(json.dumps(self.context,sort_keys=True,separators=(',',':')))

    def request(self,source,system,policy_prompt='',retry=False):
        if not isinstance(source,str) or not source.strip() or not isinstance(system,str) or not system.strip():
            raise ValueError('complete literal/system required')
        row={'source_literal':source,'source_sha256':digest(source),'system_control':system,
             'system_sha256':digest(system),'policy_prompt':policy_prompt,'retry':bool(retry)}
        row['key']=digest(json.dumps({'context':self.identity,'source':row['source_sha256'],
                                     'system':row['system_sha256']},sort_keys=True))
        return row

    def verify_request(self,request):
        expected=self.request(request['source_literal'],request['system_control'],request['policy_prompt'],request['retry'])
        if request!=expected:raise ValueError('source cache request fields or digest changed')

    def verify_coverage(self,ref,request):
        coverage=bound_json(ref)
        if (coverage.get('status')!='pass_complete_source_units' or coverage.get('context_ref')!=self.context_ref
            or coverage.get('input_ref')!=self.context['input_ref']
            or coverage.get('source_collection_ref')!=file_ref(self.collection)
            or request['key'] not in coverage.get('reviewed_original_request_keys',[])):
            raise ValueError('complete source paragraph coverage review required')
        for name in ('source_il_ref','scope_ref'):
            item=coverage[name]
            if file_ref(item['path'])!=item:raise ValueError('source coverage dependency changed')

    def collect(self,request):
        self.verify_request(request)
        if self.mode!='collect':raise ValueError('collection mode required')
        with self.collection.open('a',encoding='utf-8') as file:
            file.write(json.dumps({'origin':'source_only_nontranslation','context_ref':self.context_ref,
                                   'request':request},ensure_ascii=False)+'\n')

    def verify_transport(self,ref,request,response):
        from lmstudio_native import native_payload,TRANSPORT
        raw=bound_json(ref)
        payload=native_payload(self.context['model'],request['system_control'],request['source_literal'])
        if (raw.get('context_ref')!=self.context_ref or raw.get('request')!=request
            or raw.get('payload')!=payload or raw.get('response')!=response
            or raw.get('endpoint')!=self.context['endpoint'].rstrip('/').removesuffix('/v1')+'/api/v1/chat'):
            raise ValueError('actual native transport request/response changed')
        body=raw.get('response_body')
        if not isinstance(body,str) or json.loads(body)!=response:
            raise ValueError('actual native response body differs')
        events=raw.get('events')
        if not isinstance(events,list) or [event.get('phase') for event in events]!=['start','success']:
            raise ValueError('one actual native transport start/success required')
        request_sha=digest(json.dumps(payload))
        for event in events:
            if (event.get('attempt')!=1 or event.get('max_attempts')!=TRANSPORT['max_attempts']
                or event.get('request_timeout_seconds')!=TRANSPORT['request_timeout_seconds']
                or event.get('request_sha256')!=request_sha):
                raise ValueError('actual native transport event contract changed')
        if events[1].get('response_sha256')!=digest(body):
            raise ValueError('actual native transport response SHA differs')

    def store(self,request,response,coverage_ref,transport_ref):
        self.verify_request(request)
        self.verify_coverage(coverage_ref,request)
        if self.mode!='write' or request['retry']:raise ValueError('only original complete-source request may warm')
        from lmstudio_native import native_text
        from collections import Counter
        import re
        output=native_text(response,self.context['model'])
        if Counter(re.findall(r'\{v\d+\}',request['source_literal']))!=Counter(re.findall(r'\{v\d+\}',output)):
            raise ValueError('source cache placeholder mismatch')
        self.verify_transport(transport_ref,request,response)
        row={'protocol':PROTOCOL,'origin':'native_model_response','context_ref':self.context_ref,
             'context_identity':self.identity,'request':request,'response':response,'actual_provider_calls':1,
             'coverage_ref':coverage_ref,'transport_raw_ref':transport_ref,
             'semantic_accepted':False,'human_accepted':False}
        entry=self.directory/(request['key']+'.json')
        write_new(entry,row)
        with (self.directory/'ENTRY_MANIFEST.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps({'context_ref':self.context_ref,'request_key':request['key'],
                                   'entry_ref':file_ref(entry),'transport_raw_ref':transport_ref})+'\n')

    def read(self,request):
        self.verify_request(request)
        if self.mode!='read' or request['retry']:raise ValueError('fallback/retry is outside source cache original request')
        path=self.directory/(request['key']+'.json')
        if not path.is_file():raise ValueError('unknown or missing current-attempt literal cache')
        row=json.loads(path.read_text())
        manifest=self.directory/'ENTRY_MANIFEST.jsonl'
        if not manifest.is_file():raise ValueError('actual entry manifest missing')
        matches=[json.loads(line) for line in manifest.read_text().splitlines()
                 if json.loads(line).get('request_key')==request['key']]
        expected={'context_ref':self.context_ref,'request_key':request['key'],
                  'entry_ref':file_ref(path),'transport_raw_ref':row.get('transport_raw_ref')}
        if matches!=[expected]:raise ValueError('actual entry/RAW manifest identity changed')
        if (row.get('protocol')!=PROTOCOL or row.get('origin')!='native_model_response'
            or row.get('context_ref')!=self.context_ref or row.get('context_identity')!=self.identity
            or row.get('request')!=request or type(row.get('actual_provider_calls')) is not int or row.get('actual_provider_calls')!=1):
            raise ValueError('current-attempt source cache identity changed')
        self.verify_coverage(row['coverage_ref'],request)
        self.verify_transport(row['transport_raw_ref'],request,row['response'])
        from lmstudio_native import native_text
        output=native_text(row['response'],self.context['model'])
        from collections import Counter
        import re
        if Counter(re.findall(r'\{v\d+\}',request['source_literal']))!=Counter(re.findall(r'\{v\d+\}',output)):
            raise ValueError('cached source placeholder mismatch')
        editorial=None
        for item in self.context['editorial_revisions']:
            if set(item)!={'source_ref','target_ref','review_ref','initial_failed_raw_ref','provenance_ref'}:
                raise ValueError('unknown editorial revision protocol')
            source=bound_json(item['source_ref'])
            if source.get('literal')!=request['source_literal']:continue
            if source.get('source_sha256')!=request['source_sha256'] or source.get('source_pdf_ref')!=self.context['input_ref']:
                raise ValueError('editorial source scope changed')
            target=bound_json(item['target_ref']);review=bound_json(item['review_ref'])
            bound_json(item['provenance_ref'])
            if file_ref(item['initial_failed_raw_ref']['path'])!=item['initial_failed_raw_ref']:
                raise ValueError('original failed model provenance changed')
            if (review.get('status')!='pass_semantic_proposal_only'
                or not all(ref in [{k:r[k] for k in ('path','sha256')} for r in review.get('input_refs',[])]
                           for ref in (item['source_ref'],item['target_ref']))
                or target.get('revision_kind')!='coordinator_full_paragraph_editorial'):
                raise ValueError('complete editorial proposal independent review required')
            value=target.get('target_literal')
            if not isinstance(value,str) or not value.strip() or Counter(re.findall(r'\{v\d+\}',value))!=Counter(re.findall(r'\{v\d+\}',request['source_literal'])):
                raise ValueError('editorial complete source placeholder mismatch')
            if editorial is not None:raise ValueError('duplicate full-paragraph editorial revisions')
            editorial={'origin':'coordinator_full_paragraph_editorial','output':value,'refs':item,
                       'actual_provider_calls':0,'actual_pdf_verified':False,'human_accepted':False}
        self.last_read_refs={'entry_ref':file_ref(path),'transport_raw_ref':row['transport_raw_ref'],
                             'entry_manifest_ref':file_ref(manifest)}
        return row['response'],editorial


GROUP_PROTOCOL = 'pdf_whole_group_parent_cache_v1'
GROUP_CONTRACT = {'protocol':GROUP_PROTOCOL,'backend_translation_cache':'bypass',
                  'render_provider_calls':0,'unit_scope':'independently_reviewed_complete_source_groups',
                  'parent_raw_required':True,'projection_origin':'derived_whole_group_projection'}
REVISION_PROTOCOL = 'pdf_whole_group_reviewed_projection_cache_v1'
REVISION_CONTRACT = {'protocol':REVISION_PROTOCOL,'backend_translation_cache':'bypass',
    'render_provider_calls':0,'unit_scope':'independently_reviewed_complete_source_groups',
    'historical_native_baseline_required':True,'reviewed_revision_contract_required':True,
    'projection_origin':'derived_reviewed_or_retained_group_projection'}
GROUP_PROTOCOLS = (GROUP_PROTOCOL, REVISION_PROTOCOL)
GROUP_RENDER_CONTROL = 'Render only the current reviewed whole-group projection for this exact original backend source literal. No provider generation, fallback, heuristic direct translation, or historical cache is permitted.'


GROUP_PACKET_PROTOCOL = 'pdf_whole_group_backend_literal_v2'
RENDER_INVOCATION_PROTOCOL = 'pdf_whole_group_render_invocation_v1'


def render_invocation_id(value=None):
    import os
    from uuid import UUID
    value=os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_RENDER_ID') if value is None else value
    if not isinstance(value,str) or len(value)!=32:
        raise ValueError('actual group render invocation ID required')
    try: parsed=UUID(hex=value)
    except ValueError as error: raise ValueError('invalid group render invocation ID') from error
    if parsed.hex!=value or parsed.version!=4:
        raise ValueError('canonical fresh UUID4 render invocation required')
    return value


def begin_group_render(context_ref,input_pdf,output_dir,requested_pages=None):
    from uuid import uuid4
    cache=source_cache(context_ref,'read')
    if cache.protocol not in GROUP_PROTOCOLS or cache.context['input_ref']!=file_ref(input_pdf):
        raise ValueError('current group render source/context identity differs')
    path=Path(output_dir)/'SOURCE_CACHE_RENDER_INVOCATION.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    write_new(path,{'protocol':RENDER_INVOCATION_PROTOCOL,'render_id':uuid4().hex,
        'context_ref':context_ref,'input_ref':cache.context['input_ref'],'requested_pages':requested_pages,
        'origin':'actual_run_pdf_translation_launcher','actual_provider_calls':0})
    return file_ref(path)


def group_backend_packet(context_ref, source_paragraph_sha256, source_literal, render_id=None):
    # Validate refs on the producer side as well as at the HTTP boundary.
    source_cache(context_ref, 'read')
    return {'protocol':GROUP_PACKET_PROTOCOL,'context_ref':context_ref,
            'render_id':render_invocation_id(render_id),
            'source_paragraph_sha256':source_paragraph_sha256,
            'source_literal':source_literal,'source_sha256':digest(source_literal),
            'render_control':GROUP_RENDER_CONTROL}


def validate_group_backend_packet(packet, context_ref, render_id):
    expected={'protocol','context_ref','render_id','source_paragraph_sha256','source_literal','source_sha256','render_control'}
    if not isinstance(packet,dict) or set(packet)!=expected:
        raise ValueError('invalid whole-group source packet fields')
    if packet['protocol']!=GROUP_PACKET_PROTOCOL or packet['context_ref']!=context_ref or packet['render_control']!=GROUP_RENDER_CONTROL:
        raise ValueError('whole-group source packet protocol/context/control changed')
    if not isinstance(render_id,str) or render_invocation_id(packet['render_id'])!=render_invocation_id(render_id):
        raise ValueError('source packet belongs to another render invocation')
    if not isinstance(packet['source_literal'],str) or packet['source_sha256']!=digest(packet['source_literal']):
        raise ValueError('whole-group source literal digest changed')
    if not isinstance(packet['source_paragraph_sha256'],str) or len(packet['source_paragraph_sha256'])!=64:
        raise ValueError('whole-group source paragraph identity missing')
    return source_cache(context_ref,'read')


def group_fragment_roles(cache):
    """源重算确认的纯科学片段保护；含任何普通组件的宿主仍须HTTP。"""
    import re
    from pdf_source_groups import validate_group_response
    by_paragraph={}
    for group in cache.groups.values():
        for component in group['components']:
            if component['kind']=='source_fragment':
                by_paragraph.setdefault(component['source_paragraph_sha256'],[]).append((group,component))
    ordinary={};immutable={}
    for sid,members in by_paragraph.items():
        if any(type(c.get('immutable')) is not bool for _,c in members):
            raise ValueError('source-derived immutable classification required')
        pages={c['source_page'] for _,c in members}
        if len(pages)!=1:raise ValueError('source paragraph page is ambiguous')
        if any(not c['immutable'] for _,c in members):
            ordinary[sid]=next(iter(pages));continue
        bibliography_roles={g.get('source_role')=='bibliography_identity' for g,_ in members}
        if len(bibliography_roles)!=1:raise ValueError('mixed immutable source identity roles are ambiguous')
        for group,component in members:
            value=component['input_text']
            ids=re.findall(r'\[\[PTS:([^\]]+)\]\]',value)
            bibliography=group.get('source_role')=='bibliography_identity'
            if (ids!=component['scientific_ids'] or (not bibliography and
                (not ids or re.sub(r'\[\[PTS:[^\]]+\]\]','',value).strip()))):
                raise ValueError('immutable fragment contains ordinary or unknown source')
            # The validator re-compiles kinds/ranges/glyphs from actual bound
            # source refs. A caller's immutable flag cannot protect prose.
            original='\n'.join('[[PTC:'+c['component_id']+']]'+c['input_text']+'[[/PTC:'+c['component_id']+']]' for c in group['components'])
            validate_group_response(group,original)
        immutable[sid]=next(iter(pages))
    return ordinary,immutable


def immutable_fragment_kind(cache,sid):
    roles={g['source_role'] for g in cache.groups.values() for c in g['components']
           if c['kind']=='source_fragment' and c['source_paragraph_sha256']==sid}
    return 'bibliography_identity' if roles=={'bibliography_identity'} else 'scientific_only'


def backend_group_source(paragraph, page, font_map):
    """在任意role/短段启发式前核对原源完整glyph/font/geometry身份。"""
    import os
    from dataclasses import asdict
    from pdf_source_groups import _paragraph
    mode=os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_MODE')
    if mode!='read': return None
    ref={'path':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT'],
         'sha256':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT_SHA']}
    if bound_json(ref).get('protocol') not in GROUP_PROTOCOLS: return None
    cache=source_cache(ref,'read')
    bound=_paragraph(page.page_number+1,asdict(paragraph),
                     {key:asdict(value) for key,value in font_map.items()},cache.context['input_ref']['sha256'])
    ordinary,immutable=group_fragment_roles(cache)
    ordinary=set(ordinary)
    protected={p['source_object_sha256'] for p in cache.ledger['protected_source_objects']}
    protected.update(immutable)
    if bound['sha256'] not in ordinary|protected: raise ValueError('unreviewed or changed actual backend paragraph')
    role='whole_group_projection' if bound['sha256'] in ordinary else 'protected_source_identity'
    run_id=render_invocation_id()
    # debug_id每次解析会随机生成，只绑定本次源核验事件与同一次译后对象。
    with (cache.collection.parent/'BACKEND_SOURCE_BOUNDARY.jsonl').open('a') as file:
        file.write(json.dumps({'context_ref':ref,'render_id':run_id,'source_paragraph_sha256':bound['sha256'],
            'page':page.page_number+1,'backend_paragraph_debug_id':paragraph.debug_id,
            'source_literal':bound['source_composition_masked_literal'],
            'role':role,'actual_provider_calls':0})+'\n')
    return {'role':role,'source_literal':bound['source_composition_masked_literal'],'source_sha256':bound['sha256'],'context_ref':ref,'render_id':run_id}


def record_backend_group_failure(error):
    import os
    context_path=os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT')
    if not context_path: return
    context=json.loads(Path(context_path).read_text())
    if context.get('protocol') not in GROUP_PROTOCOLS: return
    destination=Path(context['collection_file']).parent/'BACKEND_GROUP_FAILURE.jsonl'
    with destination.open('a') as file:
        file.write(json.dumps({'context_path':context_path,'error_type':type(error).__name__,
                               'render_id':os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_RENDER_ID'),
                               'message':str(error),'whole_render_rejected':True,'actual_provider_calls':0})+'\n')
    if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
        from pdf_group_source_style import release_current_runtime
        release_current_runtime('backend_source_translation_failure')


def validate_backend_group_coverage(docs):
    """源段落边界全覆盖及独立显示字形在翻译阶段未重画；PDF仍需独立QA。"""
    import os
    from dataclasses import asdict
    from pdf_source_groups import digest as source_digest, _glyph
    if os.environ.get('PAPER_TRANSLATION_SOURCE_CACHE_MODE')!='read': return
    context_ref={'path':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT'],
                 'sha256':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT_SHA']}
    if bound_json(context_ref).get('protocol') not in GROUP_PROTOCOLS: return
    cache=source_cache(context_ref,'read');directory=cache.collection.parent
    pages={p.page_number+1 for p in docs.page}
    expected={c['source_paragraph_sha256'] for g in cache.groups.values() for c in g['components']
              if c['kind']=='source_fragment' and c['source_page'] in pages}
    expected.update(p['source_object_sha256'] for p in cache.ledger['protected_source_objects'] if p['source']['page'] in pages)
    run_id=render_invocation_id()
    actual=[row for line in (directory/'BACKEND_SOURCE_BOUNDARY.jsonl').read_text().splitlines()
            if (row:=json.loads(line)).get('render_id')==run_id]
    if any(row['context_ref']!=context_ref for row in actual): raise ValueError('backend source boundary has foreign context')
    covered={row['source_paragraph_sha256'] for row in actual if row['page'] in pages}
    if covered!=expected: raise ValueError('backend skipped or changed reviewed source paragraph')
    current_identities={}
    for row in actual:
        if row['page'] not in pages:continue
        key=(row['page'],row.get('backend_paragraph_debug_id'))
        if not key[1] or (key in current_identities and current_identities[key]!=row['source_paragraph_sha256']):
            raise ValueError('ambiguous current backend source paragraph identity')
        current_identities[key]=row['source_paragraph_sha256']
    source=bound_json(cache.ledger['source_il_ref'])
    original={p['page_number']:p for p in source['page']}
    display=[];immutable_evidence=[];live_source_ids=[]
    _,immutable=group_fragment_roles(cache)
    from pdf_source_groups import _paragraph
    for live in docs.page:
        old=original[live.page_number]
        fonts={f['font_id']:f for f in old['pdf_font']}
        before=[_glyph(live.page_number+1,char,fonts) for char in old['pdf_character']]
        after=[_glyph(live.page_number+1,asdict(char),fonts) for char in live.pdf_character]
        if after!=before: raise ValueError('original top-level scientific glyph/font/GID/geometry changed during translation')
        display.append({'page':live.page_number+1,'glyph_count':len(before),'source_objects_sha256':source_digest(before)})
        # 普通段已变成目标Unicode composition；只在源角色指向保护段时
        # 重核源字形，避免把合法译文重新送进只接受源字形的解析器。
        for para in live.pdf_paragraph:
            source_sid=current_identities.get((live.page_number+1,para.debug_id))
            if source_sid not in expected:
                raise ValueError('source paragraph membership changed during translation')
            live_source_ids.append(source_sid)
            active=dict(fonts)
            for obj in old.get('pdf_xobject',[]):
                if obj['xobj_id']==para.xobj_id:active.update({f['font_id']:f for f in obj['pdf_font']})
            if source_sid in immutable:
                bound=_paragraph(live.page_number+1,asdict(para),active,cache.context['input_ref']['sha256'])
                if bound['sha256']!=source_sid:
                    raise ValueError('immutable source paragraph changed during translation')
                immutable_evidence.append({'source_paragraph_sha256':bound['sha256'],'page':live.page_number+1,
                    'source_identity_kind':immutable_fragment_kind(cache,bound['sha256']),
                    'actual_source_glyph_font_gid_geometry_unchanged':True})
    if len(live_source_ids)!=len(set(live_source_ids)) or set(live_source_ids)!=expected:
        raise ValueError('source paragraph membership changed during translation')
    if {x['source_paragraph_sha256'] for x in immutable_evidence}!={sid for sid,page in immutable.items() if page in pages}:
        raise ValueError('current immutable scientific fragment source bytes changed')
    with (directory/'BACKEND_GROUP_COVERAGE.jsonl').open('a') as file:
        file.write(json.dumps({'context_ref':context_ref,'render_id':run_id,'pages':sorted(pages),'source_paragraph_sha256':sorted(covered),
            'source_display_objects':display,'immutable_source_fragments':immutable_evidence,'actual_provider_calls':0,'stage':'after translation, before typesetting',
            'actual_pdf_verified':False})+'\n')


def validate_group_render_evidence(context_ref,invocation_ref,pages,proxy_trace_dir):
    """本次实际源边界、HTTP投影和原科学字形证据；历史命中不能覆盖。"""
    from pdf_source_groups import _glyph,digest as source_digest
    invocation=bound_json(invocation_ref);run_id=render_invocation_id(invocation.get('render_id'))
    cache=source_cache(context_ref,'read')
    if (invocation.get('protocol')!=RENDER_INVOCATION_PROTOCOL or invocation.get('context_ref')!=context_ref
        or invocation.get('input_ref')!=cache.context['input_ref']
        or invocation.get('origin')!='actual_run_pdf_translation_launcher'
        or type(invocation.get('actual_provider_calls')) is not int or invocation['actual_provider_calls']!=0):
        raise ValueError('current actual launcher invocation identity differs')
    directory=cache.collection.parent
    def current_rows(path):
        if not path.is_file():return []
        return [row for line in path.read_text().splitlines() if (row:=json.loads(line)).get('render_id')==run_id]
    if current_rows(directory/'BACKEND_GROUP_FAILURE.jsonl'):
        raise ValueError('current whole-group backend failed')
    ordinary,immutable=group_fragment_roles(cache)
    ordinary={sid:page for sid,page in ordinary.items() if page in pages}
    immutable={sid:page for sid,page in immutable.items() if page in pages}
    protected={p['source_object_sha256']:p['source']['page'] for p in cache.ledger['protected_source_objects']
               if p['source']['page'] in pages}
    protected.update(immutable)
    expected={**ordinary,**protected}
    boundary=current_rows(directory/'BACKEND_SOURCE_BOUNDARY.jsonl')
    if {row.get('source_paragraph_sha256') for row in boundary}!=set(expected):
        raise ValueError('current render source/protected roles missing; historical hits forbidden')
    for row in boundary:
        sid=row['source_paragraph_sha256']
        if (row.get('context_ref')!=context_ref or row.get('page')!=expected[sid]
            or row.get('role')!=('whole_group_projection' if sid in ordinary else 'protected_source_identity')
            or type(row.get('actual_provider_calls')) is not int or row['actual_provider_calls']!=0):
            raise ValueError('current render source boundary identity differs')
    coverage=current_rows(directory/'BACKEND_GROUP_COVERAGE.jsonl')
    covered=set();covered_pages=set();displays=[];immutable_rows=[]
    for row in coverage:
        if row.get('context_ref')!=context_ref or type(row.get('actual_provider_calls')) is not int or row['actual_provider_calls']!=0:
            raise ValueError('current backend coverage identity differs')
        covered.update(row['source_paragraph_sha256']);covered_pages.update(row['pages']);displays.extend(row['source_display_objects'])
        immutable_rows.extend(row.get('immutable_source_fragments',[]))
    source=bound_json(cache.ledger['source_il_ref']);expected_displays=[]
    for page in source['page']:
        number=page['page_number']+1
        if number not in pages:continue
        glyphs=[_glyph(number,char,{f['font_id']:f for f in page['pdf_font']}) for char in page['pdf_character']]
        expected_displays.append({'page':number,'glyph_count':len(glyphs),'source_objects_sha256':source_digest(glyphs)})
    if covered!=set(expected) or covered_pages!=set(pages) or sorted(displays,key=lambda r:r['page'])!=expected_displays:
        raise ValueError('current backend actual role/display coverage differs')
    if ({r.get('source_paragraph_sha256') for r in immutable_rows}!=set(immutable)
        or any(r.get('page')!=immutable.get(r.get('source_paragraph_sha256'))
            or r.get('source_identity_kind')!=immutable_fragment_kind(cache,r.get('source_paragraph_sha256'))
            or r.get('actual_source_glyph_font_gid_geometry_unchanged') is not True for r in immutable_rows)):
        raise ValueError('current immutable scientific fragment evidence incomplete')
    http=current_rows(Path(proxy_trace_dir)/'group_http_dispatch.jsonl');hits=set()
    for event in http:
        if event.get('status')!=200 or event.get('context_ref')!=context_ref or type(event.get('new_provider_calls')) is not int or event['new_provider_calls']!=0:
            raise ValueError('current actual HTTP projection rejected or generated')
        for name in ('request','response'):
            if digest(event[name+'_body'])!=event.get(name+'_sha256'):
                raise ValueError('actual HTTP body evidence drift')
        packet=event['packet'];validate_group_backend_packet(packet,context_ref,run_id)
        payload=json.loads(event['request_body']);messages=payload.get('messages')
        if not isinstance(messages,list) or len(messages)!=1 or messages[0].get('role')!='user' or json.loads(messages[0]['content'])!=packet:
            raise ValueError('actual HTTP request does not carry current source packet')
        if json.loads(event['response_body'])['choices'][0]['message']['content']!=event['effective_output']:
            raise ValueError('actual HTTP projection response evidence differs')
        hits.add(packet['source_paragraph_sha256'])
    if hits!=set(ordinary):raise ValueError('current ordinary paragraph HTTP projections incomplete')
    return {'render_id':run_id,'invocation_ref':invocation_ref,'context_ref':context_ref,'pages':sorted(pages),
            'ordinary_paragraphs':len(ordinary),'protected_paragraphs':len(protected),'actual_http_hits':len(http),
            'actual_provider_calls':0,'historical_rows_inherited':False,'independent_pdf_quality_pass':False}


def verified_source_paragraph(source_ref, input_ref, paragraph_sha):
    """单份原IL索引；每次仍重哈实际PDF/IL，复用完整已解析源。"""
    global _SOURCE_PARAGRAPH_INDEX
    if file_ref(source_ref['path'])!=source_ref or file_ref(input_ref['path'])!=input_ref:
        raise ValueError('actual source PDF/IL identity changed')
    key=(source_ref['path'],source_ref['sha256'],input_ref['sha256'])
    with _SOURCE_PARAGRAPH_LOCK:
        if _SOURCE_PARAGRAPH_INDEX is None or _SOURCE_PARAGRAPH_INDEX[0]!=key:
            from pdf_source_groups import _paragraph
            document=bound_json(source_ref);index={}
            for page in document['page']:
                fonts={f['font_id']:f for f in page['pdf_font']}
                for para in page['pdf_paragraph']:
                    active=dict(fonts)
                    for form in page.get('pdf_xobject',[]):
                        if form['xobj_id']==para.get('xobj_id'):active.update({f['font_id']:f for f in form['pdf_font']})
                    row=_paragraph(page['page_number']+1,para,active,input_ref['sha256'])
                    if row['sha256'] in index:raise ValueError('source paragraph identity ambiguous')
                    index[row['sha256']]=row
            _SOURCE_PARAGRAPH_INDEX=(key,index)
        if paragraph_sha not in _SOURCE_PARAGRAPH_INDEX[1]:
            raise ValueError('source paragraph identity missing/ambiguous')
        return copy.deepcopy(_SOURCE_PARAGRAPH_INDEX[1][paragraph_sha])


def source_cache(context_ref, mode):
    protocol=bound_json(context_ref).get('protocol')
    if protocol==REVISION_PROTOCOL:
        from pdf_group_editorial_revision import ReviewedGroupProjectionCache
        return ReviewedGroupProjectionCache(context_ref,mode)
    cls = GroupProjectionCache if protocol == GROUP_PROTOCOL else SourceCache
    return cls(context_ref, mode)


class GroupProjectionCache(SourceCache):
    """真实整组 parent RAW；投影只读，不伪造子段 provider response。"""
    protocol = GROUP_PROTOCOL
    extra_context_fields = {'source_ledger_ref', 'source_review_ref'}

    def __init__(self, context_ref, mode):
        super().__init__(context_ref, mode)
        from pdf_source_groups import digest as ledger_digest, PROTOCOL as ledger_protocol
        self.ledger = bound_json(self.context['source_ledger_ref'])
        unsigned = {k:v for k,v in self.ledger.items() if k != 'source_ledger_sha256'}
        if (self.ledger.get('protocol') != ledger_protocol or self.ledger.get('input_ref') != self.context['input_ref']
            or self.ledger.get('source_ledger_sha256') != ledger_digest(unsigned)):
            raise ValueError('reviewed complete source ledger changed')
        self._original_ledger_digest = self.ledger['source_ledger_sha256']
        for item in self.ledger['implementation_refs']:
            if file_ref(item['path']) != item: raise ValueError('source ledger implementation changed')
        self.verify_group_review()
        if self.context['editorial_revisions']:
            raise ValueError('whole-group editorial requires separately bound revision protocol; no implicit old revision')
        self.groups = {g['group_id']:g for g in self.ledger['groups']}
        if len(self.groups) != len(self.ledger['groups']): raise ValueError('duplicate whole source groups')

    def verify_group_review(self):
        review = bound_json(self.context['source_review_ref'])
        declared=review.get('input_refs')
        if isinstance(declared,dict):
            if declared.get('ledger')!=self.context['source_ledger_ref'] or declared.get('pdf')!=self.context['input_ref']:
                raise ValueError('named independent source ledger/PDF review differs')
            refs=[]
            for value in declared.values():
                refs.extend(value if isinstance(value,list) else [value])
        elif isinstance(declared,list):
            refs=declared
        else:
            raise ValueError('independent source review references missing')
        for evidence in refs:
            if not isinstance(evidence,dict) or set(evidence)!={'path','sha256'} or file_ref(evidence['path'])!=evidence:
                raise ValueError('independent source review dependency changed')
        if (review.get('status') != 'pass_complete_source_groups'
            or self.context['source_ledger_ref'] not in refs or self.context['input_ref'] not in refs):
            raise ValueError('independent complete source-group coverage PASS required')

    def group_request(self, group_id):
        from pdf_source_groups import build_group_input, digest as ledger_digest
        expected = getattr(self, '_original_ledger_digest', None)
        # 修订namespace自行验证其完整合同；保留既有深比较。
        if expected is None:
            valid = bound_json(self.context['source_ledger_ref']) == self.ledger
        else:
            valid = (file_ref(self.context['source_ledger_ref']['path']) == self.context['source_ledger_ref']
                     and self.ledger.get('source_ledger_sha256') == expected
                     and ledger_digest({k: v for k, v in self.ledger.items()
                                        if k != 'source_ledger_sha256'}) == expected)
        if not valid:
            raise ValueError('caller changed reviewed source ledger or atom kinds')
        if group_id not in self.groups: raise ValueError('unknown complete source group')
        packet = build_group_input(self.groups[group_id])
        return self.request(packet['source_literal'], packet['system_control'])

    def _entry(self, group_id):
        return self.directory / (group_id + '.json')

    def _append_entry(self, group_id, row):
        entry = self._entry(group_id)
        write_new(entry, row)
        with (self.directory/'GROUP_PARENT_MANIFEST.jsonl').open('a') as file:
            file.write(json.dumps({'group_id':group_id, 'context_ref':self.context_ref,
                                   'entry_ref':file_ref(entry), 'transport_raw_ref':row.get('transport_raw_ref')})+'\n')

    def store_group(self, group_id, response, transport_ref):
        from lmstudio_native import native_text
        from pdf_source_groups import validate_group_response
        if self.mode != 'write': raise ValueError('whole-group write mode required')
        request = self.group_request(group_id)
        self.verify_transport(transport_ref, request, response)
        projection = validate_group_response(self.groups[group_id], native_text(response, self.context['model']))
        self._append_entry(group_id, {'protocol':GROUP_PROTOCOL, 'context_ref':self.context_ref,
            'context_identity':self.identity, 'group_id':group_id, 'request':request,
            'response':response, 'transport_raw_ref':transport_ref, 'projection':projection,
            'origin':'native_whole_group_response', 'actual_provider_calls':1,
            'semantic_accepted':False, 'human_accepted':False})

    def preserve_group(self, group_id):
        from pdf_source_groups import validate_group_response
        group = self.groups[group_id]
        if self.mode != 'write' or group.get('source_role') != 'bibliography_identity' or not all(c['immutable'] for c in group['components']):
            raise ValueError('only complete immutable source identity may bypass generation')
        value = '\n'.join('[[PTC:'+c['component_id']+']]'+c['input_text']+'[[/PTC:'+c['component_id']+']]' for c in group['components'])
        self._append_entry(group_id, {'protocol':GROUP_PROTOCOL, 'context_ref':self.context_ref,
            'context_identity':self.identity, 'group_id':group_id, 'request':self.group_request(group_id),
            'projection':validate_group_response(group,value), 'transport_raw_ref':None,
            'origin':'protected_source_identity', 'actual_provider_calls':0,
            'semantic_accepted':False, 'human_accepted':False})

    def read_group(self, group_id):
        from lmstudio_native import native_text
        from pdf_source_groups import validate_group_response
        entry = self._entry(group_id); row = json.loads(entry.read_text())
        manifest = self.directory/'GROUP_PARENT_MANIFEST.jsonl'
        matches = [json.loads(line) for line in manifest.read_text().splitlines()
                   if json.loads(line).get('group_id') == group_id]
        expected = {'group_id':group_id,'context_ref':self.context_ref,'entry_ref':file_ref(entry),
                    'transport_raw_ref':row.get('transport_raw_ref')}
        if matches != [expected] or row.get('context_identity') != self.identity or row.get('context_ref') != self.context_ref or row.get('protocol') != GROUP_PROTOCOL or row.get('group_id') != group_id or row.get('request') != self.group_request(group_id):
            raise ValueError('current whole-group parent entry identity changed')
        if row.get('origin') == 'native_whole_group_response' and type(row.get('actual_provider_calls')) is int and row['actual_provider_calls'] == 1:
            self.verify_transport(row['transport_raw_ref'], row['request'], row['response'])
            value = native_text(row['response'], self.context['model'])
        elif row.get('origin') == 'protected_source_identity' and type(row.get('actual_provider_calls')) is int and row['actual_provider_calls'] == 0 and row.get('transport_raw_ref') is None and self.groups[group_id].get('source_role') == 'bibliography_identity' and all(c['immutable'] for c in self.groups[group_id]['components']):
            value = '\n'.join('[[PTC:'+c['component_id']+']]'+c['input_text']+'[[/PTC:'+c['component_id']+']]' for c in self.groups[group_id]['components'])
        else: raise ValueError('unknown or falsely declared parent origin')
        projection = validate_group_response(self.groups[group_id], value)
        if row.get('projection') != projection: raise ValueError('derived projection differs from immutable actual parent')
        return projection, {'group_id':group_id,'entry_ref':file_ref(entry),'transport_raw_ref':row.get('transport_raw_ref'),
                            'origin':row['origin'],'retained_provider_calls':row['actual_provider_calls']}

    def render_literal(self, source, control, retry=False, source_paragraph_sha256=None):
        from collections import Counter
        import re
        if self.mode != 'read' or retry or control != GROUP_RENDER_CONTROL:
            raise ValueError('whole-group render only exact read control; fallback forbidden')
        components = [(gid,c) for gid,g in self.groups.items() for c in g['components']
                      if c['kind']=='source_fragment' and c['backend_paragraph_source_literal']==source
                      and (source_paragraph_sha256 is None or c['source_paragraph_sha256']==source_paragraph_sha256)]
        if not components: raise ValueError('unknown current reviewed backend source literal')
        paragraph_ids = {c['source_paragraph_sha256'] for _,c in components}
        if len(paragraph_ids)!=1: raise ValueError('ambiguous duplicate source literal requires source identity')
        components.sort(key=lambda pair:pair[1]['source_range'][0])
        sid=next(iter(paragraph_ids))
        para=verified_source_paragraph(self.ledger['source_il_ref'],self.context['input_ref'],sid)
        cursor=0;outputs=[];parents=[]
        for gid,c in components:
            lo,hi=c['source_range']
            if para['unicode'][cursor:lo].strip() or lo<cursor: raise ValueError('shared paragraph gap/overlap')
            projection,parent=self.read_group(gid)
            projected=[p for p in projection['projections'] if p['component_id']==c['component_id']]
            if len(projected)!=1: raise ValueError('missing component projection')
            value=projected[0]['target_text']
            for item in c['backend_placeholder_map']:
                if item['in_component']:
                    if item.get('source_role')=='natural_formula':continue
                    marker='[[PTS:'+str(item['scientific_id'])+']]'
                    if value.count(marker)!=1: raise ValueError('scientific object host identity changed')
                    value=value.replace(marker,item['placeholder'])
            identity_objects={o['identity_id']:o for o in self.groups[gid].get('identity_objects',[])}
            for iid in c.get('identity_ids',[]):
                marker='[[PTI:'+iid+']]'
                if value.count(marker)!=1 or iid not in identity_objects:raise ValueError('source identity host changed')
                value=value.replace(marker,identity_objects[iid]['source_unicode'])
            if '[[PTS:' in value or '[[PTI:' in value or '[[PTC:' in value: raise ValueError('unrestored source encoding')
            outputs.append(value);parents.append(parent);cursor=hi
        if para['unicode'][cursor:].strip(): raise ValueError('shared paragraph suffix omitted')
        # 原生解析器可能把两个已分别审定的完整逻辑组并入同一宿主。
        # 组间保留显式换行，复用后端现有换行排版；同组片段仍连续。
        joined=[]
        for index,value in enumerate(outputs):
            if index:
                joined.append('\n' if components[index-1][0]!=components[index][0] else ' ')
            joined.append(value)
        output=''.join(joined)
        required=Counter(re.findall(r'\{v\d+\}',source))
        for _,c in components:
            for item in c['backend_placeholder_map']:
                if item['in_component'] and item.get('source_role')=='natural_formula':required[item['placeholder']]-=1
        required=+required
        if required!=Counter(re.findall(r'\{v\d+\}',output)):
            raise ValueError('original backend scientific placeholders changed')
        return output, {'origin':'derived_whole_group_projection','actual_provider_calls':0,
                        'source_paragraph_sha256':next(iter(paragraph_ids)), 'parent_refs':parents,
                        'source_literal_sha256':digest(source),'effective_output_sha256':digest(output)}
