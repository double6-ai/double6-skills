# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""兼容入口；实现按职责拆分，公开函数名称与命令保持。"""
from __future__ import annotations
from run_pdf_translation_context import *
from pdf_translation_paths import (
    repo_root,
    paper_translation_project_root,
    paper_translation_run_root,
    paper_translation_shared_library_dir,
    default_engine_home,
    vendored_pdf2zh_skill_root,
    latex_translation_after_writeback_repair,
    vendored_babeldoc_root,
    default_output_dir,
    find_pdf2zh_binary,
    pdf2zh_command_prefix,
    should_use_qwen_cli_adapter,
    should_enable_hymt_compat_proxy,
    pdf_has_toc_like_pages,
    resolve_pdf_layout_profile,
)
from pdf_translation_text_repair import (
    apply_pdf_direct_text_repairs,
)
from pdf_translation_commands import (
    build_qwen_cli_command,
    _compact_policy_items,
    _policy_item_is_active,
    build_backend_system_prompt,
    build_pdf2zh_command,
    redacted_command,
    build_latex_direct_requirement,
    build_latex_direct_command,
    has_local_latex_compiler,
    ensure_tex_docker_wrappers,
    select_latex_compile_runtime,
    infer_latex_direct_failure_stage,
)
from pdf_translation_latex_audit import (
    default_latex_baseline_pdf,
    summarize_pdf_for_baseline,
    latex_page_drift_tokens,
    latex_page_content_drift_from_text_pages,
    build_latex_page_content_drift_report,
    strip_latex_comments,
    latex_prose_for_line_estimate,
    is_line_estimate_eligible,
    cjk_width_units,
    estimated_column_lines,
    latex_content_loss_evidence,
    count_latex_headings,
    build_latex_reflow_plan,
    build_latex_line_reflow_estimate,
    write_latex_baseline_audit,
)
from pdf_translation_latex_render import (
    run_latex_direct_render,
    prepare_source,
    latex_candidate_score,
    iter_latex_candidates,
    discover_latex_source,
)
from pdf_translation_artifacts import (
    write_glossary,
    enrich_quality_artifacts,
    collect_pdfs,
    select_pdf_outputs,
    resolve_bilingual_source_pdf,
    build_standard_bilingual_output,
    maybe_build_visual_repair_output,
    mirror_latex_direct_bilingual_output,
    relocate_backend_dual_intermediate,
    extract_pdf_text,
    write_layout_map,
    write_translation_artifacts,
    run_quality_check,
    render_qa_repaired_pdf,
)
from pdf_translation_delivery import (
    build_delivery_gates,
    build_fast_full_translation_draft_gates,
)
from pdf_translation_latex_quality import (
    build_latex_direct_quality_gate,
    write_latex_segment_repair_plan,
    write_latex_paragraph_structure_repair_manifest,
    build_latex_segment_window_coverage,
    load_latex_direct_segments_for_gate,
)
from pdf_translation_backend_quality import (
    maybe_run_cloud_layout,
    fallback_to_text_path,
    parse_backend_quality,
    parse_translation_cache_stats,
    enrich_translation_cache_stats,
    annotate_backend_quality_origin,
    cjk_count,
    looks_already_translated,
    looks_formula_or_placeholder_heavy,
    plain_text_without_style_tags,
    looks_like_name_list_heavy,
    has_long_ordinary_english_run,
    classify_backend_passthrough,
    classify_backend_fallback,
    refine_backend_quality_with_retry_failures,
    resolve_backend_quality_with_pdf_direct_repairs,
    apply_pdf_direct_repair_resolutions_to_retry_failures,
    locate_backend_tracking_file,
    copy_backend_tracking_artifact,
)
from pdf_translation_tracking import (
    iter_tracking_paragraphs,
    _tracking_text_blob,
    build_dropped_text_audit,
    build_dropped_text_audit_from_files,
    extract_tracking_failures,
    dedupe_backend_retry_failures,
    write_backend_retry_failures,
)
from pdf_translation_overrides import (
    block_page_lookup,
    add_rerender_candidate,
    build_rerender_candidates,
    english_residue_context_nonblocking,
    filter_nonblocking_english_residue,
    accepted_latex_page_delta,
    visual_false_positive_confirmed,
    pdf_direct_repair_delivery_review_confirmed,
    apply_pdf_direct_repair_delivery_overrides,
    pdf_direct_text_repair_delivery_safe,
    structured_visual_candidate_review_confirmed,
    apply_structured_visual_candidate_delivery_overrides,
    structured_visual_candidate_delivery_safe,
    apply_layout_mapping_warning_delivery_overrides,
    apply_visual_false_positive_overrides,
    apply_latex_baseline_false_positive_overrides,
    append_visual_rerender_candidates,
    append_visual_rerender_plan,
)
from pdf_translation_render import (
    _run_render,
)
from pdf_translation_runtime import (
    bind_final_group_artifact,
    run,
)
from pdf_translation_cli import (
    build_parser,
    main,
)

