# Double6 Skills 维护版本（2026-10-23）：与上游v0.5.24的修改及继承维护见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
from __future__ import annotations

import copy
import json
import logging
import math
import os
import re
import statistics
import unicodedata
from functools import cache

import pymupdf
import regex
from rtree import index

from babeldoc.const import WATERMARK_VERSION
from babeldoc.format.pdf.document_il import Box
from babeldoc.format.pdf.document_il import PdfCharacter
from babeldoc.format.pdf.document_il import PdfCurve
from babeldoc.format.pdf.document_il import PdfForm
from babeldoc.format.pdf.document_il import PdfFormula
from babeldoc.format.pdf.document_il import PdfParagraphComposition
from babeldoc.format.pdf.document_il import PdfStyle
from babeldoc.format.pdf.document_il import il_version_1
from babeldoc.format.pdf.document_il.utils.fontmap import FontMapper
from babeldoc.format.pdf.document_il.utils.formular_helper import update_formula_data
from babeldoc.format.pdf.document_il.utils.layout_helper import box_to_tuple
from babeldoc.format.pdf.translation_config import TranslationConfig
from babeldoc.format.pdf.translation_config import WatermarkOutputMode

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _is_body_text_label(label: str) -> bool:
    return label in {"text", "plain text", "paragraph_hybrid", "abandon", "ordinary_text", "paragraph"}

LINE_BREAK_REGEX = regex.compile(
    r"^["
    r"a-z"
    r"A-Z"
    r"0-9"
    r"\u00C0-\u00FF"  # Latin-1 Supplement
    r"\u0100-\u017F"  # Latin Extended A
    r"\u0180-\u024F"  # Latin Extended B
    r"\u1E00-\u1EFF"  # Latin Extended Additional
    r"\u2C60-\u2C7F"  # Latin Extended C
    r"\uA720-\uA7FF"  # Latin Extended D
    r"\uAB30-\uAB6F"  # Latin Extended E
    r"\u0250-\u02A0"  # IPA Extensions
    r"\u0400-\u04FF"  # Cyrillic
    r"\u0300-\u036F"  # Combining Diacritical Marks
    r"\u0500-\u052F"  # Cyrillic Supplement
    r"\u0370-\u03FF"  # Greek and Coptic
    r"\u2DE0-\u2DFF"  # Cyrillic Extended-A
    r"\uA650-\uA69F"  # Cyrillic Extended-B
    r"\u1200-\u137F"  # Ethiopic
    r"\u1380-\u139F"  # Ethiopic Supplement
    r"\u2D80-\u2DDF"  # Ethiopic Extended
    r"\uAB00-\uAB2F"  # Ethiopic Extended-A
    r"\U0001E7E0-\U0001E7FF"  # Ethiopic Extended-B
    r"\u0E80-\u0EFF"  # Lao
    r"\u0D00-\u0D7F"  # Malayalam
    r"\u0A80-\u0AFF"  # Gujarati
    r"\u0E00-\u0E7F"  # Thai
    r"\u1000-\u109F"  # Myanmar
    r"\uAA60-\uAA7F"  # Myanmar Extended-A
    r"\uA9E0-\uA9FF"  # Myanmar Extended-B
    r"\U000116D0-\U000116FF"  # Myanmar Extended-C
    r"\u0B80-\u0BFF"  # Tamil
    r"\u0C00-\u0C7F"  # Telugu
    r"\u0B00-\u0B7F"  # Oriya
    r"\u0530-\u058F"  # Armenian
    r"\u10A0-\u10FF"  # Georgian
    r"\u1C90-\u1CBF"  # Georgian Extended
    r"\u2D00-\u2D2F"  # Georgian Supplement
    r"\u1780-\u17FF"  # Khmer
    r"\u19E0-\u19FF"  # Khmer Symbols
    r"\U00010B00-\U00010B3F"  # Avestan
    r"\u1D00-\u1D7F"  # Phonetic Extensions
    r"\u1400-\u167F"  # Unified Canadian Aboriginal Syllabics
    r"\u0B00-\u0B7F"  # Oriya
    r"\u0780-\u07BF"  # Thaana
    r"\U0001E900-\U0001E95F"  # Adlam
    r"\u1C80-\u1C8F"  # Cyrillic Extended-C
    r"\U0001E030-\U0001E08F"  # Cyrillic Extended-D
    r"\uA000-\uA48F"  # Yi Syllables
    r"\uA490-\uA4CF"  # Yi Radicals
    r"'"
    r"-"  # Hyphen
    r"·"  # Middle Dot (U+00B7) For Català
    r"ʻ"  # Spacing Modifier Letters U+02BB
    r"]+$"
)


