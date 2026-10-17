# 表格与图内文字夹具（PR #3）

每个 JSON 是用官方入口 `paper_translation_workflow.py candidate --route digital_pdf` 跑到
BabelDOC `ParagraphFinder.process_page` 入口时导出的单页逐字符几何（字符、字框、可见框、
字体 id、字号、XObject、绘制顺序）、填充/描边曲线、版面检测框和相关配置，再裁剪到表格或
插图区域。仓库沿用不提交 PDF 的约定，这里只保留几十 KB 的几何数据。

| 夹具 | 来源 | 许可 |
| --- | --- | --- |
| `usgs-mcs2024-p4-table1.json` | U.S. Geological Survey, *Mineral Commodity Summaries 2024*, p.4 Table 1（https://pubs.usgs.gov/periodicals/mcs2024/mcs2024.pdf） | 美国联邦政府作品，公有领域（17 U.S.C. §105） |
| `usgs-mcs2024-p2-figure1.json` | 同上，p.2 Figure 1 | 同上 |
| `arxiv2610.21653-p8-table1.json` | Jing, Xiong, Liu, Li, Zhang, "How Does Probabilistic Constellation Shaping Control Ranging Sidelobe Levels in ISAC?", arXiv:2610.21653, p.8 Table I | CC BY 4.0 |
| `arxiv2610.21759-p2-fig1.json` | arXiv:2610.21759, p.2 Fig. 1 及图注 | CC BY 4.0 |
| `arxiv2610.21759-p4-fig2.json` | arXiv:2610.21759, p.4 Fig. 2（Binary Quantizer 框图）及图注 | CC BY 4.0 |
| `arxiv2610.20087-p16-tables.json` | "Binary Cyclic Gradient Coding: Exact Recovery …", arXiv:2610.20087, p.16 Table II/III（数据集名与数值） | CC BY 4.0 |

字段：`chars` 每项为 `[unicode, box(4), visual_box(4), font_id, font_size, vertical, xobj_id, render_order]`，
坐标为 PDF 用户空间（左下原点）。`source` 记录文档与页码，`region` 为裁剪框。
