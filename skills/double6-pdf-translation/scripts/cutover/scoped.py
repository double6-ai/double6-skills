"""对具名产物范围核对SHA及验收证据，避免把局部接受扩展为整案通过。"""
from __future__ import annotations
import hashlib
from pathlib import Path

REQUIRED_STAGES = {'targeted_verification', 'full_page_sweep', 'targeted_region_audit',
                   'independent_visual_spot_check', 'semantic_review'}

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024**2), b''): h.update(chunk)
    return h.hexdigest()

def check_scoped_preflight(packet, acceptance):
    """只检查冻结身份及证据合同；检查内容由实际审计报告提供。"""
    blockers=[]
    artifacts=packet.get('artifacts', [])
    ids={a['id'] for a in artifacts}
    if not ids or len(ids)!=len(artifacts): blockers.append('empty_or_duplicate_scope')
    def check_ref(ref):
        path=Path(ref.get('path', ''))
        if not path.is_file() or sha(path)!=ref.get('sha256'):
            blockers.append('evidence_identity_changed:'+str(path))
    for item in artifacts: check_ref(item)
    if acceptance.get('status')!='accepted' or not acceptance.get('direct_user_authorization'):
        blockers.append('human_acceptance_missing')
    accepted={a['id']:a for a in acceptance.get('artifacts', [])}
    if set(accepted)!=ids: blockers.append('acceptance_scope_mismatch')
    for item in artifacts:
        if accepted.get(item['id'], {}).get('sha256')!=item['sha256']:
            blockers.append('accepted_artifact_identity_mismatch:'+item['id'])
    stages={s['stage']:s for s in packet.get('stages', [])}
    if REQUIRED_STAGES-set(stages): blockers.append('required_evidence_missing')
    for name in REQUIRED_STAGES & set(stages):
        stage=stages[name]
        if stage.get('status')!='verified' or stage.get('unresolved_findings')!=0:
            blockers.append('evidence_not_resolved:'+name)
        if set(stage.get('artifact_ids', []))!=ids:
            blockers.append('evidence_scope_mismatch:'+name)
        if not stage.get('reports'): blockers.append('evidence_report_missing:'+name)
        for report in stage.get('reports', []): check_ref(report)
    return {'status':'ready_for_cutover_apply' if not blockers else 'blocked',
            'blockers':blockers, 'artifact_ids':sorted(ids),
            'acceptance_scope':'仅所列最终产物SHA；不继承到其它页、旧包或Skill发布'}
