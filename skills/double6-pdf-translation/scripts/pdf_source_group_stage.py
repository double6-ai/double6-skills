"""完整源组准备：零 provider、无 PDF、append-only，独立 coverage 审校前禁止 warming。"""
from pathlib import Path
import argparse
import fcntl
import json

from bounded_execution import snapshot, violation
from independent_latex import reject_symlink_ancestors
from pdf_source_cache import file_ref, write_new
from pdf_source_groups import build_group_input, compile_groups


def prepare(args):
    if args.max_pages not in range(1, 6):
        raise ValueError('formal complete source page limit must be between 1 and 5')
    output = reject_symlink_ancestors(args.output).resolve()
    if output.exists():
        raise ValueError('prepare output must be a fresh append-only directory')
    if args.source_il.stat().st_size > 32 * 1024**2:
        raise ValueError('source IL exceeds bounded 32MiB input limit')
    from pdf_source_cache import bound_json
    import fitz
    plan = bound_json({'path': str(args.plan.resolve()), 'sha256': args.plan_sha256})
    with fitz.open(plan['input_ref']['path']) as pdf:
        if len(pdf) > args.max_pages:
            raise ValueError('source page limit exceeded before compilation')
    baseline = snapshot()
    issue = violation(baseline, baseline, rss_limit=2 * 1024**3, max_processes=32)
    if issue:
        raise RuntimeError(issue)
    ref = lambda name: {'path': str(getattr(args, name).resolve()), 'sha256': getattr(args, name + '_sha256')}
    ledger = compile_groups(ref('plan'), ref('source_il'), ref('context'), evidence_ref=ref('evidence'),
                            policy_ref=ref('policy'), approval_ref=ref('approval'),
                            whitespace_policy_ref=ref('whitespace_policy'),
                            whitespace_approval_ref=ref('whitespace_approval'),
                            scientific_region_policy_ref=ref('scientific_region_policy'),
                            scientific_region_approval_ref=ref('scientific_region_approval'))
    issue = violation(snapshot(), baseline, rss_limit=2 * 1024**3, max_processes=32)
    if issue:
        raise RuntimeError(issue)
    if max(g['source_page'] for g in ledger['groups']) > args.max_pages:
        raise ValueError('source page limit exceeded')
    output.mkdir(parents=True)
    write_new(output / 'SOURCE_LEDGER.json', ledger)
    with (output / 'GROUP_INPUTS.jsonl').open('x', encoding='utf-8') as stream:
        for group in ledger['groups']:
            stream.write(json.dumps(build_group_input(group), ensure_ascii=False) + '\n')
    result = {'status': 'prepared_independent_source_coverage_review_required',
              'prepare_implementation_ref': file_ref(Path(__file__)),
              'source_ledger_ref': file_ref(output / 'SOURCE_LEDGER.json'),
              'group_inputs_ref': file_ref(output / 'GROUP_INPUTS.jsonl'),
              'source_coverage': ledger['source_coverage'], 'actual_provider_calls': 0,
              'actual_target_pdf': None, 'warming_allowed': False, 'semantic_accepted': False,
              'human_accepted': False, 'resource_limits': {'rss_gib': 2, 'seconds': 120,
                                                        'processes': 32, 'concurrency': 1, 'max_pages': args.max_pages}}
    write_new(output / 'PREPARE_RESULT.json', result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'source-il', 'context', 'evidence', 'policy', 'approval', 'whitespace-policy', 'whitespace-approval',
                 'scientific-region-policy', 'scientific-region-approval'):
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--lock', type=Path, required=True)
    parser.add_argument('--max-pages', type=int, default=3, choices=range(1, 6))
    args = parser.parse_args(argv)
    lock = reject_symlink_ancestors(args.lock)
    with lock.open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = prepare(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
