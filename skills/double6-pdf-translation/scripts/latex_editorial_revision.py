"""将审校通过的完整源单元修订渲染为独立 LaTeX 候选，保留原模型证据。"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

import independent_latex as latex

PROTOCOL = 'latex_source_bound_complete_unit_editorial_v1'


def checked_ref(row):
    if not isinstance(row, dict) or not {'path', 'sha256'} <= set(row):
        raise ValueError('complete file identity required')
    path = latex.reject_symlink_ancestors(Path(row['path'])).resolve()
    if not path.is_file() or latex.file_sha(path) != row['sha256']:
        raise ValueError('editorial contract file identity changed')
    return path


def load(row):
    return json.loads(checked_ref(row).read_text(encoding='utf-8'))


def file_ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': latex.file_sha(path)}


def verify_contract(contract):
    if contract.get('protocol') != PROTOCOL or contract.get('schema_version') != 1:
        raise ValueError('unknown editorial revision protocol')
    renderer_refs = contract.get('renderer_refs', [])
    actual = {str(checked_ref(row)) for row in renderer_refs}
    required = {str(Path(__file__).resolve()), str(Path(latex.__file__).resolve())}
    if not required <= actual:
        raise ValueError('actual editorial renderer implementation must be frozen')
    baseline = contract['baseline']
    directory = latex.reject_symlink_ancestors(Path(baseline['directory'])).resolve()
    plan_path = checked_ref(baseline['plan_ref'])
    if plan_path != directory/'latex_plan.json':
        raise ValueError('baseline plan directory mismatch')
    plan = load(baseline['plan_ref'])
    generation_freeze = load(baseline['generation_freeze_ref'])
    source_scope = load(generation_freeze['scope_evidence'])
    if generation_freeze.get('input') != contract['source_pdf_ref'] or source_scope.get('source_pdf') != contract['source_pdf_ref']:
        raise ValueError('editorial source PDF differs from the paired generation source')
    if generation_freeze.get('latex_source') != plan['input_tex'] or source_scope.get('latex_source') != plan['input_tex']:
        raise ValueError('paired source PDF/TeX project identity mismatch')
    result = load(baseline['result_ref'])
    if result.get('status') != 'candidate':
        raise ValueError('complete baseline candidate required')
    for key in ('pdf_ref', 'tex_ref'):
        checked_ref(baseline[key])
    if result['translated_pdf'] != baseline['pdf_ref'] or result['translated_tex'] != baseline['tex_ref']:
        raise ValueError('baseline actual Tex/PDF identity mismatch')
    unit_refs = baseline['unit_refs']
    if len(unit_refs) != len(plan['units']):
        raise ValueError('baseline unit coverage incomplete')
    by_id = {}
    for item in unit_refs:
        unit_id = item['unit_id']
        if unit_id in by_id:
            raise ValueError('duplicate baseline unit')
        path = checked_ref(item['ref'])
        if path != directory/'units'/(unit_id+'.json'):
            raise ValueError('baseline unit directory mismatch')
        by_id[unit_id] = json.loads(path.read_text())
    if set(by_id) != {unit['id'] for unit in plan['units']}:
        raise ValueError('baseline unit identity coverage incomplete')
    for unit in plan['units']:
        row = by_id[unit['id']]
        if row['source_sha256'] != unit['source_sha256']:
            raise ValueError('baseline complete source changed')
        restored = latex.validate_translation(unit, row['masked_translation'])
        if row['translation'] != restored:
            raise ValueError('baseline restored translation differs from protected source bytes')
    source_pdf = checked_ref(contract['source_pdf_ref'])
    import fitz
    with fitz.open(source_pdf) as source:
        if not 1 <= len(source) <= 5:
            raise ValueError('editorial source must remain within the complete1–5 page scope')
    assets = baseline['source_assets']
    if len(assets) != len(plan['asset_dependencies']) or {row['ref']['sha256'] for row in assets} != {row['sha256'] for row in plan['asset_dependencies']}:
        raise ValueError('source asset identity coverage incomplete')
    for original in plan['asset_dependencies']:
        checked_ref(original)
    ledger = load(baseline['call_ledger_ref'])
    if ledger.get('completed_canonical_units') != len(plan['units']):
        raise ValueError('retained actual generation ledger coverage mismatch')
    observed = []
    journal_rows = {}
    for item in ledger.get('events', []):
        journal = checked_ref(item['journal_ref'])
        if journal not in journal_rows:
            journal_rows[journal] = [json.loads(line) for line in journal.read_text().splitlines()]
        if item['event'] not in journal_rows[journal]:
            raise ValueError('retained generation event differs from actual journal')
        observed.append((str(journal), json.dumps(item['event'], sort_keys=True)))
    if len(observed) != len(set(observed)):
        raise ValueError('duplicate retained generation event')
    starts = sum(json.loads(event).get('phase') == 'start' for _, event in observed)
    if ledger.get('actual_candidate_generation_calls') != starts:
        raise ValueError('retained actual generation count mismatch')
    names = set()
    for item in assets:
        relative = Path(item['relative_path'])
        if relative.is_absolute() or '..' in relative.parts or str(relative) in names:
            raise ValueError('invalid or duplicate relative source asset')
        names.add(str(relative))
        if checked_ref(item['ref']) != directory/'paper_source'/relative:
            raise ValueError('baseline copied source asset identity mismatch')
    revisions = contract['revisions']
    if not revisions:
        raise ValueError('complete source revisions required')
    revised = {}
    source_units = {unit['id']: unit for unit in plan['units']}
    for revision in revisions:
        unit_id = revision['unit_id']
        if unit_id in revised or unit_id not in source_units:
            raise ValueError('duplicate or unknown revised unit')
        source = load(revision['source_ref'])
        target = load(revision['target_ref'])
        provenance = load(revision['provenance_ref'])
        review = load(revision['review_ref'])
        if revision.get('review_selector') is not None:
            if revision['review_selector'] != unit_id:
                raise ValueError('review selector must name the same complete source unit')
            if review.get('status') != 'pass_semantic_proposals_only':
                raise ValueError('complete aggregate proposal review required')
            matches = [item for item in review.get('unit_reviews', []) if item.get('unit_id') == unit_id]
            if len(matches) != 1:
                raise ValueError('aggregate source unit review must be unique')
            review = matches[0]
        initial_path = checked_ref(revision['initial_raw_ref'])
        if initial_path != directory/'units'/(unit_id+'.raw.json'):
            raise ValueError('initial raw must be the actual baseline source unit raw')
        if revision.get('native_repair_raw_ref'):
            checked_ref(revision['native_repair_raw_ref'])
        unit = source_units[unit_id]
        native_row = by_id[unit_id]
        initial = load(revision['initial_raw_ref'])
        identity = initial.get('cache_identity', {})
        if initial.get('source_sha256') != unit['source_sha256'] or identity.get('unit_source_sha256') != unit['source_sha256']:
            raise ValueError('initial raw belongs to a different complete source unit')
        if identity.get('masked_prompt_sha256') != latex.digest(unit['masked_text']):
            raise ValueError('initial raw literal source identity mismatch')
        expected_identity = dict(native_row['cache_identity'])
        expected_identity.pop('repair_freeze_ref', None)
        expected_identity['system_prompt_sha256'] = latex.digest(latex.unit_system_prompt(unit))
        if identity != expected_identity or initial.get('model') != native_row.get('model'):
            raise ValueError('initial raw code/service/generation identity mismatch')
        if native_row.get('repair_raw_ref') != revision.get('native_repair_raw_ref'):
            raise ValueError('effective native repair raw identity mismatch')
        if revision.get('native_repair_raw_ref'):
            repaired = load(revision['native_repair_raw_ref'])
            request = repaired.get('request', {})
            if repaired.get('source_sha256') != unit['source_sha256'] or repaired.get('cache_identity') != native_row['cache_identity']:
                raise ValueError('repair raw complete source/code/service identity mismatch')
            if request.get('input') != unit['masked_text'] or latex.digest(request.get('system_prompt', '')) != native_row['cache_identity']['system_prompt_sha256']:
                raise ValueError('repair raw request literal identity mismatch')
            if repaired.get('response') != native_row.get('response'):
                raise ValueError('repair raw differs from effective native response')
        elif initial.get('response') != native_row.get('response'):
            raise ValueError('initial raw differs from effective native response')
        if source.get('source_unit') != unit:
            raise ValueError('revision must bind the entire unchanged source unit')
        if target.get('revision_kind') != 'coordinator_full_paragraph_editorial':
            raise ValueError('unknown output origin')
        if target.get('unit_id') != unit_id or target.get('source_unit_sha256') != unit['source_sha256']:
            raise ValueError('editorial target complete source identity mismatch')
        if target.get('model_generation_calls') != 0:
            raise ValueError('editorial target cannot claim model generation')
        if review.get('status') != 'pass_semantic_proposal_only' or review.get('unit_id') != unit_id:
            raise ValueError('exact complete-source proposal review required')
        if review.get('source_unit_sha256') != unit['source_sha256']:
            raise ValueError('review complete source identity mismatch')
        if review.get('input_refs', {}).get('source') != revision['source_ref'] or review.get('input_refs', {}).get('target') != revision['target_ref']:
            raise ValueError('review source/target file identities mismatch')
        if provenance.get('source_ref') != revision['source_ref'] or provenance.get('target_ref') != revision['target_ref']:
            raise ValueError('editorial provenance source/target mismatch')
        if provenance.get('initial_failed_raw_ref') != revision['initial_raw_ref'] or provenance.get('real_native_revision_raw_ref') != revision.get('native_repair_raw_ref'):
            raise ValueError('editorial prior actual model provenance mismatch')
        text = target['target_masked_text']
        restored = latex.validate_translation(unit, text)
        if review.get('target_masked_text') != text or review.get('restored_target_sha256') != latex.digest(restored):
            raise ValueError('reviewed complete target literal mismatch')
        revised[unit_id] = {'source_sha256': unit['source_sha256'], 'masked_translation': text,
                           'translation': restored, 'revision': revision}
    return plan, by_id, revised, source_pdf


def prepare_revision(contract_path, output):
    contract_path = latex.reject_symlink_ancestors(Path(contract_path)).resolve()
    contract = json.loads(contract_path.read_text())
    plan, rows, revised, source_pdf = verify_contract(contract)
    output = latex.reject_symlink_ancestors(Path(output)).resolve()
    if output.exists():
        raise ValueError('editorial output must be fresh')
    output.mkdir(parents=True)
    (output/'paper_source').mkdir()
    (output/'units').mkdir()
    for item in contract['baseline']['source_assets']:
        target = output/'paper_source'/item['relative_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(checked_ref(item['ref']), target)
    latex.write_new(output/'latex_plan.json', copy.deepcopy(plan))
    previous_refs = {item['unit_id']: item['ref'] for item in contract['baseline']['unit_refs']}
    for unit_id, row in rows.items():
        if unit_id in revised:
            item = revised[unit_id]
            effective = {'schema_version': 1, 'unit': unit_id, 'status': 'editorial_candidate',
                         'source_sha256': item['source_sha256'],
                         'masked_translation': item['masked_translation'], 'translation': item['translation'],
                         'effective_output_origin': 'coordinator_full_paragraph_editorial',
                         'native_unit_ref': previous_refs[unit_id], 'revision_refs': item['revision'],
                         'new_model_calls': 0, 'semantic_accepted': False, 'human_accepted': False}
        else:
            effective = {'schema_version': 1, 'unit': unit_id, 'status': 'retained_native_candidate',
                         'source_sha256': row['source_sha256'], 'masked_translation': row['masked_translation'],
                         'translation': row['translation'], 'effective_output_origin': 'retained_baseline_unit',
                         'native_unit_ref': previous_refs[unit_id], 'new_model_calls': 0,
                         'semantic_accepted': False, 'human_accepted': False}
        latex.write_new(output/'units'/(unit_id+'.json'), effective)
    latex.write_new(output/'EDITORIAL_PREPARATION.json', {'protocol': PROTOCOL,
        'contract_ref': file_ref(contract_path), 'retained_generation_ledger_ref': contract['baseline']['call_ledger_ref'],
        'revised_unit_ids': sorted(revised), 'complete_units': len(rows), 'new_model_calls': 0,
        'effective_origin': 'source_bound_complete_unit_editorial_revision',
        'semantic_accepted': False, 'actual_pdf_verified': False, 'human_accepted': False})
    return source_pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cjk-font', default='Songti SC')
    parser.add_argument('--cjk-emphasis-font', default='Kaiti SC')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    source_pdf = prepare_revision(args.contract, args.output)
    if args.prepare_only:
        print(json.dumps({'status': 'editorial_prepared', 'new_model_calls': 0})); return 0
    contract = load(file_ref(args.contract))
    emphasis = contract.get("cjk_emphasis_font")
    if emphasis is None or emphasis.get("name") != args.cjk_emphasis_font:
        raise ValueError("source-bound editorial emphasis font declaration missing or changed")
    checked_ref(emphasis["file_ref"])
    result = latex.compile_project(args.output, args.cjk_font, source_pdf, args.cjk_emphasis_font)
    latex.write_new(args.output/'EDITORIAL_RESULT.json', {'status': result['status'],
        'contract_ref': file_ref(args.contract), 'render_result_ref': file_ref(args.output/'latex_result.json'),
        'translated_pdf': result.get('translated_pdf'), 'translated_tex': result.get('translated_tex'),
        'new_model_calls': 0, 'retained_generation_ledger_ref': load(file_ref(args.output/'EDITORIAL_PREPARATION.json'))['retained_generation_ledger_ref'],
        'effective_origin': 'source_bound_complete_unit_editorial_revision',
        'semantic_accepted': False, 'human_accepted': False, 'strict_delivery': False})
    print(json.dumps({'status': result['status'], 'new_model_calls': 0})); return 0 if result['status'] == 'candidate' else 1


if __name__ == '__main__':
    raise SystemExit(main())
