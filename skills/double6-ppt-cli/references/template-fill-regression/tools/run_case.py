"""run_case.py <spec.json> <backend: v48|pm6|pm6-svg|pm6-svg-restore> <run_dir>

Drives the real d6ppt template-fill flow (init -> analyze -> asset import -> check -> apply) so both
backends go through identical wrapper logic (dispositions, provenance, nav, SHA-bound images, gate).
"""
import json, os, subprocess, sys, shutil, hashlib
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
D6_PM6 = Path("/workspace/wt-pm6-template/skills/double6-ppt-cli/scripts/d6ppt.py")
D6_V48 = Path("/workspace/wt-v48-ref/skills/double6-ppt-cli/scripts/d6ppt.py")
D6 = D6_PM6
PY = str(EVAL / "venv/bin/python")
RT = "/workspace/ppt-test/env/runtime"

def d6(args, env):
    tool = D6_V48 if env.get('D6PPT_TEMPLATE_BACKEND') == 'v48' else D6_PM6
    proc = subprocess.run([PY, str(tool), *args], capture_output=True, text=True, env=env, timeout=1200)
    try:
        out = json.loads(proc.stdout[proc.stdout.index("{"):]) if "{" in proc.stdout else {}
    except Exception:
        out = {"raw": proc.stdout[-3000:]}
    return proc.returncode, out, proc.stderr[-3000:]

