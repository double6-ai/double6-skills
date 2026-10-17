# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""在失败原始响应之外追加完整源单元审校修订；不改写模型响应或放宽保护门。"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import independent_latex as latex

PROTOCOL = 'latex_failed_complete_unit_review_v1'
SCRIPT_INTERFACE = 'cli'
SCRIPT_INTERFACE_REASON = '把具名、源绑定的完整单元修订追加为候选，供原工作流恢复。'


def ref(path):
    path = latex.reject_symlink_ancestors(path).resolve()
    return {'path': str(path), 'sha256': latex.file_sha(path)}


def checked(evidence):
    if not isinstance(evidence, dict) or set(evidence) != {'path', 'sha256'}:
        raise ValueError('exact_reference_required')
    path = latex.reject_symlink_ancestors(evidence['path']).resolve()
    if path.is_file() and path.stat().st_size > 32*1024**2:
        raise ValueError('review_input_over_budget')
    if not path.is_file() or ref(path) != evidence:
        raise ValueError('review_input_changed')
    return path


def apply_review(contract_path):
    contract_path = latex.reject_symlink_ancestors(contract_path).resolve()
    if contract_path.stat().st_size > 4*1024**2:
        raise ValueError('review_contract_over_budget')
    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    if contract.get('protocol') != PROTOCOL or contract.get('schema_version') != 1:
        raise ValueError('unknown_complete_unit_review_protocol')
    if contract.get('complete_source_unit_reviewed') is not True or not contract.get('reviewer'):
        raise ValueError('named_complete_source_review_required')
    output = latex.reject_symlink_ancestors(contract['output_directory']).resolve()
    plan_path = checked(contract['plan_ref'])
    if plan_path != output/'latex_plan.json':
        raise ValueError('review_plan_directory_mismatch')
    plan = json.loads(plan_path.read_text())
    matches = [u for u in plan['units'] if u['id'] == contract['unit_id']]
    if len(matches) != 1:
        raise ValueError('unique_complete_source_unit_required')
    unit = matches[0]
    if contract.get('source_unit_sha256') != unit['source_sha256']:
        raise ValueError('complete_source_unit_changed')
    raw_path = checked(contract['failed_raw_ref'])
    if raw_path != output/'units'/(unit['id']+'.raw.json'):
        raise ValueError('failed_raw_directory_mismatch')
    destination = output/'units'/(unit['id']+'.json')
    if destination.exists():
        raise ValueError('canonical_unit_already_exists')
    raw = json.loads(raw_path.read_text())
    if raw.get('source_sha256') != unit['source_sha256'] or raw.get('quality_accepted') is not False:
        raise ValueError('failed_raw_source_or_status_mismatch')
    fingerprint_path = checked(contract['model_fingerprint_ref'])
    identity = latex.cache_identity(output, plan, unit, raw['model'], raw['base_url'], fingerprint_path)
    if identity != raw.get('cache_identity'):
        raise ValueError('actual_failed_request_identity_changed')
    response = raw['response']
    if json.loads(fingerprint_path.read_text()).get('api_contract'):
        from lmstudio_native import native_text
        original_target = native_text(response, raw['model'])
    else:
        from model_client import extract_text
        original_target = extract_text(response)
    try:
        latex.normalize_markers(unit, original_target)
    except ValueError as exc:
        failed_reason = str(exc)
    else:
        raise ValueError('raw_response_was_not_a_protection_failure')
    review_path = checked(contract['source_review_ref'])
    source_review = json.loads(review_path.read_text())
    if (source_review.get('unit_source_sha256') != unit['source_sha256'] or
            source_review.get('complete_source_text') != unit['source_text'] or
            source_review.get('status') != 'complete_unit_reviewed' or
            source_review.get('reviewer') != contract['reviewer']):
        raise ValueError('review_not_bound_to_complete_source')
    target = contract.get('complete_masked_translation')
    if not isinstance(target, str) or not target.strip():
        raise ValueError('complete_reviewed_target_required')
    actual = latex.validate_translation(unit, target)
    if source_review.get('complete_masked_translation_sha256') != latex.digest(target):
        raise ValueError('reviewed_complete_target_changed')
    evidence = {'protocol': PROTOCOL, 'contract_ref': ref(contract_path),
                'source_review_ref': ref(review_path), 'failed_raw_ref': ref(raw_path),
                'original_failure': failed_reason, 'reviewer': contract['reviewer'],
                'origin': 'operator_reviewed_complete_unit', 'new_model_calls': 0,
                'human_user_accepted': False, 'strict_delivery': False}
    row = {'schema_version': 1, 'status': 'reviewed_complete_unit_candidate',
           'unit': unit['id'], 'source_sha256': unit['source_sha256'],
           'model': raw['model'], 'cache_identity': identity, 'response': response,
           'masked_translation': target, 'translation': actual,
           'reviewed_correction': evidence, 'semantic_accepted': False,
           'human_accepted': False, 'model_output_relabelled_as_reviewed_target': False}
    latex.write_new(destination, row)
    return {'status': 'reviewed_complete_unit_candidate', 'unit_ref': ref(destination),
            'new_model_calls': 0, 'original_raw_unchanged': ref(raw_path) == contract['failed_raw_ref'],
            'PDF_review_still_required': True}


def verify_reviewed_unit(output, plan, unit, row):
    evidence = row['reviewed_correction']
    contract = json.loads(checked(evidence['contract_ref']).read_text())
    review = json.loads(checked(evidence['source_review_ref']).read_text())
    raw = json.loads(checked(evidence['failed_raw_ref']).read_text())
    expected_plan = ref(Path(output)/'latex_plan.json')
    if (contract.get('protocol') != PROTOCOL or contract.get('schema_version') != 1 or
            contract.get('complete_source_unit_reviewed') is not True or
            contract.get('reviewer') != evidence.get('reviewer') or
            review.get('reviewer') != evidence.get('reviewer') or
            review.get('status') != 'complete_unit_reviewed' or
            review.get('unit_source_sha256') != unit['source_sha256'] or
            contract.get('plan_ref') != expected_plan or
            contract.get('unit_id') != unit['id'] or contract.get('source_unit_sha256') != unit['source_sha256'] or
            contract.get('complete_masked_translation') != row['masked_translation'] or
            contract.get('failed_raw_ref') != evidence['failed_raw_ref'] or
            contract.get('source_review_ref') != evidence['source_review_ref'] or
            review.get('complete_source_text') != unit['source_text'] or
            review.get('complete_masked_translation_sha256') != latex.digest(row['masked_translation']) or
            raw.get('cache_identity') != row['cache_identity'] or raw.get('response') != row['response'] or
            row.get('status') != 'reviewed_complete_unit_candidate' or evidence.get('new_model_calls') != 0 or
            row.get('human_accepted') is not False):
        raise ValueError('reviewed_complete_unit_provenance_changed')
    return evidence


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(apply_review(args.contract), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
