#!/usr/bin/env python3
"""One-click verification of the PM6 template-fill backend on a real Microsoft PowerPoint.

Run via ``verify_template_fill_windows.cmd`` (double-click) or ``verify_template_fill_macos.command``.
It (1) creates a private virtualenv and installs the locked dependencies, (2) builds the bundled
cases, runs plan check + apply with the vendored PPT Master v6.7.0 core, (3) opens every output in
PowerPoint, forces PowerPoint to recompute shrink-text-on-overflow (Windows) and measures the text
height of every frame, re-saves a copy and exports PDF/PNG, and (4) writes a report folder + ZIP
to send back. Nothing outside the report folder and the private venv is modified.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import platform
import shutil
import subprocess
import sys
import traceback
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parents[1]
SCRIPTS = HERE.parent
LOCK = SKILL / "requirements-core.lock"


def _venv_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "double6-template-fill-verify" / f"venv-py{sys.version_info.major}{sys.version_info.minor}"


def bootstrap() -> None:
    """Re-exec inside a private venv with the locked dependencies (idempotent)."""
    if os.environ.get("D6_VERIFY_IN_VENV") == "1" or os.environ.get("D6_VERIFY_NO_VENV") == "1":
        return
    if sys.version_info < (3, 11):
        sys.exit("需要 Python 3.11 或更高版本 / Python 3.11+ required")
    venv = _venv_dir()
    py = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    stamp = venv / "lock.sha"
    import hashlib
    want = hashlib.sha256(LOCK.read_bytes()).hexdigest()
    if not py.exists() or not stamp.exists() or stamp.read_text().strip() != want:
        print(f"[1/4] 创建独立环境并安装依赖：{venv}")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
        subprocess.check_call([str(py), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", str(LOCK)])
        stamp.write_text(want)
    else:
        print(f"[1/4] 复用独立环境：{venv}")
    env = dict(os.environ, D6_VERIFY_IN_VENV="1")
    sys.exit(subprocess.call([str(py), str(Path(__file__).resolve()), *sys.argv[1:]], env=env))


def _report_dir() -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    host = platform.node().split(".")[0] or "host"
    base = Path.home() / ("Desktop" if (Path.home() / "Desktop").is_dir() else "")
    return base / f"double6-template-fill-verify-{host}-{stamp}"


def run_cases(out: Path) -> list[dict]:
    sys.path.insert(0, str(SCRIPTS))
    sys.path.insert(0, str(HERE))
    from double6_ppt_cli.pm6_template import analyze_pptx, apply_plan, check_plan
    from double6_ppt_cli.pm6_template.roundtrip import pm6_root
    import cases
    results = []
    (out / "decks").mkdir(parents=True, exist_ok=True)
    for name, build, make_plan in cases.CASES:
        row = {"case": name}
        try:
            tpl = out / "decks" / f"{name}.template.pptx"
            build(tpl)
            lib = analyze_pptx(tpl)
            plan = make_plan(lib)
            (out / "decks" / f"{name}.plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
            report = check_plan(lib, plan)
            row["check_summary"] = report["summary"]
            row["check_findings"] = [r for r in report["results"] if r.get("status") != "OK"]
            row["expected"] = getattr(cases, "EXPECT", {}).get(name, "applied")
            if report["summary"].get("error"):
                row["status"] = "blocked_by_check"
                row["as_expected"] = row["expected"] == "blocked_by_check"
                results.append(row)
                continue
            dest = out / "filled" / f"{name}.pptx"
            dest.parent.mkdir(parents=True, exist_ok=True)
            receipt = apply_plan(tpl, plan, dest)
            row.update({"status": "applied", "export_summary": receipt.get("export_summary"), "text": receipt.get("text"),
                        "notes": receipt.get("notes"), "transitions": receipt.get("transitions"), "pm6_root": str(pm6_root()),
                        "as_expected": row["expected"] == "applied"})
        except Exception as exc:  # report, keep going
            row.update({"status": "error", "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-3000:]})
        results.append(row)
    return results


def _find_powerpoint() -> str | None:
    if sys.platform == "win32":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
            root = os.environ.get(env)
            if root:
                for ver in ("Office16", "Office15"):
                    exe = Path(root) / "Microsoft Office" / "root" / ver / "POWERPNT.EXE"
                    if exe.is_file():
                        return str(exe)
        return "COM"  # click-to-run installs may live elsewhere; COM activation decides
    if sys.platform == "darwin":
        app = Path("/Applications/Microsoft PowerPoint.app")
        return str(app) if app.exists() else None
    return None


def powerpoint_stage(out: Path) -> dict:
    filled, meas = out / "filled", out / "powerpoint"
    meas.mkdir(exist_ok=True)
    info = {"platform": sys.platform, "powerpoint": _find_powerpoint()}
    if not info["powerpoint"]:
        info["status"] = "skipped_no_powerpoint"
        return info
    try:
        if sys.platform == "win32":
            proc = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "powerpoint_measure.ps1"),
                                   "-InDir", str(filled), "-OutDir", str(meas)], capture_output=True, text=True, timeout=1800)
            info.update({"stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:], "returncode": proc.returncode})
            data = meas / "powerpoint_measure.json"
            if data.exists():
                raw = json.loads(data.read_text(encoding="utf-8-sig") or "[]")
                info["shapes"] = raw if isinstance(raw, list) else [raw]
        elif sys.platform == "darwin":
            info["shapes"] = []
            script = (HERE / "powerpoint_measure.applescript").read_text(encoding="utf-8")
            for deck in sorted(filled.glob("*.pptx")):
                proc = subprocess.run(["osascript", "-", str(deck), str(meas), deck.stem], input=script, capture_output=True, text=True, timeout=900)
                info.setdefault("runs", []).append({"deck": deck.stem, "returncode": proc.returncode, "stderr": proc.stderr[-1500:]})
                def num(x):
                    try:
                        return float(x.replace(",", "."))
                    except ValueError:
                        return None
                for line in proc.stdout.splitlines():
                    parts = line.split("\t")
                    if parts and parts[0] == "F" and len(parts) >= 7:
                        info.setdefault("frames", []).append({"deck": deck.stem, "slide": int(parts[1]), "name": parts[2], "left": num(parts[3]),
                                                              "top": num(parts[4]), "width": num(parts[5]), "height": num(parts[6])})
                    elif len(parts) >= 8:
                        h, bh, mt, mb = num(parts[2]), num(parts[3]), num(parts[6]), num(parts[7])
                        info["shapes"].append({"deck": deck.stem, "slide": int(parts[0]), "name": parts[1], "height": h, "bound_height_after": bh,
                                               "autosize": parts[4], "font_size_after": num(parts[5]), "margin_top": mt, "margin_bottom": mb,
                                               "overflow_pt": round(bh - (h - (mt or 0) - (mb or 0)), 2) if None not in (h, bh) else None,
                                               "left": num(parts[8]) if len(parts) > 10 else None, "top": num(parts[9]) if len(parts) > 10 else None,
                                               "width": num(parts[10]) if len(parts) > 10 else None})
        info["status"] = "measured" if info.get("shapes") else "failed"
    except Exception as exc:
        info.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
    return info


def _frames(out: Path, ppt: dict) -> list[dict]:
    f = out / "powerpoint" / "powerpoint_frames.json"
    if f.exists():
        raw = json.loads(f.read_text(encoding="utf-8-sig") or "[]")
        return raw if isinstance(raw, list) else [raw]
    return ppt.get("frames") or []


def _text_rect(m: dict) -> tuple[float, float, float, float] | None:
    if m.get("top") is None or m.get("bound_height_after") is None:
        return None
    top = m.get("bound_top_open")
    if top is None:
        top = m["top"] + (m.get("margin_top") or 0)
    left = m.get("bound_left_open", m.get("left")) or 0.0
    width = m.get("bound_width_open", m.get("width")) or 0.0
    return (left, top, left + width, top + m["bound_height_after"])


def _overlaps(m: dict, frames: list[dict], slide_w: float = 0.0, shapes: list[dict] | None = None) -> list[str]:
    """Shapes hit by the rendered text itself (PowerPoint's text bounds, not the frame).

    Frames often overlap by design (a body placeholder behind cards); only text that actually reaches
    another shape counts. For another *text* shape its rendered text is the obstacle, not its frame
    (PowerPoint 16 run: card text vs. the body placeholder frame behind it was a false positive).
    """
    text = _text_rect(m)
    if text is None:
        return []
    by_key = {(s.get("deck"), s.get("slide"), s.get("id")): s for s in (shapes or []) if s.get("id") is not None}
    hits = []
    for f in frames:
        if f.get("deck") != m.get("deck") or f.get("slide") != m.get("slide"):
            continue
        if (f.get("id") is not None and f.get("id") == m.get("id")) or (f.get("id") is None and f.get("name") == m.get("name")):
            continue
        if slide_w and f.get("width", 0) >= 0.9 * slide_w:
            continue  # full-slide background
        other = by_key.get((f.get("deck"), f.get("slide"), f.get("id")))
        r = _text_rect(other) if other is not None else None
        if r is None:
            r = (f["left"], f["top"], f["left"] + f["width"], f["top"] + f["height"])
        if r[0] < text[2] - 1 and text[0] < r[2] - 1 and r[1] < text[3] - 1 and text[1] < r[3] - 1:
            hits.append(f.get("name") or str(f.get("id")))
    return hits


def compare(out: Path, cases_rows: list[dict], ppt: dict) -> dict:
    """Join our fit decisions with PowerPoint's measurement.

    A slot FAILS when PowerPoint shows overflow (as opened or after forcing its own autofit recompute),
    when PowerPoint's recompute wants a different size than ours (font size changes or a saved fontScale
    != 1.0: we bake explicit sizes, so PowerPoint must not need to shrink further), or when the spilled
    text overlaps another shape.
    """
    from lxml import etree
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    rows = []
    shapes = ppt.get("shapes") or []
    frames = _frames(out, ppt)
    for case in cases_rows:
        if case.get("status") != "applied":
            continue
        resaved = out / "powerpoint" / f"{case['case']}.powerpoint.pptx"
        saved_scale, slide_w = {}, 0.0
        if resaved.exists():
            with zipfile.ZipFile(resaved) as z:
                pres = etree.fromstring(z.read("ppt/presentation.xml"))
                sz = pres.find("p:sldSz", ns)
                slide_w = int(sz.get("cx")) / 12700 if sz is not None else 0.0
                for n in z.namelist():
                    if n.startswith("ppt/slides/slide") and n.endswith(".xml"):
                        slide_no = int(n[len("ppt/slides/slide"):-4])
                        root = etree.fromstring(z.read(n))
                        for sp in root.iter("{%s}sp" % ns["p"]):
                            c = sp.find("./p:nvSpPr/p:cNvPr", ns)
                            norm = sp.find("./p:txBody/a:bodyPr/a:normAutofit", ns)
                            if c is not None:
                                saved_scale[(slide_no, int(c.get("id")))] = (int(norm.get("fontScale", "100000")) / 100000) if norm is not None else None
        for t in case.get("text") or []:
            sid, slide = t.get("drawingml_id"), t.get("plan_slide")
            m = next((s for s in shapes if s.get("deck") == case["case"] and s.get("slide") == slide and s.get("id") == sid), None)
            row = {"case": case["case"], "plan_slide": slide, "drawingml_id": sid, "our_fit": t.get("fit"), "our_font_scale": t.get("font_scale"),
                   "our_need_h_pt": t.get("need_h_pt"), "avail_h_pt": t.get("avail_h_pt"),
                   "powerpoint_font_scale_saved": saved_scale.get((slide, sid))}
            failures = []
            if m:
                row.update({"powerpoint_overflow_open_pt": m.get("overflow_open_pt"), "powerpoint_overflow_pt": m.get("overflow_pt"),
                            "powerpoint_font_size_open": m.get("font_size_first_run"), "powerpoint_font_size_after": m.get("font_size_after"),
                            "powerpoint_bound_h_pt": m.get("bound_height_after")})
                if max(m.get("overflow_open_pt") or -1, m.get("overflow_pt") or -1) > 2.0:
                    failures.append("overflow")
                fo, fa = m.get("font_size_first_run"), m.get("font_size_after")
                if isinstance(fo, (int, float)) and isinstance(fa, (int, float)) and abs(fo - fa) > 0.5:
                    failures.append("powerpoint_recompute_changed_size")
                hits = _overlaps(m, frames, slide_w, shapes)
                if hits:
                    row["overlaps"] = hits
                    failures.append("overlap")
            ss = row["powerpoint_font_scale_saved"]
            if ss is not None and abs(ss - 1.0) > 0.01:
                failures.append("font_scale_mismatch")
            row["failures"] = failures
            row["verdict"] = "FAIL" if failures else ("PASS" if m else "UNMEASURED")
            rows.append(row)
    overflow = [r for r in rows if "overflow" in r["failures"]]
    failed = [r for r in rows if r["failures"]]
    scale_pairs = [(r["our_font_scale"], r["powerpoint_font_scale_saved"]) for r in rows if r["our_font_scale"] and r["powerpoint_font_scale_saved"]]
    return {"slots": rows, "slots_measured": sum(1 for r in rows if r["verdict"] != "UNMEASURED"),
            "slots_overflowing_in_powerpoint": len(overflow), "overflow_detail": overflow,
            "slots_overlapping": sum(1 for r in rows if "overlap" in r["failures"]),
            "slots_font_scale_mismatch": sum(1 for r in rows if {"font_scale_mismatch", "powerpoint_recompute_changed_size"} & set(r["failures"])),
            "font_scale_max_abs_diff": round(max((abs(1.0 - b) for _a, b in scale_pairs), default=0.0), 3),
            "slots_failed": len(failed), "status": "failed" if failed else ("passed" if rows else "no_data")}


def write_markdown(out: Path, report: dict) -> None:
    L = ["# Double6 模板填充（PPT Master v6.7.0）PowerPoint 实机验证报告", "",
         f"- 时间：{report['created_at']}", f"- 系统：{report['host']['platform']} / Python {report['host']['python']}",
         f"- PowerPoint：{report['powerpoint'].get('powerpoint')}（状态：{report['powerpoint'].get('status')}）", ""]
    for c in report["cases"]:
        L.append(f"## 用例 {c['case']}：{c.get('status')}（预期 {c.get('expected')}，{'符合' if c.get('as_expected') else '不符合'}）")
        if c.get("error"):
            L.append(f"错误：`{c['error']}`")
        if c.get("check_summary"):
            L.append(f"- 计划检查：{c['check_summary']}")
        if c.get("export_summary"):
            L.append(f"- 导出：{c['export_summary']}")
        L.append("")
    cmp_ = report.get("comparison") or {}
    L += ["## PowerPoint 测量", f"- 已测量文本框：{cmp_.get('slots_measured')}",
          f"- PowerPoint 中溢出（>2pt）的文本框：{cmp_.get('slots_overflowing_in_powerpoint')}",
          f"- 溢出文字压到其他形状上的文本框：{cmp_.get('slots_overlapping')}",
          f"- PowerPoint 重算后字号/fontScale 与我方不一致的文本框：{cmp_.get('slots_font_scale_mismatch')}",
          f"- **总判定：{cmp_.get('status')}**（失败文本框 {cmp_.get('slots_failed')} 个）", ""]
    for r in cmp_.get("slots") or []:
        L.append(f"  - {r['case']} 第{r['plan_slide']}页 id={r['drawingml_id']}：{r['verdict']} "
                 f"我方={r.get('our_fit')}/{r.get('our_font_scale')} 预计高 {r.get('our_need_h_pt')}pt / 可用 {r.get('avail_h_pt')}pt；"
                 f"PowerPoint 字号 {r.get('powerpoint_font_size_open')}→{r.get('powerpoint_font_size_after')} 文本高 {r.get('powerpoint_bound_h_pt')}pt "
                 f"溢出 {r.get('powerpoint_overflow_pt')}pt {('失败原因 ' + ','.join(r['failures'])) if r['failures'] else ''} "
                 f"{('压到 ' + ','.join(r.get('overlaps') or [])) if r.get('overlaps') else ''}")
    L += ["",
          "请把同目录下的 ZIP 文件发回。"]
    (out / "REPORT.md").write_text("\n".join(L), encoding="utf-8")


def main() -> int:
    bootstrap()
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else _report_dir()
    out.mkdir(parents=True, exist_ok=True)
    print(f"[2/4] 运行模板填充用例 → {out}")
    cases_rows = run_cases(out)
    print("[3/4] 在 PowerPoint 中打开、重算自动调整并测量（请勿操作 PowerPoint）")
    ppt = powerpoint_stage(out)
    report = {"schema": "double6_template_fill_powerpoint_verify.v1", "created_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
              "host": {"platform": platform.platform(), "python": platform.python_version(), "machine": platform.machine()},
              "cases": cases_rows, "powerpoint": {k: v for k, v in ppt.items() if k != "shapes"}, "powerpoint_shapes": ppt.get("shapes")}
    report["comparison"] = compare(out, cases_rows, ppt)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    write_markdown(out, report)
    archive = out.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in out.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(out.parent))
    print(f"[4/4] 完成。请把这个文件发回：{archive}")
    ok = all(c.get("as_expected") for c in cases_rows) and report["comparison"].get("status") != "failed"
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
