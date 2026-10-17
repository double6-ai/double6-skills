"""源文独立清单与逐项角色复核。只校验证据合同，不替代可见性或语义审校。"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path
import unicodedata
import fitz

CONTEXTS = {'identifier': {'identifier'}, 'scientific_identity': {'scientific_notation'},
            'page_number': {'pagination'}, 'journal_brand': {'publication_brand'},
            'author_identity': {'author_byline'}, 'bibliographic_record': {'reference_list'},
            'layout_whitespace': {'source_blank_band'}}

def text_digest(text):
    return hashlib.sha256(unicodedata.normalize('NFKC', text).encode()).hexdigest()

def file_ref(path):
    path = Path(path).resolve()
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path), 'sha256': digest}

def read_bound_json(ref, *, max_bytes=32*1024**2):
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
        raise ValueError('evidence_reference_required')
    path = Path(ref['path'])
    if path.stat().st_size > max_bytes or file_ref(path) != ref:
        raise ValueError('evidence_identity_changed')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('evidence_object_required')
    return value

def independent_source_inventory(source, *, pages=None, maximum_pages=5, maximum_characters=150000):
    """直接读取源页；不接受生产unit/角色区域作为枚举输入。一次最多5页。"""
    if not 1 <= maximum_pages <= 5 or not 1 <= maximum_characters <= 500000:
        raise ValueError('source_inventory_limits')
    source = Path(source); identity = file_ref(source)
    elements=[]; assets=[]; page_rows=[]; count=0
    with fitz.open(source) as doc:
        requested=list(range(1,len(doc)+1)) if pages is None else list(pages)
        if not requested or len(requested)>maximum_pages or len(set(requested))!=len(requested):
            raise ValueError('source_inventory_page_bounds')
        if requested!=sorted(requested) or any(type(p) is not int or not 1<=p<=len(doc) for p in requested):
            raise ValueError('source_inventory_page_order')
        for page_number in requested:
            page=doc[page_number-1]
            # 与原生dict使用同一提取flags；RAWDICT默认CID flags会改变部分源块分组。
            rows=page.get_text('rawdict',flags=fitz.TEXTFLAGS_DICT)['blocks']
            visible_origins=set()
            for span in page.get_texttrace():
                if span['type']==3 or span.get('opacity',1)<=0:
                    continue
                visible_origins.update((round(c[2][0],2),round(c[2][1],2)) for c in span['chars'])
            start=len(elements)
            for block_index,block in enumerate(rows):
                if block['type']!=0: continue
                for line_index,line in enumerate(block['lines']):
                    chars=[c for s in line['spans'] for c in s['chars']]
                    if not ''.join(c['c'] for c in chars).strip():
                        assets.append({'id':f'p{page_number}-b{block_index}-l{line_index}',
                            'page':page_number,'bbox':list(line['bbox']),'kind':'blank_text_record',
                            'source_text':'','blank_band_review':'unverified'})
                        continue
                    # ligature可在rawdict展开为多个Unicode，不能按单字符码点删除其中一半。
                    # 只排除整行无绘制记录的文字；混合隐藏/裁剪内容继续保留可见性待审。
                    if not any((round(c['origin'][0],2),round(c['origin'][1],2)) in visible_origins for c in chars):continue
                    text=''.join(c['c'] for c in chars).strip()
                    if not text.strip():continue
                    count+=len(chars)
                    if count>maximum_characters:raise ValueError('source_inventory_character_limit')
                    elements.append({'id':f'p{page_number}-b{block_index}-l{line_index}',
                        'page':page_number,'source_block':block_index,'source_line':line_index,
                        'source_text':text,'source_text_sha256':text_digest(text),'bbox':list(line['bbox']),
                        'direction':list(line['dir']),'role':'unknown','status':'unverified'})
            image_boxes=[list(v['bbox']) for v in page.get_image_info()]
            assets.extend({'id':f'p{page_number}-image-{i}','page':page_number,'bbox':b,
                           'kind':'image','ocr_or_image_text_review':'unverified'} for i,b in enumerate(image_boxes))
            page_rows.append({'page':page_number,'rect':list(page.rect),'native_lines':len(elements)-start,
                              'ocr_or_blank_review_required':len(elements)==start,
                              'visibility_status':'unverified','blank_band_review':'unverified'})
        total=len(doc)
    if file_ref(source)!=identity:raise ValueError('source_changed_during_inventory')
    return {'schema_version':1,'source':identity,'pages':page_rows,'elements':elements,'assets':assets,
            'document_page_count':total,'enumeration_dependencies':['source_pdf'],
            'native_text_enumeration_complete':True,'visibility_proven':False,
            'translation_coverage_complete':False,'quality_pass':False}

def validate_role_review(elements, *, review_ref, source_ref, inventory_ref):
    """复核全部源元素；源清单、复核文件和实际输入逐项一致才闭合。"""
    issues=[]
    def issue(rule, key=None):issues.append({'rule':rule,**({'id':key} if key else {})})
    try:
        inventory=read_bound_json(inventory_ref); review=read_bound_json(review_ref)
        if file_ref(source_ref['path'])!=source_ref:raise ValueError('source_identity_changed')
    except (ValueError,OSError,KeyError,TypeError,json.JSONDecodeError):
        return {'status':'unverified','issues':[{'rule':'independent_role_evidence_missing_or_changed'}],
                'independent_role_review_verified':False,'quality_pass':False}
    if inventory.get('source')!=source_ref or review.get('source')!=source_ref or review.get('inventory')!=inventory_ref:
        issue('role_review_source_or_inventory_identity')
    if inventory.get('enumeration_dependencies')!=['source_pdf']:
        issue('source_inventory_depends_on_production_plan')
    if not review.get('reviewer_id') or not review.get('producer_id') or review['reviewer_id']==review['producer_id'] or review.get('method')!='source_first':
        issue('independent_source_role_reviewer_required')
    original=inventory.get('elements',[]); decisions=review.get('decisions',[])
    originals={e['id']:e for e in original}; by_id={d['id']:d for d in decisions}
    input_ids=[e['id'] for e in elements]
    if len(originals)!=len(original) or len(by_id)!=len(decisions) or len(input_ids)!=len(set(input_ids)):
        issue('source_or_role_review_duplicate')
    if set(originals)!=set(by_id) or set(originals)!=set(input_ids):
        issue('independent_inventory_role_scope_mismatch')
    for element in elements:
        key=element['id']; original=originals.get(key); decision=by_id.get(key)
        if not original or not decision:continue
        if element.get('page')!=original['page'] or text_digest(element.get('source_text',''))!=original['source_text_sha256']:
            issue('production_source_element_changed',key)
        if decision.get('page')!=original['page'] or decision.get('source_text_sha256')!=original['source_text_sha256']:
            issue('role_review_element_identity',key)
        bbox=decision.get('bbox',[])
        if len(bbox)!=4 or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in bbox) or any(abs(a-b)>.02 for a,b in zip(bbox,original['bbox'])):
            issue('role_review_source_geometry',key)
        if decision.get('decision')!='accepted' or not decision.get('reason'):
            issue('source_role_unverified',key)
        if decision.get('role')!=element.get('role') or decision.get('status')!=element.get('status'):
            issue('production_role_disagrees_with_source_review',key)
        if element.get('status')=='protected' and decision.get('context_kind') not in CONTEXTS.get(element.get('role'),set()):
            issue('protected_role_source_context_missing',key)
    return {'status':'fail' if issues else 'pass','issues':issues,
            'independent_role_review_verified':not issues,'review':review_ref,'source':source_ref,
            'inventory':inventory_ref,'reviewed_elements':len(decisions),'quality_pass':False}
