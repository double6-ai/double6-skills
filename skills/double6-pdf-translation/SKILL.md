---
name: double6-pdf-translation
version: 1.0.1
description: Translate English PDFs (academic papers, reports, technical documents) into accurate, layout-preserving Simplified Chinese. Produces a translated PDF plus a side-by-side bilingual PDF (Chinese on the left, source English on the right by default). Best for non-scanned, text-based PDFs.
metadata:
  openclaw:
    homepage: https://github.com/double6-ai/double6-skills/tree/main/skills/double6-pdf-translation
    emoji: "📑"
    requires:
      bins:
        - pdf2zh
      anyBins:
        - python3
        - python
        - py
    envVars:
      - name: LOCAL_TRANSLATION_PROVIDER
        required: false
        description: 可选的 OpenAI-compatible 服务商标识。
      - name: LOCAL_TRANSLATION_BASE_URL
        required: false
        description: 可选的 OpenAI-compatible API 地址；命令行参数也可提供。
      - name: LOCAL_TRANSLATION_MODEL
        required: false
        description: 翻译模型名；正式运行时必须通过环境变量或命令行显式指定。
      - name: LOCAL_TRANSLATION_API_KEY
        required: false
        description: 通用 API key；也可使用文档列出的服务商专用 key。
---

# Double6 PDF Translation

将英文 PDF 翻译为简体中文，尽量保持原始版式，并通过文本与视觉门禁检查成品。

> ⚠️ **适用范围**：本 skill 只针对**非扫描版 PDF**。对于扫描版 / 图像版 PDF，可能翻译失败或效果较差，请谨慎使用。

## 运行

先配置用户选择的 OpenAI-compatible Chat Completions 服务；不得假设本地模型或使用内置
默认模型。模型必须显式指定，服务商 URL 推断规则见 `references/provider-base-urls.md`。

```bash
export DEEPSEEK_API_KEY="your-api-key"
export LOCAL_TRANSLATION_MODEL="your-model-name"
```

然后在 skill 根目录运行：

```bash
python scripts/preflight_runtime.py --strict
```

先修复 required 级失败，再开始翻译；可选诊断依赖缺失只减少自动检查。

```bash
python scripts/run_pdf_translation.py <input-file.pdf> \
  --output-dir <output-dir>
```

也可用参数提供 provider、base URL、model 和 API key；缺任一必要配置时 preflight 必须阻断。
兼容代理、LaTeX 源码、离线模式和诊断参数见 `references/workflow.md`。

## 最小依赖

必须安装 `pdf2zh_next` 并提供其 `pdf2zh` 命令；推荐安装 PyMuPDF 与 reportlab：

```bash
# 通过 venv 安装（推荐用 scripts/setup_venv.sh，已内置环境规避逻辑）
pip install pdf2zh_next pymupdf reportlab
```

PyPI 的旧同名 `pdf2zh` 不兼容。后端解析顺序和可选工具职责见
`references/runtime-dependencies.md`。

## 输出

普通交付只保留两份 PDF：

- `<原文件名>.zh.pdf`：最终中文单语 PDF。
- `<原文件名>.bilingual.pdf`：默认中文译文在左、英文原文在右的双语 PDF；可用 `--bilingual-layout en-left-zh-right` 切换旧布局。

同时保留 `render_manifest.json`；内部 gate 明细仅在调试或失败时报告。

## LaTeX 与降级

优先使用显式指定或输入文件旁的本地 LaTeX 源码。arXiv 和 Docker 默认关闭，分别只在用户
同意并显式传入 `--allow-arxiv-source-autodownload`、`--latex-compile-runtime docker` 时启用。

## 安全与副作用

- 发送文档前须取得用户对模型 endpoint 的明确授权；key 不得写入日志或产物。
- 输入 PDF／源码只读；翻译和修复只写 `--output-dir`，通过 gate 后才选为交付文件。
- arXiv 与 Docker 只接受上述显式 opt-in，不得自动代用户开启。
- `PAPER_TRANSLATION_PDF2ZH_SKILL_PATH` 只接受用户确认可信的本地代码目录；不得自动查找或下载。

## Agent 能力适配

不要求 agent 自带视觉模型；按生成的报告决策。诊断工具缺失时的降级规则见
`references/workflow.md`。

## 翻译规则

使用准确、可读的简体中文，保护公式、标识符、引用和专名；完整规则见
`references/academic-translation-policy.md`。文本层为空时报告需要 OCR；版式不足、大段同文
回退或 delivery gate 为 partial/blocking 时交付诊断，不能接受退化 PDF。

## 参考

工作流、依赖、平台陷阱、翻译政策、术语模板和服务商 URL 映射均在 `references/` 中按需读取。

## 边界

该 skill 专用于高保真 PDF 翻译，不包含 benchmark runner 或私有测试报告，也不再分发第三方 PDF 后端源码。
