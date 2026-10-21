# 中译英（zh→en）测试夹具

夹具全部取自许可明确的真实中文论文 PDF（PDF 本身不入库）：

| 文件 | 来源 | 许可 | 内容 |
|---|---|---|---|
| `arxiv2512.18979_p5_chars.json` | arXiv:2512.18979（Liang et al.），原文第 5 页 | CC BY 4.0 | 两行两端对齐正文与表 1 前两行的逐字符几何（PyMuPDF rawdict 抽取，已换算为 PDF 用户坐标，y 轴向上） |
| `zh_text_samples.json` | arXiv:2601.14329（Zhao et al.）原文第 3 页 | CC0 1.0 | 一段中文正文原文；`en` 字段为本仓库回放用英文译文（人工撰写，非模型输出） |

来源与许可核对记录见测试语料目录的 SOURCES.md（PR #4 小节）。
