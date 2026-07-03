# High-Fidelity PDF Translation Workflow

This workflow targets high-fidelity PDF layout preservation. The skill repository stays light by not vendoring full backend projects, but the runtime should still use a capable PDF translation backend and the built-in layout, QA, and repair evidence layers.

## Command

Fresh installs must configure an OpenAI-compatible model before preflight. The skill has no built-in default model, because users may use different commercial, local, or self-hosted providers. If `LOCAL_TRANSLATION_PROVIDER` / `--provider` is set, or exactly one provider-specific API key is present, the runtime can infer `base_url` from `references/provider-base-urls.md`; otherwise set `LOCAL_TRANSLATION_BASE_URL` or pass `--base-url`.

```bash
export LOCAL_TRANSLATION_MODEL="your-model-name"
export DEEPSEEK_API_KEY="your-api-key"
```

Then run preflight from the installed skill root:

```bash
python scripts/preflight_runtime.py --strict
```

```bash
python scripts/run_pdf_translation.py <input-file.pdf> \
  --output-dir <output-dir>
```

Options:

- `--pdf2zh-binary`: explicit `pdf2zh` executable. Resolution order is CLI value, `PAPER_TRANSLATION_PDF2ZH_BINARY`, module mode, then `PATH`.
- `--pdf2zh-backend`: backend launch mode. `path` uses a CLI executable; `module` uses `scripts/pdf2zh_backend.py` with an installed `pdf2zh_next` module. Default can be set with `PAPER_TRANSLATION_PDF2ZH_BACKEND`.
- `--preflight-only`: run runtime checks and write manifests without starting translation.
- `--skip-preflight`: diagnostic escape hatch; real release evidence should not use it.
- `--provider`: optional provider alias used to infer `base_url`, such as `deepseek`, `openai`, `qwen`, `kimi`, `siliconflow`, `glm`, `openrouter`, or `ark`.
- `--base-url`: OpenAI-compatible Chat Completions endpoint. Required unless `LOCAL_TRANSLATION_BASE_URL`, provider selection, or exactly one provider-specific API key can infer it.
- `--model`: translation model for that endpoint. Required unless `LOCAL_TRANSLATION_MODEL` is set.
- `--api-key`: API key. Resolution prefers `LOCAL_TRANSLATION_API_KEY`; if exactly one provider-specific key is set, that key is used. This flag overrides all environment defaults.
- `--timeout`: backend command timeout in seconds. Default: `3600`.
- `--temperature`: translation temperature. Default: `0.7`.
- `--latex-render-mode`: LaTeX-source primary rendering mode. `auto` keeps PDF backend fallback.
- `--latex-source-root`: additional local roots to scan for `.tex` source.
- `--no-arxiv-source-autodownload`: disable the fallback that extracts arXiv IDs from the PDF and downloads `https://arxiv.org/e-print/<id>`.
- `--visual-check-pages`: visual/layout audit page selection.
- `--skip-visual-eval`: skip expensive visual checks only when the user explicitly accepts draft-level observability.

Environment overrides:

- `LOCAL_TRANSLATION_BASE_URL`
- `LOCAL_TRANSLATION_PROVIDER`
- `LOCAL_TRANSLATION_MODEL`
- `LOCAL_TRANSLATION_API_KEY`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `DASHSCOPE_API_KEY`
- `MOONSHOT_API_KEY`
- `SILICONFLOW_API_KEY`
- `ZHIPUAI_API_KEY`
- `OPENROUTER_API_KEY`
- `ARK_API_KEY`
- `PAPER_TRANSLATION_PDF2ZH_BINARY`
- `PAPER_TRANSLATION_PDF2ZH_BACKEND`
- `PAPER_TRANSLATION_ENGINE_HOME`
- `PAPER_TRANSLATION_PDF2ZH_SKILL_PATH`
- `PAPER_TRANSLATION_ARXIV_SOURCE_AUTODOWNLOAD`

## LaTeX Source Selection

Normal runs are LaTeX-first when source is available:

