"""四态质量汇总与错误样本校准；必要检查缺失不授予通过。"""
from qa_source_contract import file_ref,read_bound_json

STATES={'pass','fail','unverified','not_applicable'}
REQUIRED_GATES={'source_inventory','roles','coverage','paragraphs','captions','spacing','semantics','visual','assets_links'}

def aggregate_quality(requirements, results, *, source_ref, target_ref, expected_pages, declared_pages, standard_sha256):
    required={r['id']:r for r in requirements};actual={r['id']:r for r in results}
    if not required or len(required)!=len(requirements) or len(actual)!=len(results):raise ValueError('quality_requirement_or_result_duplicate')
    issues=[];pending=[]
    if not REQUIRED_GATES.issubset(required):
        pending.append({'rule':'mandatory_quality_contract_checks_missing','missing':sorted(REQUIRED_GATES-set(required))})
    if set(actual)-set(required):issues.append({'rule':'quality_result_outside_requirement_scope'})
    if not expected_pages or set(expected_pages)!=set(declared_pages) or len(set(declared_pages))!=len(declared_pages):
        issues.append({'rule':'partial_scope_cannot_grant_full_document_quality'})
    for identity in (source_ref,target_ref):
        try:
            if file_ref(identity['path'])!=identity:issues.append({'rule':'quality_artifact_identity_changed'})
        except (OSError,KeyError,TypeError):pending.append({'rule':'quality_artifact_identity_unverified'})
    for key,requirement in required.items():
        row=actual.get(key)
        if not row:pending.append({'id':key,'rule':'required_check_not_executed'});continue
        state=row.get('status')
        if state not in STATES:pending.append({'id':key,'rule':'quality_state_unknown'});continue
        if row.get('source')!=source_ref or row.get('target')!=target_ref or row.get('standard_sha256')!=standard_sha256:
            pending.append({'id':key,'rule':'quality_check_identity_or_standard_mismatch'});continue
        if state=='not_applicable':
            if not requirement.get('allow_not_applicable') or not row.get('reason') or not row.get('evidence'):
                pending.append({'id':key,'rule':'quality_not_applicable_unproven'})
        elif state=='fail':issues.append({'id':key,'rule':'required_quality_check_failed'})
        elif state=='unverified':pending.append({'id':key,'rule':'required_quality_check_unverified'})
        if state in {'pass','not_applicable'}:
            refs=row.get('evidence',[])
            if not refs:pending.append({'id':key,'rule':'quality_evidence_missing'})
            for ref in refs:
                try:
                    proof=read_bound_json(ref)
                    if proof.get('source')!=source_ref or proof.get('target')!=target_ref or proof.get('standard_sha256')!=standard_sha256 or proof.get('check_id')!=key or proof.get('status')!=state:
                        pending.append({'id':key,'rule':'quality_evidence_claim_mismatch'})
                    if sorted(proof.get('scope_pages',[]))!=sorted(set(expected_pages)):
                        pending.append({'id':key,'rule':'quality_evidence_scope_incomplete'})
                    items=proof.get('checked_items',[])
                    required_items=requirement.get('expected_items',[])
                    if not required_items or len(set(items))!=len(items) or set(items)!=set(required_items) or proof.get('issues') or proof.get('pending'):
                        pending.append({'id':key,'rule':'quality_evidence_items_incomplete_or_unresolved'})
                except (OSError,KeyError,TypeError,ValueError):pending.append({'id':key,'rule':'quality_evidence_unverified'})
    passed=not issues and not pending
    return {'schema_version':1,'status':'fail' if issues else 'unverified' if pending else 'pass',
            'quality_pass':passed,'issues':issues,'pending':pending,'source':source_ref,'target':target_ref,
            'expected_pages':sorted(set(expected_pages)),'declared_pages':sorted(set(declared_pages)),
            'standard_sha256':standard_sha256,'required_checks':len(required),'results':results,
            'strict_delivery':False,'human_acceptance':False,'promotion_performed':False}

def calibration_metrics(cases):
    if not cases or len({c['id'] for c in cases})!=len(cases):raise ValueError('calibration_case_scope')
    rows={};failures=[]
    for case in cases:
        if case['expected'] not in {'reject','accept','unverified'} or case['actual'] not in STATES:raise ValueError('calibration_case_state')
        key=case['severity'];row=rows.setdefault(key,{'negative_cases':0,'legitimate_cases':0,'unknown_cases':0,'false_negative':0,'false_positive':0,'unknown_misreported_pass':0})
        if case['expected']=='reject':
            row['negative_cases']+=1
            # 缺证据导致unverified并不等于定位了注入的实际错误。
            detected=case['actual']=='fail' and case.get('expected_rule') in case.get('actual_rules',[])
            row['false_negative']+=not detected
            if not detected:failures.append(case['id'])
        elif case['expected']=='accept':
            row['legitimate_cases']+=1;row['false_positive']+=case['actual']!='pass'
            if case['actual']!='pass':failures.append(case['id'])
        else:
            row['unknown_cases']+=1;row['unknown_misreported_pass']+=case['actual']=='pass'
            if case['actual']=='pass':failures.append(case['id'])
    for row in rows.values():
        row['false_negative_rate']=row['false_negative']/row['negative_cases'] if row['negative_cases'] else None
        row['false_positive_rate']=row['false_positive']/row['legitimate_cases'] if row['legitimate_cases'] else None
    return {'cases':len(cases),'by_severity':rows,'failed_case_ids':failures,'calibration_pass':not failures,
            'quality_pass':False,'scope':'仅冻结样本集，不授予通用PDF准确率或交付接受'}
