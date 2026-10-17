# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：修订namespace保留原账本摘要，复用流式防篡改校验；详见MODIFICATIONS.md。
"""具名完整组编辑修订：核历史真实调用，生成零模型派生投影 namespace。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from threading import RLock

from pdf_source_cache import (SourceCache, GroupProjectionCache, GROUP_PROTOCOL,
    REVISION_PROTOCOL, REVISION_CONTRACT, bound_json, digest, file_ref, write_new)

CONTRACT_PROTOCOL = 'pdf_whole_group_editorial_revision_v1'
CONTRACT_FIELDS = {'protocol', 'baseline_context_ref', 'baseline_freeze_ref',
    'baseline_source_snapshot_ref', 'baseline_actual_call_ledger_ref',
    'baseline_parent_manifest_ref', 'baseline_native_pdf_ref',
    'baseline_group_inputs_ref', 'current_group_inputs_ref',
    'current_source_ledger_ref', 'current_source_review_ref',
    'renderer_freeze_ref', 'policy_ref', 'approval_ref', 'revisions'}
REVISION_FIELDS = {'group_id', 'source_ref', 'target_ref', 'proposal_ref',
                   'review_ref', 'review_selector'}
_VERIFIED_CONTRACTS = {}
_VERIFY_LOCK = RLock()


def checked_ref(ref):
    from independent_latex import reject_symlink_ancestors
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        raise ValueError('exact immutable reference required')
    reject_symlink_ancestors(ref['path'])
    if file_ref(ref['path']) != ref:
        raise ValueError('revision reference changed')
    return ref


def load(ref):
    return bound_json(checked_ref(ref))


def all_refs(value):
    if isinstance(value, dict):
        if set(value) == {'path', 'sha256'}:
            yield value
        else:
            for child in value.values():
                yield from all_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_refs(child)


def source_semantics(value):
    """唯一可变字段是具名 implementation_refs 的 SHA 和外层 ledger digest。"""
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key == 'source_ledger_sha256':
                continue
            if key == 'implementation_refs':
                if not isinstance(child, list) or len({r['path'] for r in child}) != len(child):
                    raise ValueError('duplicate source implementation refs')
                result[key] = [{'path': r['path']} for r in child]
            else:
                result[key] = source_semantics(child)
        return result
    if isinstance(value, list):
        return [source_semantics(child) for child in value]
    return value


def source_equivalence(old, current, old_inputs_ref, current_inputs_ref):
    from pdf_source_groups import digest as ledger_digest, build_group_input
    for ledger in (old, current):
        if ledger.get('source_ledger_sha256') != ledger_digest(
                {k: v for k, v in ledger.items() if k != 'source_ledger_sha256'}):
            raise ValueError('source ledger digest changed')
    checked_ref(old_inputs_ref); checked_ref(current_inputs_ref)
    if (Path(old_inputs_ref['path']).read_bytes() != Path(current_inputs_ref['path']).read_bytes()
            or source_semantics(old) != source_semantics(current)):
        raise ValueError('historical/current complete source or scientific identity changed')
    for before, after in zip(old['groups'], current['groups']):
        if build_group_input(before) != build_group_input(after):
            raise ValueError('complete native source/control packet changed')
    return {'status': 'pass_exact_complete_source_equivalence',
        'original_group_inputs_ref': old_inputs_ref, 'current_group_inputs_ref': current_inputs_ref,
        'groups': [{'group_id': g['group_id'], 'source_group_sha256': digest(json.dumps(
            source_semantics(g), sort_keys=True, ensure_ascii=False))} for g in current['groups']],
        'permitted_difference': 'named implementation SHA and ledger digest only',
        'actual_provider_calls': 0, 'semantic_accepted': False, 'human_accepted': False}


def verify_snapshot(snapshot, context, freeze):
    files = snapshot.get('files')
    if snapshot.get('before_execution_copy') is not True or not isinstance(files, list):
        raise ValueError('original direct before-execution source snapshot required')
    declared = context['implementation_refs']
    if declared != freeze['implementation_refs']:
        raise ValueError('historical freeze/context implementation identity differs')
    refs = [{'path': r['path'], 'sha256': r['sha256']} for r in files]
    if (len({r['path'] for r in refs}) != len(refs)
            or sorted(refs, key=lambda r: r['path']) != sorted(declared, key=lambda r: r['path'])):
        raise ValueError('historical snapshot source membership differs')
    for row in files:
        checked_ref({'path': row['snapshot_path'], 'sha256': row['sha256']})


class HistoricalNativeInputs(GroupProjectionCache):
    """显式历史输入读取；源码核对旧 direct snapshot，当前 parser 核等价源。"""
    def group_request(self, group_id):
        from pdf_source_groups import build_group_input
        packet = build_group_input(self.groups[group_id])
        return self.request(packet['source_literal'], packet['system_control'])


def historical_inputs(contract, current_ledger):
    context = load(contract['baseline_context_ref'])
    freeze = load(contract['baseline_freeze_ref'])
    snapshot = load(contract['baseline_source_snapshot_ref'])
    if context.get('protocol') != GROUP_PROTOCOL or context.get('freeze_ref') != contract['baseline_freeze_ref']:
        raise ValueError('original native group context/freeze differs')
    verify_snapshot(snapshot, context, freeze)
    snapshot_by_path = {row['path']: row['sha256'] for row in snapshot['files']}
    for name in ('input_ref', 'scope_ref', 'model_fingerprint_ref', 'policy_ref',
                 'source_ledger_ref', 'source_review_ref'):
        checked_ref(context[name])
    from lmstudio_native import PARAMETERS, TRANSPORT, CONTRACT_ID
    fp = load(context['model_fingerprint_ref'])
    if (context['parameters'] != PARAMETERS or context['transport_contract'] != TRANSPORT
        or context['transport'] != CONTRACT_ID or fp['generation_parameters'] != PARAMETERS
        or fp['transport_contract'] != TRANSPORT or fp['model_id'] != context['model']
        or fp['endpoint'] != context['endpoint']):
        raise ValueError('historical native service/transport identity differs')
    old = load(context['source_ledger_ref'])
    for ref in old['implementation_refs']:
        if snapshot_by_path.get(ref['path']) != ref['sha256']:
            raise ValueError('historical source compiler not in original snapshot')
    equivalence = source_equivalence(old, current_ledger, contract['baseline_group_inputs_ref'],
                                     contract['current_group_inputs_ref'])
    from independent_latex import reject_symlink_ancestors
    historical = HistoricalNativeInputs.__new__(HistoricalNativeInputs)
    historical.context_ref = contract['baseline_context_ref']; historical.context = context
    historical.identity = digest(json.dumps(context, sort_keys=True, separators=(',', ':')))
    historical.directory = reject_symlink_ancestors(context['cache_directory']).resolve()
    historical.ledger = current_ledger
    historical.groups = {g['group_id']: g for g in current_ledger['groups']}
    historical.mode = 'read'
    final_ref = checked_ref(contract['baseline_parent_manifest_ref'])
    if Path(final_ref['path']).read_bytes() != (historical.directory/'GROUP_PARENT_MANIFEST.jsonl').read_bytes():
        raise ValueError('historical final manifest changed')
    ledger = load(contract['baseline_actual_call_ledger_ref'])
    if ledger['context_ref'] != historical.context_ref or ledger['final_manifest_snapshot_ref'] != final_ref:
        raise ValueError('actual call ledger/context/final manifest differs')
    rows = ledger['groups']
    if len(rows) != len(historical.groups) or {r['group_id'] for r in rows} != set(historical.groups):
        raise ValueError('historical call ledger complete group membership differs')
    total = 0
    for row in rows:
        projection, parent = historical.read_group(row['group_id'])
        if (row['entry_ref'] != parent['entry_ref'] or row['raw_ref'] != parent['transport_raw_ref']
            or row['origin'] != parent['origin'] or type(row['actual_provider_calls']) is not int
            or row['actual_provider_calls'] != parent['retained_provider_calls']):
            raise ValueError('actual historical entry/RAW/origin ledger differs')
        if row['raw_ref']:
            raw = load(row['raw_ref'])
            if row['usage'] != raw['response']['stats'] or row['model_instance_id'] != raw['response']['model_instance_id']:
                raise ValueError('historical actual usage/instance ledger differs')
        total += row['actual_provider_calls']
    if total != ledger['actual_provider_calls'] or ledger['starts'] != total or ledger['successes'] != total:
        raise ValueError('historical actual call counts differ')
    checked_ref(contract['baseline_native_pdf_ref'])
    return historical, equivalence


def revision_projection(item, group, historical, contract):
    if set(item) != REVISION_FIELDS or item['review_selector'] != group['group_id'] or item['group_id'] != group['group_id']:
        raise ValueError('exact complete group revision selector required')
    proposal = load(item['proposal_ref']); review = load(item['review_ref'])
    if (review.get('status') != 'pass_full_source_bound_proposed_text_semantics_actual_pdf_pending'
        or review.get('producer_editorial_application_authorized') is not True
        or not review.get('reviewer_id') or review['reviewer_id'] == proposal.get('author_id')
        or review.get('author_id') != proposal.get('author_id') or review.get('plan_ref') != item['proposal_ref']):
        raise ValueError('independent complete source-bound semantic text review required')
    units = proposal.get('units', [proposal])
    selected = [u for u in units if u.get('group_id') == group['group_id']]
    if len(selected) != 1 or selected[0].get('source_ref') != item['source_ref'] or selected[0].get('target_ref') != item['target_ref']:
        raise ValueError('proposal source/target/group identity differs')
    unit = selected[0]
    verified = list(all_refs(review))
    if any(ref not in verified for ref in (item['source_ref'], item['target_ref'])):
        raise ValueError('review did not bind complete source and target')
    for ref in verified:
        checked_ref(ref)
    source = load(item['source_ref']); target = load(item['target_ref'])
    if (source.get('group_id') != group['group_id'] or target.get('group_id') != group['group_id']
        or source.get('complete_source_english') != group['source_full_semantic_text']
        or source.get('source_sha256') != digest(group['source_full_semantic_text'])
        or source.get('source_pdf_ref') != historical.context['input_ref']
        or target.get('actual_native_response') is not False):
        raise ValueError('complete source/editorial origin changed')
    initial, parent = historical.read_group(group['group_id'])
    if (unit.get('native_raw_ref', unit.get('failed_native_raw_ref')) != parent['transport_raw_ref']
        or unit.get('native_entry_ref', unit.get('failed_native_entry_ref')) != parent['entry_ref']):
        raise ValueError('revision original actual group RAW/entry differs')
    value = target.get('target_masked_text')
    if not isinstance(value, str) or target.get('target_masked_sha256') != digest(value):
        raise ValueError('editorial full target digest changed')
    from pdf_source_groups import validate_group_response
    result = validate_group_response(group, value)
    before = {p['component_id']: p['target_text'] for p in initial['projections']}
    for component, after in zip(group['components'], result['projections']):
        if (component['immutable'] or component['kind'] != 'source_fragment') and after['target_text'] != before[component['component_id']]:
            raise ValueError('editorial changed fixed display/immutable native component')
    return result


def _verify_contract(contract_ref):
    contract = load(contract_ref)
    if set(contract) != CONTRACT_FIELDS or contract['protocol'] != CONTRACT_PROTOCOL or not isinstance(contract['revisions'], list):
        raise ValueError('exact whole-group editorial contract required')
    for key in CONTRACT_FIELDS - {'protocol', 'revisions'}:
        checked_ref(contract[key])
    approval = load(contract['approval_ref'])
    if (approval.get('policy_ref') != contract['policy_ref']
        or approval.get('status') != 'approved_frozen_minimal_protocol_before_implementation'
        or approval.get('new_provider_calls_authorized') != 0):
        raise ValueError('frozen editorial/immutable policy approval required')
    policy = load(contract['policy_ref'])
    baseline_fields = {'context_ref': 'baseline_context_ref', 'freeze_ref': 'baseline_freeze_ref',
        'source_snapshot_ref': 'baseline_source_snapshot_ref', 'actual_call_ledger_ref': 'baseline_actual_call_ledger_ref',
        'final_parent_manifest_ref': 'baseline_parent_manifest_ref', 'diagnostic_pdf_ref': 'baseline_native_pdf_ref'}
    declared_baseline = policy.get('baseline')
    if not isinstance(declared_baseline, dict) or any(declared_baseline.get(name) != contract[field] for name, field in baseline_fields.items()):
        raise ValueError('historical baseline differs from frozen approved policy')
    if declared_baseline.get('original_workflow_failure_ref'):
        checked_ref(declared_baseline['original_workflow_failure_ref'])
    ids = [r.get('group_id') for r in contract['revisions']]
    if len(set(ids)) != len(ids) or sorted(ids) != sorted(approval['authorized_editorial_groups']):
        raise ValueError('approved complete revision groups missing/unknown/duplicate')
    if any(r.get('review_ref') not in approval['complete_group_text_review_refs'] for r in contract['revisions']):
        raise ValueError('revision text review outside policy approval')
    ledger = load(contract['current_source_ledger_ref'])
    review_host = GroupProjectionCache.__new__(GroupProjectionCache)
    review_host.context = {'source_review_ref': contract['current_source_review_ref'],
        'source_ledger_ref': contract['current_source_ledger_ref'], 'input_ref': ledger['input_ref']}
    review_host.verify_group_review()
    current_freeze = load(contract['renderer_freeze_ref'])
    for ref in current_freeze['implementation_refs']:
        checked_ref(ref)
    import pdf_source_cache
    import pdf_source_groups
    import lmstudio_native
    required={str(Path(module.__file__).resolve()) for module in
              (pdf_source_cache,pdf_source_groups,lmstudio_native)} | {str(Path(__file__).resolve())}
    if not required.issubset({ref['path'] for ref in current_freeze['implementation_refs']}):
        raise ValueError('current revision runtime source closure incomplete')
    if current_freeze.get('source_cache_contract') != REVISION_CONTRACT or current_freeze.get('input') != ledger['input_ref']:
        raise ValueError('current renderer freeze source/revision protocol differs')
    for ref in ledger['implementation_refs']:
        checked_ref(ref)
    historical, equivalence = historical_inputs(contract, ledger)
    if len({g['group_id'] for g in ledger['groups']}) != len(ledger['groups']):
        raise ValueError('duplicate current complete source group')
    projections = {}
    revisions = {r['group_id']: r for r in contract['revisions']}
    for group in ledger['groups']:
        gid = group['group_id']
        if gid in revisions:
            projections[gid] = revision_projection(revisions[gid], group, historical, contract)
        else:
            projections[gid] = historical.read_group(gid)[0]
    return contract, ledger, historical, equivalence, projections


def verify_contract(contract_ref):
    """复用解析结果前重哈每个不可变输入；不以mtime或累计命中代身份门。

    同一backend会逐段重建cache对象。完整组parser昂贵，重复解析与模型
    响应没有新增关系；原bytes、current源码及全部review/raw/snapshot仍逐次核。
    """
    checked_ref(contract_ref)
    key = (contract_ref['path'], contract_ref['sha256'])
    with _VERIFY_LOCK:
        if key in _VERIFIED_CONTRACTS:
            dependencies, result = _VERIFIED_CONTRACTS[key]
            for ref in dependencies:
                checked_ref(ref)
            return result
        result = _verify_contract(contract_ref)
        contract, ledger, historical, _, _ = result
        refs = [contract_ref, *all_refs(contract), *all_refs(load(contract['policy_ref']).get('baseline',{})), *all_refs(ledger),
            *all_refs(load(contract['renderer_freeze_ref'])),
            *all_refs(load(contract['current_source_review_ref'])),
            *all_refs(load(contract['baseline_actual_call_ledger_ref']))]
        snapshot = load(contract['baseline_source_snapshot_ref'])
        refs.extend({'path': row['snapshot_path'], 'sha256': row['sha256']} for row in snapshot['files'])
        refs.extend(historical.context[name] for name in ('input_ref', 'scope_ref',
            'model_fingerprint_ref', 'policy_ref', 'source_ledger_ref', 'source_review_ref'))
        for item in contract['revisions']:
            refs.extend(all_refs(load(item['review_ref'])))
            refs.extend(all_refs(load(item['proposal_ref'])))
        # Original source implementation paths were checked against their old
        # direct snapshot, never against current paths. Current ledger/freeze
        # implementation refs above independently check today's renderer.
        unique = {}
        for ref in refs:
            checked_ref(ref)
            if ref['path'] in unique and unique[ref['path']] != ref:
                raise ValueError('ambiguous immutable dependency identity')
            unique[ref['path']] = ref
        _VERIFIED_CONTRACTS[key] = (list(unique.values()), result)
        return result


class ReviewedGroupProjectionCache(GroupProjectionCache):
    protocol = REVISION_PROTOCOL
    extra_context_fields = {'source_ledger_ref', 'source_review_ref', 'revision_contract_ref', 'source_equivalence_ref'}
    optional_context_fields = {'source_style_contract_ref'}

    def __init__(self, context_ref, mode):
        if mode != 'read':
            raise ValueError('reviewed projection namespace forbids provider warming/collection')
        SourceCache.__init__(self, context_ref, mode)
        declared=load(self.context['freeze_ref']).get('source_style_contract_ref')
        if self.context.get('source_style_contract_ref')!=declared:
            raise ValueError('renderer source-style contract is not frozen')
        if declared is not None:checked_ref(declared)
        self.contract, self.ledger, self.historical, equality, self.effective = verify_contract(self.context['revision_contract_ref'])
        self._original_ledger_digest = self.ledger['source_ledger_sha256']
        if (self.context['freeze_ref'] != self.contract['renderer_freeze_ref']
            or self.context['source_ledger_ref'] != self.contract['current_source_ledger_ref']
            or self.context['source_review_ref'] != self.contract['current_source_review_ref']
            or self.context['editorial_revisions']
            or load(self.context['source_equivalence_ref']) != equality):
            raise ValueError('current derived context/source equivalence differs')
        self.verify_group_review()
        self.groups = {g['group_id']: g for g in self.ledger['groups']}

    def expected_entry(self, gid):
        _, parent = self.historical.read_group(gid)
        revised = [r for r in self.contract['revisions'] if r['group_id'] == gid]
        origin = ('reviewed_full_group_editorial_projection' if revised else
            'retained_protected_source_identity' if parent['retained_provider_calls'] == 0 else 'retained_historical_native_projection')
        return {'protocol': REVISION_PROTOCOL, 'group_id': gid, 'current_context_ref': self.context_ref,
            'baseline_context_ref': self.historical.context_ref, 'baseline_parent_entry_ref': parent['entry_ref'],
            'baseline_raw_ref': parent['transport_raw_ref'], 'source_equivalence_ref': self.context['source_equivalence_ref'],
            'source_group_sha256': digest(json.dumps(source_semantics(self.groups[gid]), sort_keys=True, ensure_ascii=False)),
            'effective_projection': self.effective[gid], 'effective_origin': origin,
            'reviewed_revision_refs': revised, 'original_retained_provider_calls': parent['retained_provider_calls'],
            'new_provider_calls': 0, 'actual_pdf_verified': False, 'human_accepted': False}

    def read_group(self, gid):
        if gid not in self.groups:
            raise ValueError('unknown derived whole source group')
        entry = self._entry(gid)
        row = load(file_ref(entry))
        manifest = self.directory/'GROUP_DERIVED_MANIFEST.jsonl'
        matches = [json.loads(line) for line in manifest.read_text().splitlines() if json.loads(line).get('group_id') == gid]
        if row != self.expected_entry(gid) or matches != [{'group_id': gid, 'context_ref': self.context_ref, 'entry_ref': file_ref(entry)}]:
            raise ValueError('derived entry/source/origin/review/manifest identity changed')
        return row['effective_projection'], {'group_id': gid, 'entry_ref': file_ref(entry),
            'transport_raw_ref': row['baseline_raw_ref'], 'baseline_parent_entry_ref': row['baseline_parent_entry_ref'],
            'origin': row['effective_origin'], 'retained_provider_calls': row['original_retained_provider_calls'],
            'reviewed_revision_refs': row['reviewed_revision_refs'], 'new_provider_calls': 0}

    def render_literal(self, *args, **kwargs):
        output, provenance = super().render_literal(*args, **kwargs)
        provenance['origin'] = 'derived_reviewed_or_retained_group_projection'
        provenance['revision_contract_ref'] = self.context['revision_contract_ref']
        return output, provenance


def prepare(contract_ref, output):
    from independent_latex import reject_symlink_ancestors
    output = reject_symlink_ancestors(output).resolve()
    if output.exists():
        raise ValueError('fresh revision output required')
    contract, ledger, historical, equivalence, _ = verify_contract(contract_ref)
    output.mkdir(parents=True)
    write_new(output/'SOURCE_EQUIVALENCE.json', equivalence)
    context = dict(historical.context)
    context.update(protocol=REVISION_PROTOCOL, freeze_ref=contract['renderer_freeze_ref'],
        implementation_refs=load(contract['renderer_freeze_ref'])['implementation_refs'],
        policy_ref=load(contract['renderer_freeze_ref'])['source_cache_policy_ref'],
        source_ledger_ref=contract['current_source_ledger_ref'], source_review_ref=contract['current_source_review_ref'],
        revision_contract_ref=contract_ref, source_equivalence_ref=file_ref(output/'SOURCE_EQUIVALENCE.json'),
        cache_directory=str(output/'entries'), collection_file=str(output/'boundary'/'SOURCE_REQUESTS.jsonl'), editorial_revisions=[])
    source_style=load(contract['renderer_freeze_ref']).get('source_style_contract_ref')
    if source_style is not None:
        checked_ref(source_style);context['source_style_contract_ref']=source_style
    write_new(output/'RENDER_CONTEXT.json', context)
    cache = ReviewedGroupProjectionCache(file_ref(output/'RENDER_CONTEXT.json'), 'read')
    cache.directory.mkdir(); cache.collection.parent.mkdir()
    with (cache.directory/'GROUP_DERIVED_MANIFEST.jsonl').open('x') as manifest:
        for gid in cache.groups:
            write_new(cache._entry(gid), cache.expected_entry(gid))
            manifest.write(json.dumps({'group_id': gid, 'context_ref': cache.context_ref, 'entry_ref': file_ref(cache._entry(gid))})+'\n')
    write_new(output/'PREPARE_RESULT.json', {'status': 'prepared_reviewed_projection_namespace',
        'contract_ref': contract_ref, 'context_ref': cache.context_ref,
        'source_equivalence_ref': context['source_equivalence_ref'],
        'derived_manifest_ref': file_ref(cache.directory/'GROUP_DERIVED_MANIFEST.jsonl'),
        'groups': len(cache.groups), 'editorial_groups': len(contract['revisions']),
        'actual_provider_calls': 0, 'retained_original_provider_calls': load(contract['baseline_actual_call_ledger_ref'])['actual_provider_calls'],
        'actual_pdf_verified': False, 'human_accepted': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    stage = sub.add_parser('prepare')
    stage.add_argument('--contract', type=Path, required=True)
    stage.add_argument('--contract-sha256', required=True)
    stage.add_argument('--output', type=Path, required=True)
    stage.add_argument('--lock', type=Path, required=True)
    args = parser.parse_args()
    import fcntl
    from independent_latex import reject_symlink_ancestors
    reject_symlink_ancestors(args.contract)
    lock = reject_symlink_ancestors(args.lock)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        prepare({'path': str(args.contract.resolve()), 'sha256': args.contract_sha256}, args.output)


if __name__ == '__main__':
    main()