def main(spec_path, backend, run_dir):
    spec = json.load(open(spec_path))
    run_dir = Path(run_dir); shutil.rmtree(run_dir, ignore_errors=True); run_dir.parent.mkdir(parents=True, exist_ok=True)
    work = run_dir.with_name(run_dir.name + "_inputs"); shutil.rmtree(work, ignore_errors=True); work.mkdir()
    env = dict(os.environ, HOME="/workspace/ppt-test/env/home")
    env["D6PPT_TEMPLATE_BACKEND"] = "v48"
    if backend.startswith("pm6"):
        env["D6PPT_TEMPLATE_BACKEND"] = "pm6"
        env["D6PPT_PM6_PYTHON"] = PY
        env["D6PPT_PM6_TEXT_MODE"] = {"pm6": "native", "pm6-svg": "svg", "pm6-svg-restore": "svg-restore"}[backend]
    # content.json: one entry per plan slide holding every string that slide will show
    content = {"title": spec["title"], "slides": []}
    for i, s in enumerate(spec["slides"], 1):
        row = {"index": i}
        for k, v in s.get("text", {}).items(): row[f"text:{k}"] = v["text"] if isinstance(v, dict) else v
        for k, v in s.get("tables", {}).items(): row[f"table:{k}"] = v
        content["slides"].append(row)
    (work / "content.json").write_text(json.dumps(content, ensure_ascii=False, indent=1))
    log = {"backend": backend, "steps": []}
    def step(name, args):
        rc, out, err = d6(args, env)
        log["steps"].append({"step": name, "rc": rc, "out": out, "stderr": err})
        return rc, out
    step("init", ["init", "--mode", "template-fill", "--source", str(work / "content.json"), "--template", str(EVAL / "templates" / spec["template"]), "--out", str(run_dir), "--verify-tier", "portable"])
    rc, out = step("analyze", ["template-analyze", "--run", str(run_dir)])
    if rc: return finish(run_dir, log, "analyze_failed")
    profile = json.load(open(run_dir / "artifacts/template_profile.json"))
    scaffold = json.load(open(run_dir / "plans/template_plan_scaffold.json"))
    objs = {}
    for o in profile["objects"]:
        objs.setdefault(o["source_template_slide"], []).append(o)
    nav = spec.get("navigation") or {}
    plan = {k: v for k, v in scaffold.items() if k not in ("slides", "object_dispositions")}
    plan.update({"status": "confirmed", "slides": [], "object_dispositions": [], "image_edits": [], "numeric_claims": []})
    for i, s in enumerate(spec["slides"], 1):
        src = s["source"]
        by_name = {}
        for o in objs.get(src, []):
            by_name.setdefault(o["drawingml_name"], []).append(o)
        reps, used = [], {}
        def one(name):
            cands = by_name.get(name) or []
            if len(cands) != 1: raise SystemExit(f"slide {src}: name {name!r} matches {len(cands)}")
            return cands[0]
        for name, text in s.get("text", {}).items():
            o = one(name); used[o["source_object_id"]] = "replace_content"
            extra = {}
            if isinstance(text, dict):
                if backend.startswith("pm6") and "levels" in text: extra["levels"] = text["levels"]
                text = text["text"]
            reps.append({"slot_id": f"s{src:02d}_sh{o['drawingml_id']}", "old_text": o["text"], "text": text, **extra})
        for name, label in (nav.get("tabs") or {}).items():
            if name in by_name:
                o = one(name); used[o["source_object_id"]] = "update_navigation"
                reps.append({"slot_id": f"s{src:02d}_sh{o['drawingml_id']}", "old_text": o["text"], "text": label})
        tedits = []
        for name, rows in s.get("tables", {}).items():
            o = one(name); used[o["source_object_id"]] = "replace_content"
            tedits.append({"table_id": f"s{src:02d}_tbl{o['drawingml_id']}", "cells": [{"row": r, "col": c, "text": v} for r, row in enumerate(rows) for c, v in enumerate(row)]})
        cedits = []
        for name, data in s.get("charts", {}).items():
            o = one(name); used[o["source_object_id"]] = "replace_content"
            cedits.append({"chart_id": f"s{src:02d}_ch{o['drawingml_id']}", **data})
        for name, asset in s.get("images", {}).items():
            o = one(name); used[o["source_object_id"]] = "replace_content"
            aname = f"img_{i:02d}_{Path(asset).name}"
            rc, out = step("asset", ["template-asset-import", "--run", str(run_dir), "--asset", str(EVAL / asset), "--name", aname])
            digest = hashlib.sha256((EVAL / asset).read_bytes()).hexdigest()
            plan["image_edits"].append({"plan_slide": i, "source_object_id": o["source_object_id"], "asset_name": aname, "asset_sha256": digest, "user_confirmed": True,
                                        "expected_fingerprint": {"drawingml_id": o["drawingml_id"], "object_type": o["object_type"], "text_sha256": o["text_sha256"], "media_sha256": o["media_sha256"]}})
        for name in s.get("remove", []):
            o = one(name); used[o["source_object_id"]] = "remove_sample"
        ps = {"source_slide": src, "purpose": "content", "layout_rationale": {"layout_pattern": "content", "why_fit": "spec", "risk": "low"},
              "replacements": reps, "table_edits": tedits, "chart_edits": cedits}
        if "notes" in s: ps["notes"] = s["notes"]
        if "transition" in s: ps["transition"] = s["transition"]
        plan["slides"].append(ps)
        for o in objs.get(src, []):
            disp = used.get(o["source_object_id"])
            if disp is None:
                disp = "remove_sample" if o["role"] in ("sample_content", "sample_formula_media") else "keep_design"
                if o["role"] == "navigation": disp = "keep_design"
            plan["object_dispositions"].append({"plan_slide": i, "source_slide": src, "source_object_id": o["source_object_id"], "disposition": disp,
                "user_confirmed": True, "expected_fingerprint": {"drawingml_id": o["drawingml_id"], "object_type": o["object_type"], "text_sha256": o["text_sha256"], "media_sha256": o["media_sha256"]}})
    if nav:
        plan["navigation_targets"] = [{"label": k, "target_plan_slide": v} for k, v in nav["targets"].items()]
        plan["navigation_source_targets"] = [{"source_template_slide": int(k), "target_plan_slide": v} for k, v in nav["source_targets"].items()]
    plan_path = run_dir.parent / (run_dir.name + "_plan.json")
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1))
    rc, out = step("check", ["template-check-plan", "--run", str(run_dir), "--plan", str(plan_path)])
    if rc: return finish(run_dir, log, "check_failed")
    rc, out = step("apply", ["template-apply", "--run", str(run_dir), "--plan", str(plan_path), "--runtime-dir", RT])
    if rc: return finish(run_dir, log, "apply_failed")
    return finish(run_dir, log, "ok")

def finish(run_dir, log, status):
    log["status"] = status
    (run_dir.parent / (run_dir.name + "_log.json")).write_text(json.dumps(log, ensure_ascii=False, indent=1))
    print(status, run_dir)
    if status != "ok":
        last = log["steps"][-1]
        print(json.dumps(last["out"], ensure_ascii=False)[:2500], last["stderr"][-1500:])
    return 0 if status == "ok" else 1

if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
