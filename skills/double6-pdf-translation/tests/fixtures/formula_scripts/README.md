# 公式上/下标层级回归夹具（PR #25 公式结构项）

`arxiv2610.21653-p8-vnmax.json` 不是 PDF：它是用官方入口 `paper_translation_workflow.py candidate --route digital_pdf`
处理 arXiv 2610.21653 原文 p8（CC BY 4.0，arXiv 摘要页已核对；输入 SHA-256 `36497e88…`）时，在 BabelDOC
「Parse Formulas and Styles」阶段开始前导出的**单个段落**逐字符几何。格式与 `../inline_math/` 相同，每个字符多一个
第 14 列 `pdf_character_id`：段落切分阶段按字距补入的合成空格没有源字形编号（`null`）。

段内 `namely V > V_n^max(U)`：基字 V（CMMI10 9.96）后紧跟一个合成空格，然后是上标 `max`（CMR7 6.97，抬高）
和叠放的下标 `n`（CMMI7 6.97，降低）。修复前合成空格让 `max` 不再被识别为角标，成为基线上的普通样式片段，
成品中 V_n^max 被压平为 “V maxn”（见 `tests/test_formula_structure_fidelity.py`）。
