"""Experimental template-fill backend on PPT Master v6.7 Edit-Native roundtrip (exp/pm6-template)."""
from .library import analyze_pptx, check_plan, scaffold_plan
from .roundtrip import PM6Error, apply_plan

__all__ = ["analyze_pptx", "apply_plan", "check_plan", "scaffold_plan", "PM6Error"]
