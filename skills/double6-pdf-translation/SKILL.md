---
name: double6-pdf-translation
description: Layout-preserving English PDF and academic paper translation into Simplified Chinese. Use when a local-execution agent must run a PDF backend, preserve layout, protect terms/spans, and emit QA evidence. Do not use for plain text translation, summaries, web pages, or non-PDF conversion.
---

# Double6 PDF Translation

将英文 PDF 翻译为准确、可读的简体中文，并尽量保持原始版式。该 skill 使用外部高保真 PDF 后端，叠加文本/视觉 QA gate 和可复现的修复证据；本仓库不内置 PDFMathTranslate-next、BabelDOC 或 pdf2zh-skill 源码树。

## 运行

在新机器或新 agent 安装后，先在 skill 根目录运行：

```bash
python scripts/preflight_runtime.py --strict
```

必须先修复 required 级失败，再开始翻译。可选诊断依赖缺失只会减少自动检查和辅助报告，不会降低外部 PDF 后端本身的版式保持能力。

```bash
python scripts/run_pdf_translation.py <input-file.pdf> \
  --output-dir <output-dir>
```

大模型调用使用 OpenAI-compatible Chat Completions 接口。默认推荐 endpoint 为 `https://api.deepseek.com`、模型为 `deepseek-v4-flash`，但任何兼容 OpenAI 接口的商业、本地或自托管服务都可通过 CLI 参数或 `LOCAL_TRANSLATION_BASE_URL`、`LOCAL_TRANSLATION_MODEL`、`LOCAL_TRANSLATION_API_KEY` 覆盖。密钥解析优先级为 `LOCAL_TRANSLATION_API_KEY`、`OPENAI_API_KEY`、`DEEPSEEK_API_KEY`。

## 最小依赖

需要暴露一个兼容的外部 PDF 后端：

```bash
pdf2zh --help
```

后端解析顺序为：`--pdf2zh-binary`、`PAPER_TRANSLATION_PDF2ZH_BINARY`、module backend，然后是 `PATH` 中的 `pdf2zh`。`PAPER_TRANSLATION_PDF2ZH_SKILL_PATH` 仅用于外部 LaTeX 直接渲染器。PyMuPDF、Poppler、reportlab、pypdf 只用于可选诊断、辅助抽取或降级产物。

## 输出

输出目录包含 `translated.pdf`、可选双语 PDF、`translation.md`、`render_manifest.json`、后端元数据、版式/审计报告，以及术语和 protected span 证据。

## LaTeX 源码优先

默认启用 LaTeX-first 自动发现：

- 如果用户显式传入 `--latex-source` / `--source-override`，优先使用该 `.tex`。
- 否则扫描 `PAPER_TRANSLATION_LATEX_SOURCE_HINT`、`PAPER_TRANSLATION_LATEX_SOURCE_ROOTS`、`--latex-source-root` 和 PDF 相邻的 `source/`、`paper_source/`、`latex/`、`arxiv/` 等目录。
- 如果本地没有找到主 `.tex`，先抽取 PDF 文本并识别 arXiv 编号；识别成功时尝试下载 `https://arxiv.org/e-print/<id>` 并选择主 `.tex`。
- 如果没有 arXiv 编号、下载失败、解包失败或源码不可编译，就记录 `source_manifest.json` / `direct_latex_render_manifest.json` 中的原因，并回退到正常 PDF 解析/后端路径。
- 可用 `--no-latex-autodiscovery` 关闭 LaTeX 自动发现；可用 `--no-arxiv-source-autodownload` 或 `PAPER_TRANSLATION_ARXIV_SOURCE_AUTODOWNLOAD=0` 禁止 arXiv 源码下载。

## Agent 能力适配

该 skill 不要求 agent 自带视觉模型。视觉/版式判断应优先依赖脚本生成的 `visual_layout_report.json`、`pymupdf_layout_audit.json`、`layout_structure_gate.json` 和 `render_manifest.json` gate，而不是依赖 agent 直接看截图。

- 有 PyMuPDF、Poppler、reportlab、pypdf 时，可以生成更完整的诊断证据和辅助产物。
- 没有视觉模型但能运行本地 shell 的 agent，也应读取 JSON/Markdown 证据并按 gate 状态决策。
- 缺少这些可选工具时，主 PDF 翻译路径仍可运行；只是自动发现版式问题和生成辅助报告的能力会减少。
- `--skip-visual-eval` 用于跳过较慢的可选视觉检查。
- 没有网络的环境应关闭或接受 arXiv 源码下载失败回退，并使用本地/可达的 OpenAI-compatible endpoint。

## 翻译规则

- 使用简体中文。
- 保持学术、准确、可读的表达。
- 保留公式、URL、DOI、代码、引用编号、图表编号、数据集名、模型名、邮箱地址和拉丁字母人名。
- 常见缩写首次出现时可按需展开，例如 `LLMs（大型语言模型）`。
- 保留目录/章节索引的换行边界、页码列和数字顺序。
- 如果提取出的文本很少或为空，应报告需要 OCR，不要编造内容。
- 如果版式保真度不足，应输出诊断和修复证据，不要接受退化 PDF。

## 参考

- 翻译较长学术内容前，阅读 `references/academic-translation-policy.md`。
- 人工修订术语时，使用 `references/glossary-template.tsv`。
- 查看命令参数和失败处理时，阅读 `references/workflow.md`。
- 安装或审查本地运行时要求时，阅读 `references/runtime-dependencies.md`。

## 边界

该 skill 专用于高保真 PDF 翻译，不包含 benchmark runner 或私有测试报告，也不再分发第三方 PDF 后端源码。
