# 行内公式折行回归夹具（PR #2）

这些 JSON 不是 PDF：它们是用官方入口 `paper_translation_workflow.py candidate --route digital_pdf`
处理真实论文时，在 BabelDOC「Parse Formulas and Styles」阶段开始前导出的**单个段落**
逐字符几何（`box` / `visual_bbox`）、字体 ID、字号、字体名，以及运行时目标字体
`FontMapper.has_char` 的结果。仓库不提交 PDF，测试只用这些几十 KB 的几何数据重建 IL，
然后调用真实的 `StylesAndFormulas.process_page`。

字段：`lines` 中每个字符为
`[unicode, box.x, box.y, box.x2, box.y2, vbox.x, vbox.y, vbox.x2, vbox.y2, font_id, font_size, vertical, formula_layout_id]`。

| 夹具 | 论文 | 页 | 来源 | 许可（已在 arXiv 摘要页核对） |
|---|---|---|---|---|
| `arxiv2501.00659-p2-nonautoregressive.json` | Irie, *Why Are Positional Encodings Nonessential for Deep Autoregressive Transformers? Revisiting a Petroglyph* | 原文 p2 右栏 "Non-Autoregressive Self-Attention" 段 | https://arxiv.org/abs/2501.00659 | CC BY 4.0 |
| `arxiv2501.00659-p3.json` | 同上 | 原文 p3 左栏 "We can straightforwardly check this…" 段 | https://arxiv.org/abs/2501.00659 | CC BY 4.0 |
| `arxiv2610.21231-p4-a.json` / `-p4-b.json` | Abin, Gohari, *On the Subadditivity of Mutual f-Information* | 原文 p4 Example 2 / Example 3 段 | https://arxiv.org/abs/2610.21231 | CC BY 4.0 |
| `arxiv2610.21759-p5.json` / `-p7.json` | Guo, He, Huang, He, *Model-Driven Deep Learning for Distributed Detection with Low-Bit Quantization* | 原文 p5 "Induced Joint Distribution…" 段 / p7 Theorem 2 段 | https://arxiv.org/abs/2610.21759 | CC BY 4.0 |

每个段落都包含一处被行切分合并到同一 `PdfLine` 的视觉折行，折行两侧都有行内公式；
修复前这些公式被归成一个跨行公式并吞并同行其余公式（见 `tests/test_inline_math_wrap.py`）。