1. Manual `--latex-source` / `--source-override` wins.
2. Environment hints and explicit `--latex-source-root` roots are scanned.
3. Adjacent PDF directories are scanned: the PDF directory plus `source/`, `paper_source/`, `latex/`, and `arxiv/`.
4. If local discovery misses, the skill extracts PDF text, looks for arXiv IDs, downloads `https://arxiv.org/e-print/<id>`, unpacks it under the output directory, and chooses the highest-scoring main `.tex`.
5. If no usable source is found or LaTeX direct rendering fails in `auto` mode, the pipeline records the failure evidence and falls back to normal PDF backend parsing/rendering.

Use `--latex-render-mode required` only when LaTeX direct rendering must succeed and PDF fallback should be treated as a failure.

## Agent Capability Modes

The runtime should work for local-execution agents that do not have a built-in vision model:

- Full diagnostic mode: Python, PDF backend, PyMuPDF, Poppler, pypdf, and reportlab are available, so the run can emit richer layout evidence and fallback artifacts.
- Headless evidence mode: the agent cannot visually inspect screenshots, but can read generated JSON/Markdown reports. It should decide from `render_manifest.json`, delivery gates, visual/layout audit JSON, and quality reports.
- Core translation mode: optional visual/layout dependencies are missing or `--skip-visual-eval` is used. The main PDF translation path still relies on the external PDF backend, but automatic problem detection is reduced.
- Network-restricted mode: arXiv source download or remote model calls may fail. The run should record the failure and fall back to local source/PDF backend paths where possible.

Do not require GUI tools, Preview, screenshots, or agent-side multimodal inspection for normal operation. If a human visual review is needed, record it as additional evidence, not as the only gate.

## Dependencies

Required runtime capability:

```bash
pdf2zh --help
```

The repository does not vendor PDFMathTranslate-next, BabelDOC, or pdf2zh-skill source trees. Use an external installation, package, virtual environment, or wrapper that exposes a compatible `pdf2zh` CLI. If you prefer Python module launch, install a compatible `pdf2zh_next` module and run with `--pdf2zh-backend module`.

If `pdf2zh --help` fails with `ModuleNotFoundError: No module named 'pdf2zh_next'`, the executable is present but the backend environment is incomplete. Fix the backend environment or point `--pdf2zh-binary` / `PAPER_TRANSLATION_PDF2ZH_BINARY` at a working executable before running translation.

Recommended optional tools:

- PyMuPDF for PDF text extraction and layout audits.
- pypdf for vector bilingual PDF composition and text extraction fallback.
- reportlab for readable fallback PDFs.
- Poppler tools for independent bbox/text checks.
- A CJK-capable font setup for rendered Chinese text.
- A local LaTeX toolchain or Docker image when translating from LaTeX sources.

## Output Contract

- `<input-stem>.zh.pdf`: final high-fidelity Chinese monolingual PDF.
- `<input-stem>.bilingual.pdf`: final bilingual PDF with original English on the left and Chinese translation on the right.
- `render_manifest.json`: selected outputs, backend command, quality gates, visual reports, and error evidence.
- `backend_run_manifest.json`: backend status and translation metadata.
- `layout_map.json`, `block_bridge.json`: layout and block correspondence evidence when backend tracking is available.
- `visual_layout_report.json`, `pymupdf_layout_audit.json`, `layout_structure_gate.json`: visual and structural audit evidence when checks are enabled.
- `translation.md`, `term_policy.json`, `entity_map.json`, `protected_spans.json`: text and terminology evidence.

Normal user-facing responses should mention only the two delivery PDFs and the manifest path. Do not surface internal `backend_quality`, `tracking_incomplete`, `rerender_candidates`, or glossary-completion recommendations as user next steps unless the user asks for diagnostics or the run failed.

## Failure Handling

- If the PDF backend is missing, install or expose a compatible backend rather than switching to a low-fidelity overlay path.
- If preflight fails, inspect `preflight_report.json`; do not use `--skip-preflight` unless you are intentionally bypassing diagnostics for a known-good environment.
- If the local model endpoint is unreachable, verify the model server outside Codex sandboxing before changing prompts.
- If visual or structural gates report layout risk, inspect the manifest and repair candidates before treating the PDF as final.
- If the document is scanned, OCR/layout recognition must be supplied before high-fidelity translation can be expected.
