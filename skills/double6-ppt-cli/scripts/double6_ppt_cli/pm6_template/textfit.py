"""Width-aware line breaking and fit estimation with real font metrics (CJK + Latin).

Fonts are resolved the way LibreOffice does on Linux (fontconfig substitution via ``fc-match``),
so the estimate tracks the LibreOffice render used as evidence. On hosts without fontconfig/Pillow
the engine degrades to a conservative per-character width model (CJK=1em, Latin=0.55em).
"""
from __future__ import annotations

import functools
import shutil
import subprocess
import unicodedata
from typing import Any

try:  # Pillow is optional at runtime; the heuristic fallback keeps the engine usable.
    from PIL import ImageFont
except Exception:  # pragma: no cover
    ImageFont = None  # type: ignore

SCALE = 20  # measure at 20x point size for sub-point precision
NO_LINE_START = set("，。、；：？！）》」』】〕〉,.;:?!)]}%‰’”…—·・ー")
NO_LINE_END = set("（《「『【〔〈([{‘“$￥")
DEFAULT_EA = "Noto Sans CJK SC"
DEFAULT_LATIN = "Liberation Sans"
MIN_FONT_SCALE = 0.70
EXPLICIT_SHRINK_FLOOR = 0.85


def is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


@functools.lru_cache(maxsize=256)
def font_file(family: str, ea: bool, bold: bool) -> tuple[str, int] | None:
    if not shutil.which("fc-match"):
        return None
    pattern = (family or (DEFAULT_EA if ea else DEFAULT_LATIN))
    if bold:
        pattern += ":bold"
    if ea:
        pattern += ":lang=zh-cn"
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}|%{index}", pattern], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return None
    if "|" not in out:
        return None
    path, index = out.rsplit("|", 1)
    return path, int(index or 0)


@functools.lru_cache(maxsize=512)
def _font(family: str, ea: bool, bold: bool, size_pt: float):
    if ImageFont is None:
        return None
    located = font_file(family, ea, bold)
    if not located:
        return None
    try:
        return ImageFont.truetype(located[0], max(1, int(round(size_pt * SCALE))), index=located[1])
    except Exception:
        return None


class Metrics:
    def __init__(self, props: dict[str, Any], scale: float = 1.0):
        self.size = props["sz"] * scale
        self.bold = bool(props.get("bold"))
        self.latin = props.get("latin") or ""
        self.ea = props.get("ea") or ""
        self.f_lat = _font(self.latin, False, self.bold, round(self.size, 2))
        self.f_ea = _font(self.ea, True, self.bold, round(self.size, 2))
        self.engine = "fontconfig" if (self.f_lat and self.f_ea) else "heuristic"

    def width(self, text: str) -> float:
        total = 0.0
        buf, buf_wide = "", None
        for ch in text + "\0":
            wide = is_wide(ch) if ch != "\0" else None
            if ch == "\0" or (buf and wide != buf_wide):
                total += self._seg(buf, bool(buf_wide))
                buf = ""
            if ch != "\0":
                buf += ch
                buf_wide = wide
        return total

    def _seg(self, seg: str, wide: bool) -> float:
        if not seg:
            return 0.0
        f = self.f_ea if wide else self.f_lat
        if f is not None:
            return f.getlength(seg) / SCALE
        return sum((1.0 if wide else 0.55) for _ in seg) * self.size

    def line_height(self, has_wide: bool, has_narrow: bool) -> float:
        h = 0.0
        for f, used in ((self.f_ea, has_wide), (self.f_lat, has_narrow or not has_wide)):
            if not used:
                continue
            if f is not None:
                asc, desc = f.getmetrics()
                h = max(h, (asc + desc) / SCALE)
            else:
                h = max(h, self.size * 1.25)
        return h or self.size * 1.2


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    word = ""
    for ch in text:
        if is_wide(ch) or ch in NO_LINE_START:
            if word:
                tokens.append(word)
                word = ""
            tokens.append(ch)
        elif ch == " ":
            word += ch
            tokens.append(word)
            word = ""
        else:
            if word.endswith(" "):
                tokens.append(word)
                word = ""
            word += ch
    if word:
        tokens.append(word)
    return tokens


