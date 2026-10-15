"""Restrained deck-wide design presets for `init --mode generate --design <preset>`.

Every preset is one deck-wide palette: a neutral field, ONE primary and ONE accent, a neutral
ramp, and chart series derived from them. Chroma (max-min of RGB) is deliberately low (<= 0.45). Presets map to the vendored PPT Master v6.7.0 style
(`templates/styles/<style_id>`) and visual style (`references/visual-styles/<visual_style>.md`).
"""
from __future__ import annotations

TYPE_LADDER = {  # SVG px on the 1280x720 canvas; 1 px = 0.75 pt
    "display": 64, "title": 34, "subtitle": 24, "body": 18, "label": 14, "caption": 12,
}

_NEUTRAL = {"text": "#1E2733", "muted": "#5B6573", "line": "#D9DDE2"}

PRESETS: dict[str, dict] = {
    "consulting": {
        "style_id": "consulting-decision", "visual_style": "swiss-minimal",
        "bg": "#FFFFFF", "surface": "#F3F5F7", "primary": "#1F3A5F", "accent": "#3C7A78",
    },
    "investor-pitch": {
        "style_id": "investor-pitch", "visual_style": "swiss-minimal",
        "bg": "#F7F6F3", "surface": "#FFFFFF", "primary": "#22344F", "accent": "#3C7A78",
    },
    "product-launch": {
        "style_id": "product-launch", "visual_style": "editorial",
        "bg": "#F8F7F4", "surface": "#FFFFFF", "primary": "#16181C", "accent": "#B08D57",
    },
    "operating-review": {
        "style_id": "operating-review", "visual_style": "data-journalism",
        "bg": "#FFFFFF", "surface": "#EEF3F8", "primary": "#1F3A5F", "accent": "#2F6E9E",
    },
    "academic": {
        "style_id": "academic-research", "visual_style": "swiss-minimal",
        "bg": "#FAFAF7", "surface": "#F1F1EC", "primary": "#263B4F", "accent": "#8A5A44",
    },
    "training": {
        "style_id": "workshop-teaching", "visual_style": "soft-rounded",
        "bg": "#FFFDF8", "surface": "#F5F1E8", "primary": "#3D4A3F", "accent": "#B9853F",
    },
}
# Backward-compatible aliases (0.4.x names).
ALIASES = {"business": "consulting"}


def _tint(hex_color: str, amount: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c + (255 - c) * amount)  # noqa: E731
    return "#{:02X}{:02X}{:02X}".format(mix(r), mix(g), mix(b))


def resolve(name: str) -> dict:
    key = ALIASES.get(name, name)
    base = dict(PRESETS[key])
    base.update(_NEUTRAL)
    base["name"] = key
    base["tint"] = _tint(base["accent"], 0.88)
    # Chart series: accent for the focal series, then primary, then two neutral tints.
    base["chart_series"] = [base["accent"], base["primary"], _tint(base["primary"], 0.45), _tint(base["primary"], 0.7)]
    base["type"] = dict(TYPE_LADDER)
    return base


def names() -> tuple[str, ...]:
    return tuple(PRESETS) + tuple(ALIASES)
