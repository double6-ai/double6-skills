# 行边缘残片与目录结构夹具（realmodel-r1 问题 #3/#5）

每个 JSON 是用 BabelDOC 调试输出（`layout_generator.json`，即 `ParagraphFinder.process_page` 的输入）导出的
单页逐字符几何（字符、字框、可见框、字体 id、字号、XObject、绘制顺序）和版面检测框，字符裁剪到问题区域。
版面框保留整页全部条目且保持原顺序：两个同级框重叠时，旧逻辑的归属取决于 R-tree 的插入顺序，
裁掉其他框会让问题不再复现。仓库沿用不提交 PDF 的约定，这里只保留几十 KB 的几何数据。
格式与 `tests/fixtures/table_figure_text/` 相同。

| 夹具 | 来源 | 许可 |
| --- | --- | --- |
| `nist-ai100-1-p2-update-schedule.json` | NIST AI 100-1, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, 2023, "Update Schedule and Versions"（https://doi.org/10.6028/NIST.AI.100-1） | 美国联邦政府作品，公有领域（17 U.S.C. §105） |
| `nist-ai100-1-p3-toc-top.json` | 同上，Table of Contents 前 10 行 | 同上 |
| `nist-ai100-1-p3-list-of-tables.json` | 同上，List of Tables | 同上 |
| `arxiv2512.18979-p5-table2-header.json` | Liang et al., arXiv:2512.18979v1（2025）PDF 第 5 页表 2：只含表头 7 个统计量名称与一行数值的 54 个字符几何、表格与行框、两条横线（https://arxiv.org/abs/2512.18979） | 原文许可页面未注明；只取表头通用统计量名称与一行数值的最小几何片段，用于列锚点回归，不含正文 |

字段：`chars` 每项为 `[unicode, box(4), visual_box(4), font_id, font_size, vertical, xobj_id, render_order]`，
坐标为 PDF 用户空间（左下原点），保留调试输出的完整浮点精度：词间距按字符间隙与阈值比较，
舍入到三位小数会改变“subcategoriesfor”这类贴近阈值的词间判断，使夹具与真实运行不一致。`source` 记录文档与页码，`region` 为字符裁剪框。
`config` 为 `toc-safe` 版面配置（`--split-short-lines --short-line-split-factor 0.95 --no-merge-alternating-line-numbers`）。
`arxiv2512.18979-p5-table2-header.json` 由 17b 运行的 `layout_generator.json` 导出（裁剪框 `[140,58,450,98]`，完整浮点精度），版面框只保留与裁剪框相交的条目。
