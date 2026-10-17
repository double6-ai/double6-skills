# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""兼容入口；实现按职责拆分，公开函数名称与命令保持。"""
from __future__ import annotations
from visual_layout_context import *
from visual_layout_core import (
    pdf_identity,
    graphic_paint_profile,
    graphic_visibility_findings,
    normalize_lines,
    cjk_count,
    ascii_word_count,
    extract_key_texts,
    dominant_color_ratio,
    nonblack_color_ratio,
    bbox_overlap_ratio,
    bbox_overlap_area,
    is_code_placeholder_span_text,
    should_ignore_overlap_pair,
    count_overlapping_spans,
    total_overlapping_area,
    overlap_pair_samples,
    infer_failure_stage,
    infer_layout_role,
    infer_cause_category,
    infer_user_feedback_layout_role,
    normalize_user_visual_feedback,
    normalize_finding,
)
from visual_layout_structure import (
    has_toc_heading,
    looks_like_chapter_highlights_page,
    looks_like_toc_page,
    numeric_toc_lines,
    toc_page_numbers,
    parse_page_selection,
    directory_order_findings,
    directory_order_warnings,
    _local_bbox_center,
    has_near_acceptable_duplicate_span,
    small_font_stats,
    tiny_heading_spans,
)
from visual_layout_styles import (
    _visual_spans,
    _span_text,
    _span_size,
    _bbox_center,
    _select_spatially_matching_span,
    _is_regular_cjk_font,
    _is_cjk_body_font_for_mixed_latin,
    _is_toc_like_page,
    _is_source_heading_weighted,
    _heading_size_regressed,
    source_translated_heading_style_findings,
    extract_latin_person_names,
    source_translated_protected_name_findings,
    source_translated_chart_title_findings,
    chart_axis_label_malformed_findings,
    preview_region_pixel_stats,
    source_translated_publisher_badge_findings,
    source_translated_table_caption_findings,
    abstract_typography_findings,
)
from visual_layout_density import (
    text_density_stats,
    is_allowed_compact_label,
    is_neutral_compact_label,
    is_policy_passthrough_compact_label,
    is_ai_roster_page_text,
    is_ai_roster_page,
    compact_text_for_context,
    is_latextrans_placeholder_diagram_text,
    is_latextrans_embedded_case_figure_text,
    is_latextrans_visual_passthrough_page,
    compact_label_stats,
    is_dense_chart_or_index_page,
    analyze_visual_pages,
)
from visual_layout_extract import (
    _load_fitz,
    pdf_page_count,
    extract_pdf_full_text,
    infer_default_visual_check_pages,
    text_layer_health,
    page_text_layer_health,
    typography_profile,
    geometry_profile,
    block_role_profile,
    extract_pdf_pages,
    _clip_page_text_stats,
    _clip_pixel_stats,
    _page_region_metrics,
    build_full_document_coverage_report,
    extract_pdf_text_pages,
    reference_tail_from_explicit_heading,
    reference_body_text_for_translation_check,
)
from visual_layout_semantic import (
    semantic_layout_findings_for_pages,
    build_semantic_layout_report,
)
from visual_layout_reports import (
    build_dual_visual_report,
    build_paragraph_label_audit,
    build_visual_layout_report,
    main,
)

