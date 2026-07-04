# Runtime Dependencies

This skill does not vendor full PDFMathTranslate-next, BabelDOC, pdf2zh-skill, Poppler, PyMuPDF, TeX Live, Docker, or model-serving projects. Treat those as external runtime tools configured by the user environment.

Set the model API information before the first real run. The skill intentionally ships without a default model. If `LOCAL_TRANSLATION_PROVIDER` / `--provider` is set, or exactly one provider-specific API key is present, the runtime can infer `base_url` from `references/provider-base-urls.md`; otherwise set `LOCAL_TRANSLATION_BASE_URL` or pass `--base-url`.

```bash
export LOCAL_TRANSLATION_MODEL="your-model-name"
export DEEPSEEK_API_KEY="your-api-key"
```

Then run this from the installed skill root on every fresh install:

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
- OpenAI-compatible Chat Completions endpoint configured by `LOCAL_TRANSLATION_BASE_URL` / `--base-url`, inferred from `LOCAL_TRANSLATION_PROVIDER` / `--provider`, or inferred from a single provider-specific API key.
- Translation model configured by `LOCAL_TRANSLATION_MODEL` or `--model`.
- API key from `LOCAL_TRANSLATION_API_KEY`, provider-specific API key env vars such as `DEEPSEEK_API_KEY`, or `--api-key`.

The runtime may start `scripts/translation_compat_proxy.py` automatically as an internal adapter for PDF backend calls. This proxy forwards to the configured Chat Completions endpoint and records translation retry/quality evidence; it does not require the user to deploy a local model server.

## Optional Diagnostic Tools

- PyMuPDF for text extraction, layout inspection, and visual reports.
- reportlab for readable QA fallback PDFs.
- pypdf for vector bilingual PDF composition and text extraction fallback.
- Poppler tools for text bounding-box audits when available.
- External compatible `pdf2zh-skill` checkout for LaTeX-source direct rendering via `PAPER_TRANSLATION_PDF2ZH_SKILL_PATH`.
- TeX Live or Docker for LaTeX direct-render compile checks.
- Network access to `https://arxiv.org/e-print/<id>` when arXiv source auto-download is enabled and no local LaTeX source is found.

## Third-Party Notice

This skill does not vendor or redistribute PDF backend runtime code. Users provide compatible runtime dependencies outside this repository.

Depending on the selected backend and optional diagnostics, third-party components may include a `pdf2zh` executable, a compatible `pdf2zh_next` Python module, PDFMathTranslate-next, PDFMathTranslate, BabelDOC, PyMuPDF, Poppler tools, LaTeX tooling, Docker images, or compatible components required by the user's backend installation.

All third-party dependencies are governed by their own licenses and are not redistributed in this repository.

## Review Notes

- Missing optional audit tools reduce observability; they do not lower the expected final layout quality.
- Agent-side vision is not a runtime requirement. Non-vision agents should rely on generated audit artifacts and delivery gates.
- Runtime caches and generated backend working directories must stay outside the open-source skill package.
- API keys should be provided through environment variables such as `LOCAL_TRANSLATION_API_KEY`, provider-specific API key env vars, or CLI flags and must not be committed.
- `render_manifest.json` records the resolved backend and preflight report path so release evidence can be reproduced on another machine.
