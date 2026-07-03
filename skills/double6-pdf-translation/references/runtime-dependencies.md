# Runtime Dependencies

This skill does not vendor full PDFMathTranslate-next, BabelDOC, pdf2zh-skill, Poppler, PyMuPDF, TeX Live, Docker, or model-serving projects. Treat those as external runtime tools configured by the user environment.

Run this first from the installed skill root on every fresh install:

```bash
python scripts/preflight_runtime.py --strict
```

The preflight report is the runtime contract: required failures block real translation; optional warnings reduce automatic diagnostics or fallback rendering only.

## Required Runtime Surface

- Python 3.11-compatible interpreter for the scripts in `scripts/`.
- A high-fidelity PDF backend:
  - `--pdf2zh-binary /path/to/pdf2zh`, or
  - `PAPER_TRANSLATION_PDF2ZH_BINARY=/path/to/pdf2zh`, or
  - installed `pdf2zh_next` module used through `scripts/pdf2zh_backend.py`, or
  - `pdf2zh` executable on `PATH`.
- OpenAI-compatible Chat Completions endpoint. DeepSeek at `https://api.deepseek.com` is the default recommendation, not a hard dependency.
- Translation model configured by `LOCAL_TRANSLATION_MODEL`, defaulting to `deepseek-v4-flash`.
- API key from `LOCAL_TRANSLATION_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, or `--api-key`.

## Optional Diagnostic Tools

- PyMuPDF for text extraction, layout inspection, and visual reports.
- reportlab for readable QA fallback PDFs.
- pypdf for vector bilingual PDF composition and text extraction fallback.
- Poppler tools for text bounding-box audits when available.
- External compatible `pdf2zh-skill` checkout for LaTeX-source direct rendering via `PAPER_TRANSLATION_PDF2ZH_SKILL_PATH`.
- TeX Live or Docker for LaTeX direct-render compile checks.
- Network access to `https://arxiv.org/e-print/<id>` when arXiv source auto-download is enabled and no local LaTeX source is found.

## Review Notes

- Missing optional audit tools reduce observability; they do not lower the expected final layout quality.
- Agent-side vision is not a runtime requirement. Non-vision agents should rely on generated audit artifacts and delivery gates.
- Runtime caches and generated backend working directories must stay outside the open-source skill package.
- API keys should be provided through environment variables such as `LOCAL_TRANSLATION_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, or CLI flags and must not be committed.
- `render_manifest.json` records the resolved backend and preflight report path so release evidence can be reproduced on another machine.
