"""Double6-maintained port of PPT Master v4.8.0 ``template_fill_pptx`` analysis/check/scaffold.

Upstream removed Template Fill Native in v5.0.0. The read-only parts (slide library analysis,
SmartArt/chart reading, edit-safety, plan checking, scaffolding, notes/transition helpers) are kept
here under the original MIT license so the PM6 backend keeps v4.8 parity; writing goes through the
PPT Master v6.7.0 roundtrip instead of the removed applier. Shared helpers (``pptx_transitions``,
``svg_to_pptx.pptx_package.notes``) are imported from the vendored v6.7.0 core.
"""
from __future__ import annotations

import sys

from ..roundtrip import pm6_root

_scripts = str(pm6_root() / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

from .analyzer import analyze_pptx  # noqa: E402
from .checker import check_plan  # noqa: E402
from .scaffolder import scaffold_plan  # noqa: E402

__all__ = ["analyze_pptx", "check_plan", "scaffold_plan"]
