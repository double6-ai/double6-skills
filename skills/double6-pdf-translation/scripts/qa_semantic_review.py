"""完整段落语义复核合同；模型线索和具名裁决同时保留。"""
from qa_source_contract import read_bound_json,text_digest
from semantic_invariants import invariant_findings

ASPECTS={'completeness','conditions','negation','comparisons','entities','numbers','units','references'}

def validate_semantic_review(units, *, review_ref, source_ref, target_ref, standard_sha256, producer_id):
    issues=[];pending=[]
    try:review=read_bound_json(review_ref)
    except (ValueError,OSError,KeyError,TypeError):
        return {'status':'unverified','pending':[{'rule':'semantic_review_evidence_missing_or_changed'}],'issues':[],'quality_pass':False}
    if review.get('source')!=source_ref or review.get('target')!=target_ref or review.get('standard_sha256')!=standard_sha256:
        pending.append({'rule':'semantic_review_identity_or_standard_changed'})
    if not review.get('reviewer_id') or review['reviewer_id']==producer_id:
        pending.append({'rule':'independent_semantic_reviewer_required'})
    decisions=review.get('decisions',[]);by_id={d['id']:d for d in decisions}
    if len(by_id)!=len(decisions) or len({u['id'] for u in units})!=len(units) or set(by_id)!={u['id'] for u in units}:
        pending.append({'rule':'semantic_complete_unit_scope_mismatch'})
    hints=[]
    for unit in units:
        decision=by_id.get(unit['id'])
        if not decision:continue
        if decision.get('source_text_sha256')!=text_digest(unit['source_text']) or decision.get('target_text_sha256')!=text_digest(unit['target_text']) or decision.get('complete_source_context')!=unit['source_line_ids']:
            pending.append({'id':unit['id'],'rule':'semantic_full_paragraph_identity_or_context_changed'});continue
        aspects=decision.get('aspects',{})
        if set(aspects)!=ASPECTS or any(not isinstance(v,dict) or v.get('status') not in {'accepted','not_applicable'} or not v.get('rationale') for v in aspects.values()):
            pending.append({'id':unit['id'],'rule':'semantic_aspects_unresolved'})
        if decision.get('decision')=='rejected':issues.append({'id':unit['id'],'rule':'semantic_review_rejected_translation'})
        elif decision.get('decision')!='accepted':pending.append({'id':unit['id'],'rule':'semantic_decision_unverified'})
        if max(len(unit['source_text']),len(unit['target_text']))>4000:
            pending.append({'id':unit['id'],'rule':'semantic_aligned_chunks_required_over_text_limit'});continue
        findings=invariant_findings(unit['source_text'],unit['target_text'])
        hints.extend({'id':unit['id'],**f} for f in findings)
        resolutions=decision.get('hint_resolutions',{})
        for finding in findings:
            resolution=resolutions.get(finding['rule'])
            if not resolution or resolution.get('decision')!='source_verified_equivalence' or not resolution.get('source_evidence') or not resolution.get('target_evidence'):
                pending.append({'id':unit['id'],'rule':'semantic_invariant_hint_unresolved','hint_rule':finding['rule']})
    return {'status':'fail' if issues else 'unverified' if pending else 'pass','issues':issues,'pending':pending,
            'hints':hints,'reviewed_units':len(decisions),'quality_pass':False}