from legacy_module_api import bind_legacy_exports
bind_legacy_exports(globals(), {'repo_root': 'pdf_translation_paths', 'paper_translation_project_root': 'pdf_translation_paths', 'paper_translation_run_root': 'pdf_translation_paths', 'paper_translation_shared_library_dir': 'pdf_translation_paths', 'default_engine_home': 'pdf_translation_paths', 'vendored_pdf2zh_skill_root': 'pdf_translation_paths', 'latex_translation_after_writeback_repair': 'pdf_translation_paths', 'vendored_babeldoc_root': 'pdf_translation_paths', 'default_output_dir': 'pdf_translation_paths', 'find_pdf2zh_binary': 'pdf_translation_paths', 'pdf2zh_command_prefix': 'pdf_translation_paths', 'should_use_qwen_cli_adapter': 'pdf_translation_paths', 'should_enable_hymt_compat_proxy': 'pdf_translation_paths', 'pdf_has_toc_like_pages': 'pdf_translation_paths', 'resolve_pdf_layout_profile': 'pdf_translation_paths', 'apply_pdf_direct_text_repairs': 'pdf_translation_text_repair', 'build_qwen_cli_command': 'pdf_translation_commands', '_compact_policy_items': 'pdf_translation_commands', '_policy_item_is_active': 'pdf_translation_commands', 'build_backend_system_prompt': 'pdf_translation_commands', 'build_pdf2zh_command': 'pdf_translation_commands', 'redacted_command': 'pdf_translation_commands', 'build_latex_direct_requirement': 'pdf_translation_commands', 'build_latex_direct_command': 'pdf_translation_commands', 'has_local_latex_compiler': 'pdf_translation_commands', 'ensure_tex_docker_wrappers': 'pdf_translation_commands', 'select_latex_compile_runtime': 'pdf_translation_commands', 'infer_latex_direct_failure_stage': 'pdf_translation_commands', 'default_latex_baseline_pdf': 'pdf_translation_latex_audit', 'summarize_pdf_for_baseline': 'pdf_translation_latex_audit', 'latex_page_drift_tokens': 'pdf_translation_latex_audit', 'latex_page_content_drift_from_text_pages': 'pdf_translation_latex_audit', 'build_latex_page_content_drift_report': 'pdf_translation_latex_audit', 'strip_latex_comments': 'pdf_translation_latex_audit', 'latex_prose_for_line_estimate': 'pdf_translation_latex_audit', 'is_line_estimate_eligible': 'pdf_translation_latex_audit', 'cjk_width_units': 'pdf_translation_latex_audit', 'estimated_column_lines': 'pdf_translation_latex_audit', 'latex_content_loss_evidence': 'pdf_translation_latex_audit', 'count_latex_headings': 'pdf_translation_latex_audit', 'build_latex_reflow_plan': 'pdf_translation_latex_audit', 'build_latex_line_reflow_estimate': 'pdf_translation_latex_audit', 'write_latex_baseline_audit': 'pdf_translation_latex_audit', 'run_latex_direct_render': 'pdf_translation_latex_render', 'prepare_source': 'pdf_translation_latex_render', 'latex_candidate_score': 'pdf_translation_latex_render', 'iter_latex_candidates': 'pdf_translation_latex_render', 'discover_latex_source': 'pdf_translation_latex_render', 'write_glossary': 'pdf_translation_artifacts', 'enrich_quality_artifacts': 'pdf_translation_artifacts', 'collect_pdfs': 'pdf_translation_artifacts', 'select_pdf_outputs': 'pdf_translation_artifacts', 'resolve_bilingual_source_pdf': 'pdf_translation_artifacts', 'build_standard_bilingual_output': 'pdf_translation_artifacts', 'maybe_build_visual_repair_output': 'pdf_translation_artifacts', 'mirror_latex_direct_bilingual_output': 'pdf_translation_artifacts', 'relocate_backend_dual_intermediate': 'pdf_translation_artifacts', 'extract_pdf_text': 'pdf_translation_artifacts', 'write_layout_map': 'pdf_translation_artifacts', 'write_translation_artifacts': 'pdf_translation_artifacts', 'run_quality_check': 'pdf_translation_artifacts', 'render_qa_repaired_pdf': 'pdf_translation_artifacts', 'build_delivery_gates': 'pdf_translation_delivery', 'build_fast_full_translation_draft_gates': 'pdf_translation_delivery', 'build_latex_direct_quality_gate': 'pdf_translation_latex_quality', 'write_latex_segment_repair_plan': 'pdf_translation_latex_quality', 'write_latex_paragraph_structure_repair_manifest': 'pdf_translation_latex_quality', 'build_latex_segment_window_coverage': 'pdf_translation_latex_quality', 'load_latex_direct_segments_for_gate': 'pdf_translation_latex_quality', 'maybe_run_cloud_layout': 'pdf_translation_backend_quality', 'fallback_to_text_path': 'pdf_translation_backend_quality', 'parse_backend_quality': 'pdf_translation_backend_quality', 'parse_translation_cache_stats': 'pdf_translation_backend_quality', 'enrich_translation_cache_stats': 'pdf_translation_backend_quality', 'annotate_backend_quality_origin': 'pdf_translation_backend_quality', 'cjk_count': 'pdf_translation_backend_quality', 'looks_already_translated': 'pdf_translation_backend_quality', 'looks_formula_or_placeholder_heavy': 'pdf_translation_backend_quality', 'plain_text_without_style_tags': 'pdf_translation_backend_quality', 'looks_like_name_list_heavy': 'pdf_translation_backend_quality', 'has_long_ordinary_english_run': 'pdf_translation_backend_quality', 'classify_backend_passthrough': 'pdf_translation_backend_quality', 'classify_backend_fallback': 'pdf_translation_backend_quality', 'refine_backend_quality_with_retry_failures': 'pdf_translation_backend_quality', 'resolve_backend_quality_with_pdf_direct_repairs': 'pdf_translation_backend_quality', 'apply_pdf_direct_repair_resolutions_to_retry_failures': 'pdf_translation_backend_quality', 'locate_backend_tracking_file': 'pdf_translation_backend_quality', 'copy_backend_tracking_artifact': 'pdf_translation_backend_quality', 'iter_tracking_paragraphs': 'pdf_translation_tracking', '_tracking_text_blob': 'pdf_translation_tracking', 'build_dropped_text_audit': 'pdf_translation_tracking', 'build_dropped_text_audit_from_files': 'pdf_translation_tracking', 'extract_tracking_failures': 'pdf_translation_tracking', 'dedupe_backend_retry_failures': 'pdf_translation_tracking', 'write_backend_retry_failures': 'pdf_translation_tracking', 'block_page_lookup': 'pdf_translation_overrides', 'add_rerender_candidate': 'pdf_translation_overrides', 'build_rerender_candidates': 'pdf_translation_overrides', 'english_residue_context_nonblocking': 'pdf_translation_overrides', 'filter_nonblocking_english_residue': 'pdf_translation_overrides', 'accepted_latex_page_delta': 'pdf_translation_overrides', 'visual_false_positive_confirmed': 'pdf_translation_overrides', 'pdf_direct_repair_delivery_review_confirmed': 'pdf_translation_overrides', 'apply_pdf_direct_repair_delivery_overrides': 'pdf_translation_overrides', 'pdf_direct_text_repair_delivery_safe': 'pdf_translation_overrides', 'structured_visual_candidate_review_confirmed': 'pdf_translation_overrides', 'apply_structured_visual_candidate_delivery_overrides': 'pdf_translation_overrides', 'structured_visual_candidate_delivery_safe': 'pdf_translation_overrides', 'apply_layout_mapping_warning_delivery_overrides': 'pdf_translation_overrides', 'apply_visual_false_positive_overrides': 'pdf_translation_overrides', 'apply_latex_baseline_false_positive_overrides': 'pdf_translation_overrides', 'append_visual_rerender_candidates': 'pdf_translation_overrides', 'append_visual_rerender_plan': 'pdf_translation_overrides', '_run_render': 'pdf_translation_render', 'bind_final_group_artifact': 'pdf_translation_runtime', 'run': 'pdf_translation_runtime', 'build_parser': 'pdf_translation_cli', 'main': 'pdf_translation_cli'}, ['run_pdf_translation_context', 'pdf_translation_paths', 'pdf_translation_text_repair', 'pdf_translation_commands', 'pdf_translation_latex_audit', 'pdf_translation_latex_render', 'pdf_translation_artifacts', 'pdf_translation_delivery', 'pdf_translation_latex_quality', 'pdf_translation_backend_quality', 'pdf_translation_tracking', 'pdf_translation_overrides', 'pdf_translation_render', 'pdf_translation_runtime', 'pdf_translation_cli'])

if __name__ == "__main__":
    raise SystemExit(main())