class TypesettingUnit:
    def __str__(self):
        return self.try_get_unicode() or ""

    def __init__(
        self,
        char: PdfCharacter | None = None,
        formular: PdfFormula | None = None,
        unicode: str | None = None,
        font: pymupdf.Font | None = None,
        original_font: il_version_1.PdfFont | None = None,
        font_size: float | None = None,
        style: PdfStyle | None = None,
        xobj_id: int | None = None,
        debug_info: bool = False,
        vertical: bool = False,
    ):
        assert (char is not None) + (formular is not None) + (
            unicode is not None
        ) == 1, "Only one of chars and formular can be not None"
        self.char = char
        self.formular = formular
        self.unicode = unicode
        self.x = None
        self.y = None
        self.scale = None
        self.debug_info = debug_info

        # Cache variables
        self.box_cache: Box | None = None
        self.can_break_line_cache: bool | None = None
        self.is_cjk_char_cache: bool | None = None
        self.mixed_character_blacklist_cache: bool | None = None
        self.is_space_cache: bool | None = None
        self.is_hung_punctuation_cache: bool | None = None
        self.is_cannot_appear_in_line_end_punctuation_cache: bool | None = None
        self.can_passthrough_cache: bool | None = None
        self.width_cache: float | None = None
        self.height_cache: float | None = None

        self.font_size: float | None = None

        if unicode:
            assert font_size, "Font size must be provided when unicode is provided"
            assert style, "Style must be provided when unicode is provided"
            assert len(unicode) == 1, "Unicode must be a single character"
            assert xobj_id is not None, (
                "Xobj id must be provided when unicode is provided"
            )

            self.font = font
            if font is not None and hasattr(font, "font_id"):
                self.font_id = font.font_id
            else:
                self.font_id = "base"
            if original_font:
                self.original_font = original_font
            else:
                self.original_font = None

            self.font_size = font_size
            self.style = style
            self.xobj_id = xobj_id
            self.vertical = vertical

    def try_resue_cache(self, old_tu: TypesettingUnit):
        if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
            from pdf_group_source_style import current_registry
            registry=current_registry();registry.transfer(old_tu,self)
            if old_tu.char is not None and self.char is not None:registry.transfer(old_tu.char,self.char)
            if old_tu.formular is not None and self.formular is not None:
                old_chars=old_tu.formular.pdf_character;new_chars=self.formular.pdf_character
                if len(old_chars)!=len(new_chars):raise ValueError('reviewed SCI relocation lost original member')
                for old,new in zip(old_chars,new_chars):registry.transfer(old,new)
        if old_tu.is_cjk_char_cache is not None:
            self.is_cjk_char_cache = old_tu.is_cjk_char_cache

        if old_tu.can_break_line_cache is not None:
            self.can_break_line_cache = old_tu.can_break_line_cache

        if old_tu.is_space_cache is not None:
            self.is_space_cache = old_tu.is_space_cache

        if old_tu.is_hung_punctuation_cache is not None:
            self.is_hung_punctuation_cache = old_tu.is_hung_punctuation_cache

        if old_tu.is_cannot_appear_in_line_end_punctuation_cache is not None:
            self.is_cannot_appear_in_line_end_punctuation_cache = (
                old_tu.is_cannot_appear_in_line_end_punctuation_cache
            )

        if old_tu.can_passthrough_cache is not None:
            self.can_passthrough_cache = old_tu.can_passthrough_cache

        if old_tu.mixed_character_blacklist_cache is not None:
            self.mixed_character_blacklist_cache = (
                old_tu.mixed_character_blacklist_cache
            )

    def try_get_unicode(self) -> str | None:
        if self.char:
            return self.char.char_unicode
        elif self.formular:
            return None
        elif self.unicode:
            return self.unicode

    @property
    def mixed_character_blacklist(self):
        if self.mixed_character_blacklist_cache is None:
            self.mixed_character_blacklist_cache = self.calc_mixed_character_blacklist()

        return self.mixed_character_blacklist_cache

    def calc_mixed_character_blacklist(self):
        unicode = self.try_get_unicode()
        if unicode:
            return unicode in [
                "。",
                "，",
                "：",
                "？",
                "！",
            ]
        return False

    @property
    def can_break_line(self):
        if self.can_break_line_cache is None:
            self.can_break_line_cache = self.calc_can_break_line()

        return self.can_break_line_cache

    def calc_can_break_line(self):
        unicode = self.try_get_unicode()
        if not unicode:
            return True
        if LINE_BREAK_REGEX.match(unicode):
            return False
        return True

    @property
    def is_cjk_char(self):
        if self.is_cjk_char_cache is None:
            self.is_cjk_char_cache = self.calc_is_cjk_char()

        return self.is_cjk_char_cache

    def calc_is_cjk_char(self):
        if self.formular:
            return False
        unicode = self.try_get_unicode()
        if not unicode:
            return False
        if "(cid" in unicode:
            return False
        if len(unicode) > 1:
            return False
        assert len(unicode) == 1, "Unicode must be a single character"
        if unicode in [
            "（",
            "）",
            "【",
            "】",
            "《",
            "》",
            "〔",
            "〕",
            "〈",
            "〉",
            "〖",
            "〗",
            "「",
            "」",
            "『",
            "』",
            "、",
            "。",
            "：",
            "？",
            "！",
            "，",
        ]:
            return True
        if unicode:
            if re.match(
                r"^["
                r"\u3000-\u303f"  # CJK Symbols and Punctuation
                r"\u3040-\u309f"  # Hiragana
                r"\u30a0-\u30ff"  # Katakana
                r"\u3100-\u312f"  # Bopomofo
                r"\uac00-\ud7af"  # Hangul Syllables
                r"\u1100-\u11ff"  # Hangul Jamo
                r"\u3130-\u318f"  # Hangul Compatibility Jamo
                r"\ua960-\ua97f"  # Hangul Jamo Extended-A
                r"\ud7b0-\ud7ff"  # Hangul Jamo Extended-B
                r"\u3190-\u319f"  # Kanbun
                r"\u3200-\u32ff"  # Enclosed CJK Letters and Months
                r"\u3300-\u33ff"  # CJK Compatibility
                r"\ufe30-\ufe4f"  # CJK Compatibility Forms
                r"\u4e00-\u9fff"  # CJK Unified Ideographs
                r"\u2e80-\u2eff"  # CJK Radicals Supplement
                r"\u31c0-\u31ef"  # CJK Strokes
                r"\u2f00-\u2fdf"  # Kangxi Radicals
                r"\ufe10-\ufe1f"  # Vertical Forms
                r"]+$",
                unicode,
            ):
                return True
            try:
                unicodedata_name = unicodedata.name(unicode)
                return (
                    "CJK UNIFIED IDEOGRAPH" in unicodedata_name
                    or "FULLWIDTH" in unicodedata_name
                )
            except ValueError:
                return False
        return False

    @property
    def is_space(self):
        if self.is_space_cache is None:
            self.is_space_cache = self.calc_is_space()

        return self.is_space_cache

    def calc_is_space(self):
        if self.formular:
            return False
        unicode = self.try_get_unicode()
        return unicode == " "

    @property
    def is_hung_punctuation(self):
        if self.is_hung_punctuation_cache is None:
            self.is_hung_punctuation_cache = self.calc_is_hung_punctuation()

        return self.is_hung_punctuation_cache

    def calc_is_hung_punctuation(self):
        if self.formular:
            return False
        unicode = self.try_get_unicode()

        if unicode:
            return unicode in [
                # 英文标点
                ",",
                ".",
                ":",
                ";",
                "?",
                "!",
                # 中文点号
                "，",  # 逗号
                "。",  # 句号
                "．",  # 全角句号
                "、",  # 顿号
                "：",  # 冒号
                "；",  # 分号
                "！",  # 叹号
                "‼",  # 双叹号
                "？",  # 问号
                "⁇",  # 双问号
                # 结束引号
                "”",  # 右双引号
                "’",  # 右单引号
                "」",  # 右直角单引号
                "』",  # 右直角双引号
                # 结束括号
                ")",  # 右圆括号
                "]",  # 右方括号
                "}",  # 右花括号
                "）",  # 右圆括号
                "〕",  # 右龟甲括号
                "〉",  # 右单书名号
                "】",  # 右黑色方头括号
                "〗",  # 右空白方头括号
                "］",  # 全角右方括号
                "｝",  # 全角右花括号
                # 结束双书名号
                "》",  # 右双书名号
                # 连接号
                "～",  # 全角波浪号
                "-",  # 连字符减号
                "–",  # 短破折号 (EN DASH)
                "—",  # 长破折号 (EM DASH)
                # 间隔号
                "·",  # 中间点
                "・",  # 片假名中间点
                "‧",  # 连字点
                # 分隔号
                "/",  # 斜杠
                "／",  # 全角斜杠
                "⁄",  # 分数斜杠
            ]
        return False

    @property
    def is_cannot_appear_in_line_end_punctuation(self):
        if self.is_cannot_appear_in_line_end_punctuation_cache is None:
            self.is_cannot_appear_in_line_end_punctuation_cache = (
                self.calc_is_cannot_appear_in_line_end_punctuation()
            )

        return self.is_cannot_appear_in_line_end_punctuation_cache

    def calc_is_cannot_appear_in_line_end_punctuation(self):
        if self.formular:
            return False
        unicode = self.try_get_unicode()
        if not unicode:
            return False
        return unicode in [
            # 开始引号
            "“",  # 左双引号
            "‘",  # 左单引号
            "「",  # 左直角单引号
            "『",  # 左直角双引号
            # 开始括号
            "(",  # 左圆括号
            "[",  # 左方括号
            "{",  # 左花括号
            "（",  # 左圆括号
            "〔",  # 左龟甲括号
            "〈",  # 左单书名号
            "《",  # 左双书名号
            # 开始单双书名号
            "〖",  # 左空白方头括号
            "〘",  # 左黑色方头括号
            "〚",  # 左单书名号
        ]

    def passthrough(
        self,
    ) -> tuple[list[PdfCharacter], list[PdfCurve], list[PdfForm]]:
        if self.char:
            return [self.char], [], []
        elif self.formular:
            return (
                self.formular.pdf_character,
                self.formular.pdf_curve,
                self.formular.pdf_form,
            )
        elif self.unicode:
            logger.error(f"Cannot passthrough unicode. TypesettingUnit: {self}. ")
            logger.error(f"Cannot passthrough unicode. TypesettingUnit: {self}. ")
            return [], [], []

    @property
    def can_passthrough(self):
        if self.can_passthrough_cache is None:
            self.can_passthrough_cache = self.calc_can_passthrough()

        return self.can_passthrough_cache

    def calc_can_passthrough(self):
        return self.unicode is None

    def calculate_box(self):
        if self.char:
            box = copy.deepcopy(self.char.box)
            if self.char.visual_bbox and self.char.visual_bbox.box:
                box.y = self.char.visual_bbox.box.y
                box.y2 = self.char.visual_bbox.box.y2
                # return self.char.visual_bbox.box

            return box
        elif self.formular:
            return self.formular.box
            # if self.formular.x_offset <= 0.5:
            #     return self.formular.box
            # formular_box = copy.copy(self.formular.box)
            # formular_box.x2 += self.formular.x_advance
            # return formular_box
        elif self.unicode:
            char_width = self.font.char_lengths(self.unicode, self.font_size)[0]
            if self.x is None or self.y is None or self.scale is None:
                return Box(0, 0, char_width, self.font_size)
            return Box(self.x, self.y, self.x + char_width, self.y + self.font_size)

    @property
    def box(self):
        if not self.box_cache:
            self.box_cache = self.calculate_box()

        return self.box_cache

    @property
    def width(self):
        if self.width_cache is None:
            self.width_cache = self.calc_width()

        return self.width_cache

    def calc_width(self):
        if self.unicode == "\n":
            return 0.0
        box = self.box
        return box.x2 - box.x

    @property
    def height(self):
        if self.height_cache is None:
            self.height_cache = self.calc_height()

        return self.height_cache

    def calc_height(self):
        if self.unicode == "\n":
            return self.font_size
        box = self.box
        return box.y2 - box.y

    def relocate(
        self,
        x: float,
        y: float,
        scale: float,
    ) -> TypesettingUnit:
        """重定位并缩放排版单元

        Args:
            x: 新的 x 坐标
            y: 新的 y 坐标
            scale: 缩放因子

        Returns:
            新的排版单元
        """
        if self.char:
            # 创建新的字符对象
            new_char = PdfCharacter(
                pdf_character_id=self.char.pdf_character_id,
                char_unicode=self.char.char_unicode,
                box=Box(
                    x=x,
                    y=y,
                    x2=x + self.width * scale,
                    y2=y + self.height * scale,
                ),
                pdf_style=PdfStyle(
                    font_id=self.char.pdf_style.font_id,
                    font_size=self.char.pdf_style.font_size * scale,
                    graphic_state=self.char.pdf_style.graphic_state,
                ),
                scale=scale,
                vertical=self.char.vertical,
                advance=self.char.advance * scale if self.char.advance else None,
                debug_info=self.debug_info,
                xobj_id=self.char.xobj_id,
            )
            new_tu = TypesettingUnit(char=new_char)
            new_tu.try_resue_cache(self)
            return new_tu

        elif self.formular:
            # 创建新的公式对象，保持内部字符的相对位置
            new_chars = []
            min_x = self.formular.box.x
            min_y = self.formular.box.y

            for char in self.formular.pdf_character:
                # 计算相对位置
                rel_x = char.box.x - min_x
                rel_y = char.box.y - min_y

                visual_rel_x = char.visual_bbox.box.x - min_x
                visual_rel_y = char.visual_bbox.box.y - min_y

                # 创建新的字符对象
                new_char = PdfCharacter(
                    pdf_character_id=char.pdf_character_id,
                    char_unicode=char.char_unicode,
                    box=Box(
                        x=x + (rel_x + self.formular.x_offset) * scale,
                        y=y + (rel_y + self.formular.y_offset) * scale,
                        x2=x
                        + (rel_x + (char.box.x2 - char.box.x) + self.formular.x_offset)
                        * scale,
                        y2=y
                        + (rel_y + (char.box.y2 - char.box.y) + self.formular.y_offset)
                        * scale,
                    ),
                    visual_bbox=il_version_1.VisualBbox(
                        box=Box(
                            x=x + (visual_rel_x + self.formular.x_offset) * scale,
                            y=y + (visual_rel_y + self.formular.y_offset) * scale,
                            x2=x
                            + (
                                visual_rel_x
                                + (char.visual_bbox.box.x2 - char.visual_bbox.box.x)
                                + self.formular.x_offset
                            )
                            * scale,
                            y2=y
                            + (
                                visual_rel_y
                                + (char.visual_bbox.box.y2 - char.visual_bbox.box.y)
                                + self.formular.y_offset
                            )
                            * scale,
                        ),
                    ),
                    pdf_style=PdfStyle(
                        font_id=char.pdf_style.font_id,
                        font_size=char.pdf_style.font_size * scale,
                        graphic_state=char.pdf_style.graphic_state,
                    ),
                    scale=scale,
                    vertical=char.vertical,
                    advance=char.advance * scale if char.advance else None,
                    xobj_id=char.xobj_id,
                )
                new_chars.append(new_char)

            # Calculate bounding box from new_chars
            min_x = min(char.visual_bbox.box.x for char in new_chars)
            min_y = min(char.visual_bbox.box.y for char in new_chars)
            max_x = max(char.visual_bbox.box.x2 for char in new_chars)
            max_y = max(char.visual_bbox.box.y2 for char in new_chars)

            new_formula = PdfFormula(
                box=Box(
                    x=min_x,
                    y=min_y,
                    x2=max_x,
                    y2=max_y,
                ),
                pdf_character=new_chars,
                x_offset=self.formular.x_offset * scale,
                y_offset=self.formular.y_offset * scale,
                x_advance=self.formular.x_advance * scale,
            )

            # Handle contained curves
            new_curves = []
            for curve in self.formular.pdf_curve:
                new_curve = self._transform_curve_for_relocation(
                    curve,
                    self.formular.box.x,
                    self.formular.box.y,
                    x,
                    y,
                    scale,
                )
                new_curves.append(new_curve)
            new_formula.pdf_curve = new_curves

            # Handle contained forms
            new_forms = []
            for form in self.formular.pdf_form:
                new_form = self._transform_form_for_relocation(
                    form, self.formular.box.x, self.formular.box.y, x, y, scale
                )
                new_forms.append(new_form)
            new_formula.pdf_form = new_forms

            update_formula_data(new_formula)

            new_tu = TypesettingUnit(formular=new_formula)
            new_tu.try_resue_cache(self)
            return new_tu

        elif self.unicode:
            # 对于 Unicode 字符，我们存储新的位置信息
            new_unit = TypesettingUnit(
                unicode=self.unicode,
                font=self.font,
                original_font=self.original_font,
                font_size=self.font_size * scale,
                style=self.style,
                xobj_id=self.xobj_id,
                debug_info=self.debug_info,
                vertical=getattr(self, "vertical", False),
            )
            new_unit.x = x
            new_unit.y = y
            new_unit.scale = scale
            new_unit.try_resue_cache(self)
            return new_unit

    def _transform_curve_for_relocation(
        self,
        curve,
        original_formula_x: float,
        original_formula_y: float,
        new_x: float,
        new_y: float,
        scale: float,
    ):
        """Transform a curve for formula relocation."""
        import copy

        new_curve = copy.deepcopy(curve)

        if new_curve.box:
            # Calculate relative position to formula's original position (same as chars)
            rel_x = new_curve.box.x - original_formula_x
            rel_y = new_curve.box.y - original_formula_y

            # Apply same transformation as characters
            new_curve.box = Box(
                x=new_x + (rel_x + self.formular.x_offset) * scale,
                y=new_y + (rel_y + self.formular.y_offset) * scale,
                x2=new_x
                + (
                    rel_x
                    + (new_curve.box.x2 - new_curve.box.x)
                    + self.formular.x_offset
                )
                * scale,
                y2=new_y
                + (
                    rel_y
                    + (new_curve.box.y2 - new_curve.box.y)
                    + self.formular.y_offset
                )
                * scale,
            )

        # Set relocation transform instead of modifying original CTM
        translation_x = (
            new_x + self.formular.x_offset * scale - original_formula_x * scale
        )
        translation_y = (
            new_y + self.formular.y_offset * scale - original_formula_y * scale
        )

        # Create relocation transformation matrix
        from babeldoc.format.pdf.document_il.utils.matrix_helper import (
            create_translation_and_scale_matrix,
        )

        relocation_matrix = create_translation_and_scale_matrix(
            translation_x, translation_y, scale
        )
        new_curve.relocation_transform = list(relocation_matrix)

        return new_curve

    def _transform_form_for_relocation(
        self,
        form,
        original_formula_x: float,
        original_formula_y: float,
        new_x: float,
        new_y: float,
        scale: float,
    ):
        """Transform a form for formula relocation."""
        import copy

        new_form = copy.deepcopy(form)

        if new_form.box:
            # Calculate relative position to formula's original position (same as chars)
            rel_x = new_form.box.x - original_formula_x
            rel_y = new_form.box.y - original_formula_y

            # Apply same transformation as characters
            new_form.box = Box(
                x=new_x + (rel_x + self.formular.x_offset) * scale,
                y=new_y + (rel_y + self.formular.y_offset) * scale,
                x2=new_x
                + (rel_x + (new_form.box.x2 - new_form.box.x) + self.formular.x_offset)
                * scale,
                y2=new_y
                + (rel_y + (new_form.box.y2 - new_form.box.y) + self.formular.y_offset)
                * scale,
            )

        # Set relocation transform instead of modifying original matrices
        translation_x = (
            new_x + self.formular.x_offset * scale - original_formula_x * scale
        )
        translation_y = (
            new_y + self.formular.y_offset * scale - original_formula_y * scale
        )

        # Create relocation transformation matrix
        from babeldoc.format.pdf.document_il.utils.matrix_helper import (
            create_translation_and_scale_matrix,
        )

        relocation_matrix = create_translation_and_scale_matrix(
            translation_x, translation_y, scale
        )
        new_form.relocation_transform = list(relocation_matrix)

        return new_form

    def render(
        self,
    ) -> tuple[list[PdfCharacter], list[PdfCurve], list[PdfForm]]:
        """渲染排版单元为 PdfCharacter 列表

        Returns:
            PdfCharacter 列表
        """
        if self.can_passthrough:
            return self.passthrough()
        elif self.unicode:
            assert self.x is not None, (
                "x position must be set, should be set by `relocate`"
            )
            assert self.y is not None, (
                "y position must be set, should be set by `relocate`"
            )
            assert self.scale is not None, (
                "scale must be set, should be set by `relocate`"
            )
            x = self.x
            y = self.y
            # if self.original_font and self.font and hasattr(self.original_font, "descent") and hasattr(self.font, "descent_fontmap"):
            #     original_descent = self.original_font.descent
            #     new_descent = self.font.descent_fontmap
            #     y -= (original_descent - new_descent) * self.font_size / 1000

            # 计算字符宽度
            char_width = self.width

            new_char = PdfCharacter(
                pdf_character_id=self.font.has_glyph(ord(self.unicode)),
                char_unicode=self.unicode,
                box=Box(
                    x=x,  # 使用存储的位置
                    y=y,
                    x2=x + char_width,
                    y2=y + self.font_size,
                ),
                pdf_style=PdfStyle(
                    font_id=self.font_id,
                    font_size=self.font_size,
                    graphic_state=self.style.graphic_state,
                ),
                scale=self.scale,
                vertical=getattr(self, "vertical", False),
                advance=char_width,
                xobj_id=self.xobj_id,
                debug_info=self.debug_info,
            )
            if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
                from pdf_group_source_style import current_registry
                registry=current_registry()
                if registry.facts(self) is None:raise ValueError('reviewed natural character lost target span provenance')
                registry.transfer(self,new_char)
            return [new_char], [], []
        else:
            logger.error(f"Unknown typesetting unit. TypesettingUnit: {self}. ")
            logger.error(f"Unknown typesetting unit. TypesettingUnit: {self}. ")
            return [], [], []