from legacy_module_api import bind_legacy_exports
bind_legacy_exports(globals(), {'pdf_identity': 'visual_layout_core', 'graphic_paint_profile': 'visual_layout_core', 'graphic_visibility_findings': 'visual_layout_core', 'normalize_lines': 'visual_layout_core', 'cjk_count': 'visual_layout_core', 'ascii_word_count': 'visual_layout_core', 'extract_key_texts': 'visual_layout_core', 'dominant_color_ratio': 'visual_layout_core', 'nonblack_color_ratio': 'visual_layout_core', 'bbox_overlap_ratio': 'visual_layout_core', 'bbox_overlap_area': 'visual_layout_core', 'is_code_placeholder_span_text': 'visual_layout_core', 'should_ignore_overlap_pair': 'visual_layout_core', 'count_overlapping_spans': 'visual_layout_core', 'total_overlapping_area': 'visual_layout_core', 'overlap_pair_samples': 'visual_layout_core', 'infer_failure_stage': 'visual_layout_core', 'infer_layout_role': 'visual_layout_core', 'infer_cause_category': 'visual_layout_core', 'infer_user_feedback_layout_role': 'visual_layout_core', 'normalize_user_visual_feedback': 'visual_layout_core', 'normalize_finding': 'visual_layout_core', 'has_toc_heading': 'visual_layout_structure', 'looks_like_chapter_highlights_page': 'visual_layout_structure', 'looks_like_toc_page': 'visual_layout_structure', 'numeric_toc_lines': 'visual_layout_structure', 'toc_page_numbers': 'visual_layout_structure', 'parse_page_selection': 'visual_layout_structure', 'directory_order_findings': 'visual_layout_structure', 'directory_order_warnings': 'visual_layout_structure', '_local_bbox_center': 'visual_layout_structure', 'has_near_acceptable_duplicate_span': 'visual_layout_structure', 'small_font_stats': 'visual_layout_structure', 'tiny_heading_spans': 'visual_layout_structure', '_visual_spans': 'visual_layout_styles', '_span_text': 'visual_layout_styles', '_span_size': 'visual_layout_styles', '_bbox_center': 'visual_layout_styles', '_select_spatially_matching_span': 'visual_layout_styles', '_is_regular_cjk_font': 'visual_layout_styles', '_is_cjk_body_font_for_mixed_latin': 'visual_layout_styles', '_is_toc_like_page': 'visual_layout_styles', '_is_source_heading_weighted': 'visual_layout_styles', '_heading_size_regressed': 'visual_layout_styles', 'source_translated_heading_style_findings': 'visual_layout_styles', 'extract_latin_person_names': 'visual_layout_styles', 'source_translated_protected_name_findings': 'visual_layout_styles', 'source_translated_chart_title_findings': 'visual_layout_styles', 'chart_axis_label_malformed_findings': 'visual_layout_styles', 'preview_region_pixel_stats': 'visual_layout_styles', 'source_translated_publisher_badge_findings': 'visual_layout_styles', 'source_translated_table_caption_findings': 'visual_layout_styles', 'abstract_typography_findings': 'visual_layout_styles', 'text_density_stats': 'visual_layout_density', 'is_allowed_compact_label': 'visual_layout_density', 'is_neutral_compact_label': 'visual_layout_density', 'is_policy_passthrough_compact_label': 'visual_layout_density', 'is_ai_roster_page_text': 'visual_layout_density', 'is_ai_roster_page': 'visual_layout_density', 'compact_text_for_context': 'visual_layout_density', 'is_latextrans_placeholder_diagram_text': 'visual_layout_density', 'is_latextrans_embedded_case_figure_text': 'visual_layout_density', 'is_latextrans_visual_passthrough_page': 'visual_layout_density', 'compact_label_stats': 'visual_layout_density', 'is_dense_chart_or_index_page': 'visual_layout_density', 'analyze_visual_pages': 'visual_layout_density', '_load_fitz': 'visual_layout_extract', 'pdf_page_count': 'visual_layout_extract', 'extract_pdf_full_text': 'visual_layout_extract', 'infer_default_visual_check_pages': 'visual_layout_extract', 'text_layer_health': 'visual_layout_extract', 'page_text_layer_health': 'visual_layout_extract', 'typography_profile': 'visual_layout_extract', 'geometry_profile': 'visual_layout_extract', 'block_role_profile': 'visual_layout_extract', 'extract_pdf_pages': 'visual_layout_extract', '_clip_page_text_stats': 'visual_layout_extract', '_clip_pixel_stats': 'visual_layout_extract', '_page_region_metrics': 'visual_layout_extract', 'build_full_document_coverage_report': 'visual_layout_extract', 'extract_pdf_text_pages': 'visual_layout_extract', 'reference_tail_from_explicit_heading': 'visual_layout_extract', 'reference_body_text_for_translation_check': 'visual_layout_extract', 'semantic_layout_findings_for_pages': 'visual_layout_semantic', 'build_semantic_layout_report': 'visual_layout_semantic', 'build_dual_visual_report': 'visual_layout_reports', 'build_paragraph_label_audit': 'visual_layout_reports', 'build_visual_layout_report': 'visual_layout_reports', 'main': 'visual_layout_reports'}, ['visual_layout_context', 'visual_layout_core', 'visual_layout_structure', 'visual_layout_styles', 'visual_layout_density', 'visual_layout_extract', 'visual_layout_semantic', 'visual_layout_reports'])

if __name__ == "__main__":
    raise SystemExit(main())
