---
name: double6-pdf-translation
description: Translate English PDFs (academic papers, reports, technical documents) into accurate, layout-preserving Simplified Chinese. Produces a translated PDF plus a side-by-side bilingual PDF (Chinese on the left, source English on the right by default). Best for non-scanned, text-based PDFs.
---

# Double6 PDF Translation

将英文 PDF（论文、报告、技术文档等）翻译为准确、可读的简体中文，并尽量保持原始版式。翻译由高保真 PDF 后端完成，并叠加文本与视觉质量校验，确保成品可读、版式稳定。

> ⚠️ **适用范围**：本 skill 只针对**非扫描版 PDF**。对于扫描版 / 图像版 PDF，可能翻译失败或效果较差，请谨慎使用。

## 运行

在新机器或新 agent 安装后，先配置 OpenAI-compatible Chat Completions 服务。不要假设用户已经部署本地模型，也不要使用内置默认模型。模型名必须由用户通过参数或环境变量明确指定；如果设置了 `LOCAL_TRANSLATION_PROVIDER` / `--provider`，或只检测到一个厂商专属 API key，运行时可以按 `references/provider-base-urls.md` 的候选表自动推断 `base_url`。

```bash
export DEEPSEEK_API_KEY="your-api-key"
export LOCAL_TRANSLATION_MODEL="your-model-name"
```

然后在 skill 根目录运行：

```bash
python scripts/preflight_runtime.py --strict
```

必须先修复 required 级失败，再开始翻译。可选诊断依赖缺失只会减少自动检查和辅助报告，不会降低外部 PDF 后端本身的版式保持能力。

```bash
python scripts/run_pdf_translation.py <input-file.pdf> \
  --output-dir <output-dir>
```

也可以直接在命令中传入 `--provider`、`--base-url`、`--model`、`--api-key`。`--base-url` 和 `LOCAL_TRANSLATION_BASE_URL` 永远优先于候选表推断；`LOCAL_TRANSLATION_API_KEY` 是泛用 key，只有搭配 `LOCAL_TRANSLATION_PROVIDER` / `--provider` 时才会推断厂商 URL。没有可推断或显式的 `base_url`、没有 `model` 或没有 API key 时，preflight 会阻止正式翻译。

运行时可能会自动启动内置 `translation_compat_proxy.py`，用于把 PDF 后端的碎片翻译请求接入已配置的 OpenAI-compatible 服务，并执行 JSON 输出兼容、正文翻译重试和质量统计。它不是要求用户本地部署模型；如需调试，可用 `--translation-compat-proxy on|off|auto` 或 `PAPER_TRANSLATION_COMPAT_PROXY` 控制。

常用场景：

```bash
# 普通 PDF 翻译
python scripts/run_pdf_translation.py paper.pdf --output-dir paper-zh

# 网络受限环境：关闭 arXiv 源码自动下载，只使用本地 PDF/源码
python scripts/run_pdf_translation.py paper.pdf --output-dir paper-zh \
  --no-arxiv-source-autodownload

# 已有 LaTeX 源码：显式指定主 tex 文件
python scripts/run_pdf_translation.py paper.pdf --output-dir paper-zh \
  --latex-source paper_source/main.tex

# 诊断模式：只检查运行时配置和依赖，不开始翻译
python scripts/run_pdf_translation.py paper.pdf --output-dir paper-zh \
  --preflight-only
```

## 最小依赖

需要暴露一个兼容的外部 PDF 后端。推荐同时安装下列辅助包，以获得完整的文本抽取、版式审计、修复和双语拼接能力：

```bash
# 通过 venv 安装（推荐用 scripts/setup_venv.sh，已内置环境规避逻辑）
pip install pdf2zh_next pymupdf reportlab
```

| 包 | 是否必需 | 用途 |
|---|---|---|
| `pdf2zh_next` | **必需** | 高保真 PDF 翻译后端（`pdf2zh` 命令必须来自此包；PyPI 同名的旧 `pdf2zh` 不可用） |
| `pymupdf` | 推荐 | 文本抽取、版式/视觉审计、QA 门判定，以及最终中文件修复后的双语 PDF 重建 |
| `reportlab` | 推荐 | 渲染可读的 QA 修复 PDF（缺失仅降低自动诊断，不阻断主翻译） |

后端解析顺序为：`--pdf2zh-binary`、`PAPER_TRANSLATION_PDF2ZH_BINARY`、module backend，然后是 `PATH` 中的 `pdf2zh`。`PAPER_TRANSLATION_PDF2ZH_SKILL_PATH` 仅用于外部 LaTeX 直接渲染器。

