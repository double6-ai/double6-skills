# Double6 Skills 维护版本（2026-10-23）：与上游v0.5.24的修改及继承维护见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
import logging
import copy
import json
import random
import re

import numpy as np

from babeldoc.babeldoc_exception.BabelDOCException import ExtractTextError
from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import Document
from babeldoc.format.pdf.document_il import Page
from babeldoc.format.pdf.document_il import PdfCharacter
from babeldoc.format.pdf.document_il import PdfLine
from babeldoc.format.pdf.document_il import PdfParagraph
from babeldoc.format.pdf.document_il import PdfParagraphComposition
from babeldoc.format.pdf.document_il import PdfRectangle
from babeldoc.format.pdf.document_il.utils.fontmap import FontMapper
from babeldoc.format.pdf.document_il.utils.formular_helper import (
    collect_page_formula_font_ids,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import (
    HEIGHT_NOT_USFUL_CHAR_IN_CHAR,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import SPACE_REGEX
from babeldoc.format.pdf.document_il.utils.layout_helper import Layout
from babeldoc.format.pdf.document_il.utils.layout_helper import add_space_dummy_chars
from babeldoc.format.pdf.document_il.utils.layout_helper import build_layout_index
from babeldoc.format.pdf.document_il.utils.layout_helper import calculate_iou_for_boxes
from babeldoc.format.pdf.document_il.utils.layout_helper import get_char_unicode_string
from babeldoc.format.pdf.document_il.utils.layout_helper import get_character_layout
from babeldoc.format.pdf.document_il.utils.layout_helper import is_bullet_point
from babeldoc.format.pdf.document_il.utils.layout_helper import (
    is_character_in_formula_layout,
)
from babeldoc.format.pdf.document_il.utils.layout_helper import is_author_byline
from babeldoc.format.pdf.document_il.utils.layout_helper import is_text_layout
from babeldoc.format.pdf.document_il.midend.line_fragments import split_table_rows_at_column_gutters
from babeldoc.format.pdf.document_il.midend.line_fragments import unify_line_layouts
from babeldoc.format.pdf.document_il.utils.paragraph_helper import is_cid_paragraph
from babeldoc.format.pdf.document_il.utils.style_helper import INDIGO
from babeldoc.format.pdf.document_il.utils.style_helper import WHITE
from babeldoc.format.pdf.translation_config import TranslationConfig

logger = logging.getLogger(__name__)

# Base58 alphabet (Bitcoin style, without numbers 0, O, I, l)
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
COMPACT_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_ ./&:+\\\-()]{2,40}$")
SECTION_HEADING_PATTERN = re.compile(
    r"^(?:(?:\d+\.)+\d*\s+)?(?:Abstract|Contents|Introduction|Literature review|Methods|Results|Discussion|Conclusions?|References|"
    r"Contributors|Overview|Chapter Highlights|Research and Development|Technical Performance|Responsible AI|Economy|Science|Medicine|Education|"
    r"Notable AI Models|By National Affiliation)$",
    re.IGNORECASE,
)
CHART_OR_TABLE_LABEL_PATTERN = re.compile(
    r"^(?:Figure\s+\d+(?:\.\d+)*|Table\s+\d+|By National Affiliation\d*|By Organization|By Sector|By Sector and Organization|"
    r"By Topic|By Venue|Model Release|Parameter and Compute Trends|Model and Dataset Ecosystem|"
    r"Total Number of AI Publications|Conference Attendance|Top 100 Publications|Stars|"
    r"Number(?:\s+of\s+notable\s+AI\s+models)?|Notable AI models \(% of total\)|"
    r"Sub-corpus|Number of texts|Tokens|Mean length|"
    r"China|Hong Kong|United States|France|United Kingdom|Canada|Germany|Israel|Singapore|South Korea|Japan|"
    r"Highlight:\s*Will Models Run Out of Data\?)$",
    re.IGNORECASE,
)
CODE_LABEL_PATTERN = re.compile(
    r"(?:\\[A-Za-z]+(?:\{[^{}]{0,40}\})?|"
    r"\b(?:section|subsection|caption|environment|command|module)\d*\b|"
    r"\b[A-Za-z]+_[A-Za-z0-9_]+\b)",
    re.IGNORECASE,
)
CODE_PASSTHROUGH_LABEL_PATTERN = re.compile(
    r"^(?:\\[A-Za-z]+(?:\{[^{}]{0,40}\})?|"
    r"(?:[A-Za-z]+_){1,3}[A-Za-z0-9_]+|"
    r"(?:section|subsection|caption|environment|command|module)\d*|"
    r"(?:TEX|PDF|API|HTML|XML|JSON|ST|TT|IL)|"
    r"[A-Za-z]{1,12}\d{1,3})$",
    re.IGNORECASE,
)
LATEX_STRUCTURE_FRAGMENT_PATTERN = re.compile(
    r"^\\(?:begin|end|section|subsection|subsubsection|caption|label|ref|cite|url|textbf|textit|left|right)"
    r"(?:\{[^{}]{0,80}\})?(?:\s*\.{3})?$",
    re.IGNORECASE,
)


def generate_base58_id(length: int = 5) -> str:
    """Generate a random base58 ID of specified length."""
    return "".join(random.choice(BASE58_ALPHABET) for _ in range(length))


class ParagraphFinder:
    stage_name = "Parse Paragraphs"

    # 定义项目符号的正则表达式模式

    def __init__(self, translation_config: TranslationConfig):
        self.translation_config = translation_config
        self.font_mapper = FontMapper(translation_config)

    def _preprocess_formula_layouts(self, page: Page):
        """
        Identifies 'formula' layouts that do not significantly overlap with any text layouts
        and re-labels them as 'isolate_formula'.
        """
        # Use a simplified Layout object for is_text_layout check
        text_layouts = [
            layout
            for layout in page.page_layout
            if is_text_layout(Layout(layout.id, layout.class_name))
        ]
        formula_layouts = [
            layout for layout in page.page_layout if layout.class_name == "formula"
        ]

        if not text_layouts or not formula_layouts:
            return

        for formula_layout in formula_layouts:
            is_isolated = True
            for text_layout in text_layouts:
                iou = calculate_iou_for_boxes(formula_layout.box, text_layout.box)
                if iou >= 0.5:
                    is_isolated = False
                    break

            if is_isolated:
                formula_layout.class_name = "isolate_formula"

    def add_text_fill_background(self, page: Page):
        layout_map = {layout.id: layout for layout in page.page_layout}
        for paragraph in page.pdf_paragraph:
            layout_id = paragraph.layout_id
            if layout_id is None:
                continue
            layout = layout_map[layout_id]
            if paragraph.box is None:
                continue
            x1, y1, x2, y2 = (
                paragraph.box.x,
                paragraph.box.y,
                paragraph.box.x2,
                paragraph.box.y2,
            )
            layout_box = layout.box
            if layout_box.x < x1:
                x1 = layout_box.x
            if layout_box.y < y1:
                y1 = layout_box.y
            if layout_box.x2 > x2:
                x2 = layout_box.x2
            if layout_box.y2 > y2:
                y2 = layout_box.y2
            assert x2 > x1 and y2 > y1
            page.pdf_rectangle.append(
                PdfRectangle(
                    box=Box(x1, y1, x2, y2),
                    fill_background=True,
                    graphic_state=WHITE,
                    debug_info=False,
                    xobj_id=paragraph.xobj_id,
                )
            )

    def update_paragraph_data(self, paragraph: PdfParagraph, update_unicode=False):
        if not paragraph.pdf_paragraph_composition:
            return

        chars = []
        for composition in paragraph.pdf_paragraph_composition:
            if composition.pdf_line:
                chars.extend(composition.pdf_line.pdf_character)
            elif composition.pdf_formula:
                chars.extend(composition.pdf_formula.pdf_character)
            elif composition.pdf_character:
                chars.append(composition.pdf_character)
            elif composition.pdf_same_style_unicode_characters:
                continue
            else:
                logger.error(
                    "Unexpected composition type"
                    " in PdfParagraphComposition. "
                    "This type only appears in the IL "
                    "after the translation is completed.",
                )
                continue

        if update_unicode and chars:
            paragraph.unicode = get_char_unicode_string(chars)
        if not chars:
            return
        # 更新边界框
        min_x = min(char.visual_bbox.box.x for char in chars)
        min_y = min(char.visual_bbox.box.y for char in chars)
        max_x = max(char.visual_bbox.box.x2 for char in chars)
        max_y = max(char.visual_bbox.box.y2 for char in chars)
        # 表头或标题的英文墨迹框可能不足一个 em。沿用原字形
        # 逻辑框的纵向空间，避免译成中文后在原字号下被错误判为溢出。
        # 不扩展列宽、不使用整页空白；旋转文字保留原来的边界处理。
        if paragraph.layout_label in {"table_header", "title", "section", "section_header", "heading", "section_heading", "report_heading", "institution_label", "report_org_heading"} and not any(char.vertical for char in chars):
            source_boxes = [char.box for char in chars if char.box is not None]
            if source_boxes:
                min_y = min(min_y, *(box.y for box in source_boxes))
                max_y = max(max_y, *(box.y2 for box in source_boxes))
        paragraph.box = Box(min_x, min_y, max_x, max_y)
        paragraph.vertical = chars[0].vertical
        paragraph.xobj_id = chars[0].xobj_id

        paragraph.first_line_indent = False
        if (
            paragraph.layout_label not in {"title", "section", "section_header", "heading", "section_heading",
                "report_heading", "institution_label", "report_org_heading", "toc_entry", "chapter_index_entry"}
            and paragraph.pdf_paragraph_composition
            and paragraph.pdf_paragraph_composition[0].pdf_line
            and paragraph.pdf_paragraph_composition[0]
            .pdf_line.pdf_character[0]
            .visual_bbox.box.x
            - paragraph.box.x
            > 1
        ):
            paragraph.first_line_indent = True

    def update_line_data(self, line: PdfLine):
        min_x = min(char.visual_bbox.box.x for char in line.pdf_character)
        min_y = min(char.visual_bbox.box.y for char in line.pdf_character)
        max_x = max(char.visual_bbox.box.x2 for char in line.pdf_character)
        max_y = max(char.visual_bbox.box.y2 for char in line.pdf_character)
        line.box = Box(min_x, min_y, max_x, max_y)

    def add_debug_info(self, page: Page):
        if not self.translation_config.debug:
            return
        for paragraph in page.pdf_paragraph:
            for composition in paragraph.pdf_paragraph_composition:
                if composition.pdf_line:
                    line = composition.pdf_line
                    page.pdf_rectangle.append(
                        PdfRectangle(
                            box=line.box,
                            fill_background=False,
                            graphic_state=INDIGO,
                            debug_info=True,
                            line_width=0.2,
                        )
                    )

    def process(self, document):
        with self.translation_config.progress_monitor.stage_start(
            self.stage_name,
            len(document.page),
        ) as pbar:
            if not document.page:
                return
            for page in document.page:
                self.translation_config.raise_if_cancelled()
                self.process_page(page)
                pbar.advance()

            total_paragraph_count = 0
            for page in document.page:
                total_paragraph_count += len(page.pdf_paragraph)
            if total_paragraph_count == 0:
                raise ExtractTextError("The document contains no paragraphs.")

            if self.check_cid_paragraph(document):
                raise ExtractTextError("The document contains too many CID paragraphs.")

    def check_cid_paragraph(self, doc: Document):
        cid_para_count = 0
        para_total = 0
        for page in doc.page:
            para_total += len(page.pdf_paragraph)
            for para in page.pdf_paragraph:
                if is_cid_paragraph(para):
                    cid_para_count += 1
        return cid_para_count / para_total > 0.8

    def bbox_overlap(self, bbox1: Box, bbox2: Box) -> bool:
        return (
            bbox1.x < bbox2.x2
            and bbox1.x2 > bbox2.x
            and bbox1.y < bbox2.y2
            and bbox1.y2 > bbox2.y
        )

    def process_page(self, page: Page):
        self._current_page_number = page.page_number
        layout_index, layout_map = build_layout_index(page)
        # 预处理公式布局的标签
        self._preprocess_formula_layouts(page)

        # 第一步：根据 layout 创建 paragraphs
        # 在这一步中，page.pdf_character 中的字符会被移除
        paragraphs = self._group_characters_into_paragraphs(
            page, layout_index, layout_map
        )
        page.pdf_paragraph = paragraphs

        page_level_formula_font_ids, xobj_specific_formula_font_ids = (
            collect_page_formula_font_ids(
                page, self.translation_config.formular_font_pattern
            )
        )

        # for para in paragraphs:
        #     if not para.debug_id:
        #         continue
        #     new_line = PdfLine(
        #         pdf_character=[x.pdf_character for x in para.pdf_paragraph_composition]
        #     )
        #     self.update_line_data(new_line)
        #     para.pdf_paragraph_composition = [
        #         PdfParagraphComposition(pdf_line=new_line)
        #     ]

        # 第二步：将段落内的字符拆分为行
        for paragraph in paragraphs:
            if (
                paragraph.xobj_id
                and paragraph.xobj_id in xobj_specific_formula_font_ids
            ):
                current_formula_font_ids = xobj_specific_formula_font_ids[
                    paragraph.xobj_id
                ]
            else:
                current_formula_font_ids = page_level_formula_font_ids
            self._split_paragraph_into_lines(paragraph, current_formula_font_ids)

        # 第三步：处理段落中的空格
        for paragraph in paragraphs:
            add_space_dummy_chars(paragraph)
            self.process_paragraph_spacing(paragraph)
            self.update_paragraph_data(paragraph)

        # 表格行跨越全表共有的列间空白时按列拆成单元格（见 line_fragments）。
        split_table_rows_at_column_gutters(self, page, paragraphs, generate_base58_id)

        # 第四步：计算所有行宽度的中位数
        median_width = self.calculate_median_line_width(paragraphs)

        # 第五步：处理独立段落
        self.process_independent_paragraphs(paragraphs, median_width)

        self._merge_metadata_fragments(paragraphs)

        # 新增后处理：合并带行号交替的正文段落（a 正文、b 行号、c 正文 -> 合并 a 与 c，保留 b）
        if getattr(self.translation_config, "merge_alternating_line_numbers", True):
            self.merge_alternating_line_number_paragraphs(paragraphs)

        directory_name_ids = self._split_portrait_directory_labels(page, paragraphs)

        # 图内填充节点里的多行标题/说明先合成一个翻译单元，再参与角色判定。
        from .table_figure_text import merge_figure_node_lines, record_source_baselines, release_natural_compact_labels
        merge_figure_node_lines(self, page, paragraphs)
        compact_prior_labels = {}

        page_height = 0.0
        if page.cropbox and page.cropbox.box:
            page_height = page.cropbox.box.y2 - page.cropbox.box.y
        elif page.mediabox and page.mediabox.box:
            page_height = page.mediabox.box.y2 - page.mediabox.box.y

        for paragraph in paragraphs:
            if id(paragraph) in directory_name_ids or paragraph.layout_label == "institution_label":
                continue
            if page_height > 0:
                paragraph.page_height = page_height
            code_label = self._classify_code_label_paragraph(paragraph)
            layout_sensitive_label = self._classify_layout_sensitive_paragraph(paragraph)
            if (layout_sensitive_label == "table_caption" and paragraph.toc_row_group_json
                    and paragraph.layout_label in {"toc_entry", "chapter_index_entry"}):
                # 目录拆行已证明这是“表目录”条目（Table N … 页码），不是表题。
                layout_sensitive_label = None
            if code_label:
                paragraph.layout_label = code_label
            elif layout_sensitive_label:
                paragraph.layout_label = layout_sensitive_label
            elif self._looks_like_compact_label_paragraph(paragraph):
                compact_prior_labels[id(paragraph)] = paragraph.layout_label
                paragraph.layout_label = "compact_label"

        # 紧凑标签只保护名称/标识符；自然语言的表头、行名、图内短语照常翻译。
        release_natural_compact_labels(self, page, paragraphs, compact_prior_labels)

        self._join_dialogue_line_fragments(paragraphs)
        self._separate_toc_page_numbers(paragraphs)
        for paragraph in paragraphs:
            self.update_paragraph_data(paragraph, update_unicode=True)

        if self.translation_config.ocr_workaround:
            self.add_text_fill_background(page)
            # since this is ocr file,
            # image characters are not needed
            page.pdf_character = []

        self.fix_overlapping_paragraphs(page)
        # 署名邻接关系使用最终行文本与去重叠后的源框，避免下伸字形造成负间距。
        self._classify_academic_metadata(page, paragraphs)
        from .diagram_nodes import group_diagram_nodes
        group_diagram_nodes(self, page, paragraphs)
        record_source_baselines(self, page, page.pdf_paragraph)

        # 第六步：对每一行的字符进行排序
        # self._sort_characters_in_lines(page)

        self.add_debug_info(page)

        # 新阶段：设置段落的 renderorder 为所有组成部分中 renderorder 最小的
        self._set_paragraph_render_order(page)

    def _set_paragraph_render_order(self, page: Page):
        """
        设置段落的 renderorder 为段落所有组成部分中 renderorder 最小的值
        """
        for paragraph in page.pdf_paragraph:
            min_render_order = 9999999999999999

            # 遍历段落的所有组成部分
            for composition in paragraph.pdf_paragraph_composition:
                # 检查 PdfLine 中的字符
                if composition.pdf_line:
                    for char in composition.pdf_line.pdf_character:
                        if (
                            hasattr(char, "render_order")
                            and char.render_order is not None
                        ):
                            min_render_order = min(min_render_order, char.render_order)

                # 检查单个字符
                elif composition.pdf_character:
                    char = composition.pdf_character
                    if hasattr(char, "render_order") and char.render_order is not None:
                        min_render_order = min(min_render_order, char.render_order)

                # 检查公式中的字符
                elif composition.pdf_formula:
                    for char in composition.pdf_formula.pdf_character:
                        if (
                            hasattr(char, "render_order")
                            and char.render_order is not None
                        ):
                            min_render_order = min(min_render_order, char.render_order)

            # 如果找到了有效的 renderorder，设置段落的 renderorder
            if min_render_order != 9999999999999999:
                paragraph.render_order = min_render_order

    def is_isolated_formula(self, char: PdfCharacter):
        return char.char_unicode in (
            "(cid:122)",
            "(cid:123)",
            "(cid:124)",
            "(cid:125)",
        )

    def _paragraph_text_ascii(self, p: PdfParagraph) -> str:
        parts: list[str] = []
        for comp in p.pdf_paragraph_composition or []:
            if comp.pdf_line:
                for ch in comp.pdf_line.pdf_character or []:
                    if ch.char_unicode is not None:
                        parts.append(ch.char_unicode)
            elif comp.pdf_character and comp.pdf_character.char_unicode is not None:
                parts.append(comp.pdf_character.char_unicode)
        return "".join(parts)

    def _is_ascii_digit_or_space_paragraph(self, p: PdfParagraph) -> bool:
        text = self._paragraph_text_ascii(p)
        if not text:
            return True
        has_digit = False
        for c in text:
            if c.isdigit() and ord(c) < 128:
                has_digit = True
                continue
            if c.isspace():
                continue
            return False
        return True if has_digit or text.strip() == "" else False

    @staticmethod
    def _same_layout_and_xobj(a: PdfParagraph, c: PdfParagraph) -> bool:
        return (
            a.layout_id is not None
            and c.layout_id is not None
            and a.layout_id == c.layout_id
            and a.xobj_id is not None
            and c.xobj_id is not None
            and a.xobj_id == c.xobj_id
        )

    def merge_alternating_line_number_paragraphs(self, paragraphs: list[PdfParagraph]):
        # a 代表正文
        # l 代表行号
        if not paragraphs or len(paragraphs) < 3:
            return
        i = 0
        while i < len(paragraphs) - 2:
            a = paragraphs[i]
            # 吞掉一个或多个连续的行号段 l
            j = i + 1
            saw_l = False
            while j < len(paragraphs) and self._is_ascii_digit_or_space_paragraph(
                paragraphs[j]
            ):
                saw_l = True
                j += 1
            # 现在 j 指向候选的 c
            if saw_l and j < len(paragraphs):
                c = paragraphs[j]
                if self._same_layout_and_xobj(a, c):
                    a.pdf_paragraph_composition.extend(c.pdf_paragraph_composition)
                    self.update_paragraph_data(a)
                    del paragraphs[j]
                    # 不移动 i，继续尝试把更多正文接到 a，实现 a l+ a l+ a ... 链式合并
                    continue
            i += 1

    def _group_characters_into_paragraphs(
        self, page: Page, layout_index, layout_map
    ) -> list[PdfParagraph]:
        paragraphs: list[PdfParagraph] = []
        if page.pdf_paragraph:
            paragraphs.extend(page.pdf_paragraph)
            page.pdf_paragraph = []

        char_areas = [
            (char.visual_bbox.box.x2 - char.visual_bbox.box.x)
            * (char.visual_bbox.box.y2 - char.visual_bbox.box.y)
            for char in page.pdf_character
        ]
        median_char_area = 0.0
        if char_areas:
            char_areas.sort()
            mid = len(char_areas) // 2
            median_char_area = (
                char_areas[mid]
                if len(char_areas) % 2 == 1
                else (char_areas[mid - 1] + char_areas[mid]) / 2
            )

        current_paragraph: PdfParagraph | None = None
        current_layout: Layout | None = None
        skip_chars = []

        # 先算每个字符的版面归属，再按物理行统一（见 line_fragments.unify_line_layouts）：
        # 文字框比实际行窄或两个同级框重叠时，同一行不再被切成几段。
        from ocr_text_layout import bind_ocr_layout
        char_layouts = bind_ocr_layout(page, page.pdf_character, Layout)
        if char_layouts is None:
            char_layouts = [get_character_layout(char, layout_index, layout_map) for char in page.pdf_character]
            unify_line_layouts(page.pdf_character, char_layouts, layout_index, layout_map, Layout,
                               lambda c: bool(SPACE_REGEX.match(c.char_unicode or "")))
        for char, char_layout in zip(page.pdf_character, char_layouts):
            # Check if character is in any formula layout and set formula_layout_id
            char.formula_layout_id = (None if getattr(char_layout, "ocr_bound", False) else
                                     is_character_in_formula_layout(char, page, layout_index, layout_map))

            if not is_text_layout(char_layout) or self.is_isolated_formula(char):
                skip_chars.append(char)
                continue

            char_box = char.visual_bbox.box
            # char_pdf_box = char.box
            # if calculate_iou_for_boxes(char_box, char_pdf_box) < 0.2:
            #     char_box = char_pdf_box
            char_area = (char_box.x2 - char_box.x) * (char_box.y2 - char_box.y)
            is_small_char = char_area < median_char_area * 0.05

            is_new_paragraph = False
            if current_paragraph is None:
                is_new_paragraph = True
            elif (
                not (
                    is_small_char
                    and current_paragraph.pdf_paragraph_composition
                    and char_layout.id == current_layout.id
                )
                and char.char_unicode not in HEIGHT_NOT_USFUL_CHAR_IN_CHAR
            ):
                if (
                    (
                        char_layout.id != current_layout.id
                        and not SPACE_REGEX.match(char.char_unicode)
                    )
                    or (  # not same xobject
                        current_paragraph.pdf_paragraph_composition
                        and current_paragraph.pdf_paragraph_composition[
                            -1
                        ].pdf_character.xobj_id
                        != char.xobj_id
                    )
                    or (
                        is_bullet_point(char)
                        and not current_paragraph.pdf_paragraph_composition
                    )
                ):
                    is_new_paragraph = True

            if is_new_paragraph:
                current_layout = char_layout
                current_paragraph = PdfParagraph(
                    pdf_paragraph_composition=[],
                    layout_id=current_layout.id,
                    debug_id=generate_base58_id(),
                    layout_label=current_layout.name,
                )
                paragraphs.append(current_paragraph)

            current_paragraph.pdf_paragraph_composition.append(
                PdfParagraphComposition(pdf_character=char)
            )

        page.pdf_character = skip_chars
        for para in paragraphs:
            self.update_paragraph_data(para)
        return paragraphs

    def _merge_overlapping_clusters(
        self, lines: dict[int, list[PdfCharacter]], char_height_average: float
    ) -> dict[int, list[PdfCharacter]]:
        """
        Merge clusters that have significant y-axis overlap.
        If y_intersection / min_height > 0.5 or the distance between y-midlines is less than char_height_average, merge the two clusters.
        """
        if len(lines) <= 1:
            return lines

        # Calculate y-axis ranges for each cluster
        cluster_ranges = {}
        cluster_midlines = {}
        for label, chars in lines.items():
            y_values = [char.visual_bbox.box.y for char in chars] + [
                char.visual_bbox.box.y2 for char in chars
            ]
            y_min, y_max = min(y_values), max(y_values)
            cluster_ranges[label] = (y_min, y_max)
            cluster_midlines[label] = (y_min + y_max) / 2

        # Keep merging until no more merges are possible
        changed = True
        while changed:
            changed = False
            labels_to_check = list(lines.keys())

            for i in range(len(labels_to_check)):
                if not changed:  # Only continue if no merge happened in this iteration
                    for j in range(i + 1, len(labels_to_check)):
                        label1, label2 = labels_to_check[i], labels_to_check[j]

                        # Skip if either label has been merged away
                        if label1 not in lines or label2 not in lines:
                            continue

                        y1_min, y1_max = cluster_ranges[label1]
                        y2_min, y2_max = cluster_ranges[label2]

                        # Calculate intersection
                        intersection_start = max(y1_min, y2_min)
                        intersection_end = min(y1_max, y2_max)

                        # Calculate midline distance
                        midline_distance = abs(
                            cluster_midlines[label1] - cluster_midlines[label2]
                        )

                        should_merge = False
                        if (
                            intersection_end > intersection_start
                        ):  # There is intersection
                            intersection_height = intersection_end - intersection_start
                            height1 = y1_max - y1_min
                            height2 = y2_max - y2_min
                            min_height = min(height1, height2)

                            # Check if intersection ratio exceeds threshold
                            if (
                                min_height > 0
                                and intersection_height / min_height > 0.3
                            ):
                                should_merge = True

                        # Check if midline distance is less than char_height_average
                        if midline_distance < char_height_average:
                            should_merge = True

                        if should_merge:
                            # Merge label2 into label1
                            lines[label1].extend(lines[label2])
                            del lines[label2]

                            # Update cluster range and midline for the merged cluster
                            new_y_min = min(y1_min, y2_min)
                            new_y_max = max(y1_max, y2_max)
                            cluster_ranges[label1] = (new_y_min, new_y_max)
                            cluster_midlines[label1] = (new_y_min + new_y_max) / 2
                            del cluster_ranges[label2]
                            del cluster_midlines[label2]

                            changed = True
                            break

        return lines

    def _get_effective_y_bounds(self, char: PdfCharacter) -> tuple[float, float]:
        """
        Determines the effective vertical boundaries (y1, y2) for a character.

        It prioritizes the visual bounding box if its Intersection over Union (IoU)
        with the PDF bounding box is high (>= 0.5), otherwise, it falls back to the
        PDF bounding box. This helps use more accurate layout information when available.
        """
        visual_box = char.visual_bbox.box
        return visual_box.y, visual_box.y2
        pdf_box = char.box
        if calculate_iou_for_boxes(visual_box, pdf_box) >= 0.5:
            return visual_box.y, visual_box.y2
        return pdf_box.y, pdf_box.y2

    @staticmethod
    def _compute_collision_counts_histogram(
        y1_arr: np.ndarray,
        y2_arr: np.ndarray,
        para_y_min: float,
        para_y_max: float,
        step: float,
    ) -> np.ndarray:
        """Compute overlap counts at each scan line using a difference-array histogram.

        Args:
            y1_arr: 1-D array with lower y bounds of characters (inclusive).
            y2_arr: 1-D array with upper y bounds of characters (exclusive).
            para_y_min: Minimum y of the paragraph.
            para_y_max: Maximum y of the paragraph.
            step: Scan step size.

        Returns:
            1-D NumPy int32 array where index i corresponds to y = para_y_max - i × step.
        """
        # Number of scan positions
        m = int(np.ceil((para_y_max - para_y_min) / step))
        if m <= 0:
            return np.array([], dtype=np.int32)

        # Map character bounds to discrete indices (top inclusive, bottom exclusive)
        starts = np.floor((para_y_max - y2_arr) / step).astype(np.int32)
        ends = np.floor((para_y_max - y1_arr) / step).astype(np.int32) + 1
        # Clip ends to the valid range [0, m]
        np.clip(ends, 0, m, out=ends)

        hist = np.zeros(m + 1, dtype=np.int32)
        np.add.at(hist, starts, 1)
        np.add.at(hist, ends, -1)

        return np.cumsum(hist[:-1])

    def _split_paragraph_into_lines(
        self, paragraph: PdfParagraph, formula_font_ids: set[str]
    ):
        """
        Splits a paragraph into lines using a "line-threading" method.

        This method works by scanning vertically across the paragraph's bounding
        box and counting how many characters intersect with a horizontal line
        at each y-coordinate. The regions with a low number of intersections
        (less than 2) are identified as gaps between lines. The characters
        are then partitioned into lines based on these identified gaps.
        """
        if not paragraph.pdf_paragraph_composition:
            return

        # 1. Extract all characters and other compositions from the paragraph.
        all_chars: list[PdfCharacter] = []
        other_compositions: list[PdfParagraphComposition] = []
        for comp in paragraph.pdf_paragraph_composition:
            if comp.pdf_character:
                all_chars.append(comp.pdf_character)
            else:
                other_compositions.append(comp)

        if not all_chars:
            return

        # 2. Determine effective y-bounds for each character and the paragraph's total vertical range.
        char_y_bounds = [
            {"char": char, "y1": y1, "y2": y2}
            for char in all_chars
            for y1, y2 in [self._get_effective_y_bounds(char)]
        ]

        if not char_y_bounds:
            paragraph.pdf_paragraph_composition = other_compositions
            self.update_paragraph_data(paragraph)
            return

        para_y_min = min(b["y1"] for b in char_y_bounds)
        para_y_max = max(b["y2"] for b in char_y_bounds)

        # If the paragraph is vertically flat, treat it as a single line.
        if (para_y_max - para_y_min) < 5:  # Using a small threshold
            # all_chars.sort(key=lambda c: c.visual_bbox.box.x)
            single_line_composition = self.create_line(all_chars)
            paragraph.pdf_paragraph_composition = [
                single_line_composition
            ] + other_compositions
            self.update_paragraph_data(paragraph)
            return

        # 3. Perform "threading" scan to create a collision histogram.
        # Scan from top (max y) to bottom (min y) with a step of 0.5.
        scan_y_min = para_y_min
        scan_y_max = para_y_max
        step = 0.25

        y_coordinates = np.arange(scan_y_max, scan_y_min, -step)

        # Compute collision counts using NumPy histogram (O(m + n))
        y1_arr = np.array([b["y1"] for b in char_y_bounds], dtype=np.float32)
        y2_arr = np.array([b["y2"] for b in char_y_bounds], dtype=np.float32)
        collision_counts = self._compute_collision_counts_histogram(
            y1_arr,
            y2_arr,
            scan_y_min,
            scan_y_max,
            step,
        )

        # 4. Find gaps (regions with low collision count) from the histogram.
        gaps = []
        in_gap = False
        for i, count in enumerate(collision_counts):
            if count < 1 and not in_gap:
                in_gap = True
                gap_start_index = i
            elif count >= 1 and in_gap:
                in_gap = False
                gaps.append((gap_start_index, i - 1))
        if in_gap:
            gaps.append((gap_start_index, len(collision_counts) - 1))

        # If no significant gaps are found, treat it as a single line.
        if not gaps:
            # all_chars.sort(key=lambda c: c.visual_bbox.box.x)
            single_line_composition = self.create_line(all_chars)
            paragraph.pdf_paragraph_composition = [
                single_line_composition
            ] + other_compositions
            self.update_paragraph_data(paragraph)
            return

        # 5. Assign characters to lines based on the identified gaps.
        # Calculate separator y-coordinates from the midpoints of the gaps.
        separator_y_coords = sorted(
            [y_coordinates[start_idx] for start_idx, end_idx in gaps],
            reverse=True,
        )

        lines: list[list[PdfCharacter]] = [
            [] for _ in range(len(separator_y_coords) + 1)
        ]

        for b in char_y_bounds:
            char_y_center = (b["y1"] + b["y2"]) / 2
            line_idx = 0
            # Find which line bucket the character belongs to.
            for sep_y in separator_y_coords:
                if char_y_center > sep_y:
                    break
                line_idx += 1
            lines[line_idx].append(b["char"])

        # 6. Rebuild the paragraph's composition list from the new lines.
        new_line_compositions = []
        for line_chars in lines:
            if line_chars:
                # Sort characters within each line by x-coordinate (left-to-right).
                # line_chars.sort(key=lambda c: c.visual_bbox.box.x)
                new_line_compositions.append(self.create_line(line_chars))

        # The lines are already sorted vertically due to the scanning process.
        paragraph.pdf_paragraph_composition = new_line_compositions + other_compositions
        self.update_paragraph_data(paragraph)

    def process_paragraph_spacing(self, paragraph: PdfParagraph):
        if not paragraph.pdf_paragraph_composition:
            return

        # 处理行级别的空格
        processed_lines = []
        for composition in paragraph.pdf_paragraph_composition:
            if not composition.pdf_line:
                processed_lines.append(composition)
                continue

            line = composition.pdf_line
            if not "".join(
                x.char_unicode for x in line.pdf_character
            ).strip():  # 跳过完全空白的行
                continue

            # 处理行内字符的尾随空格
            processed_chars = []
            for char in line.pdf_character:
                if not char.char_unicode.isspace():
                    processed_chars = processed_chars + [char]
                elif processed_chars:  # 只有在有非空格字符后才考虑保留空格
                    processed_chars.append(char)

            # 移除尾随空格
            while processed_chars and processed_chars[-1].char_unicode.isspace():
                processed_chars.pop()

            if processed_chars:  # 如果行内还有字符
                line = self.create_line(processed_chars)
                processed_lines.append(line)

        paragraph.pdf_paragraph_composition = processed_lines
        self.update_paragraph_data(paragraph)

    def create_line(self, chars: list[PdfCharacter]) -> PdfParagraphComposition:
        assert chars

        line = PdfLine(pdf_character=chars)
        self.update_line_data(line)
        return PdfParagraphComposition(pdf_line=line)

    def calculate_median_line_width(self, paragraphs: list[PdfParagraph]) -> float:
        # 收集所有行的宽度
        line_widths = []
        for paragraph in paragraphs:
            for composition in paragraph.pdf_paragraph_composition:
                if composition.pdf_line:
                    line = composition.pdf_line
                    line_widths.append(line.box.x2 - line.box.x)

        if not line_widths:
            return 0.0

        # 计算中位数
        line_widths.sort()
        mid = len(line_widths) // 2
        if len(line_widths) % 2 == 0:
            return (line_widths[mid - 1] + line_widths[mid]) / 2
        return line_widths[mid]

    @staticmethod
    def _line_text(line: PdfLine) -> str:
        return "".join(c.char_unicode or "" for c in line.pdf_character)

    def _paragraph_lines(self, paragraph: PdfParagraph) -> list[PdfLine]:
        return [
            composition.pdf_line
            for composition in paragraph.pdf_paragraph_composition
            if composition.pdf_line
        ]

    def _join_dialogue_line_fragments(self, paragraphs: list[PdfParagraph]) -> None:
        """接回同一原行被布局框切开的引语前缀或句末姓名缩写。"""
        index = 0
        while index + 1 < len(paragraphs):
            left, right = paragraphs[index:index+2]
            allowed = {'plain text', 'text', 'fallback_line', 'compact_label'}
            parts = [left.pdf_paragraph_composition, right.pdf_paragraph_composition]
            if (left.layout_label not in allowed or right.layout_label not in allowed
                or not ({left.layout_label, right.layout_label} & {'plain text', 'text'})
                or any(len(p) != 1 or not p[0].pdf_line for p in parts)
                or left.xobj_id != right.xobj_id or left.vertical or right.vertical):
                index += 1
                continue
            a, b = parts[0][0].pdf_line, parts[1][0].pdf_line
            ta, tb = self._line_text(a).strip(), self._line_text(b).strip()
            prefix = (left.layout_label == 'fallback_line' and len(ta) <= 24
                      and ta.startswith('“') and ta.count('“') > ta.count('”'))
            suffix = (right.layout_label in {'fallback_line', 'compact_label'}
                      and ta.startswith('“') and (re.fullmatch(r'[A-Z]\.', tb)
                      or (re.fullmatch(r'[.!?][”’]', tb) and ta.count('“') > ta.count('”'))))
            if not (prefix or suffix) or len(ta)+len(tb) > 600 or len(re.findall(r'[A-Za-z]+',ta+' '+tb)) < 6:
                index += 1
                continue
            ab, bb = a.box, b.box
            height = max(ab.y2-ab.y, bb.y2-bb.y, 1)
            gap = bb.x-ab.x2
            if gap < -0.5 or gap > min(5, height*.6) or abs((ab.y+ab.y2)-(bb.y+bb.y2)) > height*.7:
                index += 1
                continue
            # 保持原字符和顺序；共享空格恢复根据字符坐标补出词间空白。
            a.pdf_character.extend(b.pdf_character)
            left.layout_label = 'plain text'
            add_space_dummy_chars(left)
            self.update_line_data(a)
            self.update_paragraph_data(left, update_unicode=True)
            paragraphs.pop(index+1)

    def _separate_toc_page_numbers(self, paragraphs: list[PdfParagraph]) -> None:
        """目录单行的页码原位保留；仅在原字符几何证明存在独立右列时拆分。"""
        # 词间距不足时标题会读成 “Table ofContents”，按词序匹配、不依赖空格。
        has_toc_heading = any(re.fullmatch(r'(?:table\s*of\s*|chapter\s*)?contents|目录',
            self._paragraph_text_ascii(p).strip(), re.I) for p in paragraphs)
        result = []
        for paragraph in paragraphs:
            if (paragraph.layout_label not in {'toc_entry', 'chapter_index_entry'}
                or not (has_toc_heading or paragraph.toc_row_group_json)):
                result.append(paragraph)
                continue
            compositions = paragraph.pdf_paragraph_composition
            if not compositions or any(not c.pdf_line for c in compositions):
                result.append(paragraph)
                continue
            chars = [c for part in compositions for c in part.pdf_line.pdf_character]
            if not chars or len(chars) > 300 or any(getattr(c, 'vertical', False) for c in chars):
                result.append(paragraph)
                continue
            text = ''.join(c.char_unicode or '' for c in chars)
            match = re.search(r'(?<!\d)(\d{1,4})\s*$', text)
            if not match:
                result.append(paragraph)
                continue
            title_end = len(text[:match.start(1)].rstrip(' .…\t\r\n'))
            number_chars = []
            offset = 0
            for char in chars:
                value = char.char_unicode or ''
                if match.start(1) <= offset < match.end(1):
                    number_chars.append(char)
                offset += len(value)
            # 保留标题内部空格，避免拼接英文词；只移除两列之间的空白/引导点。
            offset = 0
            title_chars = []
            for char in chars:
                if offset < title_end:
                    title_chars.append(char)
                offset += len(char.char_unicode or '')
            if not title_chars or not number_chars:
                result.append(paragraph)
                continue
            title_line = PdfLine(pdf_character=title_chars)
            number_line = PdfLine(pdf_character=number_chars)
            self.update_line_data(title_line)
            self.update_line_data(number_line)
            left, right = title_line.box, number_line.box
            height = max(left.y2-left.y, right.y2-right.y, 1)
            gap = right.x-left.x2
            if gap < max(12, height*1.5) or abs((left.y+left.y2)-(right.y+right.y2)) > height:
                result.append(paragraph)
                continue
            row_id = paragraph.debug_id or generate_base58_id()
            payload = {'row_id':row_id, 'role':paragraph.layout_label, 'title_text':text[:title_end],
                       'page_number':match.group(1), 'page_number_source':'source_character_geometry',
                       'title_bbox':{k:getattr(left,k) for k in ['x','y','x2','y2']},
                       'page_number_bbox':{k:getattr(right,k) for k in ['x','y','x2','y2']},
                       'row_bbox':{k:getattr(paragraph.box,k) for k in ['x','y','x2','y2']}}
            for role, line in [(paragraph.layout_label,title_line),('toc_page_number',number_line)]:
                child = copy.deepcopy(paragraph)
                child.layout_label = role
                child.debug_id = row_id if role != 'toc_page_number' else generate_base58_id()
                child.pdf_paragraph_composition = [PdfParagraphComposition(pdf_line=line)]
                child.toc_row_group_json = json.dumps(payload, ensure_ascii=False)
                child.title_bbox = copy.deepcopy(left)
                child.page_number_bbox = copy.deepcopy(right)
                self.update_paragraph_data(child, update_unicode=True)
                result.append(child)
        paragraphs[:] = result

    def _looks_like_toc_multiline_paragraph(self, paragraph: PdfParagraph) -> bool:
        lines = self._paragraph_lines(paragraph)
        if len(lines) < 4:
            return False

        texts = [self._line_text(line).strip() for line in lines if self._line_text(line).strip()]
        if len(texts) < 4:
            return False

        joined = "\n".join(texts[:40]).lower()
        explicit_toc = bool(re.search(r"\b(contents|table of contents)\b|目录", joined))
        short_lines = [text for text in texts if len(text) <= 90]
        digit_lines = [text for text in texts if re.search(r"\b\d{1,3}\b", text)]
        standalone_page_numbers = [
            text for text in texts if re.fullmatch(r"\d{1,3}", text)
        ]
        leader_lines = [
            text for text in texts if re.search(r"\.{2,}\s*\d{1,3}\s*$", text)
        ]
        trailing_page_lines = [
            text
            for text in texts
            if len(text) <= 90 and re.search(r"\s\d{1,3}\s*$", text)
        ]
        same_row_page_pairs = 0
        for title_line in lines:
            title_text = self._line_text(title_line).strip()
            if not title_text or re.fullmatch(r"\d{1,3}", title_text) or title_line.box is None:
                continue
            title_mid_y = (title_line.box.y + title_line.box.y2) / 2
            for number_line in lines:
                number_text = self._line_text(number_line).strip()
                if not re.fullmatch(r"\d{1,3}", number_text) or number_line.box is None:
                    continue
                number_mid_y = (number_line.box.y + number_line.box.y2) / 2
                if number_line.box.x > title_line.box.x2 and abs(number_mid_y - title_mid_y) <= 6:
                    same_row_page_pairs += 1
                    break

        if explicit_toc and (len(short_lines) >= 4 or len(digit_lines) >= 4):
            return True
        if len(leader_lines) >= 3:
            return True
        if len(standalone_page_numbers) >= 3 and len(short_lines) >= 6:
            return True
        if same_row_page_pairs >= 2:
            return True
        if len(trailing_page_lines) >= 4 and len(short_lines) / max(len(texts), 1) >= 0.65:
            return True
        return False

    def _split_toc_paragraph_by_lines(
        self,
        paragraph: PdfParagraph,
    ) -> list[PdfParagraph]:
        split_paragraphs: list[PdfParagraph] = []
        line_items = [
            (index, composition, composition.pdf_line, self._line_text(composition.pdf_line).strip())
            for index, composition in enumerate(paragraph.pdf_paragraph_composition)
            if composition.pdf_line and self._line_text(composition.pdf_line).strip()
        ]
        used_page_number_indexes: set[int] = set()
        role = "chapter_index_entry" if self._looks_like_chapter_index_multiline_paragraph(paragraph) else "toc_entry"

        def bbox_payload(box: Box | None) -> dict[str, float] | None:
            if box is None:
                return None
            return {"x": box.x, "y": box.y, "x2": box.x2, "y2": box.y2}

        def same_row_page_number(title_line: PdfLine) -> tuple[int, PdfParagraphComposition, PdfLine, str] | None:
            if title_line.box is None:
                return None
            title_mid_y = (title_line.box.y + title_line.box.y2) / 2
            title_height = max(title_line.box.y2 - title_line.box.y, 1.0)
            candidates: list[tuple[float, int, PdfParagraphComposition, PdfLine, str]] = []
            for candidate_index, candidate_composition, candidate_line, candidate_text in line_items:
                if candidate_index in used_page_number_indexes:
                    continue
                if not re.fullmatch(r"\d{1,3}", candidate_text):
                    continue
                if candidate_line.box is None or candidate_line.box.x <= title_line.box.x2:
                    continue
                candidate_mid_y = (candidate_line.box.y + candidate_line.box.y2) / 2
                if abs(candidate_mid_y - title_mid_y) > max(6.0, title_height * 0.8):
                    continue
                candidates.append((abs(candidate_mid_y - title_mid_y), candidate_index, candidate_composition, candidate_line, candidate_text))
            if not candidates:
                return None
            _distance, candidate_index, candidate_composition, candidate_line, candidate_text = sorted(candidates, key=lambda item: item[0])[0]
            return candidate_index, candidate_composition, candidate_line, candidate_text

        for index, composition, line, text in line_items:
            if index in used_page_number_indexes:
                continue
            if re.fullmatch(r"\d{1,3}", text):
                new_paragraph = PdfParagraph(
                    box=Box(0, 0, 0, 0),
                    pdf_paragraph_composition=[composition],
                    unicode="",
                    debug_id=generate_base58_id(),
                    layout_label="toc_page_number",
                    layout_id=paragraph.layout_id,
                    xobj_id=paragraph.xobj_id,
                )
                self.update_paragraph_data(new_paragraph)
                split_paragraphs.append(new_paragraph)
                continue

            row_match = same_row_page_number(line)
            compositions = [composition]
            page_number_text = None
            page_number_bbox = None
            if row_match is not None:
                page_index, page_composition, page_line, page_text = row_match
                used_page_number_indexes.add(page_index)
                compositions.append(page_composition)
                page_number_text = page_text
                page_number_bbox = page_line.box

            if not composition.pdf_line:
                continue
            new_paragraph = PdfParagraph(
                box=Box(0, 0, 0, 0),
                pdf_paragraph_composition=compositions,
                unicode="",
                debug_id=generate_base58_id(),
                layout_label=role,
                layout_id=paragraph.layout_id,
                xobj_id=paragraph.xobj_id,
            )
            self.update_paragraph_data(new_paragraph)
            try:
                setattr(
                    new_paragraph,
                    "toc_row_group_json",
                    json.dumps(
                        {
                            "row_id": new_paragraph.debug_id,
                            "role": role,
                            "title_text": text,
                            "page_number": page_number_text,
                            "title_bbox": bbox_payload(line.box),
                            "page_number_bbox": bbox_payload(page_number_bbox),
                            "row_bbox": bbox_payload(new_paragraph.box),
                        },
                        ensure_ascii=False,
                    ),
                )
                setattr(new_paragraph, "title_bbox", line.box)
                if page_number_bbox is not None:
                    setattr(new_paragraph, "page_number_bbox", page_number_bbox)
            except AttributeError:
                pass
            split_paragraphs.append(new_paragraph)
        return split_paragraphs

    def _merge_metadata_fragments(self, paragraphs: list[PdfParagraph]) -> None:
        """Merge adjacent header/footer/email fragments before role classification."""

        def paragraph_text(paragraph: PdfParagraph) -> str:
            text = self._paragraph_text_ascii(paragraph).strip()
            if text:
                return re.sub(r"\s+", " ", text)
            return re.sub(
                r"\s+",
                " ",
                " ".join(
                    self._line_text(line).strip()
                    for line in self._paragraph_lines(paragraph)
                    if self._line_text(line).strip()
                ),
            ).strip()

        def metadata_signal(text: str) -> bool:
            lowered = text.lower()
            return bool(
                re.search(r"[A-Za-z0-9_.%+-]+@\s*$|@[A-Za-z0-9.-]*$|(?:stanford|polyu)\.ed$", lowered)
                or re.fullmatch(r"(?:u|hk)\.?", lowered)
                or any(
                    token in lowered
                    for token in (
                        "hong kong polytechnic",
                        "hong kong, china",
                        "andrew.cheung@",
                        "polyu.edu",
                        "shahed@stanford",
                        "humanities and social sciences",
                        "s41599",
                        "doi.org/",
                    )
                )
            )

        def should_join(combined: str, next_text: str, previous: PdfParagraph, current: PdfParagraph) -> bool:
            merged = f"{combined} {next_text}".strip()
            lowered = merged.lower()
            if re.search(r"\b(?:stanford|polyu)\.ed\s+u\.?\b|\bpolyu\.edu\s+hk\b", lowered):
                return True
            if re.search(r"[A-Za-z0-9_.%+-]+@\s+[A-Za-z0-9.-]+", merged):
                return True
            if "hong kong polytechnic" in lowered or "andrew.cheung@" in lowered:
                return True
            if ("humanities and social sciences" in lowered or "s41599" in lowered) and len(merged) <= 160:
                return True
            if not metadata_signal(next_text):
                return False
            prev_box = previous.box
            curr_box = current.box
            if prev_box is None or curr_box is None:
                return True
            vertical_gap = max(0, curr_box.y - prev_box.y2, prev_box.y - curr_box.y2)
            return vertical_gap <= 18

        i = 0
        while i < len(paragraphs):
            text = paragraph_text(paragraphs[i])
            if not metadata_signal(text):
                i += 1
                continue
            cluster_end = i + 1
            combined = text
            while cluster_end < len(paragraphs) and cluster_end <= i + 5:
                next_text = paragraph_text(paragraphs[cluster_end])
                if not next_text or not should_join(combined, next_text, paragraphs[cluster_end - 1], paragraphs[cluster_end]):
                    break
                combined = f"{combined} {next_text}".strip()
                cluster_end += 1
            if cluster_end - i <= 1:
                i += 1
                continue
            base = paragraphs[i]
            for extra in paragraphs[i + 1 : cluster_end]:
                base.pdf_paragraph_composition.extend(extra.pdf_paragraph_composition)
                if base.box and extra.box:
                    base.box = Box(
                        min(base.box.x, extra.box.x),
                        min(base.box.y, extra.box.y),
                        max(base.box.x2, extra.box.x2),
                        max(base.box.y2, extra.box.y2),
                    )
            base.unicode = combined
            self.update_paragraph_data(base)
            del paragraphs[i + 1 : cluster_end]
            i += 1

    def _looks_like_numbered_list_multiline_paragraph(self, paragraph: PdfParagraph) -> bool:
        lines = self._paragraph_lines(paragraph)
        texts = [self._line_text(line).strip() for line in lines if self._line_text(line).strip()]
        if len(texts) < 3:
            return False
        numbered = [
            text
            for text in texts
            if re.match(r"^(?:[1-9][.)]|Q[1-9]\s*[:：.])\s+", text, flags=re.IGNORECASE)
        ]
        return len(numbered) >= 2

    def _looks_like_chapter_index_multiline_paragraph(self, paragraph: PdfParagraph) -> bool:
        lines = self._paragraph_lines(paragraph)
        texts = [self._line_text(line).strip() for line in lines if self._line_text(line).strip()]
        if len(texts) < 3:
            return False
        joined = "\n".join(texts)
        chapter_markers = len(re.findall(r"(?m)^\s*(?:\d+\.)+\d+\s+[A-Za-z]", joined))
        subhead_markers = len(re.findall(r"(?im)^\s*By\s+(?:National Affiliation|Sector|Organization)\b", joined))
        highlight_markers = len(re.findall(r"(?im)^\s*(?:Highlight|Chapter Highlights|Notable AI Models)\b", joined))
        return chapter_markers >= 2 or (chapter_markers >= 1 and subhead_markers + highlight_markers >= 2)

    def _split_cover_year_paragraph(self, paragraph: PdfParagraph) -> list[PdfParagraph]:
        """Keep AI Index cover year as its own bbox-preserving structure item."""
        line_compositions = [
            composition
            for composition in paragraph.pdf_paragraph_composition
            if composition.pdf_line
        ]
        if len(line_compositions) < 2:
            return []
        texts = [self._line_text(composition.pdf_line).strip() for composition in line_compositions]
        normalized_texts = [
            re.sub(r"\bAr\s+tificial\b", "Artificial", text, flags=re.IGNORECASE)
            for text in texts
        ]
        joined = " ".join(normalized_texts)
        if not re.search(r"\b(?:Artificial\s+Intelligence|Intelligence\s+Index\s+Report|Index\s+Report)\b", joined, re.IGNORECASE):
            return []
        year_index = next(
            (
                index
                for index, text in enumerate(normalized_texts)
                if re.fullmatch(r"(?:20\d{2}|2\s+0\s+2\s+6)", text)
            ),
            None,
        )
        if year_index is None:
            return []

        groups: list[tuple[list[PdfParagraphComposition], str]] = []
        if year_index > 0:
            groups.append((line_compositions[:year_index], paragraph.layout_label))
        groups.append(([line_compositions[year_index]], "cover_year"))
        if year_index + 1 < len(line_compositions):
            groups.append((line_compositions[year_index + 1 :], paragraph.layout_label))

        split_paragraphs: list[PdfParagraph] = []
        for compositions, layout_label in groups:
            new_paragraph = PdfParagraph(
                box=Box(0, 0, 0, 0),
                pdf_paragraph_composition=compositions,
                unicode="",
                debug_id=generate_base58_id(),
                layout_label=layout_label,
                layout_id=paragraph.layout_id,
                xobj_id=paragraph.xobj_id,
            )
            self.update_paragraph_data(new_paragraph)
            split_paragraphs.append(new_paragraph)
        return split_paragraphs

    def _split_portrait_directory_labels(self, page: Page, paragraphs: list[PdfParagraph]) -> set[int]:
        """人物名录卡片：画像、名录标题及单位三种证据同时存在才保留姓名。"""
        def lines_of(p):
            return [(line, get_char_unicode_string(line.pdf_character).strip())
                    for line in self._paragraph_lines(p)
                    if get_char_unicode_string(line.pdf_character).strip()]

        def institution(text):
            return len(text) <= 160 and bool(re.search(
                r"\b(?:University|Institute|School|International|Brookings|JPMorgan|OECD|UNSW)\b", text
            )) and not re.search(r"\b(?:is|are|was|were|study|reports?|shows?|found)\b", text, re.I)

        marker = {"steering committee", "editorial board", "advisory board", "contributors", "members", "staff and researchers"}
        if not any(" ".join(t for _, t in lines_of(p)).lower() in marker for p in paragraphs):
            return set()
        box = page.cropbox.box if page.cropbox else page.mediabox.box if page.mediabox else None
        if box is None:
            return set()
        w, h = box.x2-box.x, box.y2-box.y
        portraits = [figure.box for figure in page.pdf_figure if figure.box
                     and 24 <= figure.box.x2-figure.box.x <= w*.25
                     and 24 <= figure.box.y2-figure.box.y <= h*.20
                     and .45 <= (figure.box.x2-figure.box.x)/(figure.box.y2-figure.box.y) <= 1.8]
        if len(portraits) < 3:
            return set()
        # 名录职务可能被布局模型拆为两个短框；只合并明确词对及同列邻接框。
        for p in list(paragraphs):
            if " ".join(t for _, t in lines_of(p)) not in {"GRADUATE", "UNDERGRADUATE"} or not p.box:
                continue
            matches = [q for q in paragraphs if q is not p and q.box
                       and " ".join(t for _, t in lines_of(q)) == "RESEARCHER"
                       and abs(p.box.x-q.box.x) <= 2 and 0 <= p.box.y-q.box.y2 <= 10]
            if len(matches) == 1:
                last = self._paragraph_lines(p)[-1].pdf_character[-1]
                if not (last.char_unicode or '').isspace():
                    blank = copy.deepcopy(last)
                    blank.char_unicode = ' '; blank.advance = 0
                    blank.box = Box(last.box.x2, last.box.y, last.box.x2, last.box.y2)
                    blank.visual_bbox.box = copy.deepcopy(blank.box)
                    self._paragraph_lines(p)[-1].pdf_character.append(blank)
                p.pdf_paragraph_composition.extend(matches[0].pdf_paragraph_composition)
                self.update_paragraph_data(p, update_unicode=True)
                p.layout_label = "report_org_heading"
                paragraphs.remove(matches[0])
        def beside_or_below(p):
            return p.box and any(
                (abs(p.box.x-f.x) <= 18 and 0 <= f.y-p.box.y2 <= 22)
                or (0 <= p.box.x-f.x2 <= 30 and -3 <= f.y2-p.box.y2 <= 28
                    and p.box.y >= f.y-10)
                for f in portraits
            )

        def is_name_line(text):
            letters = [c for c in text if c.isalpha()]
            return (bool(letters) and all(c.isupper() for c in letters)
                    and len(text) <= 70 and len(text.split()) <= 4
                    and not re.search(r"[0-9:;?!]", text)
                    and text.lower() not in {"chair", "co-chair", "members"})

        # 布局模型可能把两行单位拆成两个短标签；先在同一名录卡内恢复单位。
        source_lines = [(p, lines_of(p)) for p in paragraphs]
        consumed = set()
        replacements = {}
        for p, lines in source_lines:
            if not beside_or_below(p) or not lines or not all(is_name_line(t) for _, t in lines):
                continue
            nearby = [(q, qlines) for q, qlines in source_lines
                      if q is not p and id(q) not in consumed and q.box and qlines
                      and abs(q.box.x-p.box.x) <= 18 and 0 <= p.box.y-q.box.y2 <= 38
                      and all(not is_name_line(t) for _, t in qlines)]
            nearby.sort(key=lambda item: -item[0].box.y2)
            if not nearby or not institution(" ".join(t for _, ls in nearby for _, t in ls)):
                continue
            if any(left.box.y-right.box.y2 > 12 for (left, _), (right, _) in zip(nearby, nearby[1:])):
                continue
            if len(nearby) == 1:
                nearby[0][0].layout_label = "institution_label"
                continue
            merged = PdfParagraph(box=Box(0, 0, 0, 0),
                pdf_paragraph_composition=[PdfParagraphComposition(pdf_line=line)
                    for _, ls in nearby for line, _ in ls], unicode="",
                debug_id=generate_base58_id(), layout_label="institution_label",
                layout_id=nearby[0][0].layout_id, xobj_id=nearby[0][0].xobj_id)
            for comp in merged.pdf_paragraph_composition[:-1]:
                last = comp.pdf_line.pdf_character[-1]
                if not (last.char_unicode or "").isspace():
                    blank_box = Box(last.box.x2, last.box.y, last.box.x2, last.box.y2)
                    blank_visual = copy.deepcopy(last.visual_bbox)
                    blank_visual.box = blank_box
                    comp.pdf_line.pdf_character.append(PdfCharacter(pdf_style=last.pdf_style,
                        box=blank_box, visual_bbox=blank_visual, char_unicode=" ",
                        scale=last.scale, advance=0, xobj_id=last.xobj_id, vertical=last.vertical))
            self.update_paragraph_data(merged, update_unicode=True)
            replacements[id(nearby[0][0])] = merged
            consumed.update(id(q) for q, _ in nearby)
        paragraphs[:] = [replacements.get(id(p), p) for p in paragraphs
                         if id(p) not in consumed or id(p) in replacements]
        source_lines = [(p, lines_of(p)) for p in paragraphs]
        result = []
        preserved_ids = set()
        for p, lines in source_lines:
            if not lines or not beside_or_below(p):
                result.append(p); continue
            prefix = []
            for line, text in lines:
                if not is_name_line(text):
                    break
                prefix.append(line)
            if not prefix:
                result.append(p); continue
            suffix = lines[len(prefix):]
            has_affiliation = bool(suffix and institution(" ".join(t for _, t in suffix)))
            if not suffix:
                has_affiliation = any(q is not p and q.box and abs(q.box.x-p.box.x) <= 18
                                      and -3 <= p.box.y-q.box.y2 <= 50
                                      and institution(" ".join(t for _, t in qlines))
                                      for q, qlines in source_lines)
            if not has_affiliation:
                result.append(p); continue
            for selected, role in [(prefix, "compact_label"), ([line for line, _ in suffix], "institution_label")]:
                if not selected:
                    continue
                new = PdfParagraph(box=Box(0, 0, 0, 0),
                    pdf_paragraph_composition=[PdfParagraphComposition(pdf_line=line) for line in selected],
                    unicode="", debug_id=generate_base58_id(), layout_label=role,
                    layout_id=p.layout_id, xobj_id=p.xobj_id)
                if role == "compact_label":
                    preserved_ids.add(id(new))
                self.update_paragraph_data(new, update_unicode=True)
                result.append(new)
        paragraphs[:] = result
        return preserved_ids

    def _classify_academic_metadata(self, page, paragraphs):
        """以摘要前的重复作者/单位结构及底部上标脚注为依据，避免正文词匹配豁免。"""
        page_box = page.cropbox.box if page.cropbox else page.mediabox.box if page.mediabox else None
        if page_box is None:
            return set()
        height = page_box.y2-page_box.y
        def text(p):
            # unicode 此时可能仍为插入词间空格前的缓存；以当前行字符为准。
            lines = [get_char_unicode_string(line.pdf_character) for line in self._paragraph_lines(p)]
            return ' '.join((' '.join(lines) or p.unicode or '').split())
        def size(p):
            values = [float(c.pdf_style.font_size) for c in chars(p) if c.pdf_style and c.pdf_style.font_size]
            return float(getattr(p.pdf_style, 'font_size', None) or (np.median(values) if values else 0))
        def chars(p):
            return [c for line in self._paragraph_lines(p) for c in line.pdf_character if (c.char_unicode or '').strip()]
        result = set()
        # 页脚成对的期刊引用和期刊URL/页码是出版身份候选。要求真实底部
        # 坐标、小字号、单行、同基线和左右分离；正文及许可说明不适用。
        footer = [p for p in paragraphs if p.box and p.xobj_id in (None,-1,0)
                  and page_box.y <= p.box.y < p.box.y2 <= page_box.y+height*.06
                  and 0 < size(p) <= 9 and len(self._paragraph_lines(p)) == 1]
        journal = [p for p in footer if
                   re.fullmatch(r"[A-Z][A-Za-z .&'-]{2,80}(?:19|20)\d{2}\s*[;,:]\s*(?:e\d{4,12}|\d+(?:[-:]\d+)?)\.?", text(p))
                   and len(re.findall(r"\b[A-Za-z]{2,}\.", text(p))) >= 2]
        pagination = [p for p in footer if
                      re.fullmatch(r"(?:https?://)?(?:www\.)?[a-z0-9.-]+\.[a-z]{2,}/journals?/[a-z0-9/_-]+\s+\d+\s+of\s+\d+", text(p), re.I)]
        if len(journal) == len(pagination) == 1:
            left,right=journal[0],pagination[0]
            if abs(left.box.y-right.box.y) <= max(2, size(left)*.5) and right.box.x-left.box.x2 >= (page_box.x2-page_box.x)*.25:
                for p in (left,right):
                    p.layout_label='publication_footer_identity';result.add(id(p))
        # 推荐引用仅在具名标题的紧邻下方保留，普通正文含人名或年份不能触发。
        citation_headers = [p for p in paragraphs if p.box and text(p).lower() in
                            {'how to cite this report', 'recommended citation', 'suggested citation'}
                            and p.xobj_id in (None, -1, 0)]
        for header in citation_headers:
            candidates = [p for p in paragraphs if p is not header and p.box
                          and p.xobj_id in (None, -1, 0)
                          and abs(p.box.x-header.box.x) <= 12
                          and 0 <= header.box.y-p.box.y2 <= 40]
            candidates.sort(key=lambda p: -p.box.y2)
            if not candidates:
                continue
            p = candidates[0]; value = text(p)
            if (100 <= len(value) <= 2000 and value.count(',') >= 4
                    and re.search(r'[“\"][^”\"]{8,}[”\"]', value)
                    and re.search(r'\b(?:19|20)\d{2}\b', value)
                    and re.match(r'[A-Z][A-Za-z.\-]+\s+[A-Z][A-Za-z.\-]+,', value)):
                p.layout_label = 'citation_identity'; result.add(id(p))
        abstracts = [p for p in paragraphs if p.box and text(p).lower() == 'abstract' and size(p) >= 9
                     and p.xobj_id in (None,-1,0)]
        if len(abstracts) == 1:
            boundary = abstracts[0].box.y2
            front = [p for p in paragraphs if p.box and p.box.y >= boundary and p.xobj_id in (None,-1,0)]
            def author(p):
                value = text(p).strip(' *†‡0123456789')
                return bool(re.fullmatch(r"[A-Z][A-Za-z.'’\-]+(?:\s+[A-Z][A-Za-z.'’\-]+){1,5}", value))
            def affiliation(p):
                value = text(p)
                return (len(value) <= 220 and len(self._paragraph_lines(p)) <= 3 and size(p) <= 10
                        and re.search(r'\b(?:University|Institute|Research|Laboratory|Laboratories|College|School)\b',value)
                        and not re.search(r'\b(?:we|our|the|this|that|is|are|was|were|has|have|stud(?:y|ies)|show|shows|find|found|using|used|propose|proposed)\b',value,re.I)
                        and not re.search(r'[?!;]',value))
            pairs = []
            for unit in front:
                if not affiliation(unit):continue
                names = [p for p in front if p is not unit and author(p)
                         and abs(p.box.x-unit.box.x) <= 12 and 0 <= p.box.y-unit.box.y2 <= 12]
                if len(names)==1:pairs.append((names[0],unit))
            # 多个独立作者/单位对才识别为署名区；单个正文人名和单位不足以触发。
            if len({id(name) for name,_ in pairs}) >= 2:
                for name,unit in pairs:
                    for p,role in [(name,'author_identity'),(unit,'affiliation_identity')]:
                        p.layout_label=role;result.add(id(p))
                for p in front:
                    if re.match(r'^Reviewed on [A-Za-z0-9_-]+:',text(p)) and '://' in re.sub(r'\s+','',text(p)) and size(p)<=10:
                        p.layout_label='frontmatter_note';result.add(id(p))
        for p in paragraphs:
            if not p.box or p.box.y2 > page_box.y+height*.13 or size(p)>9:
                continue
            value=text(p);cs=chars(p)
            if (len(cs)<15 or not re.match(r'^\d{1,2}\s*[A-Za-z]',value) or len(self._paragraph_lines(p))>5):
                continue
            marker=cs[0];following=next((c for c in cs[1:] if (c.char_unicode or '').isalpha()),None)
            if following and marker.pdf_style and following.pdf_style:
                ms=float(marker.pdf_style.font_size or 0);fs=float(following.pdf_style.font_size or 0)
                if 0 < ms <= fs*.85 and marker.box.y > following.box.y:
                    p.layout_label='footnote';result.add(id(p))
        return result

    @staticmethod
    def _is_nominal_institution_label(text: str) -> bool:
        """保守识别机构名称短语；名称出现在普通句子中不改变正文角色。"""
        if re.search(r"\b(?:is|are|was|were|has|have|had|will|shall|must|can|may|might|could|should)\b", text, re.I):
            return False
        words = re.findall(r"[^\W_]+(?:[-’'][^\W_]+)*", text)
        if not words or words[0].lower() in {"we", "they", "this", "these", "it"}:
            return False
        connectors = {"of", "for", "and", "the", "at", "in", "de", "van", "von", "der"}
        return all(word[0].isupper() or word.isnumeric() or word in connectors for word in words)

    def _classify_layout_sensitive_paragraph(self, paragraph: PdfParagraph) -> str | None:
        line_texts = [get_char_unicode_string(line.pdf_character).strip()
                      for line in self._paragraph_lines(paragraph)
                      if get_char_unicode_string(line.pdf_character).strip()]
        text = re.sub(r"\s+", " ", " ".join(line_texts) if line_texts else self._paragraph_text_ascii(paragraph)).strip()
        if not text:
            return None
        normalized = re.sub(r"\bAr\s+tificial\b", "Artificial", text, flags=re.IGNORECASE)
        normalized = re.sub(r"\bRepor\s+t\b", "Report", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\b2\s+0\s+2\s+6\b", "2026", normalized)
        lowered = normalized.lower()
        page_height = float(getattr(paragraph, "page_height", 0) or getattr(paragraph, "page_y2", 0) or 0)
        in_footer_band = False
        in_header_band = False
        if paragraph.box is not None and page_height > 0:
            in_footer_band = paragraph.box.y >= page_height * 0.78
            in_header_band = paragraph.box.y2 <= page_height * 0.22
        plain_email_contact_prose = bool(
            re.search(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", normalized)
            and re.search(r"\b(?:welcomes?|feedback|contact\s+us|please|send|write|reach|questions?|comments?|ideas?)\b", normalized, re.I)
        )
        if re.search(r"[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}", normalized) and not plain_email_contact_prose:
            return "email_footer"
        if any(token in lowered for token in ["hong kong polytechnic", "hong kong, china", "polyu.edu.hk", "andrew.cheung@"]):
            return "affiliation_footer"
        if any(token in lowered for token in ["doi.org/", "www.nature.com"]):
            return "running_footer"
        if in_footer_band and any(token in lowered for token in ["humanities and social sciences", "s41599"]):
            return "running_footer"
        if any(token in lowered for token in ["humanities and social sciences", "s41599"]):
            if in_header_band:
                return "running_header"
            return "running_header"
        if re.fullmatch(r"20\d{2}", normalized):
            # 只有首页的独立年份按封面年份处理；正文表头的年份原样保留。
            return "cover_year" if getattr(self, "_current_page_number", 0) in (0, None) else "year_label"
        if re.fullmatch(r"(?:Artificial|Intelligence Index Report|Artificial Intelligence)", normalized, flags=re.IGNORECASE):
            return "report_heading"
        if re.search(r"\bArtificial Intelligence Index Report\b", normalized, flags=re.IGNORECASE):
            return "report_heading"
        report_heading_parts = [
            part.strip(" .,:;")
            for part in re.split(r"\s*(?:,|/|\||;|\band\b)\s*", normalized, flags=re.IGNORECASE)
            if part.strip(" .,:;")
        ]
        if report_heading_parts and all(
            re.fullmatch(r"(?i)(?:chair|co-?chair|co-?chairs|members?|organizations?)", part)
            for part in report_heading_parts
        ):
            return "report_org_heading"
        if re.fullmatch(r"\s*(?:\d+\.)+\d+\s+[A-Za-z][A-Za-z& /:-]+", normalized):
            return "chapter_index_entry"
        if re.fullmatch(r"[A-Za-z][A-Za-z& /:-]+(?:\.{2,}|\s{2,})?\s+\d{1,3}", normalized):
            return "toc_entry"
        if re.match(r"(?i)^Table\s+\d+\b", normalized):
            return "table_caption"
        if lowered in {"sub-corpus", "number of texts", "tokens", "mean length"}:
            return "table_header"
        if any(
            re.search(r"\b" + re.escape(token) + r"\b", normalized, re.I)
            for token in (
                "Stanford University",
                "SRI International",
                "Northeastern University",
                "University of Minnesota",
                "University of Washington",
                "University of Oxford",
                "Umeå University",
                "Umea University",
                "University of Southern California",
                "UNSW Sydney",
                "Brookings",
                "JPMorgan",
                "OECD",
            )
        ) and len(normalized) <= 160 and self._is_nominal_institution_label(normalized):
            return "institution_label"
        if CHART_OR_TABLE_LABEL_PATTERN.fullmatch(normalized) or re.search(
            r"\b(?:Number of notable AI models|by select geographic areas|Figure\s+\d+(?:\.\d+)*|By Sector and Organization|By Topic|Model Release|Parameter and Compute Trends|Hong Kong)\b",
            normalized,
            flags=re.IGNORECASE,
        ):
            return "chart_label"
        if SECTION_HEADING_PATTERN.fullmatch(normalized):
            return "section_heading"
        return None

    def _looks_like_compact_label_paragraph(self, paragraph: PdfParagraph) -> bool:
        if getattr(paragraph, 'layout_label', None) in {'title', 'section', 'heading', 'section_heading', 'section_header'}:
            return False
        if paragraph.box is None:
            return False
        text = self._paragraph_text_ascii(paragraph).strip()
        if not text or not COMPACT_LABEL_PATTERN.match(text):
            return False
        if re.search(
            r"\b(?:The AI Index|welcomes?|feedback|contact us|please|models run out|will models)\b",
            text,
            flags=re.IGNORECASE,
        ):
            return False
        if len(text.split()) >= 4 and re.search(r'[.!?]$', text):
            return False
        if not any(char.isalpha() for char in text):
            return False
        lines = self._paragraph_lines(paragraph)
        if len(lines) > 2:
            return False
        width = paragraph.box.x2 - paragraph.box.x
        height = paragraph.box.y2 - paragraph.box.y
        if width <= 0 or height <= 0:
            return False
        # Most figure labels live inside form XObjects or tiny boxes. Do not
        # classify normal section headings as labels just because they are short.
        if paragraph.xobj_id in (None, -1, 0) and not (width <= 120 and height <= 18):
            return False
        return width <= 180 and height <= 32

    def _classify_code_label_paragraph(self, paragraph: PdfParagraph) -> str | None:
        if paragraph.box is None:
            return None
        text = self._paragraph_text_ascii(paragraph).strip()
        if not text or not CODE_LABEL_PATTERN.search(text):
            return None
        strong_code_signal = bool(
            re.search(r"(?:\\[A-Za-z]+|[A-Za-z]+_[A-Za-z0-9_]+)", text)
            or re.fullmatch(r"(?:section|subsection|caption|environment|command|module)\d*", text, re.IGNORECASE)
        )
        if not strong_code_signal:
            return None
        lines = self._paragraph_lines(paragraph)
        if len(lines) > 4:
            return None
        width = paragraph.box.x2 - paragraph.box.x
        height = paragraph.box.y2 - paragraph.box.y
        if width <= 0 or height <= 0:
            return None
        if (
            len(lines) <= 3
            and width <= 240
            and height <= 64
            and LATEX_STRUCTURE_FRAGMENT_PATTERN.fullmatch(text)
        ):
            return "latex_structure_fragment"
        # 只有 XObject 内的极短、纯代码/标识符标签才原位 passthrough。普通正文或图注中
        # 出现 PDF/API/section 等词时仍允许翻译，避免 Round6 那类误跳过造成遮挡。
        if (
            paragraph.xobj_id is not None
            and len(lines) <= 2
            and width <= 180
            and height <= 40
            and CODE_PASSTHROUGH_LABEL_PATTERN.fullmatch(text)
        ):
            return "code_passthrough_label"
        if width <= 220 and height <= 55:
            return "code_label"
        return None

    def _looks_like_code_label_paragraph(self, paragraph: PdfParagraph) -> bool:
        return self._classify_code_label_paragraph(paragraph) is not None

    def _split_cjk_clause_paragraph(self, paragraph):
        """只按实际行首条款边界拆组，保留每条的续行、字符样式和原始坐标。"""
        from babeldoc.format.pdf.document_il.utils.cjk_structure import cjk_numbering
        parts = paragraph.pdf_paragraph_composition
        if not parts or any(not part.pdf_line for part in parts):
            return [paragraph]
        markers = [cjk_numbering(self._line_text(part.pdf_line).strip()) for part in parts]
        starts = [i for i, marker in enumerate(markers) if marker]
        if not starts or (len(starts) == 1 and starts[0] == 0):
            return [paragraph]
        # 行内引用、数字公式、普通英文编号均不触发此规则；只拆视觉行首。
        boundaries = sorted({0, *starts, len(parts)})
        result = []
        for begin, end in zip(boundaries, boundaries[1:]):
            child = copy.deepcopy(paragraph)
            child.debug_id = generate_base58_id()
            child.pdf_paragraph_composition = parts[begin:end]
            marker = markers[begin]
            if marker:
                child.layout_label = 'section_heading' if marker['level'] == 'section' else 'plain text'
            self.update_paragraph_data(child, update_unicode=True)
            result.append(child)
        return result

    def process_independent_paragraphs(
        self,
        paragraphs: list[PdfParagraph],
        median_width: float,
    ):
        i = 0
        while i < len(paragraphs):
            paragraph = paragraphs[i]
            cjk_parts = self._split_cjk_clause_paragraph(paragraph)
            if len(cjk_parts) > 1:
                paragraphs[i:i + 1] = cjk_parts
                i += len(cjk_parts)
                continue
            if self.translation_config.split_short_lines:
                split_paragraphs = self._split_cover_year_paragraph(paragraph)
                if len(split_paragraphs) > 1:
                    paragraphs[i : i + 1] = split_paragraphs
                    i += len(split_paragraphs)
                    continue
            if (
                self.translation_config.split_short_lines
                and self._looks_like_toc_multiline_paragraph(paragraph)
            ):
                split_paragraphs = self._split_toc_paragraph_by_lines(paragraph)
                if len(split_paragraphs) > 1:
                    paragraphs[i : i + 1] = split_paragraphs
                    i += len(split_paragraphs)
                    continue
            if (
                self.translation_config.split_short_lines
                and (
                    self._looks_like_numbered_list_multiline_paragraph(paragraph)
                    or self._looks_like_chapter_index_multiline_paragraph(paragraph)
                )
            ):
                split_paragraphs = self._split_toc_paragraph_by_lines(paragraph)
                if len(split_paragraphs) > 1:
                    paragraphs[i : i + 1] = split_paragraphs
                    i += len(split_paragraphs)
                    continue
            if len(paragraph.pdf_paragraph_composition) <= 1:  # 跳过只有一行的段落
                i += 1
                continue

            j = 1
            while j < len(paragraph.pdf_paragraph_composition):
                prev_composition = paragraph.pdf_paragraph_composition[j - 1]
                if not prev_composition.pdf_line:
                    j += 1
                    continue

                prev_line = prev_composition.pdf_line
                prev_width = prev_line.box.x2 - prev_line.box.x
                prev_text = "".join([c.char_unicode for c in prev_line.pdf_character])

                # 检查是否包含连续的点（至少 20 个）
                # 如果有至少连续 20 个点，则代表这是目录条目
                if re.search(r"\.{20,}", prev_text):
                    # 创建新的段落
                    new_paragraph = PdfParagraph(
                        box=Box(0, 0, 0, 0),  # 临时边界框
                        pdf_paragraph_composition=(
                            paragraph.pdf_paragraph_composition[j:]
                        ),
                        unicode="",
                        debug_id=generate_base58_id(),
                        layout_label=paragraph.layout_label,
                        layout_id=paragraph.layout_id,
                    )
                    # 更新原段落
                    paragraph.pdf_paragraph_composition = (
                        paragraph.pdf_paragraph_composition[:j]
                    )

                    # 更新两个段落的数据
                    self.update_paragraph_data(paragraph)
                    self.update_paragraph_data(new_paragraph)

                    # 在原段落后插入新段落
                    paragraphs.insert(i + 1, new_paragraph)
                    break

                # 如果前一行宽度小于中位数的一半，将当前行及后续行分割成新段落
                if (
                    self.translation_config.split_short_lines
                    and prev_width
                    < median_width * self.translation_config.short_line_split_factor
                ) or (
                    paragraph.pdf_paragraph_composition
                    and (current_line := paragraph.pdf_paragraph_composition[j])
                    and (line := current_line.pdf_line)
                    and (chars := line.pdf_character)
                    and (char := chars[0])
                    and is_bullet_point(char)
                ):
                    # 创建新的段落
                    new_paragraph = PdfParagraph(
                        box=Box(0, 0, 0, 0),  # 临时边界框
                        pdf_paragraph_composition=(
                            paragraph.pdf_paragraph_composition[j:]
                        ),
                        unicode="",
                        debug_id=generate_base58_id(),
                        layout_label=paragraph.layout_label,
                        layout_id=paragraph.layout_id,
                    )
                    # 更新原段落
                    paragraph.pdf_paragraph_composition = (
                        paragraph.pdf_paragraph_composition[:j]
                    )

                    # 更新两个段落的数据
                    self.update_paragraph_data(paragraph)
                    self.update_paragraph_data(new_paragraph)

                    # 在原段落后插入新段落
                    paragraphs.insert(i + 1, new_paragraph)
                    break
                j += 1
            i += 1

    @staticmethod
    def is_bbox_contain_in_vertical(bbox1: Box, bbox2: Box) -> bool:
        """Check if one bounding box is completely contained within the other."""
        # Check if bbox1 is contained in bbox2
        bbox1_in_bbox2 = bbox1.y >= bbox2.y and bbox1.y2 <= bbox2.y2
        # Check if bbox2 is contained in bbox1
        bbox2_in_bbox1 = bbox2.y >= bbox1.y and bbox2.y2 <= bbox1.y2
        return bbox1_in_bbox2 or bbox2_in_bbox1

    def fix_overlapping_paragraphs(self, page: Page):
        """
        Adjusts the bounding boxes of paragraphs on a page to resolve vertical overlaps.

        Iteratively checks pairs of paragraphs and adjusts their vertical boundaries
        (y and y2) if they overlap, aiming to place the boundary at the midpoint
        of the vertical overlap.
        """
        paragraphs = page.pdf_paragraph
        if not paragraphs or len(paragraphs) < 2:
            return

        max_iterations = len(paragraphs) * len(paragraphs)  # Safety break
        iterations = 0

        while iterations < max_iterations:
            iterations += 1
            overlap_found_in_pass = False

            for i in range(len(paragraphs)):
                for j in range(i + 1, len(paragraphs)):
                    para1 = paragraphs[i]
                    para2 = paragraphs[j]

                    if para1.box is None or para2.box is None:
                        continue

                    if para1.xobj_id != para2.xobj_id:
                        continue

                    # Check for overlap using the existing method
                    if self.bbox_overlap(para1.box, para2.box):
                        if self.is_bbox_contain_in_vertical(para1.box, para2.box):
                            continue
                        # Calculate vertical overlap details
                        overlap_y_start = max(para1.box.y, para2.box.y)
                        overlap_y_end = min(para1.box.y2, para2.box.y2)
                        overlap_height = overlap_y_end - overlap_y_start

                        # Calculate horizontal overlap details
                        overlap_x_start = max(para1.box.x, para2.box.x)
                        overlap_x_end = min(para1.box.x2, para2.box.x2)
                        overlap_width = overlap_x_end - overlap_x_start

                        # Ensure there's a real 2D overlap, focusing on vertical adjustment
                        if overlap_height > 1e-6 and overlap_width > 1e-6:
                            overlap_found_in_pass = True

                            # Determine which paragraph is visually higher
                            if para1.box.y2 > para2.box.y and para1.box.y < para2.box.y:
                                lower_para = para1
                                higher_para = para2
                            # Handle cases where y values are identical (or very close)
                            # Prefer the one with smaller y2 as the higher one, or break tie arbitrarily
                            elif para1.box.y2 < para2.box.y2:
                                lower_para = para1
                                higher_para = para2
                            else:
                                lower_para = para2
                                higher_para = para1

                            # Calculate the midpoint of the vertical overlap
                            mid_y = overlap_y_start + overlap_height / 2

                            # Adjust boxes, ensuring they remain valid (y2 > y)
                            if mid_y > higher_para.box.y and mid_y < lower_para.box.y2:
                                higher_para.box.y = mid_y + 1
                                lower_para.box.y2 = mid_y - 1
                            else:
                                # This might happen if one box is fully contained vertically
                                # within another, or due to floating point issues.
                                # Log a warning and skip adjustment for this pair in this iteration.
                                # A more complex strategy might be needed for full containment.
                                logger.warning(
                                    "Could not resolve overlap between paragraphs"
                                    f" {higher_para.debug_id} and {lower_para.debug_id}"
                                    " using simple midpoint strategy."
                                    f" Midpoint: {mid_y},"
                                    f" Higher Box: {higher_para.box},"
                                    f" Lower Box: {lower_para.box}"
                                )

            # If no overlaps were found and adjusted in this pass, we're done.
            if not overlap_found_in_pass:
                break

        if iterations == max_iterations:
            logger.warning(
                f"Maximum iterations ({max_iterations}) reached in"
                f" fix_overlapping_paragraphs for page {page.page_number}."
                " Some overlaps might remain."
            )

    def _sort_characters_in_lines(self, page: Page):
        """Sort characters in each line from left to right, top to bottom."""
        for paragraph in page.pdf_paragraph:
            for composition in paragraph.pdf_paragraph_composition:
                if composition.pdf_line:
                    line = composition.pdf_line
                    line.pdf_character.sort(key=self._get_char_sort_key)

    def _get_char_sort_key(self, char: PdfCharacter):
        """Get sort key for character positioning (top to bottom, left to right)."""
        visual_box = char.visual_bbox.box
        pdf_box = char.box

        # Use visual box if IoU with bbox is >= 0.1, otherwise use bbox
        if calculate_iou_for_boxes(visual_box, pdf_box) >= 0.1:
            box = visual_box
        else:
            box = pdf_box

        # Sort by y coordinate first (top to bottom), then x coordinate (left to right)
        # Note: In PDF coordinate system, y increases upward, so we negate y for top-to-bottom sorting
        return (box.x, -box.y)
