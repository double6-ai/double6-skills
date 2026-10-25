# 同一行拉丁词界（P2-7）测试夹具

`real_lines.json`：整行真实字形几何，取自许可明确的论文 PDF（PDF 本身不入库）。读取方式与审稿冻结测试相同：
`page.get_texttrace()` 的字形前进宽度框（PyMuPDF 页面坐标）与所在 span 字号，按 MuPDF rawdict 行框选取字形原点在行内的字形；
真实空格字形（如有）保留为字符。每行另存 `expected_legacy`（7112c8c 的 helper 结果）、`expected_new`（本修复）与
`mupdf_text`（MuPDF 自己的行文本，作为独立的空格判定参照）。

| 来源 | 许可 | 行 |
|---|---|---|
| arXiv:2501.00659（Irie）原件，SHA256 cd3604e0… | CC BY 4.0 | 第 5 页标题 “Excursion: Metascience Perspectives”（审稿冻结用例）与第 1 页若干行 |
| arXiv:2610.21653 原文 p8（语料 13） | CC BY 4.0 | 正文与公式行 |
| arXiv:2610.21231 原文 p1、p4（语料 11） | CC BY 4.0 | 标题、作者单位、小型大写字母节标题、含公式行 |
| arXiv:2610.21759 原文 p5、p7（语料 12） | CC BY 4.0 | 正文、小型大写字母节标题 |
| arXiv:2505.23884 原文 p1–3（语料 01） | CC BY 4.0 | 标题、作者、URL 行 |

来源与许可核对记录见测试语料目录的 SOURCES.md。
