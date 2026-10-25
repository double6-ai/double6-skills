# 独立脚注号后正文分隔逗号回归夹具（PR #25 review27）

`arxiv2501.00659-p1-footnote1.json` 不是 PDF，也不是 pickle：它是 review27 冻结的同 SHA 预分类页快照
（`PRE_STYLES_PAGE.pkl`，sha256 `ae2a157f…8d63`，由已验 3f5aa5b 源码在本机从真实源 PDF 解析得到，进入
BabelDOC「Parse Formulas and Styles」之前）中**单个段落**的逐字符几何（`box` / `visual_bbox`）、字体 ID、字号、
源字形编号，以及运行时目标字体 `FontMapper.has_char` 的结果。测试只用这些数据重建 IL，然后调用真实的
`StylesAndFormulas.process_page_formulas`。

字段：`lines` 中每个字符为
`[unicode, box.x, box.y, box.x2, box.y2, vbox.x, vbox.y, vbox.x2, vbox.y2, font_id, font_size, vertical, formula_layout_id, pdf_character_id]`。

| 夹具 | 论文 | 页 | 来源 | 许可（已在 arXiv 摘要页核对，同 `tests/fixtures/inline_math`） |
|---|---|---|---|---|
| `arxiv2501.00659-p1-footnote1.json` | Irie, *Why Are Positional Encodings Nonessential for Deep Autoregressive Transformers? Revisiting a Petroglyph* | 原文 p1 "…LLM-era…decade" 段，脚注锚 `1`（链接 `Hfootnote.1`） | https://arxiv.org/abs/2501.00659 | CC BY 4.0 |

源 PDF sha256 `cd3604e020f8e74d2014e91a9eb88df6d93a6b3cf2d0cd6dccde7c062384f255`：脚注号 `1` 原点 y696.9490、7.9701pt、
flags5（上标）；其后逗号原点 y700.9080、11.0177pt、flags4，与前方正文同基线。修复前该逗号与合成空格被
“公式中间逗号”续接规则一并锁进脚注公式 `1, `。
