# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""兼容入口；实现按职责拆分，公开函数名称与命令保持。"""
from __future__ import annotations
from scanned_raster.pipeline_context import *
from scanned_raster.pipeline_resources import (
    _sha256_bytes,
    _config_sha256,
    _polygon_bbox,
    _process_rss_gib,
    _check_memory_limit,
    render_page_png,
)
from scanned_raster.pipeline_ocr import (
    run_rapidocr_page,
    _rapidocr_geometry_fragments,
    _annotate_mineru_regions_with_rapidocr_geometry,
    _annotate_rapidocr_regions,
)
from scanned_raster.pipeline_ocr_groups import (
    _ends_terminal_punctuation,
    _join_ocr_group_text,
    _coalesce_rapidocr_line_fragments,
    _coalesce_rapidocr_paragraph_bands,
)
from scanned_raster.pipeline_translation import (
    _split_translation_for_regions,
    _selected_pages,
    _default_translate,
    _unwrap_latex_text_commands,
    _normalize_inline_math_for_text_layer,
    _normalize_structured_field_translation,
    _clip_rect_against_protected,
    _translate_regions,
)
from scanned_raster.pipeline_fonts import (
    _embedded_cjk_font,
    _font_name_values,
    _load_preferred_serif_font,
    _verify_embedded_font,
    _insert_fitted_textbox,
    _overbar_math_font_buffer,
    _insert_shaped_overbar_textbox,
    _insert_invisible_search_text,
)
from scanned_raster.pipeline_rendering import (
    _source_text_boxes,
    _destroke_page_image,
    _render_text_style,
    _sample_background_color,
    _readable_scanned_block,
    _render_translated_pdf,
)
from scanned_raster.pipeline_runtime import (
    _extract_text,
    _write_json,
    run_scanned_translation,
    _run_with_response_checkpoint,
    _render_isolated_writeback,
    _run_scanned_translation,
)

from legacy_module_api import bind_legacy_exports
bind_legacy_exports(globals(), {'_sha256_bytes': 'scanned_raster.pipeline_resources', '_config_sha256': 'scanned_raster.pipeline_resources', '_polygon_bbox': 'scanned_raster.pipeline_resources', '_process_rss_gib': 'scanned_raster.pipeline_resources', '_check_memory_limit': 'scanned_raster.pipeline_resources', 'render_page_png': 'scanned_raster.pipeline_resources', 'run_rapidocr_page': 'scanned_raster.pipeline_ocr', '_rapidocr_geometry_fragments': 'scanned_raster.pipeline_ocr', '_annotate_mineru_regions_with_rapidocr_geometry': 'scanned_raster.pipeline_ocr', '_annotate_rapidocr_regions': 'scanned_raster.pipeline_ocr', '_ends_terminal_punctuation': 'scanned_raster.pipeline_ocr_groups', '_join_ocr_group_text': 'scanned_raster.pipeline_ocr_groups', '_coalesce_rapidocr_line_fragments': 'scanned_raster.pipeline_ocr_groups', '_coalesce_rapidocr_paragraph_bands': 'scanned_raster.pipeline_ocr_groups', '_split_translation_for_regions': 'scanned_raster.pipeline_translation', '_selected_pages': 'scanned_raster.pipeline_translation', '_default_translate': 'scanned_raster.pipeline_translation', '_unwrap_latex_text_commands': 'scanned_raster.pipeline_translation', '_normalize_inline_math_for_text_layer': 'scanned_raster.pipeline_translation', '_normalize_structured_field_translation': 'scanned_raster.pipeline_translation', '_clip_rect_against_protected': 'scanned_raster.pipeline_translation', '_translate_regions': 'scanned_raster.pipeline_translation', '_embedded_cjk_font': 'scanned_raster.pipeline_fonts', '_font_name_values': 'scanned_raster.pipeline_fonts', '_load_preferred_serif_font': 'scanned_raster.pipeline_fonts', '_verify_embedded_font': 'scanned_raster.pipeline_fonts', '_insert_fitted_textbox': 'scanned_raster.pipeline_fonts', '_overbar_math_font_buffer': 'scanned_raster.pipeline_fonts', '_insert_shaped_overbar_textbox': 'scanned_raster.pipeline_fonts', '_insert_invisible_search_text': 'scanned_raster.pipeline_fonts', '_source_text_boxes': 'scanned_raster.pipeline_rendering', '_destroke_page_image': 'scanned_raster.pipeline_rendering', '_render_text_style': 'scanned_raster.pipeline_rendering', '_sample_background_color': 'scanned_raster.pipeline_rendering', '_readable_scanned_block': 'scanned_raster.pipeline_rendering', '_render_translated_pdf': 'scanned_raster.pipeline_rendering', '_extract_text': 'scanned_raster.pipeline_runtime', '_write_json': 'scanned_raster.pipeline_runtime', 'run_scanned_translation': 'scanned_raster.pipeline_runtime', '_run_with_response_checkpoint': 'scanned_raster.pipeline_runtime', '_render_isolated_writeback': 'scanned_raster.pipeline_runtime', '_run_scanned_translation': 'scanned_raster.pipeline_runtime'}, ['scanned_raster.pipeline_context', 'scanned_raster.pipeline_resources', 'scanned_raster.pipeline_ocr', 'scanned_raster.pipeline_ocr_groups', 'scanned_raster.pipeline_translation', 'scanned_raster.pipeline_fonts', 'scanned_raster.pipeline_rendering', 'scanned_raster.pipeline_runtime'])

SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "扫描渲染兼容API，由工作流及冻结试排入口调用。"
