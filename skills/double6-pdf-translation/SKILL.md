---
name: double6-pdf-translation
version: 1.0.4
description: Translate user-supplied text PDFs into Simplified Chinese and bilingual PDFs. Reads the PDF and only explicitly selected local LaTeX, sends extracted text to an explicitly approved OpenAI-compatible endpoint, runs local PDF/Python subprocesses, and writes outputs, diagnostics, and the default runtime cache under the chosen directory. Local proxy, arXiv download, Docker compilation, and external cache paths require explicit command-line opt-in.
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
---

# Double6 PDF Translation

将英文 PDF 翻译为简体中文，尽量保持原始版式，并通过文本与视觉门禁检查成品。

> ⚠️ **适用范围**：本 skill 只针对**非扫描版 PDF**。对于扫描版 / 图像版 PDF，可能翻译失败或效果较差，请谨慎使用。

## 运行

先配置用户选择的 OpenAI-compatible Chat Completions 服务；不得假设本地模型或使用内置
默认模型。模型必须显式指定，服务商 URL 推断规则见 `references/provider-base-urls.md`。

在 skill 根目录运行，并为本次调用显式传入 endpoint、模型和凭据：

```bash
python scripts/preflight_runtime.py --strict \
  --provider deepseek --model <model-name> --api-key-file <key-file>
# 用户确认目标 host 后才做带凭据的联网探测：追加 --allow-endpoint-check
```

先修复 required 级失败，再开始翻译；可选诊断依赖缺失只减少自动检查。

```bash
python scripts/run_pdf_translation.py <input-file.pdf> \
  --output-dir <output-dir> \
  --provider deepseek --model <model-name> --api-key-file <key-file>
```

也可用参数提供 provider、base URL、model 和 API key；缺任一必要配置时 preflight 必须阻断。
兼容代理、LaTeX 源码、离线模式和诊断参数见 `references/workflow.md`。

## 最小依赖

必须安装 `pdf2zh_next` 并提供其 `pdf2zh` 命令；推荐安装 PyMuPDF 与 reportlab：

```bash
# 通过专用 venv 安装（也可使用 scripts/setup_venv.sh）
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

只使用 `--latex-source` 或 `--latex-source-root` 显式批准的本地 LaTeX 源码。arXiv 和 Docker 默认关闭，分别只在用户
同意并显式传入 `--allow-arxiv-source-autodownload`、`--latex-compile-runtime docker` 时启用。

## 安全与副作用

- 权限为 `file_read`（用户 PDF／显式批准的可信源码）、`file_write`（默认仅 `--output-dir`）、
  `network`（获批模型 endpoint）和 `shell`（本地 Python／PDF 工具）；宿主必须按此最小授权。
- 发送文档前须确认 endpoint；key 不得写入日志或产物，子进程只继承白名单环境变量。
- 输入只读；输出、QA 中间件和本地质量记录只写 `--output-dir`。
- arXiv 与 Docker 只接受上述显式 opt-in，不得自动代用户开启。
- 本地兼容代理默认关闭；仅 `--translation-compat-proxy on` 会监听回环地址。`--engine-home` 可显式选择输出目录之外的缓存路径。
- 本地代理忽略调用方的认证头，向上游只使用本次显式配置的 key，避免成为任意凭据中继。

## 翻译规则

使用准确、可读的简体中文，保护公式、标识符、引用和专名；完整规则见
`references/academic-translation-policy.md`。文本层为空时报告需要 OCR；版式不足、大段同文
回退或 delivery gate 为 partial/blocking 时交付诊断，不能接受退化 PDF。

## 参考

工作流、依赖、平台陷阱、翻译政策、术语模板和服务商 URL 映射均在 `references/` 中按需读取。