def wrap(text: str, m: Metrics, first_width: float, width: float) -> list[str]:
    """Greedy line breaking with basic kinsoku (no line-start punctuation, no line-end opening bracket)."""
    if text == "":
        return [""]
    lines: list[str] = []
    cur = ""
    avail = first_width
    for tok in tokenize(text):
        candidate = cur + tok
        if not cur or m.width(candidate.rstrip()) <= avail + 0.01:
            cur = candidate
            continue
        # kinsoku: closing punctuation stays on the current line
        if tok and tok[0] in NO_LINE_START and len(tok) == 1:
            cur = candidate
            continue
        carry = ""
        if cur and cur[-1] in NO_LINE_END:
            carry, cur = cur[-1], cur[:-1]
        if m.width(tok.rstrip()) > width and not is_wide(tok[0]):
            # over-long Latin token: hard-break by character
            for ch in tok:
                if m.width((cur + ch).rstrip()) > avail and cur:
                    lines.append(cur.rstrip())
                    cur, avail = "", width
                cur += ch
            continue
        lines.append(cur.rstrip())
        cur, avail = carry + tok, width
    lines.append(cur.rstrip())
    return lines


def _spacing_pt(spec, size: float, line_h: float) -> float:
    if not spec:
        return 0.0
    kind, value = spec
    return value if kind == "pts" else value * line_h


def layout(ctx: dict[str, Any], paragraphs: list[tuple[int, str]], scale: float = 1.0, ln_reduction: float = 0.0) -> dict[str, Any]:
    body = ctx["body"]
    inner_w = ctx["box"]["w_pt"] - body["lIns"] - body["rIns"]
    if body.get("vert") in ("vert", "vert270", "eaVert"):
        inner_w = ctx["box"]["h_pt"] - body["tIns"] - body["bIns"]
    total = 0.0
    out_lines = []
    max_line_w = 0.0
    engines = set()
    for index, (lvl, text) in enumerate(paragraphs):
        props = ctx["levels"].get(str(lvl)) or ctx["levels"].get("0")
        m = Metrics(props, scale)
        engines.add(m.engine)
        mar = props["marL"]
        first = mar + (props["indent"] if not props["bullet"] else 0.0)
        width = max(1.0, inner_w - mar)
        first_width = max(1.0, inner_w - max(0.0, first))
        if body["wrap"] == "none":
            lines = text.split("\v")
        else:
            lines = []
            for seg in text.split("\v"):
                lines.extend(wrap(seg, m, first_width if not lines else width, width))
        for line in lines:
            max_line_w = max(max_line_w, m.width(line) + mar)
            has_wide = any(is_wide(c) for c in line)
            has_narrow = any(not is_wide(c) and not c.isspace() for c in line)
            lh = m.line_height(has_wide, has_narrow)
            spc = props.get("lnSpc")
            if spc and spc[0] == "pct":
                lh *= spc[1]
            elif spc and spc[0] == "pts":
                lh = spc[1] * scale
            lh *= (1.0 - ln_reduction)
            total += lh
        out_lines.append(lines)
        if index > 0:
            total += _spacing_pt(props.get("spcBef"), m.size, m.size * 1.2)
        if index < len(paragraphs) - 1:
            total += _spacing_pt(props.get("spcAft"), m.size, m.size * 1.2)
    need_h = total + body["tIns"] + body["bIns"]
    return {"lines": out_lines, "line_count": sum(len(x) for x in out_lines), "need_h_pt": need_h,
            "max_line_w_pt": max_line_w, "inner_w_pt": inner_w, "engine": "+".join(sorted(engines))}


