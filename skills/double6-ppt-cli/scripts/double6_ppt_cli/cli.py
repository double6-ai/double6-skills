"""CLI entry. Heavy imports are deferred so bootstrap/doctor work without lxml."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bootstrap import bootstrap
from .common import D6PPTError, default_runtime_dir


def _emit(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="d6ppt", description="Double6 native editable PPTX authoring and postflight CLI")
    parser.add_argument("--runtime-dir", type=Path, default=None, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("doctor"); p.add_argument("--json", action="store_true"); p.add_argument("--runtime-dir", type=Path); p.add_argument("--verify-tier", choices=("auto", "native", "portable"), default="auto"); p.add_argument("--mode", choices=("generate", "postflight", "template-fill"))
    p = sub.add_parser("bootstrap"); p.add_argument("--runtime-dir", type=Path, required=True); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("init"); p.add_argument("--mode", choices=("generate", "postflight", "template-fill"), required=True); p.add_argument("--source", type=Path, required=True); p.add_argument("--template", type=Path); p.add_argument("--contract", type=Path); p.add_argument("--out", type=Path, required=True); p.add_argument("--verify-tier", choices=("auto", "native", "portable"), default="auto"); p.add_argument("--design-profile", "--design", dest="design_profile", choices=("neutral", "academic", "business", "training"), default="neutral")
    p = sub.add_parser("compile"); p.add_argument("--run", type=Path, required=True); p.add_argument("--no-native-charts-and-tables", action="store_true")
    p = sub.add_parser("template-analyze"); p.add_argument("--run", type=Path, required=True)
    p = sub.add_parser("template-asset-import"); p.add_argument("--run", type=Path, required=True); p.add_argument("--asset", type=Path, required=True); p.add_argument("--name", required=True)
    p = sub.add_parser("template-check-plan"); p.add_argument("--run", type=Path, required=True); p.add_argument("--plan", type=Path, required=True)
    p = sub.add_parser("template-apply"); p.add_argument("--run", type=Path, required=True); p.add_argument("--plan", type=Path, required=True); p.add_argument("--runtime-dir", type=Path)
    p = sub.add_parser("package-clean"); p.add_argument("--run", type=Path, required=True)
    p = sub.add_parser("visual-policy"); p.add_argument("--run", type=Path, required=True); p.add_argument("--capability", choices=("available", "unavailable", "unknown"), required=True); p.add_argument("--decision", choices=("perform", "waive"), required=True); p.add_argument("--reason", choices=("user_declined_switch", "no_visual_model", "user_requested_skip")); p.add_argument("--user-ack", action="store_true")
    p = sub.add_parser("visual-review"); p.add_argument("--run", type=Path, required=True); p.add_argument("--status", choices=("accepted", "accepted_with_warnings", "rejected"), required=True); p.add_argument("--reviewer", required=True); p.add_argument("--notes", required=True)
    p = sub.add_parser("render-import"); p.add_argument("--run", type=Path, required=True); p.add_argument("--pdf", type=Path, required=True); p.add_argument("--pages", type=Path, required=True, nargs="+"); p.add_argument("--contact-sheet", type=Path, required=True); p.add_argument("--tier", choices=("portable", "native"), default="portable"); p.add_argument("--renderer", required=True); p.add_argument("--fact-source", required=True)
    p = sub.add_parser("inspect"); p.add_argument("--run", type=Path, required=True); p.add_argument("--runtime-dir", type=Path)
    p = sub.add_parser("route"); p.add_argument("--run", type=Path, required=True); p.add_argument("--finding", required=True)
    p = sub.add_parser("patch"); p.add_argument("--run", type=Path, required=True); p.add_argument("--spec", type=Path, required=True); p.add_argument("--runtime-dir", type=Path)
    p = sub.add_parser("patch-plan"); p.add_argument("--run", type=Path, required=True); p.add_argument("--out", type=Path, required=True); p.add_argument("--confirm-finding", action="append", default=[])
    p = sub.add_parser("verify"); p.add_argument("--run", type=Path, required=True); p.add_argument("--runtime-dir", type=Path); p.add_argument("--compatibility", choices=("none", "libreoffice"), default="none"); p.add_argument("--verify-tier", dest="verify_tier", choices=("auto", "native", "portable"), default="auto", help="auto: native when PowerPoint is usable, else portable OfficeCLI tier")
    p = sub.add_parser("finalize"); p.add_argument("--run", type=Path, required=True)
    p = sub.add_parser("self-test"); p.add_argument("--runtime-dir", type=Path); p.add_argument("--integration", action="store_true")
    return parser


def _import_render_importer():
    from .render_evidence import record_render_manifest
    from .common import load_run, resolve_run_path, sha256_file
    return record_render_manifest, load_run, resolve_run_path, sha256_file


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            from .doctor import doctor
            result = doctor(args.runtime_dir, verify_tier=args.verify_tier, mode=args.mode)
        elif args.command == "bootstrap":
            result = bootstrap(args.runtime_dir, confirmed=args.yes)
        elif args.command == "init":
            from .runs import init_run
            result = init_run(
                args.mode,
                args.source,
                args.out,
                args.template,
                args.contract,
                verify_tier=args.verify_tier,
                design_profile=args.design_profile,
            )
        elif args.command == "compile":
            from .compiler import compile_run
            result = compile_run(args.run, native_charts_and_tables=not args.no_native_charts_and_tables)
        elif args.command == "template-analyze":
            from .template_workflow import analyze_template
            result = analyze_template(args.run)
        elif args.command == "template-asset-import":
            from .template_workflow import import_template_asset
            result = import_template_asset(args.run, args.asset, args.name)
        elif args.command == "template-check-plan":
            from .template_workflow import check_template_plan
            result = check_template_plan(args.run, args.plan)
        elif args.command == "template-apply":
            from .template_workflow import apply_template_plan
            result = apply_template_plan(args.run, args.plan, args.runtime_dir)
        elif args.command == "package-clean":
            from .package_hygiene import clean_orphan_slides
            result = clean_orphan_slides(args.run)
        elif args.command == "visual-policy":
            from .visual_policy import set_visual_policy
            result = set_visual_policy(args.run, args.capability, args.decision, args.reason, args.user_ack)
        elif args.command == "visual-review":
            from .visual_review import record_visual_review
            result = record_visual_review(args.run, args.status, args.reviewer, args.notes)
        elif args.command == "render-import":
            record_render_manifest, load_run, resolve_run_path, sha256_file = _import_render_importer()
            run = args.run.resolve()
            manifest = load_run(run)
            current = resolve_run_path(run, manifest["artifacts"]["current_pptx"])
            pdf = args.pdf.resolve()
            pages = [p.resolve() for p in args.pages]
            sheet = args.contact_sheet.resolve()
            # Copy into run evidence if outside
            import shutil
            evidence = run / "evidence"
            ext = evidence / "external_render"
            ext.mkdir(parents=True, exist_ok=True)
            if pdf.parent != ext:
                target_pdf = ext / pdf.name
                shutil.copy2(pdf, target_pdf)
                pdf = target_pdf
            page_paths = []
            for page in pages:
                if page.parent != ext:
                    target = ext / page.name
                    shutil.copy2(page, target)
                    page = target
                page_paths.append(page)
            if sheet.parent != run / "review":
                (run / "review").mkdir(parents=True, exist_ok=True)
                target_sheet = run / "review" / sheet.name
                shutil.copy2(sheet, target_sheet)
                sheet = target_sheet
            payload = record_render_manifest(
                run,
                current,
                verification_tier=args.tier,
                renderer=args.renderer,
                fact_source=args.fact_source,
                pdf=pdf,
                pages=page_paths,
                contact_sheet=sheet,
            )
            result = {
                "status": "pass",
                "render_manifest": "evidence/render_manifest.json",
                "pptx_sha256": sha256_file(current),
                "tier": args.tier,
                "renderer": args.renderer,
                "page_count": len(page_paths),
                "manifest": payload,
            }
        elif args.command == "inspect":
            from .inspector import inspect_run
            result = inspect_run(args.run, args.runtime_dir)
        elif args.command == "route":
            from .common import load_run, read_json
            from .routing import route_finding
            manifest = load_run(args.run)
            findings = read_json(args.run / "evidence" / "findings.json").get("findings", [])
            finding = next((f for f in findings if f.get("finding_id") == args.finding), None)
            if finding is None:
                raise D6PPTError(f"Finding not found: {args.finding}", "finding_missing")
            result = route_finding(finding, mode=manifest["mode"], has_source_map=bool(manifest["artifacts"].get("object_path_map")))
        elif args.command == "patch":
            from .patcher import apply_patch
            result = apply_patch(args.run, args.spec, args.runtime_dir)
        elif args.command == "patch-plan":
            from .patch_planner import build_patch_plan
            result = build_patch_plan(args.run, args.out, args.confirm_finding)
        elif args.command == "verify":
            from .verifier import verify_run
            result = verify_run(args.run, args.runtime_dir, compatibility=args.compatibility, tier=args.verify_tier)
        elif args.command == "finalize":
            from .finalizer import finalize_run
            result = finalize_run(args.run)
        else:
            from .selftest import run_self_test
            result = run_self_test(args.runtime_dir, integration=args.integration)
        _emit(result)
        return 0 if result.get("status") not in {"fail", "blocked"} else 1
    except D6PPTError as exc:
        _emit({"status": "blocked", "code": exc.code, "message": str(exc), "details": exc.details})
        return 2
