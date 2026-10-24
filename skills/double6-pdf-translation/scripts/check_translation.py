# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""兼容入口；实现按职责拆分，公开函数名称与命令保持。"""
from __future__ import annotations
from check_translation_context import *
from check_translation_core import (
    load_glossary,
    load_json,
    load_translation_blocks,
    contains_term,
    normalize_quality_text,
    should_use_document_translation,
    block_translation_or_document,
    policy_source_present,
    policy_translation_ok,
    manifest_source_text,
    metadata_source_text,
    policy_source_location,
    first_seen_block_for_policy,
    expected_translation_alternatives,
    excerpt,
    block_page_map,
    enrich_issue_locations,
    normalize_percent,
)
from check_translation_terms import (
    extract_percentages,
    check_bad_acronym_translation,
    check_bad_acronym_translation_blocks,
    check_glossary,
    check_glossary_by_blocks,
    check_default_term_policies,
    check_term_policy,
    check_entity_policies,
    check_entity_map_policies,
)
from check_translation_residue import (
    protected_values,
    term_policy_terms,
    entity_policy_terms,
    is_allowed_technical_residue,
    classify_english_residue,
    is_likely_allowed_english_phrase,
    strip_role_passthrough_lines,
    check_untranslated_english,
    check_untranslated_chinese,
    strip_zh_reference_lines,
    check_translation_metadata_leak,
    check_sections,
)
from check_translation_fidelity import (
    check_faithfulness_markers,
    has_reference_context,
    extract_protected_reference_values,
    check_citation_claim_drift,
    check_quantitative_fidelity,
    check_block_faithfulness,
    check_source_extraction_quality,
    page_tail_map_from_manifest,
    build_intra_page_continuity,
    build_coverage_gate,
    check_source_coverage,
    check_protected_spans,
)
from check_translation_gates import (
    gate_status,
    check_translation_blocks,
    check_render_manifest,
    collect_issues,
)
from check_translation_reports import (
    render_quality_report,
    build_review_focus,
    build_science_qa_review_items,
    build_quality_report,
    build_alignment_report,
)
from check_translation_memory import (
    detect_domain_term_seeds,
    merge_policy_row,
    build_term_policy,
    build_entity_map,
    build_document_memory,
)
from check_translation_repairs import (
    build_qa_checks,
    repair_type_for_issue,
    build_affected_blocks,
    repair_decision,
    normalize_manual_confirmations,
    build_confirmed_repair_plan,
    build_parser,
    main,
)

from legacy_module_api import bind_legacy_exports
bind_legacy_exports(globals(), {'load_glossary': 'check_translation_core', 'load_json': 'check_translation_core', 'load_translation_blocks': 'check_translation_core', 'contains_term': 'check_translation_core', 'normalize_quality_text': 'check_translation_core', 'should_use_document_translation': 'check_translation_core', 'block_translation_or_document': 'check_translation_core', 'policy_source_present': 'check_translation_core', 'policy_translation_ok': 'check_translation_core', 'manifest_source_text': 'check_translation_core', 'metadata_source_text': 'check_translation_core', 'policy_source_location': 'check_translation_core', 'first_seen_block_for_policy': 'check_translation_core', 'expected_translation_alternatives': 'check_translation_core', 'excerpt': 'check_translation_core', 'block_page_map': 'check_translation_core', 'enrich_issue_locations': 'check_translation_core', 'normalize_percent': 'check_translation_core', 'extract_percentages': 'check_translation_terms', 'check_bad_acronym_translation': 'check_translation_terms', 'check_bad_acronym_translation_blocks': 'check_translation_terms', 'check_glossary': 'check_translation_terms', 'check_glossary_by_blocks': 'check_translation_terms', 'check_default_term_policies': 'check_translation_terms', 'check_term_policy': 'check_translation_terms', 'check_entity_policies': 'check_translation_terms', 'check_entity_map_policies': 'check_translation_terms', 'protected_values': 'check_translation_residue', 'term_policy_terms': 'check_translation_residue', 'entity_policy_terms': 'check_translation_residue', 'is_allowed_technical_residue': 'check_translation_residue', 'classify_english_residue': 'check_translation_residue', 'is_likely_allowed_english_phrase': 'check_translation_residue', 'strip_role_passthrough_lines': 'check_translation_residue', 'check_untranslated_english': 'check_translation_residue', 'check_translation_metadata_leak': 'check_translation_residue', 'check_sections': 'check_translation_residue', 'check_faithfulness_markers': 'check_translation_fidelity', 'has_reference_context': 'check_translation_fidelity', 'extract_protected_reference_values': 'check_translation_fidelity', 'check_citation_claim_drift': 'check_translation_fidelity', 'check_quantitative_fidelity': 'check_translation_fidelity', 'check_block_faithfulness': 'check_translation_fidelity', 'check_source_extraction_quality': 'check_translation_fidelity', 'page_tail_map_from_manifest': 'check_translation_fidelity', 'build_intra_page_continuity': 'check_translation_fidelity', 'build_coverage_gate': 'check_translation_fidelity', 'check_source_coverage': 'check_translation_fidelity', 'check_protected_spans': 'check_translation_fidelity', 'gate_status': 'check_translation_gates', 'check_translation_blocks': 'check_translation_gates', 'check_render_manifest': 'check_translation_gates', 'collect_issues': 'check_translation_gates', 'render_quality_report': 'check_translation_reports', 'build_review_focus': 'check_translation_reports', 'build_science_qa_review_items': 'check_translation_reports', 'build_quality_report': 'check_translation_reports', 'build_alignment_report': 'check_translation_reports', 'detect_domain_term_seeds': 'check_translation_memory', 'merge_policy_row': 'check_translation_memory', 'build_term_policy': 'check_translation_memory', 'build_entity_map': 'check_translation_memory', 'build_document_memory': 'check_translation_memory', 'build_qa_checks': 'check_translation_repairs', 'repair_type_for_issue': 'check_translation_repairs', 'build_affected_blocks': 'check_translation_repairs', 'repair_decision': 'check_translation_repairs', 'normalize_manual_confirmations': 'check_translation_repairs', 'build_confirmed_repair_plan': 'check_translation_repairs', 'build_parser': 'check_translation_repairs', 'main': 'check_translation_repairs'}, ['check_translation_context', 'check_translation_core', 'check_translation_terms', 'check_translation_residue', 'check_translation_fidelity', 'check_translation_gates', 'check_translation_reports', 'check_translation_memory', 'check_translation_repairs'])

if __name__ == "__main__":
    raise SystemExit(main())