注意：后端可执行文件**必须来自 `pdf2zh_next` 包**；PyPI 同名 `pdf2zh` 是另一个旧项目，CLI 不匹配（会报 `unrecognized arguments`）。安装用 `pip install pdf2zh_next`。

## 输出

普通交付只保留两份 PDF：

- `<原文件名>.zh.pdf`：最终中文单语 PDF。
- `<原文件名>.bilingual.pdf`：默认中文译文在左、英文原文在右的双语 PDF；可用 `--bilingual-layout en-left-zh-right` 切换旧布局。

输出目录还会保留 `render_manifest.json`、`backend_run_manifest.json`、`translation.md`、版式/审计报告、术语和 protected span 证据，供 agent 或开发者排查使用。面向普通用户汇报时，只列两份 PDF 和 manifest 路径；不要把 `backend_quality`、`tracking_incomplete`、`rerender_candidates`、术语表补全建议等内部 gate 明细当成“建议下一步”输出，除非用户明确要求调试或交付失败。

## LaTeX 源码优先

默认启用 LaTeX-first 自动发现：

- 如果用户显式传入 `--latex-source` / `--source-override`，优先使用该 `.tex`。
- 否则扫描 `PAPER_TRANSLATION_LATEX_SOURCE_HINT`、`PAPER_TRANSLATION_LATEX_SOURCE_ROOTS`、`--latex-source-root` 和 PDF 相邻的 `source/`、`paper_source/`、`latex/`、`arxiv/` 等目录。
- 如果本地没有找到主 `.tex`，只从 PDF 元数据和首页文本识别主 arXiv 编号；唯一主 ID 识别成功时尝试下载 `https://arxiv.org/e-print/<id>` 并选择主 `.tex`。不要从参考文献或全文正文中提取 arXiv ID 作为源码候选。
- 如果首页/元数据没有唯一 arXiv 编号、主 ID 下载失败、解包失败或源码不可编译，就记录 `source_manifest.json` / `direct_latex_render_manifest.json` 中的原因，并回退到正常 PDF 解析/后端路径。
- 可用 `--no-latex-autodiscovery` 关闭 LaTeX 自动发现；可用 `--no-arxiv-source-autodownload` 或 `PAPER_TRANSLATION_ARXIV_SOURCE_AUTODOWNLOAD=0` 禁止 arXiv 源码下载。

## Agent 能力适配

该 skill 不要求 agent 自带视觉模型。视觉/版式判断应优先依赖脚本生成的 `visual_layout_report.json`、`pymupdf_layout_audit.json`、`layout_structure_gate.json` 和 `render_manifest.json` gate，而不是依赖 agent 直接看截图。

- PyMuPDF、reportlab、Poppler 为推荐或可选的诊断/辅助工具。
- 没有视觉模型但能运行本地 shell 的 agent，也应读取 JSON/Markdown 证据并按 gate 状态决策。
- 缺少这些可选工具时，主 PDF 翻译路径仍可运行；只是自动发现版式问题、生成辅助报告或拼接标准双语件的能力会减少。
- `--skip-visual-eval` 用于跳过较慢的可选视觉检查。
- 没有网络的环境应关闭或接受 arXiv 源码下载失败回退，并使用本地/可达的 OpenAI-compatible endpoint。

## 翻译规则

- 使用简体中文。
- 保持学术、准确、可读的表达。
- 保留公式、URL、DOI、代码、引用编号、图表编号、数据集名、模型名、邮箱地址和拉丁字母人名。
- 常见缩写首次出现时可按需展开，例如 `LLMs（大型语言模型）`。
- 保留目录/章节索引的换行边界、页码列和数字顺序。
- 如果提取出的文本很少或为空，应报告需要 OCR，不要编造内容。
- 如果版式保真度不足、正文存在大段英文同文回退或 delivery gate 为 partial/blocking，应输出诊断和修复证据，不要接受退化 PDF。

## 参考

- 翻译较长学术内容前，阅读 `references/academic-translation-policy.md`。
- 人工修订术语时，使用 `references/glossary-template.tsv`。
- 查看命令参数和失败处理时，阅读 `references/workflow.md`。
- 安装或审查本地运行时要求时，阅读 `references/runtime-dependencies.md`。
- 在 Windows / WorkBuddy 环境安装失败、路径异常或文本层误判时，阅读 `references/known-pitfalls.md`。
- 查看厂商 API key 到 `base_url` 的候选映射时，阅读 `references/provider-base-urls.md`。

## 边界

该 skill 专用于高保真 PDF 翻译，不包含 benchmark runner 或私有测试报告，也不再分发第三方 PDF 后端源码。
