"""Layout recipes for generate mode: `d6ppt recipe list|show|apply|deck`.

Each recipe turns a small JSON payload (title, data, image names) into one finished SVG page that follows
references/layout-recipes.md: full-bleed photos with scrims, hero numbers, annotated native charts,
highlighted native tables, open (box-free) timelines and feature columns, quote and big-number pages.
Colours come from the run's spec_lock (deck palette), sizes from its type ladder, so the output passes the
deterministic visual checks by construction. Text is measured with a font-independent width model.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Callable

from .common import D6PPTError
from . import design_presets

W, H, M = 1280, 720, 80
DEFAULT_FONT = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, Arial, sans-serif"

# ----------------------------------------------------------------------------- text model

def _cw(ch: str) -> float:
    o = ord(ch)
    if o >= 0x2E80 or 0xFF00 <= o <= 0xFFEF:
        return 1.0
    if ch == " ":
        return 0.28
    if ch in "il.,:;'|!`":
        return 0.28
    if ch in "fjrtI()[]{}\"-/":
        return 0.38
    if ch in "mwMW@%":
        return 0.86
    if ch.isupper() or ch in "#$&€£¥₩+=<>~^*?":
        return 0.66
    if ch.isdigit():
        return 0.58
    if ch in "–—":
        return 0.8 if ch == "—" else 0.56
    return 0.55


def text_width(s: str, size: float, bold: bool = False) -> float:
    return sum(_cw(c) for c in s) * size * (1.05 if bold else 1.0)


_TOK = re.compile(r"[\x21-\x7E\u2013\u2014\u2103\u00B7\u00A5\u20AC]+\s*|\s+|.")


def _is_short_tail(tail: str, whole: str) -> bool:
    latin = all(ord(c) < 0x2E80 for c in tail)
    if len(tail) <= 2:
        return True
    if latin and len(tail) <= 6:
        return True
    return False


def wrap(s: str, size: float, width: float, bold: bool = False) -> list[str]:
    out: list[str] = []
    cur = ""
    for t in _TOK.findall(s):
        if cur and text_width((cur + t).rstrip(), size, bold) > width:
            out.append(cur.rstrip())
            cur = t.lstrip()
        else:
            cur += t
    if cur.strip():
        out.append(cur.rstrip())
    if len(out) > 1 and _is_short_tail(out[-1], s):
        tail = out[-1]
        toks = _TOK.findall(out[-2])
        moved = ""
        while toks and text_width(moved + tail, size, bold) < width * 0.5:
            moved = toks.pop() + moved
            if len(moved.strip()) >= 3:
                break
        moved = moved.rstrip()
        sep = " " if moved and ord(moved[-1]) < 0x2E80 and ord(tail[0]) < 0x2E80 else ""
        out[-2] = "".join(toks).rstrip()
        out[-1] = (moved + sep + tail).strip()
        if not out[-2]:
            out.pop(-2)
    return out


def balanced(s: str, size: float, width: float, bold: bool = False) -> list[str]:
    lines = wrap(s, size, width, bold)
    if len(lines) < 2:
        return lines
    lo, hi, best = width * 0.4, width, lines
    for _ in range(18):
        mid = (lo + hi) / 2
        cand = wrap(s, size, mid, bold)
        if len(cand) <= len(lines):
            best, hi = cand, mid
        else:
            lo = mid
    return best


def _err(code: str, message: str, details: Any = None) -> D6PPTError:
    return D6PPTError(message, code, details)


def esc(s: Any) -> str:
    return html.escape(str(s), quote=False)

# ----------------------------------------------------------------------------- palette / context

def load_palette(run: Path | None, design: str | None = None) -> dict:
    """Preset palette for the run, overridden by any colours the author edited in spec_lock."""
    from .native_markers import parse_spec_lock_palette
    name = design
    lock_text = ""
    if run is not None:
        man = run / "run_manifest.json"
        if man.exists() and not name:
            name = json.loads(man.read_text(encoding="utf-8")).get("design_profile")
        lock = run / "authoring" / "project" / "spec_lock.md"
        if lock.exists():
            lock_text = lock.read_text(encoding="utf-8")
    if not name or name not in design_presets.names():
        name = "consulting"
    p = design_presets.resolve(name)
    if lock_text:
        over = parse_spec_lock_palette(lock_text)
        for k, v in over.items():
            if k == "chart_series" and isinstance(v, list) and len(v) >= 2:
                p[k] = v
            elif isinstance(v, str) and k in p:
                p[k] = v
        if "gradient_from" in over and "gradient_to" in over:
            p["gradient"] = [over["gradient_from"], over["gradient_to"]]
        for k in design_presets.TYPE_LADDER:
            m = re.search(rf"^- {k}: (\d+)\s*$", lock_text, re.M)
            if m:
                p["type"][k] = int(m.group(1))
        m = re.search(r"^- theme: (\w+)", lock_text, re.M)
        if m:
            p["theme"] = m.group(1)
        m = re.search(r"^- font_family: (.+)$", lock_text, re.M)
        if m and "[fill" not in m.group(1):
            p["font"] = m.group(1).strip()
    p.setdefault("font", DEFAULT_FONT)
    sc = p["chart_series"]
    while len(sc) < 4:
        sc.append(p["line"])
    return p


# ----------------------------------------------------------------------------- page builder

class Page:
    def __init__(self, p: dict, ctx: dict, number: int, total: int, credits: dict):
        self.p, self.ctx, self.n, self.total, self.credits = p, ctx, number, total, credits
        self.SZ = dict(p["type"])
        self.SZ["sub"] = self.SZ["subtitle"]
        self.dark = p.get("theme") == "dark"
        self.r = {"training": 20, "investor-pitch": 14, "product-launch": 16}.get(p.get("name"), 6)
        self.sid = 1000 + number * 100
        self.icons: set[str] = set()
        self.objs: list[dict] = []
        self.defs = ""
        self.deco = 0
        self.images: list[str] = []

    # primitives
    def _reg(self, role: str) -> tuple[str, int]:
        self.sid += 1
        i = f"p{self.n}-{role}-{self.sid}"
        self.objs.append({"id": i, "sid": self.sid, "role": role})
        return i, self.sid

    def text(self, x, y, s, size, fill, role="body", bold=False, anchor="start", extra=""):
        sz = self.SZ[size] if isinstance(size, str) else size
        i, sid = self._reg(role)
        w = ' font-weight="bold"' if bold else ""
        return (f'<text id="{i}" data-pptx-shape-id="{sid}" x="{x:.1f}" y="{y:.1f}" font-family="{esc(self.p["font"])}" '
                f'font-size="{sz}"{w} fill="{fill}" text-anchor="{anchor}" {extra}>{esc(s)}</text>')

    def para(self, x, y, s, size, fill, width, role="body", bold=False, lh=1.45, maxlines=4, anchor="start", extra=""):
        sz = self.SZ[size]
        fn = balanced if size in ("display", "title", "hero") or role == "title" else wrap
        lines = fn(str(s), sz, width, bold)[:maxlines]
        if len(lines) <= 1:
            return self.text(x, y, lines[0] if lines else "", size, fill, role, bold, anchor, extra), 1
        i, sid = self._reg(role)
        w = ' font-weight="bold"' if bold else ""
        sp = "".join(f'<tspan x="{x:.1f}" dy="{0 if k == 0 else round(sz * lh)}">{esc(l)}</tspan>' for k, l in enumerate(lines))
        return (f'<text id="{i}" data-pptx-shape-id="{sid}" x="{x:.1f}" y="{y:.1f}" font-family="{esc(self.p["font"])}" '
                f'font-size="{sz}"{w} fill="{fill}" text-anchor="{anchor}" {extra}>{sp}</text>'), len(lines)

    def lines(self, s, size, width, bold=False):
        return len(wrap(str(s), self.SZ[size], width, bold))

    def fit(self, s, sizes, width, bold=True):
        for size in sizes:
            if text_width(str(s), self.SZ[size], bold) <= width:
                return size
        return sizes[-1]

    def icon(self, name, x, y, s, c):
        self.icons.add(name)
        return f'<use data-icon="tabler-outline/{name}" x="{x:.1f}" y="{y:.1f}" width="{s}" height="{s}" fill="{c}"/>'

    def rect(self, x, y, w, h, fill, r=None, extra="", deco=False):
        r = self.r if r is None else r
        d = ""
        if deco:
            self.deco += 1
            d = f' id="deco{self.n}-{self.deco}" data-pptx-role="decoration"'
        return f'<rect{d} x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{r}" fill="{fill}" {extra}/>'

    def grad(self, stops, x2=1, y2=0):
        gid = f"g{self.n}x{len(self.defs)}"
        st = "".join(f'<stop offset="{o}" stop-color="{c}" stop-opacity="{a}"/>' for o, c, a in stops)
        self.defs += f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">{st}</linearGradient>'
        return f"url(#{gid})"

    def image(self, name, x, y, w, h):
        f = self.ctx["image_files"].get(name)
        if not f:
            raise _err("recipe_image_missing", f"Image '{name}' is not in authoring/project/images; add it with image-add first.",
                          {"image": name, "available": sorted(self.ctx["image_files"])})
        self.images.append(f)
        return f'<image href="../images/{f}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" preserveAspectRatio="xMidYMid slice"/>'

    def scrim(self, x, y, w, h, stops, x2=0, y2=1):
        return self.rect(x, y, w, h, self.grad(stops, x2, y2), 0, deco=True)

    def credit(self, name, x=W - 24, y=H - 18):
        f = self.ctx["image_files"].get(name, "")
        rec = self.credits.get(f, {})
        if not rec or rec.get("placeholder"):
            return ""
        lic = (rec.get("license") or "").upper().replace("UNSPLASH", "Unsplash License").replace("PEXELS", "Pexels License")
        ver = f" {rec['license_version']}" if rec.get("license_version") else ""
        txt = f"Photo: {(rec.get('creator') or 'unknown')[:32]} · {lic}{ver}"
        cw = text_width(txt, self.SZ["caption"]) + 40
        return (self.rect(x - cw + 16, y - 18, cw, 26, "#000000", 13, 'fill-opacity="0.8"')
                + self.text(x, y, txt, "caption", "#FFFFFF", "footnote", anchor="end"))

    def chrome(self, on_dark=None):
        dark = self.dark if on_dark is None else on_dark
        c = self.p["muted"] if not dark else "#FFFFFF"
        b = ""
        if self.ctx.get("footer"):
            b += self.text(M, 692, self.ctx["footer"], "caption", c, "footnote")
        return b + self.text(W - M, 692, f"{self.n:02d}", "caption", c, "page_mark", True, "end")

    def header(self, title, kicker=None, width=W - 2 * M, x=M, ink=None):
        p = self.p
        ink = ink or p["text"]
        b = self.rect(x, 62, 48, 6, p["accent"], 3)
        if kicker:
            k = kicker.upper() if self.ctx.get("lang") == "en" else kicker
            b += self.text(x + 64, 71, k, "label", ink if not self.dark else p["muted"], "kicker", True)
        t, n = self.para(x, 132, title, "title", ink, width, "title", True, 1.2, 2)
        return b + t, 132 + (n - 1) * round(self.SZ["title"] * 1.2) + 20

    def native(self, kind, x, y, w, h, meta, frame=None):
        i, sid = self._reg(kind)
        meta = dict(meta, x=round(x), y=round(y), width=round(w), height=round(h), name=i)
        fr = f' stroke="{frame}"' if frame else ""
        return (f'<g id="{i}" data-pptx-shape-id="{sid}" data-pptx-bounds="{x:.0f} {y:.0f} {w:.0f} {h:.0f}" '
                f'data-pptx-replace-with="{kind}" data-pptx-native-authority="json"><metadata type="application/json">'
                f'{esc(json.dumps(meta, ensure_ascii=False))}</metadata><rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" fill="none"{fr}/></g>')

    def svg(self, body, role="content", bg=None):
        bg = bg or self.p["bg"]
        return ('<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1280" height="720" '
                f'viewBox="0 0 1280 720" data-pptx-page-role="{role}">\n<defs>{self.defs}</defs>\n'
                f'<rect x="0" y="0" width="1280" height="720" fill="{bg}"/>\n{body}\n</svg>\n')


# ----------------------------------------------------------------------------- recipes
# Each recipe: fn(pg, d) -> (svg, rhythm). d is the page payload.

def _need(d, *keys):
    miss = [k for k in keys if k not in d or d[k] in (None, "", [])]
    if miss:
        raise _err("recipe_field_missing", f"Recipe '{d.get('recipe')}' needs: {', '.join(miss)}", {"missing": miss})


def r_cover_photo(pg: Page, d):
    _need(d, "title", "image")
    p = pg.p
    b = pg.image(d["image"], 0, 0, W, H)
    g0 = p["gradient"][0]
    b += pg.scrim(0, 0, W, H, [(0, g0, 0.94), (0.55, g0, 0.72), (1, g0, 0.05)], 1, 0)
    b += pg.scrim(0, 420, W, 300, [(0, "#000000", 0), (1, "#000000", 0.55)])
    if d.get("kicker"):
        b += pg.text(M, 228, d["kicker"], "label", "#FFFFFF", "kicker", True, extra='fill-opacity="0.9"')
    b += pg.rect(M, 250, 72, 8, p["accent"], 4)
    if text_width(d["title"], pg.SZ["hero"], True) <= 900:
        size = "hero"
    else:
        size = "display" if pg.lines(d["title"], "display", 760, True) <= 2 else "title"
    t, n = pg.para(M, 346, d["title"], size, "#FFFFFF", 760, "title", True, 1.15, 2)
    b += t
    y = 346 + (n - 1) * round(pg.SZ[size] * 1.15) + 66
    if d.get("subtitle"):
        b += pg.para(M, y, d["subtitle"], "sub", "#FFFFFF", 700, "subtitle", False, 1.4, 2, extra='fill-opacity="0.92"')[0]
    if d.get("note") or pg.ctx.get("audience"):
        b += pg.text(M, 644, d.get("note") or pg.ctx["audience"], "label", "#FFFFFF", "caption", extra='fill-opacity="0.85"')
    b += pg.credit(d["image"])
    return pg.svg(b, "cover", g0), "anchor"


def r_cover_split(pg: Page, d):
    """Bold split cover: saturated gradient field with an oversized wordmark, full-height photo bleeding off the right edge,
    an accent block bridging the seam."""
    _need(d, "title", "image")
    p = pg.p
    split = 700
    b = pg.rect(0, 0, split, H, pg.grad([(0, p["gradient"][0], 1), (1, p["gradient"][1], 1)], 1, 1), 0)
    b += pg.image(d["image"], split, 0, W - split, H)
    b += pg.scrim(split, 0, W - split, H, [(0, p["gradient"][0], 0.35), (0.4, p["gradient"][0], 0)], 1, 0)
    b += f'<circle cx="{split - 40}" cy="-40" r="230" fill="{p["accent2"]}" fill-opacity="0.28"/>'
    b += pg.rect(split - 56, 470, 112, 112, p["accent"], 0)
    if d.get("kicker"):
        b += pg.text(M, 200, d["kicker"].upper() if pg.ctx.get("lang") == "en" else d["kicker"], "label", "#FFFFFF", "kicker", True, extra='fill-opacity="0.9"')
    size = pg.fit(d["title"], ["hero", "display", "title"], split - M - 80)
    t, n = pg.para(M, 330, d["title"], size, "#FFFFFF", split - M - 80, "title", True, 1.1, 2)
    b += t
    y = 330 + (n - 1) * round(pg.SZ[size] * 1.1) + 70
    if d.get("subtitle"):
        b += pg.para(M, y, d["subtitle"], "sub", "#FFFFFF", split - M - 100, "subtitle", False, 1.35, 3, extra='fill-opacity="0.94"')[0]
    if d.get("note") or pg.ctx.get("audience"):
        b += pg.text(M, 644, d.get("note") or pg.ctx["audience"], "label", "#FFFFFF", "caption", extra='fill-opacity="0.85"')
    b += pg.credit(d["image"])
    return pg.svg(b, "cover", p["gradient"][0]), "anchor"


def r_statement_photo(pg: Page, d):
    _need(d, "title", "image")
    p = pg.p
    b = pg.image(d["image"], 0, 0, W, H) + pg.scrim(0, 0, W, H, [(0, "#000000", 0.35), (1, "#000000", 0.78)])
    b += pg.rect(W / 2 - 40, 226, 80, 8, p["accent"], 4)
    t, n = pg.para(W / 2, 340, d["title"], "display", "#FFFFFF", 1040, "title", True, 1.2, 2, anchor="middle")
    b += t
    if d.get("subtitle"):
        b += pg.text(W / 2, 340 + n * 78 + 10, d["subtitle"], "sub", "#FFFFFF", "subtitle", False, "middle", 'fill-opacity="0.9"')
    b += pg.credit(d["image"])
    return pg.svg(b, "content", "#000000"), "breathing"


def r_quote(pg: Page, d):
    """Big quotation: oversized accent quote mark, quote in display/title size, attribution; optional photo panel."""
    _need(d, "quote")
    p = pg.p
    img = d.get("image")
    tx, tw_ = (M, 660) if img else (M + 40, W - 2 * M - 80)
    b = ""
    if img:
        b += pg.image(img, 820, 0, W - 820, H)
        b += pg.credit(img)
    bg = p["gradient"][0] if d.get("dark", True) else p["bg"]
    ink = "#FFFFFF" if d.get("dark", True) else p["text"]
    b = pg.rect(0, 0, 820 if img else W, H, pg.grad([(0, p["gradient"][0], 1), (1, p["gradient"][1], 1)], 1, 1) if d.get("dark", True) else p["bg"], 0) + b
    b += pg.text(tx - 8, 250, "“", "mega", p["accent"], "data", True)
    size = "display" if pg.lines(d["quote"], "display", tw_, True) <= 3 else "title"
    t, n = pg.para(tx, 320, d["quote"], size, ink, tw_, "title", True, 1.25, 4)
    b += t
    y = 320 + (n - 1) * round(pg.SZ[size] * 1.25) + 70
    if d.get("attribution"):
        b += pg.rect(tx, y - 22, 48, 6, p["accent"], 3)
        b += pg.text(tx + 64, y - 12, d["attribution"], "sub", ink, "caption", False, extra='fill-opacity="0.85"')
    if img:
        c = "#FFFFFF" if d.get("dark", True) else p["muted"]
        if pg.ctx.get("footer"):
            b += pg.text(M, 692, pg.ctx["footer"], "caption", c, "footnote")
        b += pg.text(820 - 40, 692, f"{pg.n:02d}", "caption", c, "page_mark", True, "end")
    else:
        b += pg.chrome(True)
    return pg.svg(b, "content", bg), "breathing"


def r_big_number(pg: Page, d):
    """One giant number carries the page; context line and up to 3 supporting stats sit on an open baseline (no cards)."""
    _need(d, "value", "label")
    p = pg.p
    b = ""
    top = 100
    if d.get("title"):
        hb, top = pg.header(d["title"], d.get("kicker"))
        b += hb
    col = p["accent"] if pg.dark else p["primary"]
    sup = d.get("supporting") or []
    vsize = pg.SZ["mega"] if text_width(d["value"], pg.SZ["mega"], True) < 820 else pg.SZ["hero"]
    vy = top + 40 + vsize * 0.8 + (30 if not sup else 0)
    gx = M
    b += pg.text(gx - 6, vy, d["value"], vsize, col, "data", True)
    vw = text_width(d["value"], vsize, True)
    lx = gx + vw + 40
    if lx < W - M - 300:
        b += pg.rect(lx, vy - vsize * 0.55, 8, 64, p["accent"], 4)
        lsz = "title" if pg.lines(d["label"], "title", W - M - lx - 40, True) <= 3 and not d.get("detail") else "sub"
        b += pg.para(lx + 32, vy - vsize * 0.55 + 34, d["label"], lsz, p["text"], W - M - lx - 40, "body", True, 1.3, 4)[0]
        if d.get("detail"):
            b += pg.para(lx + 32, vy - vsize * 0.55 + 34 + pg.lines(d["label"], lsz, W - M - lx - 40, True) * round(pg.SZ[lsz] * 1.3) + 16,
                         d["detail"], "body", p["muted"], W - M - lx - 40, "body", False, 1.5, 4)[0]
    else:
        b += pg.para(gx, vy + 56, d["label"], "sub", p["text"], W - 2 * M, "body", True, 1.35, 2)[0]
    if sup:
        y = 560
        b += f'<line x1="{M}" y1="{y - 56}" x2="{W - M}" y2="{y - 56}" stroke="{p["line"]}" stroke-width="2"/>'
        cw = (W - 2 * M) / len(sup)
        for k, it in enumerate(sup):
            x = M + k * cw
            vs = pg.fit(it["value"], ["display", "title"], cw * 0.55)
            b += pg.text(x, y + 20, it["value"], vs, p["accent"] if k == 0 and not pg.dark else p["text"], "data", True)
            vw2 = text_width(it["value"], pg.SZ[vs], True)
            b += pg.para(x + vw2 + 20, y + 4, it["label"], "body", p["muted"], max(140, cw - vw2 - 44), "label", False, 1.35, 2)[0]
    b += pg.chrome()
    return pg.svg(b), "breathing" if not sup else "dense"


def r_section(pg: Page, d):
    _need(d, "title")
    p = pg.p
    img = d.get("image")
    b = pg.rect(0, 0, W, H, pg.grad([(0, p["gradient"][0], 1), (1, p["gradient"][1], 1)], 1, 1), 0)
    if img:
        b += pg.image(img, 760, 0, 520, H) + pg.credit(img)
    b += pg.text(M, 330, f"{int(d.get('number', 1)):02d}", "hero", p["accent"], "data", True)
    t, n = pg.para(M, 430, d["title"], "display", "#FFFFFF", 620 if img else 1060, "title", True, 1.2, 2)
    b += t
    if d.get("subtitle"):
        b += pg.para(M, 430 + n * 78 + 10, d["subtitle"], "body", "#FFFFFF", 600, "subtitle", False, 1.45, 2, extra='fill-opacity="0.88"')[0]
    b += pg.chrome(True)
    return pg.svg(b, "content", p["gradient"][0]), "breathing"


def r_kpi_hero(pg: Page, d):
    _need(d, "title", "data")
    p = pg.p
    items = list(d["data"].items())
    hi = int(d.get("hero_index", 0))
    hero_lab, hero_val = items[hi]
    rest = [kv for k, kv in enumerate(items) if k != hi]
    icons = d.get("icons") or ["chart-bar", "users", "trending-up", "clock"]
    b, top = pg.header(d["title"], d.get("kicker"))
    hx, hy, hw = M, top + 34, 540
    hh = 664 - hy - (64 if d.get("note") else 0)
    b += pg.rect(hx, hy, hw, hh, pg.grad([(0, p["gradient"][0], 1), (1, p["gradient"][1], 1)], 1, 1))
    b += f'<circle cx="{hx + hw - 110}" cy="{hy + 110}" r="80" fill="{p["accent"]}" fill-opacity="0.22"/>'
    b += pg.icon(icons[0], hx + 40, hy + 40, 48, p["accent"])
    hs = "hero" if text_width(hero_val, pg.SZ["hero"], True) < hw - 80 else "display"
    b += pg.text(hx + 40, hy + hh - 104, hero_val, hs, "#FFFFFF", "data", True)
    b += pg.para(hx + 40, hy + hh - 50, hero_lab, "sub", "#FFFFFF", hw - 80, "label", False, 1.3, 1, extra='fill-opacity="0.92"')[0]
    cx = hx + hw + 56
    cw = W - M - cx
    rh = hh / max(len(rest), 1)
    for k, (lab, val) in enumerate(rest):
        y = hy + k * rh
        if k:
            b += f'<line x1="{cx}" y1="{y:.1f}" x2="{cx + cw}" y2="{y:.1f}" stroke="{p["line"]}" stroke-width="1.5"/>'
        b += f'<circle cx="{cx + 30}" cy="{y + rh / 2:.1f}" r="30" fill="{p["tint"]}"/>'
        b += pg.icon(icons[(k + 1) % len(icons)], cx + 13, y + rh / 2 - 17, 34, p["primary"] if not pg.dark else p["accent"])
        vs = pg.fit(val, ["display", "title", "sub"], cw - 280)
        b += pg.text(cx + 88, y + rh / 2 + (16 if vs == "display" else 10), val, vs, p["text"], "data", True)
        vw = text_width(val, pg.SZ[vs], True)
        b += pg.para(cx + 88 + vw + 20, y + rh / 2 + 8, lab, "body", p["muted"], max(130, cw - 108 - vw), "label", False, 1.3, 2)[0]
    if d.get("note"):
        b += pg.rect(M, hy + hh + 24, 6, 34, p["accent"], 3)
        b += pg.para(M + 24, hy + hh + 50, d["note"], "body", p["text"], W - 2 * M - 24, "body", True, 1.3, 1)[0]
    b += pg.chrome()
    return pg.svg(b), "dense"


def r_kpi_photo(pg: Page, d):
    """Full-bleed photo with a scrim and an open row of big numbers across the bottom (no cards)."""
    _need(d, "title", "data", "image")
    p = pg.p
    b = pg.image(d["image"], 0, 0, W, H)
    b += pg.scrim(0, 0, W, H, [(0, "#000000", 0.55), (0.45, "#000000", 0.35), (1, "#000000", 0.88)])
    hb, top = pg.header(d["title"], d.get("kicker"), ink="#FFFFFF")
    b += hb
    items = list(d["data"].items())
    cw = (W - 2 * M) / len(items)
    order = ["hero", "display", "title"]
    sizes = [pg.fit(v, order, cw - 48) for _, v in items if text_width(v, pg.SZ["title"], True) <= cw - 48]
    row = max(sizes, key=order.index) if sizes else "title"
    for k, (lab, val) in enumerate(items):
        x = M + k * cw
        if k:
            b += f'<line x1="{x - 24:.1f}" y1="470" x2="{x - 24:.1f}" y2="630" stroke="#FFFFFF" stroke-opacity="0.35" stroke-width="1.5"/>'
        vs = row if text_width(val, pg.SZ[row], True) <= cw - 48 else "sub"
        if vs == "sub":
            b += pg.para(x, 540, val, "sub", "#FFFFFF", cw - 48, "data", True, 1.3, 2)[0]
        else:
            b += pg.text(x, 590, val, vs, "#FFFFFF", "data", True)
        b += pg.rect(x, 612, 40, 5, p["accent"], 2.5)
        b += pg.text(x, 648, lab, "body", "#FFFFFF", "label", extra='fill-opacity="0.9"')
    if d.get("note"):
        b += pg.para(M, top + 40, d["note"], "sub", "#FFFFFF", 760, "body", False, 1.4, 2, extra='fill-opacity="0.92"')[0]
    b += pg.credit(d["image"], y=24 + 6)
    return pg.svg(b, "content", "#000000"), "dense"


def r_kpi_row(pg: Page, d):
    _need(d, "title", "data")
    p = pg.p
    icons = d.get("icons") or ["chart-bar", "clock", "users", "star"]
    b, top = pg.header(d["title"], d.get("kicker"))
    items = list(d["data"].items())
    n = len(items)
    cw = (W - 2 * M) / n
    by = top + 40
    bh = 664 - by - (100 if d.get("note") else 20)
    order = ["hero", "display", "sub"]
    vs_of = lambda v: pg.fit(v, ["hero", "display"], cw - 96) if text_width(v, pg.SZ["display"], True) <= cw - 96 else "sub"  # noqa: E731
    shorts = [vs_of(v) for _, v in items if vs_of(v) != "sub"]
    row = max(shorts, key=order.index) if shorts else "sub"
    b += pg.rect(M, by, W - 2 * M, bh, pg.grad([(0, p["gradient"][0], 1), (1, p["gradient"][1], 1)], 1, 0) if not pg.dark else p["surface"])
    ink = "#FFFFFF" if not pg.dark else p["text"]
    for k, (lab, val) in enumerate(items):
        x = M + k * cw
        if k:
            b += f'<line x1="{x:.1f}" y1="{by + 50}" x2="{x:.1f}" y2="{by + bh - 50}" stroke="#FFFFFF" stroke-opacity="0.2" stroke-width="1.5"/>'
        b += pg.icon(icons[k % len(icons)], x + 48, by + 48, 44, p["accent"])
        vs = row if vs_of(val) != "sub" else "sub"
        if vs == "sub":
            b += pg.para(x + 48, by + bh - 130, val, "sub", ink, cw - 96, "data", True, 1.35, 2)[0]
        else:
            b += pg.text(x + 48, by + bh - 90, val, vs, ink, "data", True)
        b += pg.text(x + 48, by + bh - 48, lab, "body", ink if not pg.dark else p["muted"], "label")
    if d.get("note"):
        b += pg.rect(M, by + bh + 34, 6, 40, p["accent"], 3)
        b += pg.para(M + 28, by + bh + 64, d["note"], "sub", p["text"], W - 2 * M - 28, "body", True, 1.35, 1)[0]
    b += pg.chrome()
    return pg.svg(b), "dense"


def r_chart_annotated(pg: Page, d):
    _need(d, "title", "chart")
    p = pg.p
    b, top = pg.header(d["title"], d.get("kicker"))
    ch = d["chart"]
    series = ch["series"]
    x, y, w, h = M, top + 70, 740, 664 - 40 - top - 70
    cs = p["chart_series"]
    meta: dict[str, Any] = dict(type=ch.get("kind", "column"), categories=ch["categories"],
                                series=[dict(name=z["name"], values=z["values"]) for z in series], data_labels=True,
                                font_size=pg.SZ["body"])
    ncat = len(ch["categories"])
    hi = int(d.get("highlight_index", ncat - 1))
    if len(series) == 1:
        if meta["type"] in ("column", "bar"):
            meta["series"][0]["point_colors"] = [cs[0] if k == hi else cs[3] for k in range(ncat)]
            meta["style"] = {"colors": [cs[3]]}
        else:
            meta["line_style"] = "lineMarker"
            meta["marker_size"] = 10
            meta["series"][0]["point_colors"] = [None] * (ncat - 1) + [cs[0]]
            meta["style"] = {"colors": [cs[1] if not pg.dark else cs[0]]}
    else:
        meta.update(show_legend=True, legend_position="bottom")
    b += pg.native("chart", x, y, w, h, meta)
    legend_h = 0
    if d.get("annotation"):
        from .visual_quality import _hex_to_rgb, contrast_ratio
        px = x + 40 + (w - 60) * (hi + 0.5) / ncat
        bw = min(280, text_width(d["annotation"], pg.SZ["label"], True) + 40)
        bx = min(max(px - bw / 2, x), x + w - bw)
        by = y - 44
        pf = p["accent"] if contrast_ratio(_hex_to_rgb(p["on_accent"]), _hex_to_rgb(p["accent"])) >= 4.8 else p["primary"]
        pt = p["on_accent"] if pf == p["accent"] else p["on_primary"]
        b += pg.rect(bx, by, bw, 36, pf, 18)
        b += f'<path d="M{px - 8:.1f} {by + 36} L{px:.1f} {by + 48} L{px + 8:.1f} {by + 36} Z" fill="{pf}"/>'
        b += pg.text(bx + bw / 2, by + 24, d["annotation"], "label", pt, "label", True, "middle")
    px0 = x + w + 48
    pw = W - M - px0
    b += f'<line x1="{px0}" y1="{y}" x2="{px0}" y2="{y + h}" stroke="{p["line"]}" stroke-width="1.5"/>'
    if d.get("callout_label"):
        b += pg.para(px0 + 32, y + 36, d["callout_label"], "label", p["muted"], pw - 40, "label", True, 1.3, 2)[0]
    if d.get("callout"):
        cs_ = "hero" if text_width(d["callout"], pg.SZ["hero"], True) < pw - 40 else "display"
        b += pg.text(px0 + 32, y + 160, d["callout"], cs_, p["accent"] if pg.dark or p.get("name") == "consulting" else p["primary"], "data", True)
        b += pg.rect(px0 + 32, y + 190, 48, 6, p["accent"], 3)
    if d.get("insight"):
        b += pg.para(px0 + 32, y + 244, d["insight"], "body", p["text"], pw - 40, "body", False, 1.5, 6 if not legend_h else 5)[0]
    b += pg.chrome()
    return pg.svg(b), "dense"


def r_table_highlight(pg: Page, d):
    _need(d, "title", "columns", "rows")
    p = pg.p
    b, top = pg.header(d["title"], d.get("kicker"))
    cols, rows = d["columns"], d["rows"]
    hdr = cols if len(cols) == len(rows[0]) else [""] + cols
    nc = len(hdr)
    x, y, w = M, top + 70, W - 2 * M
    rh = 80
    h = rh * (len(rows) + 1)
    hl = d.get("highlight")
    body = [[({"text": c, "bold": True} if hl is not None and j == hl else c) for j, c in enumerate(r)] for r in rows]
    meta = dict(columns=hdr, rows=body, defaults={"cell": {"font_size": pg.SZ["body"], "valign": "middle", "padding": 14}},
                style={"font_size": pg.SZ["body"], "header_font_size": pg.SZ["body"]})
    b += pg.native("table", x, y, w, h, meta, frame=p["line"])
    if hl is not None:
        cw = w / nc
        fx = x + cw * hl
        b += f'<rect x="{fx - 3:.1f}" y="{y - 3}" width="{cw + 6:.1f}" height="{h + 6}" rx="6" fill="none" stroke="{p["accent"]}" stroke-width="5"/>'
        lab = d.get("badge") or ("推荐" if pg.ctx.get("lang") == "zh" else "Recommended")
        bw = text_width(lab, pg.SZ["label"], True) + 40
        b += pg.rect(fx + cw / 2 - bw / 2, y - 44, bw, 32, p["accent"], 16)
        b += pg.text(fx + cw / 2, y - 22, lab, "label", p["on_accent"], "label", True, "middle")
    if d.get("takeaway"):
        ty = y + h + 56
        b += pg.icon("arrow-right", M, ty - 30, 36, p["accent"])
        b += pg.para(M + 52, ty, d["takeaway"], "sub", p["text"], W - 2 * M - 52, "body", True, 1.35, 2)[0]
    b += pg.chrome()
    return pg.svg(b), "dense"


_MONTH = re.compile(r"^(\S+?月|Q[1-4]\S*|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*|Week \d+|Day \d+)\s+(.*)$")


def r_timeline(pg: Page, d):
    """Open timeline: gradient rail, oversized step numbers, icon + text straight on the page (no boxes),
    vertically centred, with a full-width takeaway band."""
    _need(d, "title", "steps")
    p = pg.p
    icons = d.get("icons") or ["arrow-right"]
    b, top = pg.header(d["title"], d.get("kicker"))
    st = d["steps"]
    n = len(st)
    gap = 40
    w = (W - 2 * M - gap * (n - 1)) / n
    parsed = []
    for t in st:
        if isinstance(t, (list, tuple)):
            parsed.append([t[0], t[1] if len(t) > 1 else ""])
            continue
        m = _MONTH.match(t)
        parsed.append([m.group(1), m.group(2)] if m else [None, t])
    big = pg.SZ["hero"]
    text_h = max((pg.lines(hd or tx, "sub", w - 8, True) * 36) + (pg.lines(tx, "body", w - 8) * 32 + 12 if hd else 0) for hd, tx in parsed)
    block = big * 0.85 + 34 + 120 + text_h
    band = 96 if d.get("takeaway") else 0
    avail = 664 - top - band - 20
    y0 = top + max(30, (avail - block) / 2)
    ry = y0 + big * 0.85 + 34
    b += pg.rect(M, ry - 4, W - 2 * M, 8, pg.grad([(0, p["primary"], 1), (1, p["accent"], 1)]), 4)
    for k, (hd, tx) in enumerate(parsed):
        x = M + k * (w + gap)
        last = k == n - 1
        col = p["accent"] if last else (p["primary"] if not pg.dark else p["text"])
        b += pg.text(x - 4, ry - 30, f"{k + 1:02d}", "hero", col, "data", True)
        b += f'<circle cx="{x + 14}" cy="{ry}" r="14" fill="{p["bg"]}" stroke="{col}" stroke-width="6"/>'
        b += pg.icon(icons[k % len(icons)], x, ry + 30, 48, p["accent"] if last else p["primary"])
        yy = ry + 126
        if hd:
            b += pg.para(x, yy, hd, "sub", p["text"], w - 8, "label", True, 1.3, 2)[0]
            yy += pg.lines(hd, "sub", w - 8, True) * 36 + 10
            b += pg.para(x, yy, tx, "body", p["muted"], w - 8, "body", False, 1.45, 3)[0]
        else:
            b += pg.para(x, yy, tx, "sub", p["text"], w - 8, "body", True, 1.3, 3)[0]
    if d.get("takeaway"):
        ty = 664 - band + 8
        b += pg.rect(M, ty, W - 2 * M, 76, p["tint"] if not pg.dark else p["surface"], 38)
        b += pg.rect(M + 28, ty + 22, 6, 32, p["accent"], 3)
        b += pg.para(M + 56, ty + 47, d["takeaway"], "sub", p["text"], W - 2 * M - 90, "body", True, 1.3, 1)[0]
    b += pg.chrome()
    return pg.svg(b), "dense"


def r_split_photo(pg: Page, d):
    """Half-page photo (left or right) with an optional hero stat on a scrim; the other half carries the argument.
    Two or fewer items are set large and numbered so the column never looks empty."""
    _need(d, "title", "image", "items")
    p = pg.p
    side = d.get("side", "left")
    iw = 560
    ix = 0 if side == "left" else W - iw
    tx = iw + 72 if side == "left" else M
    tw_ = W - iw - 72 - M
    b = pg.image(d["image"], ix, 0, iw, H)
    b += pg.scrim(ix, 0, iw, H, [(0, p["gradient"][0], 0.0), (1, p["gradient"][0], 0.88)])
    stat = d.get("stat")
    if stat:
        vs = "hero" if text_width(stat["value"], pg.SZ["hero"], True) < iw - 100 else "display"
        b += pg.text(ix + 56, H - 150, stat["value"], vs, "#FFFFFF", "data", True)
        b += pg.para(ix + 56, H - 94, stat["label"], "body", "#FFFFFF", iw - 112, "label", False, 1.4, 2, extra='fill-opacity="0.94"')[0]
    b += pg.credit(d["image"], x=ix + iw - 16, y=28)
    hb, top = pg.header(d["title"], d.get("kicker"), width=tw_, x=tx)
    b += hb
    items = d["items"]
    icons = d.get("icons") or ["circle-check"]
    n = len(items)
    few = n <= 2
    avail = 650 - top
    rh = min(200 if few else 140, avail / n)
    y0 = top + 20 + (avail - rh * n) / 2
    for k, it in enumerate(items):
        y = y0 + k * rh
        head, _, desc = str(it).partition(" — ")
        if few:
            lab = d.get("numbering", "Q") if d.get("numbering") is not False else ""
            num = f"{lab}{k + 1}" if lab else f"{k + 1:02d}"
            b += pg.text(tx, y + 54, num, "display", p["accent"] if k == 0 else p["primary"], "data", True)
            nw = text_width(num, pg.SZ["display"], True) + 28
            t, nl = pg.para(tx + nw, y + 30, head, "sub", p["text"], tw_ - nw, "body", True, 1.35, 3)
            b += t
            if desc:
                b += pg.para(tx + nw, y + 30 + nl * 38 + 6, desc, "body", p["muted"], tw_ - nw, "body", False, 1.45, 2)[0]
        else:
            b += f'<circle cx="{tx + 30}" cy="{y + 30:.1f}" r="30" fill="{p["accent"] if k == 0 else p["tint"]}"/>'
            b += pg.icon(icons[k % len(icons)], tx + 13, y + 13, 34, p["on_accent"] if k == 0 else p["primary"])
            if desc:
                b += pg.text(tx + 88, y + 26, head, "sub", p["text"], "label", True)
                b += pg.para(tx + 88, y + 60, desc, "body", p["muted"], tw_ - 88, "body", False, 1.4, 2)[0]
            else:
                b += pg.para(tx + 88, y + 40, head, "sub", p["text"], tw_ - 88, "body", k == 0, 1.35, 2)[0]
        if k < n - 1:
            b += f'<line x1="{tx}" y1="{y + rh - 16:.1f}" x2="{tx + tw_}" y2="{y + rh - 16:.1f}" stroke="{p["line"]}"/>'
    b += pg.text(tx + tw_, 692, f"{pg.n:02d}", "caption", p["muted"], "page_mark", True, "end")
    return pg.svg(b), "dense"


def r_features(pg: Page, d):
    """Open feature columns: oversized gradient-filled icon disc, title, accent rule, description; no card boxes.
    Optional photo band across the top."""
    _need(d, "title", "items")
    p = pg.p
    icons = d.get("icons") or ["star"]
    b, top = pg.header(d["title"], d.get("kicker"))
    it = d["items"]
    n = len(it)
    gap = 56
    w = (W - 2 * M - gap * (n - 1)) / n
    y = top + 70
    for k, item in enumerate(it):
        hd, ds = (item[0], item[1]) if isinstance(item, (list, tuple)) else (str(item).partition(" — ")[0], str(item).partition(" — ")[2])
        x = M + k * (w + gap)
        c2 = [p["accent"], p["accent2"], p["gradient"][1]][k % 3]
        fill = pg.grad([(0, p["gradient"][0] if not pg.dark else p["surface"], 1), (1, c2, 1)], 1, 1)
        b += f'<circle cx="{x + 80}" cy="{y + 80}" r="80" fill="{fill}"/>'
        b += f'<circle cx="{x + 140}" cy="{y + 22}" r="22" fill="{c2}" fill-opacity="0.85"/>'
        b += pg.icon(icons[k % len(icons)], x + 40, y + 40, 80, "#FFFFFF")
        b += pg.text(x, y + 230, f"{k + 1:02d}", "label", p["accent"], "label", True)
        t, nl = pg.para(x, y + 276, hd, "sub", p["text"], w, "label", True, 1.3, 2)
        b += t
        yy = y + 276 + (nl - 1) * 36
        b += pg.rect(x, yy + 22, 48, 6, c2, 3)
        if ds:
            b += pg.para(x, yy + 70, ds, "body", p["muted"], w, "body", False, 1.5, 3)[0]
        if k:
            b += f'<line x1="{x - gap / 2:.1f}" y1="{y + 200}" x2="{x - gap / 2:.1f}" y2="{620}" stroke="{p["line"]}" stroke-width="1.5"/>'
    b += pg.chrome()
    return pg.svg(b), "dense"


def r_comparison(pg: Page, d):
    _need(d, "title", "columns", "rows")
    p = pg.p
    b, top = pg.header(d["title"], d.get("kicker"))
    cols, rows = d["columns"], d["rows"]
    y = top + 44
    w = (W - 2 * M - 32) / 2
    h = 660 - y
    for k, c in enumerate(cols[:2]):
        x = M + k * (w + 32)
        good = k == 1
        fill = p["surface"] if not good else p["primary"]
        ink = p["text"] if not good else "#FFFFFF"
        b += pg.rect(x, y, w, h, fill)
        b += pg.icon("x" if not good else "circle-check", x + 32, y + 30, 40, p["muted"] if not good else p["accent"])
        b += pg.text(x + 88, y + 62, c, "sub", ink, "label", True)
        slot = (h - 110) / len(rows)
        for j, r in enumerate(rows):
            sy = y + 110 + j * slot
            b += f'<line x1="{x + 32}" y1="{sy:.1f}" x2="{x + w - 32}" y2="{sy:.1f}" stroke="{ink}" stroke-opacity="0.18"/>'
            b += pg.para(x + 32, sy + 54, "“" + r[k] + "”", "sub" if good else "body", ink if good else p["muted"], w - 64, "body", good, 1.4, 3)[0]
    b += pg.chrome()
    return pg.svg(b), "dense"


def r_agenda(pg: Page, d):
    _need(d, "title", "items", "image")
    p = pg.p
    iw = 460
    icons = d.get("icons") or ["circle-check"]
    b = pg.image(d["image"], 0, 0, iw, H) + pg.scrim(0, 0, iw, H, [(0, p["gradient"][0], 0.55), (1, p["gradient"][0], 0.92)])
    b += pg.text(56, 560, d["title"], pg.fit(d["title"], ["display", "title"], iw - 90), "#FFFFFF", "title", True)
    b += pg.rect(56, 592, 56, 8, p["accent"], 4)
    b += pg.credit(d["image"], x=iw - 16, y=28)
    items = d["items"]
    x0 = iw + 80
    rh = 560 / len(items)
    for k, it in enumerate(items):
        y = 80 + k * rh
        b += pg.text(x0, y + rh / 2 + 24, f"{k + 1:02d}", "display", p["accent"] if k == 0 else p["muted"], "data", True)
        b += pg.text(x0 + 130, y + rh / 2 + 10, it, "sub", p["text"], "body", k == 0)
        b += pg.icon(icons[k % len(icons)], W - M - 40, y + rh / 2 - 20, 40, p["primary"])
        if k < len(items) - 1:
            b += f'<line x1="{x0}" y1="{y + rh:.1f}" x2="{W - M}" y2="{y + rh:.1f}" stroke="{p["line"]}"/>'
    if d.get("note"):
        b += pg.text(x0, 692, d["note"], "label", p["muted"], "caption")
    return pg.svg(b), "dense"


def r_team(pg: Page, d):
    """Card-free team row: large gradient initial discs (or circle-cropped photos), name, role; highlight pill below."""
    _need(d, "title", "people")
    p = pg.p
    b, top = pg.header(d["title"], d.get("kicker"))
    ppl = d["people"]
    n = len(ppl)
    w = (W - 2 * M) / n
    cy = top + 185
    for k, person in enumerate(ppl):
        name, _, role = str(person).partition(" — ")
        cx = M + k * w + w / 2
        g = pg.grad([(0, p["gradient"][0], 1), (1, p["accent2"] if k % 2 else p["accent"], 1)], 1, 1)
        b += f'<circle cx="{cx:.1f}" cy="{cy}" r="112" fill="{g}"/>'
        b += f'<circle cx="{cx + 82:.1f}" cy="{cy - 82}" r="20" fill="{p["accent"]}"/>'
        ini = "".join(t[0] for t in name.split()[:2]) or name[:1]
        b += pg.text(cx, cy + 20, ini, "display", "#FFFFFF", "label", True, "middle")
        b += pg.text(cx, cy + 172, name, "sub", p["text"], "label", True, "middle")
        if role:
            b += pg.para(cx, cy + 212, role, "body", p["muted"], w - 48, "body", False, 1.4, 2, anchor="middle")[0]
    if d.get("note"):
        ny = 634
        b += pg.rect(M, ny - 40, W - 2 * M, 64, p["tint"] if not pg.dark else p["surface"], 32)
        b += pg.text(W / 2, ny, d["note"], "body", p["text"], "body", True, "middle")
    b += pg.chrome()
    return pg.svg(b), "dense"


def r_closing_photo(pg: Page, d):
    _need(d, "title", "image")
    p = pg.p
    b = pg.image(d["image"], 0, 0, W, H) + pg.scrim(0, 0, W, H, [(0, p["gradient"][0], 0.55), (1, p["gradient"][0], 0.92)])
    b += pg.rect(M, 296, 72, 8, p["accent"], 4)
    t, n = pg.para(M, 392, d["title"], "display", "#FFFFFF", 1060, "title", True, 1.2, 2)
    b += t
    sub = d.get("subtitle") or pg.ctx.get("audience")
    if sub:
        b += pg.text(M, 392 + n * 78 + 16, sub, "sub", "#FFFFFF", "caption", extra='fill-opacity="0.88"')
    b += pg.credit(d["image"])
    return pg.svg(b, "ending", p["gradient"][0]), "anchor"


RECIPES: dict[str, dict[str, Any]] = {
    "cover_photo": dict(fn=r_cover_photo, kind="anchor", needs=["title", "image"], optional=["subtitle", "kicker", "note"],
                        desc="Full-bleed photo cover, gradient scrim, display title bottom-left."),
    "cover_split": dict(fn=r_cover_split, kind="anchor", needs=["title", "image"], optional=["subtitle", "kicker", "note"],
                        desc="Gradient field with oversized wordmark + full-height photo bleeding off the right edge, accent block on the seam."),
    "statement_photo": dict(fn=r_statement_photo, kind="breathing", needs=["title", "image"], optional=["subtitle"],
                            desc="Full-bleed photo with centred display statement; put between data pages."),
    "quote": dict(fn=r_quote, kind="breathing", needs=["quote"], optional=["attribution", "image", "dark"],
                  desc="Oversized quote mark and display-size quote on a gradient field, optional photo panel."),
    "big_number": dict(fn=r_big_number, kind="breathing", needs=["value", "label"], optional=["title", "kicker", "detail", "supporting"],
                       desc="One giant number (180-240px) with a context line and up to 3 supporting stats on an open baseline."),
    "section": dict(fn=r_section, kind="breathing", needs=["title"], optional=["number", "subtitle", "image"],
                    desc="Chapter divider: hero number, display title, optional photo strip."),
    "kpi_hero": dict(fn=r_kpi_hero, kind="dense", needs=["title", "data"], optional=["kicker", "hero_index", "note", "icons"],
                     desc="Asymmetric KPI page: gradient hero-number panel + supporting metric column."),
    "kpi_photo": dict(fn=r_kpi_photo, kind="dense", needs=["title", "data", "image"], optional=["kicker", "note"],
                      desc="Full-bleed photo with an open row of hero numbers along the bottom (no cards)."),
    "kpi_row": dict(fn=r_kpi_row, kind="dense", needs=["title", "data"], optional=["kicker", "note", "icons"],
                    desc="Big-number row on a full-width gradient band; one size for the whole row."),
    "chart_annotated": dict(fn=r_chart_annotated, kind="dense", needs=["title", "chart"],
                            optional=["kicker", "highlight_index", "annotation", "callout", "callout_label", "insight"],
                            desc="Native chart with one highlighted point, callout bubble and a hero-number insight column."),
    "table_highlight": dict(fn=r_table_highlight, kind="dense", needs=["title", "columns", "rows"], optional=["kicker", "highlight", "badge", "takeaway"],
                            desc="Native table, recommended column framed in accent with a badge, takeaway line."),
    "timeline": dict(fn=r_timeline, kind="dense", needs=["title", "steps"], optional=["kicker", "takeaway", "icons"],
                     desc="Open timeline (no boxes): gradient rail, hero step numbers, icon + text, takeaway band."),
    "split_photo": dict(fn=r_split_photo, kind="dense", needs=["title", "image", "items"], optional=["kicker", "stat", "side", "icons", "numbering"],
                        desc="Half-page photo with hero stat; argument column (<=2 items are set large and numbered)."),
    "features": dict(fn=r_features, kind="dense", needs=["title", "items"], optional=["kicker", "icons"],
                     desc="Open feature columns with large gradient icon discs and dividers (no cards)."),
    "comparison": dict(fn=r_comparison, kind="dense", needs=["title", "columns", "rows"], optional=["kicker"],
                       desc="Avoid/prefer two-column contrast; the preferred side is set in primary with larger type."),
    "agenda": dict(fn=r_agenda, kind="dense", needs=["title", "items", "image"], optional=["note", "icons"],
                   desc="Photo panel with title + numbered agenda rows."),
    "team": dict(fn=r_team, kind="dense", needs=["title", "people"], optional=["kicker", "note"],
                 desc="Card-free team row with large gradient initial discs and a highlight pill."),
    "closing_photo": dict(fn=r_closing_photo, kind="anchor", needs=["title", "image"], optional=["subtitle"],
                          desc="Full-bleed photo close with display call to action; echo the cover, do not reuse its photo."),
}

CARD_RECIPES = {"kpi_hero", "kpi_row", "comparison"}

ROLE_MAP = {"title": "title", "subtitle": "subtitle", "body": "body", "label": "label", "caption": "caption",
            "kicker": "kicker", "data": "data", "footnote": "footnote", "page_mark": "page_mark", "chart": "chart", "table": "table"}


def list_recipes() -> list[dict]:
    return [dict(name=k, kind=v["kind"], needs=v["needs"], optional=v["optional"], description=v["desc"], uses_cards=k in CARD_RECIPES)
            for k, v in RECIPES.items()]


# ----------------------------------------------------------------------------- run integration

def _context(run: Path, plan: dict) -> tuple[dict, dict]:
    pj = run / "authoring" / "project"
    cred_path = pj / "images" / "credits.json"
    credits = json.loads(cred_path.read_text(encoding="utf-8")).get("images", {}) if cred_path.exists() else {}
    files = {}
    if (pj / "images").exists():
        for f in sorted((pj / "images").iterdir()):
            if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
                files[f.stem] = f.name
    lock = (pj / "spec_lock.md").read_text(encoding="utf-8") if (pj / "spec_lock.md").exists() else ""
    m = re.search(r"^- audience: (.+)$", lock, re.M)
    lang = plan.get("lang")
    if not lang:
        lm = re.search(r"^- primary_language: (.+)$", lock, re.M)
        lang = "zh" if lm and lm.group(1).lower().startswith("zh") else "en"
    ctx = dict(image_files=files, footer=plan.get("footer", ""), lang=lang,
               audience=plan.get("audience") or (m.group(1) if m and "[fill" not in m.group(1) else ""))
    return ctx, credits


def render_page(run: Path | None, page: dict, number: int, total: int, ctx: dict, credits: dict, palette: dict) -> dict:
    name = page.get("recipe")
    if name not in RECIPES:
        raise _err("recipe_unknown", f"Unknown recipe '{name}'. Run `recipe list`.", {"recipe": name, "known": sorted(RECIPES)})
    pg = Page(palette, ctx, number, total, credits)
    svg, rhythm = RECIPES[name]["fn"](pg, page)
    lib = Path(__file__).resolve().parents[2] / "vendor" / "ppt-master-core" / "skills" / "ppt-master" / "templates" / "icons" / "tabler-outline"
    local = (run / "authoring" / "project" / "icons" / "tabler-outline") if run is not None else None
    if lib.is_dir():
        missing = [i for i in sorted(pg.icons) if not (lib / f"{i}.svg").exists() and not (local and (local / f"{i}.svg").exists())]
        if missing:
            raise _err("recipe_icon_missing", f"Icons not in the vendored tabler-outline library: {', '.join(missing)}",
                       {"missing": missing, "list": "scripts/maintenance/design_icons_tabler_outline.txt"})
    return dict(svg=svg, rhythm=rhythm, icons=sorted(pg.icons), objects=pg.objs, images=pg.images, recipe=name)


def _update_manifest(run: Path, results: dict[int, dict]) -> None:
    path = run / "authoring" / "semantic_manifest.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"schema_version": "2.0", "objects": []}
    data.setdefault("defaults", {})
    pal_font = None
    lock = run / "authoring" / "project" / "spec_lock.md"
    if lock.exists():
        m = re.search(r"^- font_family: (.+)$", lock.read_text(encoding="utf-8"), re.M)
        if m and "[fill" not in m.group(1):
            pal_font = m.group(1).split(",")[0].strip()
    if pal_font:
        data["defaults"].setdefault("roundtrip_font_family", pal_font)
    keep = [o for o in data.get("objects", []) if o.get("slide") not in results and not str(o.get("source_id", "")).startswith("example")]
    for n, r in sorted(results.items()):
        for o in r["objects"]:
            role = ROLE_MAP[o["role"]]
            keep.append(dict(source_id=f"s{n}-{o['id']}", slide=n, role=role, editable=True,
                             postflight_sensitive=role in ("title", "body", "subtitle", "data"),
                             preferred_structure={"chart": "native_chart", "table": "native_table"}.get(role, "top_level"),
                             source_selector=dict(file=f"svg_output/{n:02d}.svg", id=o["id"]), match=dict(drawingml_id=o["sid"])))
    data["objects"] = sorted(keep, key=lambda o: (o.get("slide", 0)))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _update_spec_lock(run: Path, results: dict[int, dict], total: int) -> None:
    path = run / "authoring" / "project" / "spec_lock.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    m = re.search(r"^- inventory: (.*)$", text, re.M)
    if m:
        have = set() if "[fill" in m.group(1) else {x.strip() for x in m.group(1).split(",") if x.strip()}
        have |= {i for r in results.values() for i in r["icons"]}
        if have:
            text = text[:m.start()] + "- inventory: " + ", ".join(sorted(have)) + text[m.end():]
    # page rhythm: keep author-written lines, fill/replace the rendered pages
    sec = re.search(r"(## page_rhythm\n)(.*?)(\n## |\Z)", text, re.S)
    if sec:
        rows = {}
        for line in sec.group(2).splitlines():
            mm = re.match(r"- P(\d+): (.+)", line.strip())
            if mm and "[fill" not in mm.group(2):
                rows[int(mm.group(1))] = mm.group(2)
        for n, r in results.items():
            rows[n] = r["rhythm"]
        body = "\n".join(f"- P{n:02d}: {v}" for n, v in sorted(rows.items()))
        text = text[:sec.start(2)] + body + "\n" + text[sec.end(2):]
    path.write_text(text, encoding="utf-8")


def apply(run: Path, pages: list[dict], numbers: list[int], plan: dict | None = None, replace_all: bool = False) -> dict:
    run = Path(run)
    plan = plan or {}
    svg_dir = run / "authoring" / "project" / "svg_output"
    if not svg_dir.parent.exists():
        raise _err("recipe_run_missing", "Run has no authoring/project; run `init --mode generate` first.", {"run": str(run)})
    svg_dir.mkdir(parents=True, exist_ok=True)
    palette = load_palette(run, plan.get("design"))
    ctx, credits = _context(run, plan)
    existing = sorted(svg_dir.glob("*.svg"))
    total = max(numbers + [len(existing)]) if not replace_all else len(pages)
    results = {}
    for page, n in zip(pages, numbers):
        results[n] = render_page(run, page, n, total, ctx, credits, palette)
    if replace_all:
        for f in existing:
            f.unlink()
    for n, r in results.items():
        (svg_dir / f"{n:02d}.svg").write_text(r["svg"], encoding="utf-8")
    _update_manifest(run, results)
    _update_spec_lock(run, results, total)
    warnings = []
    seq = [r["recipe"] for _, r in sorted(results.items())]
    for a, b_ in zip(seq, seq[1:]):
        if a == b_:
            warnings.append(f"recipe '{a}' used on consecutive pages; vary the composition")
    body = [r for n, r in sorted(results.items()) if RECIPES[r["recipe"]]["kind"] == "dense"]
    if body and sum(1 for r in body if r["recipe"] in CARD_RECIPES) > len(body) / 2:
        warnings.append("more than half of the body pages are card-based; mix in split_photo / big_number / timeline / features / quote")
    used = [r["images"] for _, r in sorted(results.items())]
    flat = [i for u in used for i in u]
    dup = sorted({i for i in flat if flat.count(i) > 1})
    return dict(status="ok", pages={n: dict(file=f"svg_output/{n:02d}.svg", recipe=r["recipe"], rhythm=r["rhythm"], icons=r["icons"])
                                     for n, r in sorted(results.items())},
                warnings=warnings + ([f"image reused on several pages: {', '.join(dup)}"] if dup else []))


def apply_deck(run: Path, plan_path: Path) -> dict:
    plan = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    pages = plan.get("pages") or []
    if not pages:
        raise _err("recipe_plan_empty", "Plan needs a non-empty 'pages' list.", {"plan": str(plan_path)})
    return apply(run, pages, list(range(1, len(pages) + 1)), plan, replace_all=True)
