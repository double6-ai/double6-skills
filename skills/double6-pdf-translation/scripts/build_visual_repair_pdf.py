# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""兼容入口；实现按职责拆分，公开函数名称与命令保持。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *
from repair_pdf_drawing import (
    load_json,
    normalize_text,
    ai_index_chart_label_repair_skip_reason,
    page_lines,
    expanded_rect,
    sampled_background_color,
    fit_textbox,
    fit_source_han_textbox,
    replace_rect,
    replace_rect_source_han,
    overlay_rect_source_han,
    replace_highlight_label,
    pdf_color_to_rgb,
    first_line_color,
    adjacent_background_color,
    copy_adjacent_background_region,
    cover_text_rect,
    draw_solid_cover,
    source_han_serif_fontname,
    source_han_sans_fontname,
    cjk_text_width,
    draw_cjk_text,
    insert_source_han_sans,
    insert_source_han_sans_fake_bold,
    insert_mixed_source_han_sans,
    insert_mixed_source_han_sans_fake_bold,
    insert_ai_figure_label_fake_bold,
    insert_ai_figure_label,
    split_numeric_prefix_label,
    mixed_source_han_sans_width,
    insert_source_han_serif,
    insert_source_han_serif_fake_bold,
    draw_cjk_linked_line,
    replace_cover_year_rect,
)
from repair_pdf_ai_frontmatter import (
    copy_source_region,
    repair_cover_year,
    repair_ai_cover_title_wrap,
    repair_ai_contents_page_labels,
    repair_ai_contents_title,
    insert_right_aligned_header_text,
    repair_ai_running_headers,
    repair_ai_index_cropped_patents_running_headers,
    repair_ai_page4_closing_and_signature,
    repair_ai_page9_acknowledgement_width,
)
from repair_pdf_ai_rosters import (
    cover_ai_roster_text,
    draw_ai_roster_label,
    draw_ai_roster_card,
    draw_ai_roster_card_multiline_name,
    copy_ai_roster_background,
    redraw_ai_page5_steering_roster_text,
    repair_ai_contributor_rosters,
    cover_sampled_rect,
    redraw_ai_contributor_list_heading,
    copy_ai_contributor_name_region,
    redraw_ai_contributor_body_lines,
    repair_ai_contributor_list_pages,
)
from repair_pdf_ai_links import (
    source_page_numbers,
    target_toc_number_rows,
    repair_ai_contents_page_numbers,
    mixed_font_runs,
    draw_text_run,
    text_run_length,
    draw_linked_sentence,
    repair_ai_footer_links,
    draw_ai_serif_segments,
    repair_ai_page6_citation_passthrough,
    repair_ai_page6_link_lines,
    repair_ai_page17_text_styles,
    repair_ai_page19_sector_heading_and_orphan,
)
from repair_pdf_ai_charts import (
    toc_row_translation,
    looks_like_toc_row,
    repair_toc_page,
    draw_toc_text,
    repair_ai_research_contents_page,
    repair_ai_chapter_highlights_title,
    copy_ai_chart_regions,
    repair_ai_chart_titles_after_passthrough,
    repair_ai_page17_chart_axis_labels_after_passthrough,
    tracking_chart_repairs,
    repair_visible_strings,
)
from repair_pdf_ai_chart_text import (
    repair_ai_index_chart_labels_from_text_layer,
)
from repair_pdf_ai_chart_geometry import (
    repair_ai_index_chart_labels_from_source_bboxes,
)
from repair_pdf_ai_technical import (
    repair_ai_index_author_panel_caption_fragments,
    repair_ai_index_mobility_panel_title_band,
    repair_ai_index_technical_performance_highlight_residue,
    repair_ai_index_technical_performance_toc_headings,
    repair_ai_index_technical_performance_section_headings,
)
from repair_pdf_ai_language import (
    repair_ai_index_language_section_visible_residue,
)
from repair_pdf_ai_responsible_tables import (
    _draw_ai_index_responsible_ai_cell,
    _redraw_ai_index_responsible_ai_headers,
    repair_ai_index_responsible_ai_dimension_tables,
    repair_ai_index_responsible_ai_benchmark_tables,
    repair_ai_index_responsible_ai_organization_view_chart_labels,
    repair_ai_index_responsible_ai_academia_chart_labels,
)
from repair_pdf_ai_responsible_policy import (
    repair_ai_index_responsible_ai_policy_making_visible_labels,
    repair_ai_index_responsible_ai_privacy_fairness_visible_labels,
)
from repair_pdf_ai_responsible_culture import (
    repair_ai_index_responsible_ai_cultural_language_gap_visible_labels,
    repair_ai_index_responsible_ai_transparency_visible_labels,
)
from repair_pdf_ai_responsible_security import (
    repair_ai_index_responsible_ai_security_safety_visible_labels,
    repair_ai_index_responsible_ai_security_safety_jailbreak_visible_labels,
)
from repair_pdf_ai_economy_overview import (
    repair_ai_index_economy_contents_visible_labels,
    repair_ai_index_economy_timeline_visible_labels,
)
from repair_pdf_ai_investment import (
    repair_ai_index_economy_investment_chart_visible_labels,
)
from repair_pdf_ai_adoption import (
    repair_ai_index_economy_corporate_ai_adoption_visible_labels,
)
from repair_pdf_ai_jobs import (
    repair_ai_index_economy_jobs_visible_labels,
)
from repair_pdf_ai_science import (
    repair_ai_index_science_visible_labels,
)
from repair_pdf_ai_medicine import (
    repair_ai_index_medicine_visible_labels,
)
from repair_pdf_ai_misc import (
    repair_ai_index_invalid_question_benchmark_chart,
    repair_ai_index_inference_paragraphs_from_text_layer,
    repair_ai_index_technological_proximity_body,
    repair_ai_missing_fixed_chart_labels,
)
from repair_pdf_nature import (
    repair_nature_header_footer,
    repair_nature_header_footer_passthrough,
    repair_nature_tables,
    _redact_with_fill,
    draw_fake_bold_text,
    draw_fake_bold_run,
    cover_heading_pixels,
    find_line_rect_by_text,
    draw_mixed_font_line,
    repair_nature_section_headings,
    repair_nature_page2_numbered_question_list,
    repair_nature_page13_publication_metadata,
    repair_nature_page13_backmatter_headings,
    repair_nature_page14_backmatter,
    draw_nature_inline_label_line,
    repair_nature_inline_bold_labels,
    repair_nature_page1_abstract,
    repair_nature_page1_title_wrap,
    repair_nature_page1_doi_open_passthrough,
    repair_nature_page1_publisher_badge_passthrough,
    repair_nature_page1_footer_rule_passthrough,
    repair_nature_table1_structured,
    repair_nature_table2_structured,
)
from repair_pdf_runtime import (
    build_visual_repair_pdf,
    build_parser,
    main,
)

