# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""恢复必须沿用相同冻结输入、完整计划和已经实际结束的失败回执。"""
from __future__ import annotations
import json
from pathlib import Path
import independent_latex as latex

SCRIPT_INTERFACE = 'internal-module'
SCRIPT_INTERFACE_REASON = 'LaTeX工作流恢复前的计划、缓存和原失败链校验。'


def validate_resume(args, freeze):
    output = latex.reject_symlink_ancestors(args.output).resolve()
    previous_path = latex.reject_symlink_ancestors(args.previous_result).resolve()
    if latex.file_sha(previous_path) != args.previous_result_sha256:
        raise ValueError("previous_result_changed")
    previous = json.loads(previous_path.read_text())
    freeze_path = Path(args.freeze).resolve()
    actual_freeze = {'path': str(freeze_path), 'sha256': latex.file_sha(freeze_path)}
    if (previous.get('status') not in {'failed', 'stopped'} or
            previous.get('route') != 'latex_verified' or
            previous.get('input_ref') != freeze['input'] or
            previous.get('freeze_ref') != actual_freeze):
        raise ValueError('resume_requires_exact_original_failed_freeze')
    plan = json.loads((output/'latex_plan.json').read_text())
    if plan.get('input_tex') != freeze.get('latex_source'):
        raise ValueError('resume_source_project_changed')
    current = previous
    seen = {str(previous_path)}
    preparation = None
    for _ in range(20):
        preparation = next((s for s in current.get('stages', []) if s.get('operation') == 'prepare'), None)
        if preparation is not None:
            break
        parent = current.get('previous_result_ref')
        if not parent:
            break
        path = latex.reject_symlink_ancestors(parent['path']).resolve()
        if str(path) in seen or latex.file_sha(path) != parent['sha256']:
            raise ValueError('resume_parent_changed_or_cycle')
        seen.add(str(path))
        current = json.loads(path.read_text())
        if current.get('freeze_ref') != actual_freeze or current.get('input_ref') != freeze['input']:
            raise ValueError('resume_parent_freeze_changed')
    if preparation is None or preparation.get('status') != 'succeeded':
        raise ValueError('original_successful_preparation_receipt_required')
    argv = preparation.get('command', {}).get('argv', [])
    if '--output' not in argv or Path(argv[argv.index('--output')+1]).resolve() != output:
        raise ValueError('resume_output_differs_from_original_preparation')
    if (output/'latex_result.json').exists():
        raise ValueError('resume_requires_uncompiled_partial_candidate')
    plan_sha = latex.file_sha(output/'latex_plan.json')
    known = {u['id'] for u in plan['units']}
    for path in (output/'units').glob('unit-*.json'):
        item = json.loads(path.read_text())
        name = path.name.removesuffix('.raw.json').removesuffix('.json')
        if name not in known or item.get('cache_identity', {}).get('plan_sha256') != plan_sha:
            raise ValueError('resume_cached_plan_or_unit_changed')
        if not path.name.endswith('.raw.json'):
            unit = next(u for u in plan['units'] if u['id'] == name)
            if latex.validate_translation(unit, item['masked_translation']) != item['translation']:
                raise ValueError('resume_cached_complete_target_changed')
    return {'status': 'validated', 'unit_count': len(known), 'new_model_calls': 0}
