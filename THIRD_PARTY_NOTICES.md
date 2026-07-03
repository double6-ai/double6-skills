# Third-Party Notices

This repository does not vendor PDF backend runtime code.

`double6-pdf-translation` expects users to provide compatible runtime dependencies outside this repository. Depending on the selected backend and checks, those may include:

- A `pdf2zh` executable or compatible `pdf2zh_next` Python module for high-fidelity PDF translation.
- PDFMathTranslate-next, PDFMathTranslate, BabelDOC, or compatible components required by that backend installation.
- PyMuPDF for PDF text extraction, rendering, and layout audits.
- Poppler tools for independent PDF text/bounding-box checks.
- LaTeX tooling or a Docker image for LaTeX-source direct rendering.

All third-party dependencies are governed by their own licenses and are not redistributed in this repository.