def english_word_break_extent(is_cjk: bool, unit_width: float, lookahead_width: float) -> float:
    """英文断行检查用的“当前词剩余宽度”。

    lookahead_width 是到下一个可断点为止的前视宽度，不可断时已包含当前单元。
    CJK 目标语言沿用原式（当前单元计两次，英译中排版保持逐像素不变）；
    拉丁目标语言按整词实际宽度判断，否则会把单词拆成“c|ontext”。
    """
    if is_cjk or lookahead_width <= 0:
        return unit_width + lookahead_width
    return lookahead_width


class Typesetting:
    stage_name = "Typesetting"

    def __init__(self, translation_config: TranslationConfig):
        self.font_mapper = FontMapper(translation_config)
        self.translation_config = translation_config
        self.lang_code = self.translation_config.lang_out.upper()
        self.is_cjk = (
            # Why zh-CN/zh-HK/zh-TW here but not zh-Hans and so on?
            # See https://funstory-ai.github.io/BabelDOC/supported_languages/
            ("ZH" in self.lang_code)  # C
            or ("JA" in self.lang_code)
            or ("JP" in self.lang_code)  # J
            or ("KR" in self.lang_code)  # K
            or ("CN" in self.lang_code)
            or ("HK" in self.lang_code)
            or ("TW" in self.lang_code)
        )

    def preprocess_document(self, document: il_version_1.Document, pbar):
        """预处理文档，获取每个段落的最优缩放因子，不执行实际排版"""
        all_scales: list[float] = []
        all_paragraphs: list[il_version_1.PdfParagraph] = []

        for page in document.page:
            pbar.advance()
            # 准备字体信息（复制自 render_page 的逻辑）
            fonts: dict[
                str | int,
                il_version_1.PdfFont | dict[str, il_version_1.PdfFont],
            ] = {f.font_id: f for f in page.pdf_font if f.font_id}
            page_fonts = {f.font_id: f for f in page.pdf_font if f.font_id}
            for k, v in self.font_mapper.fontid2font.items():
                fonts[k] = v
            for xobj in page.pdf_xobject:
                if xobj.xobj_id is not None:
                    fonts[xobj.xobj_id] = page_fonts.copy()
                    for font in xobj.pdf_font:
                        if (
                            xobj.xobj_id in fonts
                            and isinstance(fonts[xobj.xobj_id], dict)
                            and font.font_id
                        ):
                            fonts[xobj.xobj_id][font.font_id] = font

            self._assign_baseline_ceilings(page)
            # 处理每个段落
            for paragraph in page.pdf_paragraph:
                all_paragraphs.append(paragraph)
                if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
                    from pdf_group_source_style import reviewed_paragraph_facts
                    facts=reviewed_paragraph_facts(paragraph)
                    if facts is None:raise ValueError('current source paragraph has no reviewed rendering role')
                    if facts['mode'] not in {'preserve_original','reviewed_fixed_layout'}:
                        raise ValueError('ordinary source paragraph was not projected to complete reviewed components')
                    paragraph.optimal_scale=1.0
                    continue
                unit_count = 0
                try:
                    typesetting_units = self.create_typesetting_units(paragraph, fonts)
                    unit_count = len(typesetting_units)
                    for unit in typesetting_units:
                        if unit.formular:
                            unit_count += len(unit.formular.pdf_character) - 1

                    needs_readable_retypeset = (
                        self._has_hard_readable_floor(paragraph)
                        and self._readable_scale_floor(paragraph) > 1.0
                        and not self._preserves_vertical_source(paragraph, typesetting_units)
                    )
                    # 如果所有单元都可以直接传递且字号已经可读，则 scale = 1.0
                    if all(unit.can_passthrough for unit in typesetting_units) and not needs_readable_retypeset:
                        paragraph.optimal_scale = 1.0
                    else:
                        # 获取最优缩放因子
                        optimal_scale = self._get_optimal_scale(
                            paragraph, page, typesetting_units
                        )
                        paragraph.optimal_scale = optimal_scale
                except Exception as e:
                    # 如果预处理出错，默认使用 1.0 缩放因子
                    logger.warning(f"预处理段落时出错：{e}")
                    paragraph.optimal_scale = 1.0

                if paragraph.optimal_scale is not None:
                    all_scales.extend([paragraph.optimal_scale] * unit_count)

        # 获取缩放因子的众数
        if all_scales:
            try:
                modes = statistics.multimode(all_scales)
                mode_scale = min(modes)
            except statistics.StatisticsError:
                logger.warning(
                    "Could not find a mode for paragraph scales. Falling back to median."
                )
                mode_scale = statistics.median(all_scales)
            # 将所有大于众数的值修改为众数
            for paragraph in all_paragraphs:
                if (
                    paragraph.optimal_scale is not None
                    and paragraph.optimal_scale
                    > self._document_mode_scale_for_paragraph(paragraph, mode_scale)
                ):
                    paragraph.optimal_scale = self._document_mode_scale_for_paragraph(
                        paragraph,
                        mode_scale,
                    )
        else:
            logger.error(
                "document_scales is empty, there seems no paragraph in this PDF"
            )

    def _find_optimal_scale_and_layout(
        self,
        paragraph: il_version_1.PdfParagraph,
        page: il_version_1.Page,
        typesetting_units: list[TypesettingUnit],
        initial_scale: float = 1.0,
        use_english_line_break: bool = True,
        apply_layout: bool = False,
    ) -> tuple[float, list[TypesettingUnit] | None]:
        """查找最优缩放因子并可选择性地执行布局

        Args:
            paragraph: 段落对象
            page: 页面对象
            typesetting_units: 排版单元列表
            initial_scale: 初始缩放因子
            use_english_line_break: 是否使用英文换行规则
            apply_layout: 是否应用布局到 paragraph（True 时执行实际排版）

        Returns:
            tuple[float, list[TypesettingUnit] | None]: (最终缩放因子，排版后的单元列表或 None)
        """
        if not paragraph.box:
            return initial_scale, None

        if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
            from pdf_group_source_style import reviewed_paragraph_facts, LINE_HEIGHT_RATIO
            facts=reviewed_paragraph_facts(paragraph)
            if facts is None or facts['mode']!='reviewed_fixed_layout':
                raise ValueError('fixed reviewed layout metadata missing')
            units,fit=self._layout_typesetting_units(typesetting_units,paragraph.box,1.0,
                LINE_HEIGHT_RATIO,paragraph,use_english_line_break)
            if not fit or not units:
                raise ValueError('reviewed uniform source layout overflow; per-paragraph shrink forbidden')
            if apply_layout:
                paragraph.scale=1.0;paragraph.pdf_paragraph_composition=[]
                for unit in units:
                    chars,curves,forms=unit.render()
                    paragraph.pdf_paragraph_composition.extend(PdfParagraphComposition(pdf_character=c) for c in chars)
                    page.pdf_curve.extend(curves);page.pdf_form.extend(forms)
            return 1.0,units

        box = self._toc_title_layout_box(paragraph)
        label = (getattr(paragraph, "layout_label", None) or "").lower()
        if label in {"institution_label", "report_org_heading"}:
            box = self._institution_layout_box(paragraph, page, box)
            if apply_layout:
                paragraph.box = box
        line_skip = 1.15 if label == "diagram_node" else (1.50 if self.is_cjk else 1.3)
        # 实验开关：只在显式设置时调整正文行距，用于验证后端段落重排，
        # 避免默认交付路径因为单个 case 的调参产生漂移。
        if self.is_cjk and _is_body_text_label(label):
            line_skip = _env_float("PAPER_TRANSLATION_CJK_BODY_LINE_SKIP", line_skip)
        readable_floor = self._readable_scale_floor(paragraph)
        scale = max(initial_scale, readable_floor)
        min_scale = readable_floor if self._has_hard_readable_floor(paragraph) else 0.1
        expand_space_flag = 0
        final_typeset_units = None
        floor_typeset_units = None
        dialogue_width_checked = False
        latin_expand_stage = 0

        while scale >= min_scale:
            try:
                # 尝试布局排版单元
                typeset_units, all_units_fit = self._layout_typesetting_units(
                    typesetting_units,
                    box,
                    scale,
                    line_skip,
                    paragraph,
                    use_english_line_break,
                )
                if scale >= readable_floor:
                    floor_typeset_units = typeset_units

                # 如果所有单元都放得下
                if all_units_fit:
                    # 对标题、图注和紧凑标签，先尝试扩展 bbox，避免用过小字号
                    # 硬塞进原框。扩展尝试用尽后仍允许继续产出，避免丢段。
                    if scale < readable_floor and expand_space_flag < 2:
                        all_units_fit = False
                    else:
                        if apply_layout:
                            # 实际应用排版结果
                            paragraph.scale = scale
                            paragraph.pdf_paragraph_composition = []
                            for unit in typeset_units:
                                chars, curves, forms = unit.render()
                                for char in chars:
                                    paragraph.pdf_paragraph_composition.append(
                                        PdfParagraphComposition(pdf_character=char),
                                    )
                                for curve in curves:
                                    page.pdf_curve.append(curve)
                                for form in forms:
                                    page.pdf_form.append(form)
                            final_typeset_units = typeset_units
                        return scale, final_typeset_units
            except Exception:
                # 如果布局检查出错，继续尝试下一个缩放因子
                pass

            # 单行正文对话先借用同栏空白，再缩字。只尝试一次，且不改纵向位置。
            if not dialogue_width_checked:
                dialogue_width_checked = True
                expanded_box = self._dialogue_layout_box(paragraph, page, box)
                if expanded_box.x2 > box.x2:
                    box = expanded_box
                    if apply_layout:
                        paragraph.box = expanded_box
                    continue

            # 拉丁目标语言的单行段落（标题、图注、表头）：先借用右侧空白，再缩字。
            # 中文标题框只有中文宽度，英文译文常常长一倍；直接缩字会得到很小的标题。
            if (not self.is_cjk and latin_expand_stage == 0
                    and self._is_single_source_line(box, typesetting_units)):
                latin_expand_stage = 1
                expanded_box = self._latin_target_expanded_box(box, page, 0)
                if expanded_box is not None:
                    box = expanded_box
                    if apply_layout:
                        paragraph.box = expanded_box
                    continue

            # 必须实际尝试下限，不能用固定步长跨过它，再把失败试排
            # 误当成下限字号的结果。下限已试过仍失败时结束搜索。
            if scale <= min_scale:
                # 拉丁目标语言（如中译英）：译文通常比中文源文长得多，紧贴中文
                # 宽度的标题/图注框在可读下限也放不下。先借用右侧、再借用下方
                # 的实际空白（与其它段落/字符/图形不相交），再按原规则拒绝。
                # CJK 目标语言不进入此分支，英译中排版保持不变。
                expanded_box = None
                while expanded_box is None and not self.is_cjk and latin_expand_stage < 2:
                    expanded_box = self._latin_target_expanded_box(box, page, latin_expand_stage)
                    latin_expand_stage += 1
                if expanded_box is not None:
                    box = expanded_box
                    if apply_layout:
                        paragraph.box = expanded_box
                    scale = max(initial_scale, readable_floor)
                    continue
                break
            scale = max(min_scale, scale - (0.05 if scale > 0.6 else 0.1))

            if scale < 0.7:
                space_expanded = False  # 标记是否成功扩展了空间

                if expand_space_flag == 0:
                    # 尝试向下扩展
                    try:
                        min_y = self.get_max_bottom_space(box, page) + 2
                        if min_y < box.y:
                            expanded_box = Box(x=box.x, y=min_y, x2=box.x2, y2=box.y2)
                            box = expanded_box
                            if apply_layout:
                                # 更新段落的边界框
                                paragraph.box = expanded_box
                            space_expanded = True
                    except Exception:
                        pass
                    expand_space_flag = 1

                    # 只有成功扩展空间时才 continue，否则继续减小 scale
                    if space_expanded:
                        continue

                elif expand_space_flag == 1:
                    # 尝试向右扩展
                    try:
                        max_x = self.get_max_right_space(box, page) - 5
                        if max_x > box.x2:
                            expanded_box = Box(x=box.x, y=box.y, x2=max_x, y2=box.y2)
                            box = expanded_box
                            if apply_layout:
                                # 更新段落的边界框
                                paragraph.box = expanded_box
                            space_expanded = True
                    except Exception:
                        pass
                    expand_space_flag = 2

                    # 只有成功扩展空间时才 continue，否则继续减小 scale
                    if space_expanded:
                        continue

                # 只有在扩展尝试阶段 (expand_space_flag < 2) 且扩展失败时才重置 scale
                # 当 expand_space_flag >= 2 时，说明已经尝试过所有扩展，应该继续正常的 scale 减小
                if expand_space_flag < 2:
                    # 如果无法扩展空间，重置 scale 并继续循环
                    scale = 1.0

        if self._has_hard_readable_floor(paragraph):
            # 硬可读字号只保证字不会太小；若内容实际放不下，继续提交会在
            # AI Index 这类目录/图表页制造遮挡。此时保留空 composition，
            # 让上层 PyMuPDF/structure gate 生成 page-level rerender candidate。
            if self._should_reject_hard_floor_overflow(paragraph):
                if apply_layout:
                    paragraph.scale = readable_floor
                    paragraph.pdf_paragraph_composition = []
                    try:
                        setattr(paragraph, "writeback_status", self._hard_floor_overflow_status(paragraph))
                        setattr(paragraph, "writeback_reason", "hard_readable_floor_overflow")
                    except AttributeError:
                        pass
                return readable_floor, None
            if apply_layout and floor_typeset_units is not None:
                paragraph.scale = readable_floor
                paragraph.pdf_paragraph_composition = []
                for unit in floor_typeset_units:
                    chars, curves, forms = unit.render()
                    for char in chars:
                        paragraph.pdf_paragraph_composition.append(
                            PdfParagraphComposition(pdf_character=char),
                        )
                    for curve in curves:
                        page.pdf_curve.append(curve)
                    for form in forms:
                        page.pdf_form.append(form)
            return readable_floor, floor_typeset_units if apply_layout else None

        # 如果仍然放不下，尝试去除英文换行限制
        if use_english_line_break:
            return self._find_optimal_scale_and_layout(
                paragraph,
                page,
                typesetting_units,
                initial_scale,
                use_english_line_break=False,
                apply_layout=apply_layout,
            )

        # 最后返回最小缩放因子
        return min_scale, final_typeset_units

    @staticmethod
    def _is_single_source_line(box: Box, typesetting_units) -> bool:
        heights = [unit.height for unit in typesetting_units if getattr(unit, "height", 0)]
        if not heights:
            return False
        return (box.y2 - box.y) < 1.8 * max(heights)

    def _latin_target_expanded_box(self, box: Box, page, stage: int) -> Box | None:
        """stage 0 向右、stage 1 向下扩展到最近的阻挡物；没有可用空白时返回 None。

        阻挡物除段落、字符、图片外，还包括矢量路径（表格线、单元格/节点边框）、Form XObject
        与版面分析的表格区域：扩展框不得越过它们，也不得借越过它们获得“放得下”。
        """
        try:
            if stage == 0:
                max_x = min(self.get_max_right_space(box, page), self._latin_vector_right_limit(box, page)) - 5
                if max_x > box.x2 + 1:
                    return Box(x=box.x, y=box.y, x2=max_x, y2=box.y2)
            elif stage == 1:
                min_y = max(self.get_max_bottom_space(box, page), self._latin_vector_bottom_limit(box, page)) + 2
                if min_y < box.y - 1:
                    return Box(x=box.x, y=min_y, x2=box.x2, y2=box.y2)
        except Exception:
            return None
        return None

    @staticmethod
    def _latin_expansion_obstacles(page) -> tuple[list[Box], list[Box]]:
        """（矢量/表单阻挡框，表格区域框）。只供拉丁目标语言扩框使用，英译中排版不调用。"""
        obstacles = [item.box for item in [*(page.pdf_curve or []), *(getattr(page, "pdf_form", None) or [])]
                     if getattr(item, "box", None) is not None]
        tables = [layout.box for layout in getattr(page, "page_layout", None) or []
                  if layout.box is not None and (layout.class_name or "").lower() in {"table", "table_body", "table_cell"}]
        return obstacles, tables

    def _latin_vector_right_limit(self, box: Box, page) -> float:
        limit = float("inf")
        eps = 0.5
        obstacles, tables = self._latin_expansion_obstacles(page)
        for other in obstacles:
            if other.y >= box.y2 - eps or other.y2 <= box.y + eps:
                continue  # 没有垂直重叠
            if other.x >= box.x2 - eps:
                limit = min(limit, other.x)  # 右侧的竖线、边框或图形
            elif other.x <= box.x + eps and other.x2 >= box.x2 - eps:
                limit = min(limit, max(other.x2, box.x2))  # 包住本段的单元格/节点框：右边框
            elif other.x2 >= box.x2 - eps:
                limit = min(limit, max(other.x2, box.x2))  # 与本段右缘相交的路径：不越过其右缘
        cx, cy = (box.x + box.x2) / 2, (box.y + box.y2) / 2
        for region in tables:
            if region.x <= cx <= region.x2 and region.y <= cy <= region.y2:
                limit = min(limit, max(region.x2, box.x2))  # 表格内的段落不越出表格区域
            elif region.x >= box.x2 - eps and not (region.y >= box.y2 or region.y2 <= box.y):
                limit = min(limit, region.x)  # 不扩入右侧表格
        return limit

    def _latin_vector_bottom_limit(self, box: Box, page) -> float:
        limit = float("-inf")
        eps = 0.5
        obstacles, tables = self._latin_expansion_obstacles(page)
        for other in obstacles:
            if other.x >= box.x2 - eps or other.x2 <= box.x + eps:
                continue  # 没有水平重叠
            if other.y2 <= box.y + eps:
                limit = max(limit, other.y2)  # 下方的横线、边框或图形
            elif other.y2 >= box.y2 - eps and other.y <= box.y + eps:
                limit = max(limit, min(other.y, box.y))  # 包住本段的单元格/节点框：下边框
            elif other.y <= box.y + eps:
                limit = max(limit, min(other.y, box.y))  # 与本段下缘相交的路径：不越过其下缘
        cx, cy = (box.x + box.x2) / 2, (box.y + box.y2) / 2
        for region in tables:
            if region.x <= cx <= region.x2 and region.y <= cy <= region.y2:
                limit = max(limit, min(region.y, box.y))
            elif region.y2 <= box.y + eps and not (region.x >= box.x2 or region.x2 <= box.x):
                limit = max(limit, region.y2)  # 不扩入下方表格
        return limit

    @staticmethod
    def _readable_scale_floor(paragraph: il_version_1.PdfParagraph) -> float:
        label = (getattr(paragraph, "layout_label", None) or "").lower()
        base_font_size = float(getattr(getattr(paragraph, "pdf_style", None), "font_size", None) or 0)
        absolute_floor = 6.0
        if label == "diagram_node":
            return max(1.0, 7.5 / base_font_size) if base_font_size else 1.0
        if label in {"footnote", "frontmatter_note", "email_footer", "affiliation_footer", "running_header", "running_footer"}:
            absolute_floor = 5.5
        if label == "latex_structure_fragment":
            return max(0.95, absolute_floor / base_font_size) if base_font_size else 0.95
        if label in {"toc_entry", "chapter_index_entry"}:
            # 目录不跟随正文的文档众数缩小；源行本身较小时保持源密度。
            return max(0.95, min(8.0, base_font_size) / base_font_size) if base_font_size else 0.95
        if label in {"institution_label", "report_org_heading"}:
            # 名录单位与角色沿用源字号，禁止文档众数或单格收缩降低可读性。
            return 1.0
        if label in {"compact_label", "code_label", "code_passthrough_label"}:
            return max(0.78, absolute_floor / base_font_size) if base_font_size else 0.78
        if label in {"title", "section", "section_header", "heading", "section_heading", "report_heading"}:
            # 配置正文可读字号后，标题不能被文档众数缩到正文下限以下。
            absolute_floor = max(absolute_floor, _env_float("PAPER_TRANSLATION_BODY_MIN_FONT_SIZE", absolute_floor))
            return max(0.78, absolute_floor / base_font_size) if base_font_size else 0.78
        if label in {"chart_label", "axis", "axis_label", "legend", "fallback_line"}:
            return max(0.72, absolute_floor / base_font_size) if base_font_size else 0.72
        if label in {"footnote", "frontmatter_note", "email_footer", "affiliation_footer", "running_header", "running_footer"}:
            return max(0.72, absolute_floor / base_font_size) if base_font_size else 0.72
        if "caption" in label or "table" in label:
            return max(0.72, absolute_floor / base_font_size) if base_font_size else 0.72
        if _is_body_text_label(label):
            absolute_floor = _env_float("PAPER_TRANSLATION_BODY_MIN_FONT_SIZE", absolute_floor)
            return max(0.58, absolute_floor / base_font_size) if base_font_size else 0.58
        return 0.5

    @staticmethod
    def _has_hard_readable_floor(paragraph: il_version_1.PdfParagraph) -> bool:
        label = (getattr(paragraph, "layout_label", None) or "").lower()
        return label in {
            "diagram_node",
            "institution_label",
            "report_org_heading",
            "title",
            "section",
            "section_header",
            "heading",
            "section_heading",
            "report_heading",
            "toc_entry",
            "chapter_index_entry",
            "chart_label",
            "axis",
            "axis_label",
            "fallback_line",
            "abandon",
            "legend",
            "text",
            "plain text",
            "paragraph_hybrid",
            "table_cell",
            "table_header",
            "table_caption",
            "footnote",
            "frontmatter_note",
        } or "caption" in label or "table" in label

    @staticmethod
    def _should_reject_hard_floor_overflow(paragraph: il_version_1.PdfParagraph) -> bool:
        # 已声明硬下限的所有角色都必须真正放得下；正文/标题不能把
        # 最后一次失败试排写进PDF后仍报告通过。
        return Typesetting._has_hard_readable_floor(paragraph)

    @staticmethod
    def _hard_floor_overflow_status(paragraph: il_version_1.PdfParagraph) -> str:
        label = (getattr(paragraph, "layout_label", None) or "").lower()
        if label in {"toc_entry", "chapter_index_entry"}:
            return "structured_toc_writeback_failed"
        if label in {"table_header", "table_cell", "table_caption"} or "table" in label:
            return "table_region_rerender_required"
        if label in {"running_footer", "running_header", "email_footer", "affiliation_footer"}:
            return "metadata_yband_role_paint_failed"
        if label == "cover_year":
            return "cover_year_writeback_failed"
        if _is_body_text_label(label):
            return "body_region_rerender_required"
        if label in {"title", "section", "section_header", "heading", "section_heading", "report_heading"}:
            return "heading_region_rerender_required"
        return "chart_region_rerender_required"

    @classmethod
    def _document_mode_scale_for_paragraph(
        cls,
        paragraph: il_version_1.PdfParagraph,
        mode_scale: float,
    ) -> float:
        # 文档级众数缩放用于统一观感，但不能把标题、图注和图内短标签压到
        # 可读阈值以下；真正放不下的段落会在实际排版阶段继续降级。
        return max(mode_scale, cls._readable_scale_floor(paragraph))

    def _get_optimal_scale(
        self,
        paragraph: il_version_1.PdfParagraph,
        page: il_version_1.Page,
        typesetting_units: list[TypesettingUnit],
        use_english_line_break: bool = True,
    ) -> float:
        """获取段落的最优缩放因子，不执行实际排版"""
        scale, _ = self._find_optimal_scale_and_layout(
            paragraph,
            page,
            typesetting_units,
            1.0,
            use_english_line_break,
            apply_layout=False,
        )
        return scale

    def retypeset_with_precomputed_scale(
        self,
        paragraph: il_version_1.PdfParagraph,
        page: il_version_1.Page,
        typesetting_units: list[TypesettingUnit],
        precomputed_scale: float,
        use_english_line_break: bool = True,
    ):
        """使用预计算的缩放因子进行排版"""
        if not paragraph.box:
            return

        # 使用通用方法进行排版，传入预计算的缩放因子作为初始值
        self._find_optimal_scale_and_layout(
            paragraph,
            page,
            typesetting_units,
            precomputed_scale,
            use_english_line_break,
            apply_layout=True,
        )

    @staticmethod
    def _toc_title_layout_box(paragraph):
        """使用完整原行高度排目录标题，右界止于独立页码列之前。"""
        if getattr(paragraph, "layout_label", None) == "diagram_node":
            payload = json.loads(paragraph.diagram_node_json or "{}")
            if payload.get("source") != "filled_form_node_and_paint_order":
                raise ValueError("diagram node lacks source geometry")
            return Box(*payload["layout_bbox"])
        if getattr(paragraph, "layout_label", None) not in {"toc_entry", "chapter_index_entry"}:
            return paragraph.box
        try:
            payload = json.loads(getattr(paragraph, "toc_row_group_json", None) or "{}")
            if payload.get("page_number_source") != "source_character_geometry":
                return paragraph.box
            row, title, number = (payload[key] for key in ("row_bbox", "title_bbox", "page_number_bbox"))
            gap = max(8.0, (row["y2"] - row["y"]) * 0.8)
            box = Box(title["x"], row["y"], number["x"] - gap, row["y2"])
            if box.x2 <= box.x or box.y2 <= box.y:
                return paragraph.box
            return box
        except (TypeError, ValueError, KeyError):
            return paragraph.box

    def _writeback_failures(self, document):
        rejections = getattr(self, "_overflow_fallback_rejections", None) or {}
        failures = []
        for page in document.page:
            for paragraph in page.pdf_paragraph:
                if not str(getattr(paragraph, "writeback_status", "") or "").endswith(("_failed", "_rerender_required")):
                    continue
                row = {"page_index": page.page_number, "paragraph_id": paragraph.debug_id,
                       "role": paragraph.layout_label, "status": paragraph.writeback_status,
                       "reason": paragraph.writeback_reason}
                if id(paragraph) in rejections:
                    row["source_fallback_rejected"] = rejections[id(paragraph)]
                failures.append(row)
        return failures

    def _apply_overflow_source_fallback(self, paragraph, page, fonts) -> bool:
        """可读下限溢出的短结构片段（目录项/页码标签、表头单元格、图内标签）保留原文字形。

        只在 overflow_source_fallback.admission 全部条件满足、且源字形可原样直通时生效；
        原位置、原字号，不缩字、不裁切；否则保持原失败状态并记录拒绝理由。"""
        from babeldoc.format.pdf.document_il.midend import overflow_source_fallback as osf
        if getattr(self, "_overflow_fallback_rejections", None) is None:
            self._overflow_fallback_rejections = {}
        if getattr(self, "_overflow_fallbacks", None) is None:
            self._overflow_fallbacks = []
        backup = list(getattr(paragraph, "overflow_source_backup", None) or [])
        source_text = osf.backup_text(backup)
        translated = paragraph.unicode
        ok, detail = osf.admission(paragraph, page, source_text, translated, backup)
        if ok:
            failure_status = paragraph.writeback_status
            paragraph.pdf_paragraph_composition = backup
            units = self.create_typesetting_units(paragraph, fonts)
            if units and all(unit.can_passthrough for unit in units):
                paragraph.pdf_paragraph_composition = self.create_passthrough_composition(units)
                paragraph.scale = 1.0
                paragraph.unicode = source_text
                paragraph.writeback_status = osf.CODE
                paragraph.writeback_reason = "hard_readable_floor_overflow"
                self._overflow_fallbacks.append({
                    "code": osf.CODE, "page_index": page.page_number, "paragraph_id": paragraph.debug_id,
                    "role": paragraph.layout_label, "category": detail, "source_text": source_text,
                    "translated_text": translated, "failure_status": failure_status, "_paragraph": paragraph,
                    "_translated": translated})
                return True
            paragraph.pdf_paragraph_composition = []
            detail = "source_not_passthrough"
        self._overflow_fallback_rejections[id(paragraph)] = detail
        return False

    def _enforce_overflow_fallback_cap(self, document) -> dict:
        """按页/文档上限检查降级；超限时整批撤销，恢复原失败状态（照旧 fail closed）。
        回执记录原始分母（每页段落数、整份段落数）；分块时整份上限推迟到合并统一执行。"""
        from babeldoc.format.pdf.document_il.midend import overflow_source_fallback as osf
        fallbacks = getattr(self, "_overflow_fallbacks", None) or []
        per_page = {page.page_number: sum(1 for p in page.pdf_paragraph if (p.unicode or "").strip())
                    for page in document.page}
        cap = osf.cap_violations([f["page_index"] for f in fallbacks], per_page)
        cap["status"] = "none" if not fallbacks else "applied"
        cap["document_cap_scope"] = osf.document_cap_scope()
        enforced = cap["violations"]
        if cap["document_cap_scope"] == osf.DOCUMENT_CAP_SCOPE_CHUNK_MERGE:
            # 分块：本块只执行按页上限；整份上限在合并时按原始整份段落数统一执行（见 chunked_translation）。
            enforced = [v for v in cap["violations"] if v.get("scope") == "page"]
            cap["deferred_violations"] = [v for v in cap["violations"] if v.get("scope") != "page"]
        if fallbacks and enforced:
            cap["status"] = "revoked_cap_exceeded"
            if getattr(self, "_overflow_fallback_rejections", None) is None:
                self._overflow_fallback_rejections = {}
            for record in fallbacks:
                paragraph = record["_paragraph"]
                paragraph.pdf_paragraph_composition = []
                paragraph.unicode = record["_translated"]
                paragraph.writeback_status = record["failure_status"]
                paragraph.writeback_reason = "hard_readable_floor_overflow"
                self._overflow_fallback_rejections[id(paragraph)] = osf.CAP_CODE
        return cap

    def typesetting_document(self, document: il_version_1.Document):
        try:return self._typesetting_document(document)
        except BaseException:
            if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
                from pdf_group_source_style import release_current_runtime
                release_current_runtime('typesetting_failure')
            raise

    def _typesetting_document(self, document: il_version_1.Document):
        self._overflow_fallbacks = []
        self._overflow_fallback_rejections = {}
        # 原有的排版逻辑
        if self.translation_config.progress_monitor:
            with self.translation_config.progress_monitor.stage_start(
                self.stage_name,
                len(document.page) * 2,
            ) as pbar:
                # 预处理：获取所有段落的最优缩放因子
                self.preprocess_document(document, pbar)

                for page in document.page:
                    self.translation_config.raise_if_cancelled()
                    self.render_page(page)
                    pbar.advance()
        else:
            for page in document.page:
                self.translation_config.raise_if_cancelled()
                self.render_page(page)

        cap = self._enforce_overflow_fallback_cap(document)
        failures = self._writeback_failures(document)
        fallbacks = [] if cap["status"] != "applied" else [
            {k: v for k, v in record.items() if not k.startswith("_")}
            for record in getattr(self, "_overflow_fallbacks", None) or []]
        receipt = {"stage": "post_typesetting",
                   "status": "blocked" if failures else "needs_review" if fallbacks else "passed",
                   "page_count": len(document.page), "failures": failures,
                   "source_fallbacks": fallbacks, "source_fallback_count": len(fallbacks),
                   "source_fallback_cap": cap,
                   "scope": "explicit_native_writeback_failures_only"}
        path = self.translation_config.get_working_file_path("typesetting_writeback_report.json")
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if failures:
            raise RuntimeError(f"Native typesetting writeback failed for {len(failures)} paragraphs; see {path}")

    def render_page(self, page: il_version_1.Page):
        fonts: dict[
            str | int,
            il_version_1.PdfFont | dict[str, il_version_1.PdfFont],
        ] = {f.font_id: f for f in page.pdf_font if f.font_id}
        page_fonts = {f.font_id: f for f in page.pdf_font if f.font_id}
        for k, v in self.font_mapper.fontid2font.items():
            fonts[k] = v
        for xobj in page.pdf_xobject:
            if xobj.xobj_id is not None:
                fonts[xobj.xobj_id] = page_fonts.copy()
                for font in xobj.pdf_font:
                    if font.font_id:
                        fonts[xobj.xobj_id][font.font_id] = font
        if (
            page.page_number == 0
            and self.translation_config.watermark_output_mode
            == WatermarkOutputMode.Watermarked
        ):
            self.add_watermark(page)
        try:
            para_index = index.Index()
            para_map = {}
            #
            valid_paras = [
                p
                for p in page.pdf_paragraph
                if p.box
                and all(c is not None for c in [p.box.x, p.box.y, p.box.x2, p.box.y2])
            ]

            for i, para in enumerate(valid_paras):
                para_map[i] = para
                para_index.insert(i, box_to_tuple(para.box))

            for i, p_upper in para_map.items():
                if not (p_upper.box and p_upper.box.y is not None):
                    continue

                # Calculate paragraph height and set required gap accordingly
                para_height = p_upper.box.y2 - p_upper.box.y
                required_gap = 0.5 if para_height < 36 else 3

                check_area = il_version_1.Box(
                    x=p_upper.box.x,
                    y=p_upper.box.y - required_gap,
                    x2=p_upper.box.x2,
                    y2=p_upper.box.y,
                )

                candidate_ids = list(para_index.intersection(box_to_tuple(check_area)))

                conflicting_paras = []
                for para_id in candidate_ids:
                    if para_id == i:
                        continue
                    p_lower = para_map[para_id]
                    if not (
                        p_lower.box
                        and p_upper.box
                        and p_lower.box.x2 < p_upper.box.x
                        or p_lower.box.x > p_upper.box.x2
                    ):
                        conflicting_paras.append(p_lower)

                if conflicting_paras:
                    max_y2 = max(
                        p.box.y2
                        for p in conflicting_paras
                        if p.box and p.box.y2 is not None
                    )

                    new_y = max_y2 + required_gap
                    if p_upper.box and new_y < p_upper.box.y2:
                        p_upper.box.y = new_y
        except Exception as e:
            logger.warning(
                f"Failed to adjust paragraph positions on page {page.page_number}: {e}"
            )
        self._assign_baseline_ceilings(page)
        # 开始实际的渲染过程
        for paragraph in page.pdf_paragraph:
            self.render_paragraph(paragraph, page, fonts)

    @staticmethod
    def _assign_baseline_ceilings(page):
        from .table_figure_text import assign_baseline_ceilings
        try:
            assign_baseline_ceilings(page)
        except Exception as e:  # 几何异常时不上移（source_ceiling 置 0 余量），不阻断排版
            logger.warning(f"Failed to assign baseline ceilings on page {page.page_number}: {e}")
            for paragraph in page.pdf_paragraph:
                if getattr(paragraph, "source_baseline", None) is not None and paragraph.box:
                    paragraph.source_ceiling = paragraph.box.y2

    def add_watermark(self, page: il_version_1.Page):
        page_width = page.cropbox.box.x2 - page.cropbox.box.x
        page_height = page.cropbox.box.y2 - page.cropbox.box.y
        style = il_version_1.PdfStyle(
            font_id="base",
            font_size=6,
            graphic_state=il_version_1.GraphicState(),
        )
        text = f"本文档由 funstory.ai 的开源 PDF 翻译库 BabelDOC {WATERMARK_VERSION} (http://yadt.io) 翻译，本仓库正在积极的建设当中，欢迎 star 和关注。"
        if self.translation_config.debug:
            text += "\n 当前为 DEBUG 模式，将显示更多辅助信息。请注意，部分框的位置对应原文，但在译文中可能不正确。"
        page.pdf_paragraph.append(
            il_version_1.PdfParagraph(
                first_line_indent=False,
                box=il_version_1.Box(
                    x=page.cropbox.box.x + page_width * 0.05,
                    y=page.cropbox.box.y,
                    x2=page.cropbox.box.x2,
                    y2=page.cropbox.box.y2 - page_height * 0.05,
                ),
                vertical=False,
                pdf_style=style,
                pdf_paragraph_composition=[
                    il_version_1.PdfParagraphComposition(
                        pdf_same_style_unicode_characters=il_version_1.PdfSameStyleUnicodeCharacters(
                            unicode=text,
                            pdf_style=style,
                        ),
                    ),
                ],
                xobj_id=-1,
            ),
        )

    @staticmethod
    def _preserves_vertical_source(paragraph, units) -> bool:
        """原始竖排及已拒绝翻译的abandon元数据保留；新译文仍执行字号门。"""
        preserve = (getattr(paragraph, "vertical", False)
                    or (getattr(paragraph, "layout_label", "") == "abandon"
                        and getattr(paragraph, "writeback_status", None) in (None, "rejected")))
        return bool(preserve and units and all(unit.can_passthrough for unit in units))

    def render_paragraph(
        self,
        paragraph: il_version_1.PdfParagraph,
        page: il_version_1.Page,
        fonts: dict[
            str | int,
            il_version_1.PdfFont | dict[str, il_version_1.PdfFont],
        ],
    ):
        if paragraph.source_text_matrix is not None:
            return self._render_in_original_text_frame(paragraph,page,fonts)
        had_composition = any(
            not (composition.pdf_same_style_unicode_characters
                 and composition.pdf_same_style_unicode_characters.debug_info)
            for composition in paragraph.pdf_paragraph_composition
        )
        typesetting_units = self.create_typesetting_units(paragraph, fonts)
        if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
            from pdf_group_source_style import reviewed_paragraph_facts
            facts=reviewed_paragraph_facts(paragraph)
            if facts is None:raise ValueError('paragraph source/style provenance missing at render')
            if facts['mode']=='preserve_original':
                if not all(unit.can_passthrough for unit in typesetting_units):
                    raise ValueError('protected source identity unexpectedly needs translation typesetting')
                paragraph.scale=1.0
                paragraph.pdf_paragraph_composition=self.create_passthrough_composition(typesetting_units)
                return
            if facts['mode']!='reviewed_fixed_layout':raise ValueError('unprojected current ordinary source')
            self._find_optimal_scale_and_layout(paragraph,page,typesetting_units,1.0,True,True)
            self._update_paragraph_render_order(paragraph)
            return
        needs_readable_retypeset = (
            self._has_hard_readable_floor(paragraph)
            and self._readable_scale_floor(paragraph) > 1.0
            and not self._preserves_vertical_source(paragraph, typesetting_units)
        )
        # 如果所有单元都可以直接传递且字号已经可读，则直接传递
        if all(unit.can_passthrough for unit in typesetting_units) and not needs_readable_retypeset:
            paragraph.scale = 1.0
            paragraph.pdf_paragraph_composition = self.create_passthrough_composition(
                typesetting_units,
            )
        else:
            # 使用预计算的缩放因子进行重排版
            precomputed_scale = (
                paragraph.optimal_scale if paragraph.optimal_scale is not None else 1.0
            )

            # 如果有单元无法直接传递，则进行重排版
            paragraph.pdf_paragraph_composition = []
            self.retypeset_with_precomputed_scale(
                paragraph, page, typesetting_units, precomputed_scale
            )

            if paragraph.layout_label == "diagram_node" and paragraph.pdf_paragraph_composition:
                self._center_diagram_characters(paragraph)
            # 可读下限仍放不下的短结构片段：按 overflow_source_fallback 准入条件保留原文字形。
            if (not paragraph.pdf_paragraph_composition
                    and str(getattr(paragraph, "writeback_reason", "") or "") == "hard_readable_floor_overflow"):
                self._apply_overflow_source_fallback(paragraph, page, fonts)
            # 重排版后，重新设置段落各字符的 render order
            self._update_paragraph_render_order(paragraph)

        if had_composition and not paragraph.pdf_paragraph_composition:
            status = str(getattr(paragraph, "writeback_status", "") or "")
            if not status.endswith(("_failed", "_rerender_required")):
                paragraph.writeback_status = "empty_paragraph_writeback_failed"
                paragraph.writeback_reason = "nonempty_input_composition_rendered_empty"

    def _render_in_original_text_frame(self, paragraph, page, fonts):
        """在原文字矩阵的局部坐标排布，完成后将全部字形映回页面。"""
        a,b,c,d,e,f=(float(v) for v in paragraph.source_text_matrix.split())
        det=a*d-b*c
        if not all(math.isfinite(v) for v in (a,b,c,d,e,f)) or abs(det)<1e-12:
            raise ValueError('invalid original text frame')
        def inverse(x,y):return ((d*(x-e)-c*(y-f))/det,(-b*(x-e)+a*(y-f))/det)
        def forward(x,y):return (a*x+c*y+e,b*x+d*y+f)
        def map_box(box, transform):
            points=[transform(x,y) for x in (box.x,box.x2) for y in (box.y,box.y2)]
            return Box(x=min(p[0] for p in points),y=min(p[1] for p in points),x2=max(p[0] for p in points),y2=max(p[1] for p in points))
        def chars(comp):
            if comp.pdf_character:return [comp.pdf_character]
            if comp.pdf_formula:return comp.pdf_formula.pdf_character
            if comp.pdf_same_style_characters:return comp.pdf_same_style_characters.pdf_character
            if comp.pdf_line:return comp.pdf_line.pdf_character
            return []
        frame=paragraph.source_text_matrix
        original_box=paragraph.box
        paragraph.source_text_matrix=None
        paragraph.box=(Box(*(float(v) for v in paragraph.source_local_bbox.split())) if paragraph.source_local_bbox is not None else map_box(original_box,inverse))
        for comp in paragraph.pdf_paragraph_composition:
            for char in chars(comp):
                char.box=map_box(char.box,inverse)
                if char.visual_bbox:char.visual_bbox.box=map_box(char.visual_bbox.box,inverse)
                char.source_text_matrix=None
            if comp.pdf_formula:comp.pdf_formula.box=map_box(comp.pdf_formula.box,inverse)
        try:self.render_paragraph(paragraph,page,fonts)
        finally:paragraph.source_text_matrix=frame
        for comp in paragraph.pdf_paragraph_composition:
            for char in chars(comp):
                x,y=char.box.x,char.box.y
                ox,oy=forward(x,y)
                char.source_text_matrix=' '.join(format(v,'.12g') for v in (a,b,c,d,ox,oy))
                char.source_local_bbox=' '.join(format(v,'.12g') for v in (0,0,char.box.x2-x,char.box.y2-y))
                char.box=map_box(char.box,forward)
                if char.visual_bbox:char.visual_bbox.box=map_box(char.visual_bbox.box,forward)
            if comp.pdf_formula:comp.pdf_formula.box=map_box(comp.pdf_formula.box,forward)
        paragraph.box=original_box

    @staticmethod
    def _center_diagram_characters(paragraph):
        box = Typesetting._toc_title_layout_box(paragraph)
        comps = paragraph.pdf_paragraph_composition
        if not all(c.pdf_character for c in comps):
            raise ValueError("diagram node output must be ordinary text characters")
        chars = [c.pdf_character for c in comps]
        low = min(c.box.y for c in chars)
        high = max(c.box.y2 for c in chars)
        dy = (box.y + box.y2 - low - high) / 2
        rows = []
        for char in chars:
            row = next((row for row in rows if abs(row[0].box.y-char.box.y)<.1), None)
            if row is None: rows.append([char])
            else: row.append(char)
        for row in rows:
            dx = (box.x+box.x2-min(c.box.x for c in row)-max(c.box.x2 for c in row))/2
            for char in row:
                b = char.box
                char.box = Box(b.x+dx,b.y+dy,b.x2+dx,b.y2+dy)
                if char.visual_bbox:
                    v = char.visual_bbox.box
                    char.visual_bbox.box = Box(v.x+dx,v.y+dy,v.x2+dx,v.y2+dy)
        paragraph.box = box

    def _get_width_before_next_break_point(
        self, typesetting_units: list[TypesettingUnit], scale: float
    ) -> float:
        if not typesetting_units:
            return 0
        if typesetting_units[0].can_break_line:
            return 0

        total_width = 0
        for unit in typesetting_units:
            if unit.can_break_line:
                return total_width * scale
            total_width += unit.width
        return total_width * scale

    @staticmethod
    def _numeric_token_span(units, scale, mixed_space=0.0):
        """返回有界数字串的单元数/宽度，跨公式占位符但不跨换行。"""
        parts = []
        ends = []
        width = 0.0
        previous = None
        for unit in units[:48]:
            text = unit.try_get_unicode()
            if text is None and getattr(unit, "formular", None):
                text = "".join(c.char_unicode or "" for c in unit.formular.pdf_character)
            if not text or "\n" in text or "\r" in text:
                break
            if not parts and not re.match(r"[0-9pPrR<>=≤≥+−(（-]", text):
                return 0, 0.0
            parts.append(text)
            if (previous and previous.is_cjk_char != unit.is_cjk_char
                    and not previous.mixed_character_blacklist and not unit.mixed_character_blacklist
                    and previous.try_get_unicode() != " " and text != " "):
                width += mixed_space
            width += unit.width * scale
            previous = unit
            ends.append((sum(map(len, parts)), len(parts), width))
            if sum(map(len, parts)) >= 128:
                break
        text = "".join(parts)
        match = re.match(
            r"[（(]?(?:[pPrR]\s*[<>=≤≥]\s*)?[<>=≤≥]?\s*[+−-]?"
            r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
            r"(?:[eE][+−-]?[0-9]+)?"
            r"(?:[%‰]| ?(?:GiB|GB|MB|MHz|Hz|kg|mg|ms|cm|mm|km|mL|μm|µm|°C|s|K)(?![A-Za-z]))?",
            text,
        )
        if not match or (match.end() < len(text) and text[match.end()].isascii() and text[match.end()].isalpha()):
            return 0, 0.0
        for end, count, width in ends:
            if end == match.end():
                return count, width
        # 不拆分一个原始公式单元来拼接数字串。
        return 0, 0.0

    def _layout_typesetting_units(
        self,
        typesetting_units: list[TypesettingUnit],
        box: Box,
        scale: float,
        line_skip: float,
        paragraph: il_version_1.PdfParagraph,
        use_english_line_break: bool = True,
    ) -> tuple[list[TypesettingUnit], bool]:
        """布局排版单元。

        Args:
            typesetting_units: 要布局的排版单元列表
            box: 布局边界框
            scale: 缩放因子

        Returns:
            tuple[list[TypesettingUnit], bool]: (已布局的排版单元列表，是否所有单元都放得下)
        """
        reviewed=None
        if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
            from pdf_group_source_style import reviewed_paragraph_facts,natural_size,LINE_HEIGHT_RATIO
            reviewed=reviewed_paragraph_facts(paragraph)
            if reviewed is None or reviewed['mode']!='reviewed_fixed_layout' or scale!=1.0:
                raise ValueError('fixed complete source layout requires exact scale1')
            fixed_step=natural_size(reviewed['metadata'])*LINE_HEIGHT_RATIO
        # 计算字号众数
        font_sizes = []
        for unit in typesetting_units:
            if unit.font_size:
                font_sizes.append(unit.font_size)
            if unit.char and unit.char.pdf_style and unit.char.pdf_style.font_size:
                font_sizes.append(unit.char.pdf_style.font_size)
        font_sizes.sort()
        font_size = statistics.mode(font_sizes)

        space_width = (
            self.font_mapper.base_font.char_lengths("你", font_size * scale)[0] * 0.5
        )

        # 计算行高（使用众数）
        unit_heights = (
            [unit.height for unit in typesetting_units] if typesetting_units else []
        )
        if not unit_heights:
            avg_height = 0
        elif len(unit_heights) == 1:
            avg_height = unit_heights[0] * scale
        else:
            try:
                avg_height = statistics.mode(unit_heights) * scale
            except statistics.StatisticsError:
                # 如果没有众数（所有值都出现相同次数），则使用平均值
                avg_height = sum(unit_heights) / len(unit_heights) * scale

        # 首行可能有比正文更高的原文引用号/公式。按可进入首行的单元预留
        # 高度，避免它永远越过上边界，使整段一路缩到兜底字号。
        first_line_height = avg_height
        first_line_width = space_width * 4 if paragraph.first_line_indent else 0
        for unit in typesetting_units:
            if unit.try_get_unicode() == "\n":
                break
            next_width = unit.width * scale
            if first_line_width + next_width > box.x2 - box.x:
                break
            first_line_height = max(first_line_height, unit.height * scale)
            first_line_width += next_width

        # 初始化到首行下边界。
        current_x = box.x
        current_y = box.y2 - first_line_height
        box = copy.deepcopy(box)
        if reviewed is not None:
            metadata=reviewed['metadata']
            left=metadata.get('source_native_host_left_origin')
            if type(left) not in (float,int):raise ValueError('actual source native host left origin required')
            box.x=left;current_x=left+metadata['first_line_indent_pt']
            current_y=reviewed['page_height']-metadata['source_first_baseline']
        # 单行表格/图内文字：首行落到原文基线。源字框下沿含下伸部，直接从框底排会让
        # 整行下移约 0.3 em 压到下一行。只上移、最多半个行高，上边界同步放宽同样距离。
        # 上移量再受 source_ceiling 限制（正上方相邻行/表格线渲染后不会低于的位置，见
        # table_figure_text.assign_baseline_ceilings）：放宽后的上边界不越过它，行顶越界即报不合身。
        top_limit = box.y2
        anchor = getattr(paragraph, "source_baseline", None) if reviewed is None else None
        if anchor is not None:
            lift = float(anchor) - current_y
            if 0 < lift <= 0.5 * first_line_height:
                ceiling = getattr(paragraph, "source_ceiling", None)
                if ceiling is not None:
                    lift = min(lift, max(0.0, float(ceiling) - box.y2))
                if lift > 0:
                    current_y += lift
                    top_limit = box.y2 + lift
        # box.y -= avg_height * (line_spacing - 1.01) # line_spacing 已被替换为 line_skip
        line_height = 0
        current_line_heights = []  # 存储当前行所有元素的高度

        # 存储已排版的单元
        typeset_units = []
        reviewed_placements = {}
        all_units_fit = True
        last_unit: TypesettingUnit | None = None
        line_ys = [current_y]
        if paragraph.first_line_indent and reviewed is None:
            current_x += space_width * 4
        # 遍历所有排版单元；数字串内部不再触发英语词或标点换行。
        numeric_end = 0
        for i, unit in enumerate(typesetting_units):
            # 显式换行是译文结构，不生成控制字符字形。连续换行保留空行；
            # 行高沿用自然换行规则，后续文字仍接受相同的边界检查。
            if unit.try_get_unicode() == "\n":
                heights = current_line_heights or [unit.height * scale]
                current_y -= fixed_step if reviewed is not None else max(statistics.mode(heights) * line_skip, max(heights) * 1.05)
                current_x = box.x+(reviewed['metadata']['hanging_indent_pt'] if reviewed is not None else 0)
                current_line_heights = []
                line_height = 0.0
                last_unit = None
                line_ys.append(current_y)
                continue
            # 计算当前单元在当前缩放下的尺寸
            unit_width = unit.width * scale
            unit_height = unit.height * scale

            # 跳过行首的空格
            if current_x == box.x and unit.is_space:
                continue

            if (
                last_unit  # 有上一个单元
                and last_unit.is_cjk_char ^ unit.is_cjk_char  # 中英文交界处
                and (
                    last_unit.box
                    and last_unit.box.y
                    and current_y - 0.1
                    <= last_unit.box.y2
                    <= current_y + line_height + 0.1
                )  # 在同一行，且有垂直重叠
                and not last_unit.mixed_character_blacklist  # 不是混排空格黑名单字符
                and not unit.mixed_character_blacklist  # 同上
                and current_x > box.x  # 不是行首
                and unit.try_get_unicode() != " "  # 不是空格
                and last_unit.try_get_unicode() != " "  # 不是空格
                and last_unit.try_get_unicode()
                not in [
                    "。",
                    "！",
                    "？",
                    "；",
                    "：",
                    "，",
                ]
            ):
                current_x += space_width * 0.5
            numeric_width = 0.0
            if i >= numeric_end:
                count, numeric_width = self._numeric_token_span(typesetting_units[i:], scale, space_width * .5)
                numeric_end = i + count
                if numeric_width > box.x2 - box.x + 0.01:
                    return [], False
            in_numeric = i < numeric_end
            if use_english_line_break and not in_numeric:
                width_before_next_break_point = self._get_width_before_next_break_point(
                    typesetting_units[i:], scale
                )
            else:
                width_before_next_break_point = 0
            # 见 english_word_break_extent：拉丁目标语言按整词宽度判断，英译中保持原式。
            english_word_extent = english_word_break_extent(
                self.is_cjk, unit_width, width_before_next_break_point
            )

            # 开括号/引号必须预留后续词所需的空间。英语换行检查本身
            # 也计入首字符宽度，因此这里用同样的前视量，避免括号留下而词移走。
            opening_width = 0.0
            if unit.is_cannot_appear_in_line_end_punctuation and not in_numeric:
                opening_width = unit_width
                previous = unit
                for offset, following in enumerate(typesetting_units[i+1:i+33], start=i+1):
                    if following.try_get_unicode() == "\n":
                        return [], False
                    opening_width += following.width * scale
                    if (previous.is_cjk_char != following.is_cjk_char
                            and not previous.mixed_character_blacklist
                            and not following.mixed_character_blacklist
                            and not previous.is_space and not following.is_space):
                        opening_width += space_width * .5
                    previous = following
                    if following.is_space or following.is_cannot_appear_in_line_end_punctuation:
                        continue
                    if use_english_line_break:
                        opening_width += self._get_width_before_next_break_point(typesetting_units[offset:], scale)
                    break
                if opening_width > box.x2-box.x + .01:
                    return [], False

            # 如果当前行放不下这个元素，换行
            if (not unit.is_hung_punctuation or numeric_width > 0) and (
                (current_x + unit_width > box.x2)
                or (numeric_width and current_x + numeric_width > box.x2)
                or (
                    use_english_line_break
                    and current_x + english_word_extent > box.x2
                )
                or (
                    opening_width
                    and current_x + opening_width > box.x2
                )
            ):
                # 换行
                current_x = box.x+(reviewed['metadata']['hanging_indent_pt'] if reviewed is not None else 0)
                if not current_line_heights:
                    return [], False
                max_height = max(current_line_heights)
                mode_height = statistics.mode(current_line_heights)

                current_y -= fixed_step if reviewed is not None else max(mode_height * line_skip, max_height * 1.05)
                line_ys.append(current_y)
                line_height = 0.0
                current_line_heights = []  # 清空当前行高度列表

                # 检查是否超出底部边界
                if current_y < box.y - 0.01:
                    all_units_fit = False
                    # 这里不要 break，继续排版剩余内容

                if unit.is_space:
                    line_height = max(line_height, unit_height)
                    continue

            # relocate(x,y) 的 y 是字框下边；上方已减平均字高，
            # 再减一次字高会把可容纳的一行判为溢出并丢段。
            if current_y < box.y - 0.01:
                all_units_fit = False
            if current_y + unit_height > top_limit + 0.01:
                all_units_fit = False

            # 放置当前单元
            relocated_unit = unit.relocate(current_x, current_y, scale)
            typeset_units.append(relocated_unit)
            if reviewed is not None:
                reviewed_placements[id(relocated_unit)] = (unit, current_x, current_y, len(line_ys)-1)

            # 添加当前单元的高度到当前行高度列表
            if not unit.is_space:
                current_line_heights.append(unit_height)

            prev_x = current_x
            # 更新 x 坐标
            current_x = relocated_unit.box.x2
            if prev_x > current_x:
                logger.warning(f"坐标回绕！！！TypesettingUnit: {unit.box}, ")

            last_unit = relocated_unit

        if reviewed is not None:
            groups={}
            for unit in typeset_units:
                line_id=reviewed_placements[id(unit)][3]
                groups.setdefault(line_id,[]).append(unit)
            alignment=reviewed['metadata']['alignment']
            for index,row in enumerate(groups.values()):
                low=min(u.box.x for u in row);high=max(u.box.x2 for u in row)
                if alignment=='center':offset=(box.x+box.x2-low-high)/2;spacing=0
                elif alignment=='right':offset=box.x2-high;spacing=0
                elif alignment=='justified' and index<len(groups)-1 and len(row)>1:
                    offset=0;spacing=(box.x2-high)/(len(row)-1)
                else:offset=spacing=0
                for at,unit in enumerate(row):
                    original,layout_x,layout_y,_=reviewed_placements[id(unit)]
                    replacement=original.relocate(layout_x+offset+spacing*at,layout_y,1.0)
                    typeset_units[typeset_units.index(unit)]=replacement
        if self._has_excessive_typesetting_overlap(typeset_units):
            all_units_fit = False

        return typeset_units, all_units_fit

    def _has_excessive_typesetting_overlap(
        self,
        typeset_units: list[TypesettingUnit],
        threshold: float = 0.55,
    ) -> bool:
        boxes = [
            unit.box
            for unit in typeset_units
            if unit.box
            and not unit.is_space
            and unit.box.x is not None
            and unit.box.y is not None
            and unit.box.x2 is not None
            and unit.box.y2 is not None
        ]
        overlap_count = 0
        for index, box_a in enumerate(boxes):
            area_a = max((box_a.x2 - box_a.x) * (box_a.y2 - box_a.y), 1.0)
            for box_b in boxes[index + 1 :]:
                x0 = max(box_a.x, box_b.x)
                y0 = max(box_a.y, box_b.y)
                x1 = min(box_a.x2, box_b.x2)
                y1 = min(box_a.y2, box_b.y2)
                if x1 <= x0 or y1 <= y0:
                    continue
                area_b = max((box_b.x2 - box_b.x) * (box_b.y2 - box_b.y), 1.0)
                ratio = ((x1 - x0) * (y1 - y0)) / min(area_a, area_b)
                if ratio >= threshold:
                    overlap_count += 1
                    break
            if overlap_count >= 3:
                return True
        return False

    def create_typesetting_units(
        self,
        paragraph: il_version_1.PdfParagraph,
        fonts: dict[str, il_version_1.PdfFont],
    ) -> list[TypesettingUnit]:
        if not paragraph.pdf_paragraph_composition:
            return []
        result = []

        @cache
        def get_font(font_id: str, xobj_id: int | None):
            if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
                from pdf_group_source_style import current_registry
                alias=getattr(current_registry(),'font_aliases',{}).get(font_id)
                if alias is not None:return alias
            if xobj_id in fonts:
                font = fonts[xobj_id][font_id]
            else:
                font = fonts[font_id]
            return font

        for composition in paragraph.pdf_paragraph_composition:
            if composition is None:
                continue
            if composition.pdf_line:
                result.extend(
                    [
                        TypesettingUnit(char=char)
                        for char in composition.pdf_line.pdf_character
                    ],
                )
            elif composition.pdf_character:
                result.append(
                    TypesettingUnit(
                        char=composition.pdf_character,
                        debug_info=paragraph.debug_info,
                    ),
                )
            elif composition.pdf_same_style_characters:
                result.extend(
                    [
                        TypesettingUnit(char=char)
                        for char in composition.pdf_same_style_characters.pdf_character
                    ],
                )
            elif composition.pdf_same_style_unicode_characters:
                style = composition.pdf_same_style_unicode_characters.pdf_style
                if style is None:
                    logger.warning(
                        f"Style is None. "
                        f"Composition: {composition}. "
                        f"Paragraph: {paragraph}. ",
                    )
                    continue
                font_id = style.font_id
                if font_id is None:
                    logger.warning(
                        f"Font ID is None. "
                        f"Composition: {composition}. "
                        f"Paragraph: {paragraph}. ",
                    )
                    continue
                font = get_font(font_id, paragraph.xobj_id)
                if composition.pdf_same_style_unicode_characters.unicode:
                    previous_count=len(result)
                    result.extend(
                        [
                            TypesettingUnit(
                                unicode=char_unicode,
                                font=self.font_mapper.map(
                                    font,
                                    " " if char_unicode == "\n" else char_unicode,
                                ),
                                original_font=font,
                                font_size=style.font_size,
                                style=style,
                                xobj_id=paragraph.xobj_id,
                                debug_info=composition.pdf_same_style_unicode_characters.debug_info
                                or False,
                                vertical=bool(getattr(paragraph, "vertical", False)),
                            )
                            for char_unicode in composition.pdf_same_style_unicode_characters.unicode.replace("\r\n", "\n").replace("\r", "\n")
                        ],
                    )
                    if os.environ.get('PAPER_TRANSLATION_SOURCE_STYLE_CONTRACT'):
                        from pdf_group_source_style import bind_natural_typesetting_units
                        bind_natural_typesetting_units(composition,result[previous_count:])
            elif composition.pdf_formula:
                result.extend([TypesettingUnit(formular=composition.pdf_formula)])
            else:
                logger.error(
                    f"Unknown composition type. "
                    f"Composition: {composition}. "
                    f"Paragraph: {paragraph}. ",
                )
                continue
        result = list(
            filter(
                lambda x: x.unicode is None or x.font is not None,
                result,
            ),
        )

        if any(x.width < 0 for x in result):
            logger.warning("有排版单元宽度小于 0，请检查字体映射是否正确。")
        return result

    def create_passthrough_composition(
        self,
        typesetting_units: list[TypesettingUnit],
    ) -> list[PdfParagraphComposition]:
        """从排版单元创建直接传递的段落组合。

        Args:
            typesetting_units: 排版单元列表

        Returns:
            段落组合列表
        """
        composition = []
        for unit in typesetting_units:
            if unit.formular:
                # 对于公式单元，直接创建包含完整公式的组合
                composition.append(PdfParagraphComposition(pdf_formula=unit.formular))
            else:
                # 对于字符单元，使用原有逻辑
                chars, curves, forms = unit.passthrough()
                composition.extend(
                    [PdfParagraphComposition(pdf_character=char) for char in chars],
                )
        return composition

    def _dialogue_layout_box(self, paragraph, page, box):
        """按附近同栏正文与实际障碍限制短对话右界，不扩表格、图注或代码。"""
        label = (getattr(paragraph, "layout_label", None) or "").lower()
        text = (getattr(paragraph, "unicode", None) or "").strip()
        size = float(getattr(getattr(paragraph, "pdf_style", None), "font_size", None) or 0)
        if (not self.is_cjk or not _is_body_text_label(label) or size <= 0
                or not text.startswith("“") or not text.endswith("”")
                or len(text) > 100 or box.y2 - box.y > size * 1.5):
            return box
        peers = []
        for other in page.pdf_paragraph:
            other_box = other.box
            other_label = (getattr(other, "layout_label", None) or "").lower()
            other_size = float(getattr(getattr(other, "pdf_style", None), "font_size", None) or 0)
            if (other is paragraph or other_box is None or not _is_body_text_label(other_label)
                    or getattr(other, "xobj_id", None) != getattr(paragraph, "xobj_id", None)
                    or not size * .9 <= other_size <= size * 1.1
                    or not 0 <= box.x - other_box.x <= size * 2
                    or abs((box.y + box.y2 - other_box.y - other_box.y2) / 2) > size * 10):
                continue
            peers.append(other_box.x2)
        if not peers:
            return box
        right = min(max(peers), self.get_max_right_space(box, page) - 5)
        if right <= box.x2:
            return box
        # 表格/图形检测区域可以含有误标为正文的短文本，禁止横跨其边界。
        for region in getattr(page, "page_layout", []):
            region_box = region.box
            region_label = (getattr(region, "class_name", None) or "").lower()
            if region_box is not None and ("table" in region_label or region_label in {"figure", "image", "chart"}):
                if (region_box.x < right and region_box.x2 > box.x
                        and region_box.y < box.y2 and region_box.y2 > box.y):
                    return box
        return Box(x=box.x, y=box.y, x2=right, y2=box.y2)

    def _institution_layout_box(self, paragraph, page, box):
        """名录单位最多借用三行及144pt宽的同卡片空白，不跨相邻文字/照片。"""
        size = float(getattr(getattr(paragraph, "pdf_style", None), "font_size", None) or 0)
        if size <= 0 or getattr(page, "cropbox", None) is None:
            return box
        right = min(self.get_max_right_space(box, page, page_right_ratio=.95)-5, box.x+max(144, box.x2-box.x))
        right = max(box.x2, right)
        # 横向扩展后再次按扩展后的列宽查找下方障碍。
        wide = Box(box.x, box.y, right, box.y2)
        bottom = max(self.get_max_bottom_space(wide, page)+2,
                     page.cropbox.box.y+10, box.y2-size*4.5)
        bottom = min(box.y, bottom)
        return Box(box.x, bottom, right, box.y2)

    def get_max_right_space(self, current_box: Box, page, page_right_ratio=.9) -> float:
        """获取段落右侧最大可用空间

        Args:
            current_box: 当前段落的边界框
            page: 当前页面

        Returns:
            可以扩展到的最大 x 坐标
        """
        # 获取页面的裁剪框作为初始最大限制
        max_x = page.cropbox.box.x2 * page_right_ratio

        # 检查所有可能的阻挡元素
        for para in page.pdf_paragraph:
            if para.box == current_box or para.box is None:  # 跳过当前段落
                continue
            # 只考虑在当前段落右侧且有垂直重叠的元素
            if para.box.x > current_box.x and not (
                para.box.y >= current_box.y2 or para.box.y2 <= current_box.y
            ):
                max_x = min(max_x, para.box.x)
        for char in page.pdf_character:
            if char.box.x > current_box.x and not (
                char.box.y >= current_box.y2 or char.box.y2 <= current_box.y
            ):
                max_x = min(max_x, char.box.x)
        # 检查图形
        for figure in page.pdf_figure:
            if figure.box.x > current_box.x and not (
                figure.box.y >= current_box.y2 or figure.box.y2 <= current_box.y
            ):
                max_x = min(max_x, figure.box.x)

        return max_x

    def get_max_bottom_space(self, current_box: Box, page: il_version_1.Page) -> float:
        """获取段落下方最大可用空间

        Args:
            current_box: 当前段落的边界框
            page: 当前页面

        Returns:
            可以扩展到的最小 y 坐标
        """
        # 获取页面的裁剪框作为初始最小限制
        min_y = page.cropbox.box.y * 1.1

        # 检查所有可能的阻挡元素
        for para in page.pdf_paragraph:
            if para.box == current_box or para.box is None:  # 跳过当前段落
                continue
            # 只考虑在当前段落下方且有水平重叠的元素
            if para.box.y2 < current_box.y and not (
                para.box.x >= current_box.x2 or para.box.x2 <= current_box.x
            ):
                min_y = max(min_y, para.box.y2)
        for char in page.pdf_character:
            if char.box.y2 < current_box.y and not (
                char.box.x >= current_box.x2 or char.box.x2 <= current_box.x
            ):
                min_y = max(min_y, char.box.y2)
        # 检查图形
        for figure in page.pdf_figure:
            if figure.box.y2 < current_box.y and not (
                figure.box.x >= current_box.x2 or figure.box.x2 <= current_box.x
            ):
                min_y = max(min_y, figure.box.y2)

        return min_y

    def _update_paragraph_render_order(self, paragraph: il_version_1.PdfParagraph):
        """
        重新设置段落各字符的 render order
        主 render order 等于 paragraph 的 renderorder，sub render order 从 1 开始自增
        """
        if not hasattr(paragraph, "render_order") or paragraph.render_order is None:
            return

        main_render_order = paragraph.render_order
        sub_render_order = 1

        # 遍历段落的所有组成部分
        for composition in paragraph.pdf_paragraph_composition:
            # 检查单个字符
            if composition.pdf_character:
                char = composition.pdf_character
                char.render_order = main_render_order
                char.sub_render_order = sub_render_order
                sub_render_order += 1
