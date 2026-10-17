"""按独立批准的字符范围核定保留身份和自然语言混排，覆盖和保护门的逐片段处理。

覆盖/保护为整行的现有源决策保持原文；本层只产生经过逐片段核对的处理结果。
实际字形须先由当前PDF测量层提供，不能仅凭模型文本授予可见性。
"""
from collections import Counter
import hashlib,json,re,unicodedata

def digest(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
def compact(value):return re.sub(r'\s+','',unicodedata.normalize('NFKC',value))

def audit_mixed_treatment(elements,units,actual_texts,review,*,source_ref,target_ref,standard_sha256,producer_id,authorized_reviewer_id,source_role_review_ref,reviewer_authorization_ref,calibration=False):
    """完整源/译非空白字符必须恰好归属一次；未知与明确拒绝分别保留。"""
    if len(elements)>30000 or len(units)>10000 or len(review.get('rows',[]))>2000:raise ValueError('mixed_treatment_scope_limit')
    source_by={e['id']:e for e in elements};unit_by={u['id']:u for u in units}
    if len(source_by)!=len(elements) or len(unit_by)!=len(units):raise ValueError('mixed_treatment_duplicate_inputs')
    issues=[];pending=[];accepted=[];measured=[]
    def issue(rule,key=None,**details):issues.append({'rule':rule,**({'id':key}if key is not None else {}),**details})
    def unknown(rule,key=None):pending.append({'rule':rule,**({'id':key}if key is not None else {})})
    for key,expected in [('source',source_ref),('target',target_ref),('standard_sha256',standard_sha256)]:
        if review.get(key)!=expected:issue('mixed_treatment_identity_changed',field=key)
    if review.get('reviewer_id')!=authorized_reviewer_id or not authorized_reviewer_id or authorized_reviewer_id==producer_id or review.get('method')!='source_first':unknown('mixed_treatment_independent_reviewer_required')
    if review.get('calibration_fixture')and not calibration:unknown('mixed_treatment_fixture_cannot_authorize_delivery')
    for key,expected in [('source_role_review_ref',source_role_review_ref),('reviewer_authorization_ref',reviewer_authorization_ref)]:
        if not isinstance(expected,dict)or set(expected)!={'path','sha256'}or review.get(key)!=expected:unknown('mixed_treatment_bound_role_and_authorization_required')
    rows=review.get('rows',[])
    ids=[r.get('source_line_id')for r in rows]
    if len(ids)!=len(set(ids)):issue('mixed_treatment_duplicate_source_ids')
    # 头部身份或独立性不成立时，不生成任何可用于覆盖豁免的accepted_ids。
    if issues or pending:return {'status':'fail'if issues else 'unverified','issues':issues,'pending':pending,'accepted_source_ids':[],'bindings':[],'quality_pass':False}
    for row in rows:
        key=row.get('source_line_id');begin_i=len(issues);begin_p=len(pending)
        element=source_by.get(key);unit=unit_by.get(row.get('unit_id'))
        if not element or not unit:issue('mixed_treatment_unknown_source_or_unit',key);continue
        if element.get('status')!='protected':issue('mixed_treatment_requires_original_protected_role',key)
        refs=[r['id']for f in unit.get('fragments',[])for r in f.get('source_line_refs',[])]
        if key not in refs:issue('mixed_treatment_source_not_bound_to_unit',key)
        source=element['source_text'];target=unit['target_text'];actual=actual_texts.get(unit['id'])
        if row.get('source_text_sha256')!=digest(source)or row.get('target_text_sha256')!=digest(target):issue('mixed_treatment_text_identity_changed',key)
        if actual is None:unknown('mixed_treatment_actual_pdf_text_required',key)
        elif compact(actual)!=compact(target):issue('mixed_treatment_target_not_completely_visible',key)
        decision=row.get('decision')
        if decision=='reject':issue('mixed_treatment_rejected',key)
        elif decision!='accept':unknown('mixed_treatment_decision_unverified',key)
        if not row.get('rationale'):unknown('mixed_treatment_rationale_required',key)
        spans=row.get('spans',[])
        if not spans or len(spans)>200:issue('mixed_treatment_span_scope_required',key);continue
        owned={'source':Counter(),'target':Counter()};span_measurements=[]
        for span in spans:
            text={'source':source,'target':target};pieces={};valid=True
            for side in ['source','target']:
                ranges=span.get(side+'_ranges',[])
                if not ranges or len(ranges)>20:issue('mixed_treatment_ranges_required',key,side=side);valid=False;continue
                pieces[side]=''
                for ran in ranges:
                    if not isinstance(ran,list)or len(ran)!=2 or any(type(v)is not int for v in ran)or not 0<=ran[0]<ran[1]<=len(text[side]):issue('mixed_treatment_range_outside_text',key,side=side);valid=False;continue
                    owned[side].update(i for i in range(*ran)if not text[side][i].isspace())
                    pieces[side]+=text[side][ran[0]:ran[1]]
            if not valid:continue
            action=span.get('action')
            if action=='preserve_identity':
                if span.get('identity_kind')not in {'journal_brand','number','identifier','scientific_expression','source_punctuation','person_name'}:issue('mixed_treatment_identity_kind_required',key)
                if compact(pieces['source'])!=compact(pieces['target']):issue('mixed_treatment_protected_identity_changed',key,source=pieces['source'],target=pieces['target'])
                if span.get('identity_kind')=='person_name':
                    binding=span.get('person_name_source_binding')
                    if not isinstance(binding,dict):
                        unknown('mixed_treatment_person_name_source_binding_required',key)
                    else:
                        author_id=binding.get('source_line_id')
                        author=source_by.get(author_id)if isinstance(author_id,str)else None
                        if (binding.get('source')!=source_ref or binding.get('source_role_review_ref')!=source_role_review_ref):
                            issue('mixed_treatment_person_name_source_or_role_identity_changed',key)
                        if not author or author.get('role')!='author_identity' or author.get('status')!='protected':
                            issue('mixed_treatment_person_name_author_byline_required',key)
                        else:
                            author_text=author['source_text']
                            if binding.get('source_text_sha256')!=digest(author_text):
                                issue('mixed_treatment_person_name_author_text_changed',key)
                            ranges=binding.get('source_ranges');name='';valid_name_ranges=True
                            if not isinstance(ranges,list)or not 1<=len(ranges)<=20:
                                valid_name_ranges=False
                            else:
                                owned_name=Counter()
                                for ran in ranges:
                                    if (not isinstance(ran,list)or len(ran)!=2 or any(type(v)is not int for v in ran)
                                            or not 0<=ran[0]<ran[1]<=len(author_text)):
                                        valid_name_ranges=False;continue
                                    name+=author_text[ran[0]:ran[1]]
                                    owned_name.update(range(*ran))
                                if any(v!=1 for v in owned_name.values()):valid_name_ranges=False
                            if not valid_name_ranges:
                                issue('mixed_treatment_person_name_author_range_invalid',key)
                            elif compact(name)!=compact(pieces['source']):
                                issue('mixed_treatment_person_name_author_identity_mismatch',key)
                            name_review_ref=binding.get('person_name_review_ref')
                            if not isinstance(name_review_ref,dict):
                                unknown('mixed_treatment_person_name_independent_range_review_required',key)
                            else:
                                try:
                                    from qa_source_contract import read_bound_json
                                    name_review=read_bound_json(name_review_ref)
                                    if not isinstance(name_review.get('standard'),dict):
                                        raise ValueError('person_name_review_standard_object_required')
                                    if (name_review.get('source')!=source_ref
                                            or name_review.get('standard',{}).get('sha256')!=standard_sha256
                                            or name_review.get('reviewer_id')!=authorized_reviewer_id
                                            or name_review.get('producer_id')!=producer_id
                                            or name_review.get('reviewer_id')==name_review.get('producer_id')):
                                        issue('mixed_treatment_person_name_range_review_identity_changed',key)
                                    names=name_review.get('independent_source_person_names',[])
                                    if not isinstance(names,list)or len(names)>10000:
                                        raise ValueError('person_name_review_scope_invalid')
                                    approved=[v for v in names if isinstance(v,dict)
                                        and v.get('author_source_line')==author_id
                                        and v.get('author_source_text_sha256')==digest(author_text)
                                        and [v.get('author_name_range')]==ranges
                                        and compact(v.get('name',''))==compact(pieces['source'])
                                        and v.get('independent_source_person_name_decision')=='pass']
                                    if len(approved)!=1:
                                        issue('mixed_treatment_person_name_range_not_independently_approved',key)
                                except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
                                    unknown('mixed_treatment_person_name_range_review_missing_or_changed',key)


            elif action=='translate_language':
                if span.get('decision')=='reject':issue('mixed_treatment_language_span_rejected',key)
                elif span.get('decision')!='accept':unknown('mixed_treatment_language_span_unverified',key)
                contexts=span.get('source_context_ids',[])
                if not span.get('rationale')or not isinstance(contexts,list)or not contexts or any(v not in source_by for v in contexts):unknown('mixed_treatment_language_span_source_evidence_required',key)
                # 必须说明源词为什么可译；不得把丢失数字或英文字形吞入“翻译”桶。
                if not re.search(r'[\u3400-\u9fff]',pieces['target']):issue('mixed_treatment_language_span_not_translated',key)
                source_nums=Counter(re.findall(r'\d+',pieces['source']));target_nums=Counter(re.findall(r'\d+',pieces['target']))
                if source_nums!=target_nums:
                    month={name.casefold():f'{i}月'for i,name in enumerate(['January','February','March','April','May','June','July','August','September','October','November','December'],1)}
                    named=span.get('named_equivalence')
                    valid_named=False
                    if isinstance(named,dict)and named.get('source_value')==pieces['source']and named.get('target_value')==pieces['target']and named.get('source_context_ids')==contexts:
                        if named.get('kind')=='calendar_month':valid_named=compact(pieces['target'])==month.get(compact(pieces['source']).casefold())
                        elif named.get('kind')=='calendar_date':
                            match=re.fullmatch(r'([A-Za-z]+)(\d{4})',compact(pieces['source']))
                            valid_named=bool(match and match[1].casefold()in month and compact(pieces['target'])==match[2]+'年'+month[match[1].casefold()])
                    if not valid_named:issue('mixed_treatment_numeric_identity_in_translation_span_changed',key)
            else:issue('mixed_treatment_unknown_action',key)
            span_measurements.append({'action':action,'source':pieces['source'],'target':pieces['target']})
        for side,text in [('source',source),('target',target)]:
            required={i for i,c in enumerate(text)if not c.isspace()}
            if set(owned[side])!=required:issue('mixed_treatment_character_scope_incomplete',key,side=side,missing=sorted(required-set(owned[side])),extra=sorted(set(owned[side])-required))
            if any(count!=1 for count in owned[side].values()):issue('mixed_treatment_character_bound_more_than_once',key,side=side)
        if not any(s.get('action')=='translate_language'for s in spans):issue('mixed_treatment_natural_language_span_required',key)
        measured.append({'source_line_id':key,'unit_id':unit['id'],'spans':span_measurements,'source_text_sha256':digest(source),'target_text_sha256':digest(target)})
        if len(issues)==begin_i and len(pending)==begin_p:accepted.append(key)
    return {'status':'fail'if issues else 'unverified'if pending else 'pass','issues':issues,'pending':pending,'accepted_source_ids':accepted,'bindings':measured,'quality_pass':False}


def audit_bound_mixed_treatment(elements, units, actual_texts, *, review_ref,
        source_ref, target_ref, standard_ref, producer_id, authorized_reviewer_id,
        source_role_review_ref, reviewer_authorization_ref, inventory_ref):
    """读取具名SHA证据并验证授权及原角色；不接受调用方提供的通过布尔值。"""
    from qa_source_contract import read_bound_json, file_ref, validate_role_review
    def unknown(rule):
        return {'status':'unverified','issues':[],'pending':[{'rule':rule}],
                'accepted_source_ids':[],'bindings':[],'quality_pass':False}
    if review_ref is None:
        return {'status':'not_applicable','issues':[],'pending':[],
                'accepted_source_ids':[],'bindings':[],'quality_pass':False}
    try:
        review=read_bound_json(review_ref)
        authority=read_bound_json(reviewer_authorization_ref)
        if (file_ref(source_ref['path'])!=source_ref or
                file_ref(target_ref['path'])!=target_ref or
                file_ref(standard_ref['path'])!=standard_ref):
            return unknown('mixed_treatment_actual_artifact_or_standard_changed')
        if (authority.get('reviewer_id')!=authorized_reviewer_id or
                authority.get('producer_id')!=producer_id or
                authority.get('source')!=source_ref or
                authority.get('target')!=target_ref or
                authority.get('standard')!=standard_ref or
                authority.get('scope') not in {'complete_document_quality',
                                               'complete_document_quality_repair_rereview'}):
            return unknown('mixed_treatment_reviewer_authority_scope_changed')
        role=validate_role_review(elements,review_ref=source_role_review_ref,
                source_ref=source_ref,inventory_ref=inventory_ref)
        if role['status']!='pass':
            return {'status':role['status'],'issues':role['issues'] if role['status']=='fail' else [],
                    'pending':role['issues'] if role['status']=='unverified' else [],
                    'accepted_source_ids':[],'bindings':[],'quality_pass':False}
        role_review=read_bound_json(source_role_review_ref)
        if (role_review.get('reviewer_id')!=authorized_reviewer_id or
                role_review.get('producer_id')!=producer_id or
                role_review.get('standard_sha256')!=standard_ref['sha256']):
            return unknown('mixed_treatment_role_reviewer_outside_authorized_scope')
        if not isinstance(actual_texts,dict):
            return unknown('mixed_treatment_actual_pdf_text_required')
        return audit_mixed_treatment(elements,units,actual_texts,review,
                source_ref=source_ref,target_ref=target_ref,
                standard_sha256=standard_ref['sha256'],producer_id=producer_id,
                authorized_reviewer_id=authorized_reviewer_id,
                source_role_review_ref=source_role_review_ref,
                reviewer_authorization_ref=reviewer_authorization_ref)
    except (KeyError,ValueError,TypeError,OSError,json.JSONDecodeError):
        return unknown('mixed_treatment_bound_evidence_missing_or_changed')
