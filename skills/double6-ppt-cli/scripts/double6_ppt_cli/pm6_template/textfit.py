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
# Calibrated against PowerPoint 16 / Win11 bound heights (tests/fixtures/powerpoint_win11_measurements.json):
# single line spacing = max(font ascent+descent, 1.2 em); spcBef applies to every paragraph incl. the first.
PPT_LINE_FACTOR = 1.2
SAFETY_H = 1.06   # conservative: need_h * SAFETY_H must fit
SAFETY_W = 0.97   # conservative: wrap at 97% of the inner width
MAX_OVERFILL = 1.75  # unscaled need/avail above this is a rewrite, not a shrink -> check ERROR
MIN_PT = {"title": 20.0, "body": 12.0}  # never shrink below these point sizes


def is_wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


EA_FALLBACKS = ("Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", "Hiragino Sans GB", "SimHei", "SimSun")
LATIN_FALLBACKS = ("Calibri", "Arial", "Helvetica", "Helvetica Neue", "Liberation Sans", "DejaVu Sans")


def _font_dirs() -> list[str]:
    import os
    import sys
    dirs: list[str] = []
    if sys.platform.startswith("win"):
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(os.path.join(windir, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
                 os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
                 os.path.expanduser("~/.local/share/fonts")]
    return [d for d in dirs if os.path.isdir(d)]


@functools.lru_cache(maxsize=1)
def _font_index() -> dict[tuple[str, bool], tuple[str, int]]:
    """family(lower), bold -> (file, face index), built with Pillow's name lookup (no fontconfig)."""
    import os
    index: dict[tuple[str, bool], tuple[str, int]] = {}
    if ImageFont is None:
        return index
    for root_dir in _font_dirs():
        for dirpath, _dirs, files in os.walk(root_dir):
            for name in files:
                if not name.lower().endswith((".ttf", ".otf", ".ttc", ".otc")):
                    continue
                path = os.path.join(dirpath, name)
                for face in range(8 if name.lower().endswith((".ttc", ".otc")) else 1):
                    try:
                        family, style = ImageFont.truetype(path, 12, index=face).getname()
                    except Exception:
                        break
                    if not family:
                        continue
                    bold = "bold" in (style or "").lower()
                    key = (family.lower(), bold)
                    regular = (style or "").lower() in ("regular", "normal", "roman", "book", "")
                    if key not in index or regular:
                        index[key] = (path, face)
    return index


def _lookup_by_name(family: str, ea: bool, bold: bool) -> tuple[str, int] | None:
    idx = _font_index()
    for fam in ((family,) if family else ()) + (EA_FALLBACKS if ea else LATIN_FALLBACKS):
        for b in ((bold, False) if bold else (False,)):
            hit = idx.get((fam.lower(), b))
            if hit:
                return hit
    return None


@functools.lru_cache(maxsize=1)
def _fc_has_cjk() -> bool:
    try:
        out = subprocess.run(["fc-list", ":charset=4e2d", "file"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return False
    return bool(out.strip())


@functools.lru_cache(maxsize=256)
def font_file(family: str, ea: bool, bold: bool) -> tuple[str, int] | None:
    """Resolve a font file: fontconfig (Linux, matches LibreOffice) else a name index of the OS font
    folders (Windows/macOS, approximates PowerPoint's substitution with common fallbacks)."""
    import os
    forced = os.environ.get("D6PPT_FONT_RESOLVER", "").lower()  # "index" | "none" (diagnostics/tests)
    if forced == "none":
        return None
    if forced == "index" or not shutil.which("fc-match"):
        return _lookup_by_name(family, ea, bold)
    if ea and not _fc_has_cjk():
        return None  # no CJK-capable font installed: measuring tofu glyphs would be wrong -> heuristic
    pattern = (family or (DEFAULT_EA if ea else DEFAULT_LATIN))
    if bold:
        pattern += ":bold"
    if ea:
        pattern += ":lang=zh-cn:charset=4e2d"
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}|%{index}", pattern], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return _lookup_by_name(family, ea, bold)
    if "|" not in out:
        return _lookup_by_name(family, ea, bold)
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
        self.engine = ("fontconfig" if shutil.which("fc-match") else "font-index") if (self.f_lat and self.f_ea) else (
            "partial" if (self.f_lat or self.f_ea) else "heuristic")

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
        # PowerPoint "single" spacing is 1.2 em for Latin and CJK alike (measured: 44pt -> 52.8pt per line,
        # 32pt -> 38.4pt, Calibri and the zh-CN default EA font); font ascent+descent is not used.
        return self.size * PPT_LINE_FACTOR


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


def layout(ctx: dict[str, Any], paragraphs: list[tuple[int, str]], scale: float = 1.0, ln_reduction: float = 0.0,
           safety: bool = True) -> dict[str, Any]:
    body = ctx["body"]
    inner_w = ctx["box"]["w_pt"] - body["lIns"] - body["rIns"]
    wrap_w = inner_w * (SAFETY_W if safety else 1.0)
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
        width = max(1.0, wrap_w - mar)
        first_width = max(1.0, wrap_w - max(0.0, first))
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
        total += _spacing_pt(props.get("spcBef"), m.size, m.size * PPT_LINE_FACTOR)
        if index < len(paragraphs) - 1:
            total += _spacing_pt(props.get("spcAft"), m.size, m.size * PPT_LINE_FACTOR)
    need_h = total * (SAFETY_H if safety else 1.0) + body["tIns"] + body["bIns"]
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

    status: fits | grow (spAutoFit) | shrunk (explicit reduced sz written into the runs) | overflow

    PowerPoint does not reliably apply a saved normAutofit fontScale (verified on PowerPoint 16/Win11:
    the scale is reset to 100% on recompute), so shrinking is always baked into explicit run sizes.
    The floor is the larger of the scale floor and the role's minimum point size.
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
    base_sz = max((v["sz"] for v in ctx["levels"].values()), default=18.0)
    min_pt = MIN_PT["title"] if ctx.get("is_title") else MIN_PT["body"]
    floor = max(floor, min(1.0, min_pt / max(base_sz, 1.0)))
    report["min_scale"] = round(floor, 3)
    overfill = base["need_h_pt"] / max(avail_h, 1)
    if policy != "never-shrink" and overfill > MAX_OVERFILL:
        report.update(status="overflow", reason="overfill", font_scale=floor, ratio=round(overfill, 3))
        return report
    if policy == "never-shrink":
        floor = 1.0
    best = None
    scale = 0.975
    while scale >= floor - 1e-6 and best is None:
        for red in (0.0,):
            trial = layout(ctx, paragraphs, scale, red)
            w_ok = body["wrap"] != "none" or trial["max_line_w_pt"] <= trial["inner_w_pt"] + 0.5
            if trial["need_h_pt"] <= avail_h + 0.5 and w_ok:
                best = (scale, red, trial)
                break
        scale -= 0.025
    if best is not None:
        s, red, trial = best
        report.update(status="shrunk", font_scale=round(s, 3),
                      ln_spc_reduction=red, need_h_pt=round(trial["need_h_pt"], 2), lines=trial["lines"],
                      line_count=trial["line_count"], ratio=round(trial["need_h_pt"] / max(avail_h, 1), 3))
        return report
    trial = layout(ctx, paragraphs, floor, 0.0)
    report.update(status="overflow", font_scale=floor, need_h_pt=round(trial["need_h_pt"], 2),
                  ratio=round(trial["need_h_pt"] / max(avail_h, 1), 3), lines=trial["lines"], line_count=trial["line_count"])
    return report