from legacy_module_api import bind_legacy_exports
bind_legacy_exports(globals(), {'load_json': 'repair_pdf_drawing', 'normalize_text': 'repair_pdf_drawing', 'ai_index_chart_label_repair_skip_reason': 'repair_pdf_drawing', 'page_lines': 'repair_pdf_drawing', 'expanded_rect': 'repair_pdf_drawing', 'sampled_background_color': 'repair_pdf_drawing', 'fit_textbox': 'repair_pdf_drawing', 'fit_source_han_textbox': 'repair_pdf_drawing', 'replace_rect': 'repair_pdf_drawing', 'replace_rect_source_han': 'repair_pdf_drawing', 'overlay_rect_source_han': 'repair_pdf_drawing', 'replace_highlight_label': 'repair_pdf_drawing', 'pdf_color_to_rgb': 'repair_pdf_drawing', 'first_line_color': 'repair_pdf_drawing', 'adjacent_background_color': 'repair_pdf_drawing', 'copy_adjacent_background_region': 'repair_pdf_drawing', 'cover_text_rect': 'repair_pdf_drawing', 'draw_solid_cover': 'repair_pdf_drawing', 'source_han_serif_fontname': 'repair_pdf_drawing', 'source_han_sans_fontname': 'repair_pdf_drawing', 'cjk_text_width': 'repair_pdf_drawing', 'draw_cjk_text': 'repair_pdf_drawing', 'insert_source_han_sans': 'repair_pdf_drawing', 'insert_source_han_sans_fake_bold': 'repair_pdf_drawing', 'insert_mixed_source_han_sans': 'repair_pdf_drawing', 'insert_mixed_source_han_sans_fake_bold': 'repair_pdf_drawing', 'insert_ai_figure_label_fake_bold': 'repair_pdf_drawing', 'insert_ai_figure_label': 'repair_pdf_drawing', 'split_numeric_prefix_label': 'repair_pdf_drawing', 'mixed_source_han_sans_width': 'repair_pdf_drawing', 'insert_source_han_serif': 'repair_pdf_drawing', 'insert_source_han_serif_fake_bold': 'repair_pdf_drawing', 'draw_cjk_linked_line': 'repair_pdf_drawing', 'replace_cover_year_rect': 'repair_pdf_drawing', 'copy_source_region': 'repair_pdf_ai_frontmatter', 'repair_cover_year': 'repair_pdf_ai_frontmatter', 'repair_ai_cover_title_wrap': 'repair_pdf_ai_frontmatter', 'repair_ai_contents_page_labels': 'repair_pdf_ai_frontmatter', 'repair_ai_contents_title': 'repair_pdf_ai_frontmatter', 'insert_right_aligned_header_text': 'repair_pdf_ai_frontmatter', 'repair_ai_running_headers': 'repair_pdf_ai_frontmatter', 'repair_ai_index_cropped_patents_running_headers': 'repair_pdf_ai_frontmatter', 'repair_ai_page4_closing_and_signature': 'repair_pdf_ai_frontmatter', 'repair_ai_page9_acknowledgement_width': 'repair_pdf_ai_frontmatter', 'cover_ai_roster_text': 'repair_pdf_ai_rosters', 'draw_ai_roster_label': 'repair_pdf_ai_rosters', 'draw_ai_roster_card': 'repair_pdf_ai_rosters', 'draw_ai_roster_card_multiline_name': 'repair_pdf_ai_rosters', 'copy_ai_roster_background': 'repair_pdf_ai_rosters', 'redraw_ai_page5_steering_roster_text': 'repair_pdf_ai_rosters', 'repair_ai_contributor_rosters': 'repair_pdf_ai_rosters', 'cover_sampled_rect': 'repair_pdf_ai_rosters', 'redraw_ai_contributor_list_heading': 'repair_pdf_ai_rosters', 'copy_ai_contributor_name_region': 'repair_pdf_ai_rosters', 'redraw_ai_contributor_body_lines': 'repair_pdf_ai_rosters', 'repair_ai_contributor_list_pages': 'repair_pdf_ai_rosters', 'source_page_numbers': 'repair_pdf_ai_links', 'target_toc_number_rows': 'repair_pdf_ai_links', 'repair_ai_contents_page_numbers': 'repair_pdf_ai_links', 'mixed_font_runs': 'repair_pdf_ai_links', 'draw_text_run': 'repair_pdf_ai_links', 'text_run_length': 'repair_pdf_ai_links', 'draw_linked_sentence': 'repair_pdf_ai_links', 'repair_ai_footer_links': 'repair_pdf_ai_links', 'draw_ai_serif_segments': 'repair_pdf_ai_links', 'repair_ai_page6_citation_passthrough': 'repair_pdf_ai_links', 'repair_ai_page6_link_lines': 'repair_pdf_ai_links', 'repair_ai_page17_text_styles': 'repair_pdf_ai_links', 'repair_ai_page19_sector_heading_and_orphan': 'repair_pdf_ai_links', 'toc_row_translation': 'repair_pdf_ai_charts', 'looks_like_toc_row': 'repair_pdf_ai_charts', 'repair_toc_page': 'repair_pdf_ai_charts', 'draw_toc_text': 'repair_pdf_ai_charts', 'repair_ai_research_contents_page': 'repair_pdf_ai_charts', 'repair_ai_chapter_highlights_title': 'repair_pdf_ai_charts', 'copy_ai_chart_regions': 'repair_pdf_ai_charts', 'repair_ai_chart_titles_after_passthrough': 'repair_pdf_ai_charts', 'repair_ai_page17_chart_axis_labels_after_passthrough': 'repair_pdf_ai_charts', 'tracking_chart_repairs': 'repair_pdf_ai_charts', 'repair_visible_strings': 'repair_pdf_ai_charts', 'repair_ai_index_chart_labels_from_text_layer': 'repair_pdf_ai_chart_text', 'repair_ai_index_chart_labels_from_source_bboxes': 'repair_pdf_ai_chart_geometry', 'repair_ai_index_author_panel_caption_fragments': 'repair_pdf_ai_technical', 'repair_ai_index_mobility_panel_title_band': 'repair_pdf_ai_technical', 'repair_ai_index_technical_performance_highlight_residue': 'repair_pdf_ai_technical', 'repair_ai_index_technical_performance_toc_headings': 'repair_pdf_ai_technical', 'repair_ai_index_technical_performance_section_headings': 'repair_pdf_ai_technical', 'repair_ai_index_language_section_visible_residue': 'repair_pdf_ai_language', '_draw_ai_index_responsible_ai_cell': 'repair_pdf_ai_responsible_tables', '_redraw_ai_index_responsible_ai_headers': 'repair_pdf_ai_responsible_tables', 'repair_ai_index_responsible_ai_dimension_tables': 'repair_pdf_ai_responsible_tables', 'repair_ai_index_responsible_ai_benchmark_tables': 'repair_pdf_ai_responsible_tables', 'repair_ai_index_responsible_ai_organization_view_chart_labels': 'repair_pdf_ai_responsible_tables', 'repair_ai_index_responsible_ai_academia_chart_labels': 'repair_pdf_ai_responsible_tables', 'repair_ai_index_responsible_ai_policy_making_visible_labels': 'repair_pdf_ai_responsible_policy', 'repair_ai_index_responsible_ai_privacy_fairness_visible_labels': 'repair_pdf_ai_responsible_policy', 'repair_ai_index_responsible_ai_cultural_language_gap_visible_labels': 'repair_pdf_ai_responsible_culture', 'repair_ai_index_responsible_ai_transparency_visible_labels': 'repair_pdf_ai_responsible_culture', 'repair_ai_index_responsible_ai_security_safety_visible_labels': 'repair_pdf_ai_responsible_security', 'repair_ai_index_responsible_ai_security_safety_jailbreak_visible_labels': 'repair_pdf_ai_responsible_security', 'repair_ai_index_economy_contents_visible_labels': 'repair_pdf_ai_economy_overview', 'repair_ai_index_economy_timeline_visible_labels': 'repair_pdf_ai_economy_overview', 'repair_ai_index_economy_investment_chart_visible_labels': 'repair_pdf_ai_investment', 'repair_ai_index_economy_corporate_ai_adoption_visible_labels': 'repair_pdf_ai_adoption', 'repair_ai_index_economy_jobs_visible_labels': 'repair_pdf_ai_jobs', 'repair_ai_index_science_visible_labels': 'repair_pdf_ai_science', 'repair_ai_index_medicine_visible_labels': 'repair_pdf_ai_medicine', 'repair_ai_index_invalid_question_benchmark_chart': 'repair_pdf_ai_misc', 'repair_ai_index_inference_paragraphs_from_text_layer': 'repair_pdf_ai_misc', 'repair_ai_index_technological_proximity_body': 'repair_pdf_ai_misc', 'repair_ai_missing_fixed_chart_labels': 'repair_pdf_ai_misc', 'repair_nature_header_footer': 'repair_pdf_nature', 'repair_nature_header_footer_passthrough': 'repair_pdf_nature', 'repair_nature_tables': 'repair_pdf_nature', '_redact_with_fill': 'repair_pdf_nature', 'draw_fake_bold_text': 'repair_pdf_nature', 'draw_fake_bold_run': 'repair_pdf_nature', 'cover_heading_pixels': 'repair_pdf_nature', 'find_line_rect_by_text': 'repair_pdf_nature', 'draw_mixed_font_line': 'repair_pdf_nature', 'repair_nature_section_headings': 'repair_pdf_nature', 'repair_nature_page2_numbered_question_list': 'repair_pdf_nature', 'repair_nature_page13_publication_metadata': 'repair_pdf_nature', 'repair_nature_page13_backmatter_headings': 'repair_pdf_nature', 'repair_nature_page14_backmatter': 'repair_pdf_nature', 'draw_nature_inline_label_line': 'repair_pdf_nature', 'repair_nature_inline_bold_labels': 'repair_pdf_nature', 'repair_nature_page1_abstract': 'repair_pdf_nature', 'repair_nature_page1_title_wrap': 'repair_pdf_nature', 'repair_nature_page1_doi_open_passthrough': 'repair_pdf_nature', 'repair_nature_page1_publisher_badge_passthrough': 'repair_pdf_nature', 'repair_nature_page1_footer_rule_passthrough': 'repair_pdf_nature', 'repair_nature_table1_structured': 'repair_pdf_nature', 'repair_nature_table2_structured': 'repair_pdf_nature', 'build_visual_repair_pdf': 'repair_pdf_runtime', 'build_parser': 'repair_pdf_runtime', 'main': 'repair_pdf_runtime'}, ['build_visual_repair_pdf_context', 'repair_pdf_drawing', 'repair_pdf_ai_frontmatter', 'repair_pdf_ai_rosters', 'repair_pdf_ai_links', 'repair_pdf_ai_charts', 'repair_pdf_ai_chart_text', 'repair_pdf_ai_chart_geometry', 'repair_pdf_ai_technical', 'repair_pdf_ai_language', 'repair_pdf_ai_responsible_tables', 'repair_pdf_ai_responsible_policy', 'repair_pdf_ai_responsible_culture', 'repair_pdf_ai_responsible_security', 'repair_pdf_ai_economy_overview', 'repair_pdf_ai_investment', 'repair_pdf_ai_adoption', 'repair_pdf_ai_jobs', 'repair_pdf_ai_science', 'repair_pdf_ai_medicine', 'repair_pdf_ai_misc', 'repair_pdf_nature', 'repair_pdf_runtime', 'repair_pdf_ai_jobs_demand', 'repair_pdf_ai_jobs_talent', 'repair_pdf_ai_jobs_workforce', 'repair_pdf_ai_jobs_robotics'])

if __name__ == "__main__":
    raise SystemExit(main())
