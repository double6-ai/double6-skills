"""Deck-wide design presets for `init --mode generate --design <preset>`.

Each preset is a complete palette (field, surface, primary, accent, second accent, hero gradient,
distinct chart series), a type ladder with hero numbers, and an imagery direction. Presets map to the vendored PPT Master v6.7.0 style
(`templates/styles/<style_id>`) and visual style (`references/visual-styles/<visual_style>.md`).
"""
from __future__ import annotations

TYPE_LADDER = {  # SVG px on the 1280x720 canvas; 1 px = 0.75 pt. Seven steps, hero numbers included.
    "hero": 112, "display": 60, "title": 36, "subtitle": 24, "body": 18, "label": 14, "caption": 12,
}

_NEUTRAL_LIGHT = {"text": "#141A22", "muted": "#566070", "line": "#DCE0E6"}
_NEUTRAL_DARK = {"text": "#F5F5F7", "muted": "#A6A6B0", "line": "#34343C"}

# Presets range from bold to elegant. Colour behaviour follows the mapped upstream style;
# chart_series are chosen so every pair stays visually distinct (CIE76 dE >= 25).
PRESETS: dict[str, dict] = {
    "consulting": {  # McKinsey/BCG-like: deep navy field + electric blue signal
        "style_id": "consulting-decision", "visual_style": "swiss-minimal", "theme": "light",
        "bg": "#FFFFFF", "surface": "#F1F4F9", "primary": "#051C2C", "accent": "#2251FF", "accent2": "#00A9F4",
        "gradient": ["#051C2C", "#123C69"],
        "chart_series": ["#2251FF", "#051C2C", "#00A9F4", "#A7B3C2"],
        "imagery": "architectural / city / people-at-work photos, duotone navy",
    },
    "investor-pitch": {  # Pitch.com-like: saturated indigo + coral, gradient heroes
        "style_id": "investor-pitch", "visual_style": "swiss-minimal", "theme": "light",
        "bg": "#FFFFFF", "surface": "#F4F2FF", "primary": "#2B1C8F", "accent": "#FF5A3C", "accent2": "#8B7CF6",
        "gradient": ["#2B1C8F", "#6D4AFF"],
        "chart_series": ["#FF5A3C", "#2B1C8F", "#8B7CF6", "#C3BCE8"],
        "imagery": "product-in-context photos, full-bleed with indigo scrim",
    },
    "product-launch": {  # Keynote-like: black stage, warm gold-to-coral light
        "style_id": "product-launch", "visual_style": "editorial", "theme": "dark",
        "bg": "#0A0A0D", "surface": "#17171D", "primary": "#24242C", "accent": "#F2B544", "accent2": "#FF6A3D",
        "gradient": ["#0A0A0D", "#2A1F12"],
        "chart_series": ["#F2B544", "#FF6A3D", "#9A9AA6", "#4F4F5C"],
        "imagery": "hero product shots on dark, big crops, edge bleed",
    },
    "operating-review": {  # data-journalism: ink navy + signal orange
        "style_id": "operating-review", "visual_style": "data-journalism", "theme": "light",
        "bg": "#FFFFFF", "surface": "#F3F6FA", "primary": "#0F2A4A", "accent": "#F26B38", "accent2": "#3D7DCA",
        "gradient": ["#0F2A4A", "#1D4E89"],
        "chart_series": ["#F26B38", "#0F2A4A", "#3D7DCA", "#B9C6D6"],
        "imagery": "operations / team photos, cool duotone",
    },
    "academic": {  # elegant: ink blue + terracotta on warm paper
        "style_id": "academic-research", "visual_style": "swiss-minimal", "theme": "light",
        "bg": "#FBFAF6", "surface": "#F1EEE6", "primary": "#1F3B4D", "accent": "#C0582B", "accent2": "#6E8F72",
        "gradient": ["#1F3B4D", "#2F5A6E"],
        "chart_series": ["#C0582B", "#1F3B4D", "#6E8F72", "#C9B8A6"],
        "imagery": "field / landscape / aerial photos, natural colour",
    },
    "training": {  # friendly bold: deep teal + tangerine, rounded
        "style_id": "workshop-teaching", "visual_style": "soft-rounded", "theme": "light",
        "bg": "#FFFBF3", "surface": "#FFF0DB", "primary": "#124E5C", "accent": "#FF8A3D", "accent2": "#5BB5C8",
        "gradient": ["#124E5C", "#1F7A8C"],
        "chart_series": ["#FF8A3D", "#124E5C", "#5BB5C8", "#F7C99B"],
        "imagery": "people collaborating, warm light, rounded crops",
    },
}
# Backward-compatible aliases (0.4.x names).
ALIASES = {"business": "consulting"}


def _tint(hex_color: str, amount: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mix = lambda c: round(c + (255 - c) * amount)  # noqa: E731
    return "#{:02X}{:02X}{:02X}".format(mix(r), mix(g), mix(b))


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    def ch(v: int) -> float:
        c = v / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _on(fill: str, base: dict) -> str:
    """Text colour that reads on ``fill``: white or the darkest ink available."""
    ink = "#0A0A0D" if base.get("theme") == "dark" else base.get("text", "#141A22")
    white = (1.05) / (_lum(fill) + 0.05)
    dark = (_lum(fill) + 0.05) / (_lum(ink) + 0.05)
    return "#FFFFFF" if white >= dark else ink


def resolve(name: str) -> dict:
    key = ALIASES.get(name, name)
    base = dict(PRESETS[key])
    neutral = _NEUTRAL_DARK if base.get("theme") == "dark" else _NEUTRAL_LIGHT
    base = {**neutral, **base}
    base["name"] = key
    base["tint"] = _tint(base["accent"], 0.88) if base.get("theme") != "dark" else "#1E1E26"
    base["chart_series"] = list(base["chart_series"])
    base["on_accent"] = _on(base["accent"], base)
    base["on_primary"] = _on(base["primary"], base)
    base["type"] = dict(TYPE_LADDER)
    return base


def names() -> tuple[str, ...]:
    return tuple(PRESETS) + tuple(ALIASES)