def map_levels(ctx: dict[str, Any], text: str, levels: list[int] | None = None) -> list[tuple[int, str]]:
    """Map new lines to list levels.

    Priority: explicit ``levels`` list (plan field) > leading tabs (if any line has one, every line is
    explicit and untabbed lines are level 0) > the template's paragraph-level pattern by position.
    """
    raw = text.split("\n")
    if levels is not None and len(levels) == len(raw):
        return [(int(l), r.lstrip("\t")) for l, r in zip(levels, raw)]
    explicit = any(r.startswith("\t") for r in raw)
    template_levels = ctx.get("template_paragraph_levels") or [0]
    out = []
    for i, r in enumerate(raw):
        stripped = r.lstrip("\t")
        tabs = len(r) - len(stripped)
        lvl = tabs if explicit else template_levels[min(i, len(template_levels) - 1)]
        out.append((lvl, stripped))
    return out


def levels_are_implicit(ctx: dict[str, Any], text: str, levels: list[int] | None = None) -> bool:
    template_levels = ctx.get("template_paragraph_levels") or [0]
    return levels is None and len(set(template_levels)) > 1 and not any(r.startswith("\t") for r in text.split("\n"))


def fit(ctx: dict[str, Any], text: str, *, policy: str = "auto", levels: list[int] | None = None) -> dict[str, Any]:
    """Decide how a replacement text fits its native frame.

    status: fits | autofit (normAutofit fontScale) | grow (spAutoFit) | shrunk (explicit size) | overflow
    """
    paragraphs = map_levels(ctx, text, levels)
    body = ctx["body"]
    avail_h = ctx["box"]["h_pt"]
    base = layout(ctx, paragraphs)
    report = {"paragraphs": len(paragraphs), "avail_h_pt": round(avail_h, 2), "need_h_pt": round(base["need_h_pt"], 2),
              "line_count": base["line_count"], "lines": base["lines"], "font_scale": 1.0, "ln_spc_reduction": 0.0,
              "autofit_mode": body["autofit"], "wrap": body["wrap"], "engine": base["engine"]}
    width_ok = body["wrap"] != "none" or base["max_line_w_pt"] <= base["inner_w_pt"] + 0.5
    if base["need_h_pt"] <= avail_h + 0.5 and width_ok:
        report["status"] = "fits"
        report["ratio"] = round(base["need_h_pt"] / max(avail_h, 1), 3)
        return report
    if body["autofit"] == "shape" and body["wrap"] != "none":
        bottom = ctx["box"]["y_pt"] + base["need_h_pt"]
        if bottom <= ctx["slide"]["h_pt"]:
            report.update(status="grow", ratio=round(base["need_h_pt"] / max(avail_h, 1), 3), new_h_pt=round(base["need_h_pt"], 2))
            return report
    floor = MIN_FONT_SCALE if body["autofit"] == "norm" else EXPLICIT_SHRINK_FLOOR
    if policy == "never-shrink":
        floor = 1.0
    best = None
    scale = 0.975
    while scale >= floor - 1e-6 and best is None:
        for red in (0.0, 0.1, 0.2) if body["autofit"] == "norm" else (0.0,):
            trial = layout(ctx, paragraphs, scale, red)
            w_ok = body["wrap"] != "none" or trial["max_line_w_pt"] <= trial["inner_w_pt"] + 0.5
            if trial["need_h_pt"] <= avail_h + 0.5 and w_ok:
                best = (scale, red, trial)
                break
        scale -= 0.025
    if best is not None:
        s, red, trial = best
        report.update(status="autofit" if body["autofit"] == "norm" else "shrunk", font_scale=round(s, 3),
                      ln_spc_reduction=red, need_h_pt=round(trial["need_h_pt"], 2), lines=trial["lines"],
                      line_count=trial["line_count"], ratio=round(trial["need_h_pt"] / max(avail_h, 1), 3))
        return report
    trial = layout(ctx, paragraphs, floor, 0.2 if body["autofit"] == "norm" else 0.0)
    report.update(status="overflow", font_scale=floor, need_h_pt=round(trial["need_h_pt"], 2),
                  ratio=round(trial["need_h_pt"] / max(avail_h, 1), 3), lines=trial["lines"], line_count=trial["line_count"])
    return report
