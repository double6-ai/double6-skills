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
| `arxiv2512.18979-p5-table2-header.json` | Liang Guoqiang, Sun Jian, Lin Gege, Zhang Shuo, *Research on Novelty Measurement Indicator of Academic Papers Based on the Atypical Recombination of Knowledge*, arXiv:2512.18979v1（2025-12-22，中文稿），https://arxiv.org/abs/2512.18979v1 ；原文第 5 页表 2 的表头行与唯一一行数据（来源与裁剪见下） | CC BY 4.0（https://creativecommons.org/licenses/by/4.0/ ，arXiv 摘要页 “view license” 链接）；按 CC BY 4.0 署名使用，**已修改**：只抽取并裁剪了下述几何片段 |

字段：`chars` 每项为 `[unicode, box(4), visual_box(4), font_id, font_size, vertical, xobj_id, render_order]`，
坐标为 PDF 用户空间（左下原点），保留调试输出的完整浮点精度：词间距按字符间隙与阈值比较，
舍入到三位小数会改变“subcategoriesfor”这类贴近阈值的词间判断，使夹具与真实运行不一致。`source` 记录文档与页码，`region` 为字符裁剪框。
`config` 为 `toc-safe` 版面配置（`--split-short-lines --short-line-split-factor 0.95 --no-merge-alternating-line-numbers`）。

### `arxiv2512.18979-p5-table2-header.json` 的来源、许可与抽取方式

- 原文：Liang Guoqiang, Sun Jian, Lin Gege, Zhang Shuo，*Research on Novelty Measurement Indicator of Academic Papers Based on the
  Atypical Recombination of Knowledge*，arXiv:2512.18979v1（2025-12-22 提交，arXiv 上只有 v1），https://arxiv.org/abs/2512.18979v1 。
  作者姓名与顺序照 arXiv 摘要页署名。
- 许可：CC BY 4.0（https://creativecommons.org/licenses/by/4.0/ ）。本夹具是该论文的**修改后片段**（抽取并裁剪，见下），按 CC BY 4.0 署名使用。
  更正：本夹具首次提交时 README 写作“原文许可页面未注明”，有误；arXiv 摘要页（abs 与 abs/…v1）的 “view license” 链接指向 CC BY 4.0。
- 源页：测试语料 `17-zh-tables-figure-arxiv2512.18979-p5-p10.pdf`（sha256 `eba2b59c…f4b6e7`）由 arXiv v1 PDF（sha256 `e47d7783…3023`）的
  原文第 5、10 页组成；语料第 1 页与 v1 第 5 页的内容流、668 个字符几何与页面框（`[0, 0, 595.35, 810.8]`）逐一相同。夹具取自语料第 1 页（= 原文第 5 页）。
- 工具：先用本仓库内置的 pdf2zh_next + BabelDOC 以 `--debug` 处理该语料 PDF（版面检测为 BabelDOC 内置的 ONNX DocLayout 模型，未用远程版面服务；默认版面配置），当时仓库 HEAD 为 main 8585737，
  得到 `ParagraphFinder.process_page` 的输入 IL `layout_generator.json`（sha256 `37204d2e…db46`，第 1 页共 652 个字符、63 个版面框、6 条曲线），
  再用测试工作区脚本 `gen_fixture.py` 按区域导出。
- 裁剪：保留字框中心落在 `[140, 58, 450, 98]`（x0, y0, x1, y1）内的字符，即表 2 的表头行（y≈84）与唯一的数据行（y≈64–67）；
  表题（y≈97–111）与正文均不在内。保留与该区域相交的 8 个版面框（`table` 5、`table_caption` 11、6 个 `fallback_line`）与中心落在区域内的
  2 条横线（y 94.96、77.66，即表 2 的顶线和表头下线）；字体表只保留用到的 FT14（Times New Roman）、FT29（方正书宋）。
- 保留文字：共 54 个字符。表头 19 个：组1、组2、均差*、校正p、下限、上限、拒绝原假设；数据行 35 个：健康科学、生命科学（8 个）和
  -0.018、0.000、-0.027、-0.008、TRUE（27 个）。
- 变换：无。坐标、字框、可见框、字号、绘制顺序均原样取自 BabelDOC IL（PDF 用户空间，左下原点，单位 pt），没有平移、缩放或舍入，
  保留完整浮点精度。IL 的字框是 BabelDOC 按字体度量从 PDF 推得，不是 PDF 原始指令。`config` 为上文的 `toc-safe` 配置；
  测试 `tests/test_table_value_columns.py` 同时用该配置和默认配置运行。
