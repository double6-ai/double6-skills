from __future__ import annotations

import inspect
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from double6_ppt_cli.common import D6PPTError, SCHEMA_VERSION, load_run, save_run, sha256_file, write_json
from double6_ppt_cli.inspector import _capture_html_preview, _generic_findings
from double6_ppt_cli.powerpoint import (
    PDF_SCRIPT,
    resolve_powerpoint_staging_root,
    validate_powerpoint_path,
    verify_with_powerpoint,
)
from double6_ppt_cli.runs import init_run
from double6_ppt_cli.template_workflow import (
    _apply_confirmed_navigation_states,
    _check_content_slot_bindings,
    _check_numeric_claims,
    _inject_confirmed_navigation_links,
    _replace_confirmed_images,
    _strip_confirmed_navigation_links,
    build_pptx_profile,
    check_template_plan,
    import_template_asset,
)
from double6_ppt_cli.visual_policy import resolve_visual_gate, set_visual_policy
from double6_ppt_cli.visual_review import record_visual_review


class TemplateAndVisualTests(unittest.TestCase):
    def test_structured_content_slots_pass_extractively_and_block_invented_copy(self):
        source = {
            "slides": [{
                "index": 1,
                "title": "四个让超级团队跑起来的系统",
                "body": ["决策机制", "协调方式", "技术地基", "激励机制", "管理从控制收缩为校准，剩下交给人和 Agent。"],
            }],
        }
        objects = [{
            "source_object_id": "s08:shape:9304", "source_template_slide": 8,
            "drawingml_id": 9304, "object_type": "shape", "text": "阶段说明文字",
        }]
        keyed = {(1, "s08:shape:9304"): {"disposition": "replace_content"}}
        plan = {"slides": [{
            "source_slide": 8,
            "replacements": [{"slot_id": "s08_sh9304", "old_text": "阶段说明文字", "text": "管理从控制收缩为校准，剩下交给人和 Agent"}],
        }]}
        passed = _check_content_slot_bindings(plan, source, {}, keyed, objects)
        self.assertEqual([row["status"] for row in passed], ["OK"])
        plan["slides"][0]["replacements"][0]["text"] = "支撑人与 Agent 协作的共享底座"
        blocked = _check_content_slot_bindings(plan, source, {}, keyed, objects)
        self.assertEqual(blocked[0]["status"], "ERROR")
        self.assertEqual(blocked[0]["code"], "slot_copy_not_supported_by_source")
        self.assertEqual(blocked[0]["plan_slide"], 1)
        self.assertEqual(blocked[0]["slot_id"], "s08_sh9304")

    def test_user_confirmed_paraphrase_requires_same_slide_source_binding(self):
        source = {"slides": [
            {"index": 1, "body": ["让成果被看见", "围绕他们试点", "管理者亲自下场"]},
            {"index": 2, "body": ["其它页面"]},
        ]}
        objects = [{
            "source_object_id": "s06:shape:9132", "source_template_slide": 6,
            "drawingml_id": 9132, "object_type": "shape", "text": "结论条示例",
        }]
        keyed = {(1, "s06:shape:9132"): {"disposition": "replace_content"}}
        replacement = {
            "slot_id": "s06_sh9132", "old_text": "结论条示例", "text": "从看见、试点到亲自下场，三步即可启动",
            "content_binding": {
                "mode": "user_confirmed_paraphrase",
                "source_refs": ["source:/slides/0/body"],
                "user_confirmed": True,
            },
        }
        plan = {"slides": [{"source_slide": 6, "replacements": [replacement]}]}
        accepted = _check_content_slot_bindings(plan, source, {}, keyed, objects)
        self.assertEqual(accepted[0]["status"], "WARN")
        self.assertEqual(accepted[0]["code"], "slot_user_confirmed_paraphrase")
        replacement["content_binding"]["source_refs"] = ["source:/slides/1/body/0"]
        rejected = _check_content_slot_bindings(plan, source, {}, keyed, objects)
        self.assertEqual(rejected[0]["status"], "ERROR")
        self.assertEqual(rejected[0]["code"], "slot_source_ref_invalid")

    def test_navigation_state_moves_unique_template_style_to_active_section(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "navigation.pptx"
            pairs = []
            links = []
            for index in range(5):
                target = index + 1
                background_id = 30 + index
                text_id = 36 + index
                background_fill = '<a:srgbClr val="254AA5"/>' if index == 0 else '<a:schemeClr val="bg1"/>'
                text_fill = '<a:schemeClr val="bg1"/>' if index == 0 else '<a:srgbClr val="254AA5"/>'
                pairs.append(f'''<p:sp><p:nvSpPr><p:cNvPr id="{background_id}" name="nav-bg-{target}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:solidFill>{background_fill}</a:solidFill></p:spPr></p:sp><p:sp><p:nvSpPr><p:cNvPr id="{text_id}" name="nav-text-{target}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:noFill/></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr><a:solidFill>{text_fill}</a:solidFill></a:rPr><a:t>Nav {target}</a:t></a:r><a:endParaRPr><a:solidFill>{text_fill}</a:solidFill></a:endParaRPr></a:p></p:txBody></p:sp>''')
                for drawingml_id in (background_id, text_id):
                    links.append({
                        "plan_slide": 1,
                        "source_object_id": f"s01:shape:{drawingml_id}",
                        "drawingml_id": drawingml_id,
                        "target_plan_slide": target,
                        "active_target_plan_slide": 3,
                        "selection_state": "selected" if target == 3 else "unselected",
                    })
            parts = {
                "ppt/presentation.xml": b'''<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>''',
                "ppt/_rels/presentation.xml.rels": b'''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/></Relationships>''',
                "ppt/slides/slide1.xml": ('''<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/>''' + "".join(pairs) + '''</p:spTree></p:cSld></p:sld>''').encode(),
            }
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in parts.items():
                    archive.writestr(name, data)
            receipts, diff = _apply_confirmed_navigation_states(output, links)
            self.assertEqual(len(receipts), 10)
            self.assertIn("ppt/slides/slide1.xml", diff["changed"])
            with zipfile.ZipFile(output) as archive:
                xml = archive.read("ppt/slides/slide1.xml")
            root = __import__("lxml.etree", fromlist=["etree"]).fromstring(xml)
            ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main", "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
            def color_for(drawingml_id: int, text_role: bool) -> tuple[str, str]:
                shape = root.xpath(f".//p:sp[p:nvSpPr/p:cNvPr[@id='{drawingml_id}']]", namespaces=ns)[0]
                fill = shape.xpath(".//a:r/a:rPr/a:solidFill/*", namespaces=ns)[0] if text_role else shape.xpath("./p:spPr/a:solidFill/*", namespaces=ns)[0]
                return fill.tag.rsplit("}", 1)[-1], str(fill.get("val"))
            self.assertEqual(color_for(32, False), ("srgbClr", "254AA5"))
            self.assertEqual(color_for(38, True), ("schemeClr", "bg1"))
            self.assertEqual(color_for(30, False), ("schemeClr", "bg1"))
            self.assertEqual(color_for(36, True), ("srgbClr", "254AA5"))

    def test_template_asset_import_and_picture_replacement_are_sha_locked(self):
        old_image = b"\x89PNG\r\n\x1a\nold-image"
        new_image = b"\x89PNG\r\n\x1a\nnew-image"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "content.json"; source.write_text("{}", encoding="utf-8")
            template = root / "template.pptx"; template.write_bytes(b"template")
            run = root / "run"; init_run("template-fill", source, run, template)
            asset = root / "replacement.png"; asset.write_bytes(new_image)
            imported = import_template_asset(run, asset, "approved.png")
            self.assertEqual(imported["sha256"], sha256_file(asset))
            output = run / "artifacts" / "template-filled.pptx"
            parts = {
                "[Content_Types].xml": b'''<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/></Types>''',
                "ppt/presentation.xml": b'''<?xml version="1.0" encoding="UTF-8"?><p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId1"/><p:sldId id="257" r:id="rId2"/></p:sldIdLst></p:presentation>''',
                "ppt/_rels/presentation.xml.rels": b'''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide2.xml"/></Relationships>''',
                "ppt/slides/slide1.xml": b'''<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/><p:sp><p:nvSpPr><p:cNvPr id="42" name="Navigation"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>BG</a:t></a:r></a:p></p:txBody></p:sp><p:pic><p:nvPicPr><p:cNvPr id="9004" name="Picture"/><p:cNvPicPr/><p:nvPr/></p:nvPicPr><p:blipFill><a:blip r:embed="rId2"/></p:blipFill><p:spPr/></p:pic></p:spTree></p:cSld></p:sld>''',
                "ppt/slides/_rels/slide1.xml.rels": b'''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/old.png"/></Relationships>''',
                "ppt/slides/slide2.xml": b'''<?xml version="1.0" encoding="UTF-8"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"><p:cSld><p:spTree><p:nvGrpSpPr/><p:grpSpPr/></p:spTree></p:cSld></p:sld>''',
                "ppt/slides/_rels/slide2.xml.rels": b'''<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>''',
                "ppt/media/old.png": old_image,
            }
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, data in parts.items():
                    archive.writestr(name, data)
            profile = {"objects": [{
                "source_object_id": "s05:picture:9004", "object_type": "picture",
                "drawingml_id": 9004, "media_sha256": __import__("hashlib").sha256(old_image).hexdigest(),
            }]}
            receipts, diff = _replace_confirmed_images(output, run, profile, [{
                "plan_slide": 1, "source_object_id": "s05:picture:9004",
                "asset_path": imported["copied_path"], "asset_sha256": imported["sha256"],
                "extension": "png", "content_type": "image/png",
            }])
            self.assertEqual(len(receipts), 1)
            self.assertEqual(diff["removed"], [])
            self.assertIn("ppt/slides/_rels/slide1.xml.rels", diff["changed"])
            self.assertEqual(len(diff["added"]), 1)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read(receipts[0]["new_media_part"]), new_image)
                self.assertEqual(archive.read("ppt/media/old.png"), old_image)
            nav_receipts, nav_diff = _inject_confirmed_navigation_links(output, [{
                "plan_slide": 1, "source_object_id": "s01:shape:42", "drawingml_id": 42,
                "label": "背景", "target_plan_slide": 2,
            }])
            self.assertEqual(nav_receipts[0]["target_plan_slide"], 2)
            self.assertIn("ppt/slides/slide1.xml", nav_diff["changed"])
            with zipfile.ZipFile(output) as archive:
                self.assertIn(b"ppaction://hlinksldjump", archive.read("ppt/slides/slide1.xml"))
                self.assertIn(b"slide2.xml", archive.read("ppt/slides/_rels/slide1.xml.rels"))
            linked_profile = build_pptx_profile(output)
            nav_object = next(obj for obj in linked_profile["objects"] if obj["drawingml_id"] == 42)
            self.assertEqual(nav_object["slide_jump_source_slides"], [2])
            stripped = root / "stripped.pptx"
            strip_receipts, strip_diff = _strip_confirmed_navigation_links(
                output,
                stripped,
                {"objects": [{
                    "source_object_id": "s01:shape:42", "slide_part": "ppt/slides/slide1.xml",
                    "source_template_slide": 1, "drawingml_id": 42,
                }]},
                [{"source_object_id": "s01:shape:42"}],
            )
            self.assertEqual(len(strip_receipts), 1)
            self.assertIn("ppt/slides/slide1.xml", strip_diff["changed"])
            with zipfile.ZipFile(stripped) as archive:
                self.assertNotIn(b"ppaction://hlinksldjump", archive.read("ppt/slides/slide1.xml"))

    def test_template_asset_import_rejects_extension_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "content.json"; source.write_text("{}", encoding="utf-8")
            template = root / "template.pptx"; template.write_bytes(b"template")
            run = root / "run"; init_run("template-fill", source, run, template)
            asset = root / "replacement.png"; asset.write_bytes(b"\x89PNG\r\n\x1a\nimage")
            with self.assertRaises(D6PPTError) as caught:
                import_template_asset(run, asset, "approved.jpg")
            self.assertEqual(caught.exception.code, "template_asset_extension_mismatch")

    def test_powerpoint_pdf_export_has_long_timeout_and_cleanup(self):
        self.assertIn("with timeout of 600 seconds", PDF_SCRIPT)
        self.assertIn("repeat 240 times", PDF_SCRIPT)
        self.assertIn("close openedPresentation saving no", PDF_SCRIPT)

    def test_isolated_home_does_not_change_real_powerpoint_staging_root(self):
        with patch.dict(os.environ, {"HOME": "/isolated/home"}, clear=False), \
             patch("double6_ppt_cli.powerpoint.pwd.getpwuid", return_value=SimpleNamespace(pw_dir="/Users/real-user")), \
             patch("double6_ppt_cli.powerpoint.os.getuid", return_value=501):
            os.environ.pop("POWERPOINT_STAGING_ROOT", None)
            root = resolve_powerpoint_staging_root(create=False)
        self.assertEqual(root, Path("/Users/real-user/Library/Containers/com.microsoft.Powerpoint/Data/tmp/d6ppt"))

    def test_powerpoint_rejects_non_staged_and_diag_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "real-container"; root.mkdir()
            inside = root / "session" / "input.pptx"
            self.assertEqual(validate_powerpoint_path(inside, root), inside.resolve())
            with self.assertRaises(D6PPTError) as outside:
                validate_powerpoint_path(Path(temp) / "attempt/raw/deck.pptx", root)
            self.assertEqual(outside.exception.code, "powerpoint_path_outside_staging")
            with self.assertRaises(D6PPTError) as diag:
                validate_powerpoint_path(Path(temp) / "process/tmp/opencode/diag/diag.pptx", root)
            self.assertEqual(diag.exception.code, "powerpoint_diag_path_forbidden")

    def test_powerpoint_verify_uses_one_batch_session(self):
        source = inspect.getsource(verify_with_powerpoint)
        self.assertEqual(source.count("_run_osascript("), 1)
        self.assertNotIn("render_with_powerpoint(", source)
        probe = Path(inspect.getfile(verify_with_powerpoint)).with_name("powerpoint_roundtrip_probe.applescript")
        script = probe.read_text(encoding="utf-8")
        self.assertIn("set pdfOutputPosix to item 9 of argv", script)
        self.assertIn("set currentStage to \"export_pdf\"", script)

    def test_business_formula_text_is_manual_review_not_deterministic_residue(self):
        findings = _generic_findings([{
            "path": "/slide[5]/shape[@id=42]",
            "text": "组织竞争力公式：人才密度 × AI 杠杆 / 组织摩擦",
            "type": "shape",
            "format": {},
        }])
        self.assertEqual(len(findings), 1)
        self.assertTrue(findings[0]["finding_id"].startswith("d6-formula-like-business-content-"))
        self.assertEqual(findings[0]["severity"], "warning")
        self.assertFalse(findings[0]["deterministic"])
        self.assertTrue(findings[0]["requires_user_confirmation"])
        self.assertNotIn("suggested_operation", findings[0])

    def test_static_navigation_selection_is_detected_but_not_auto_fixed(self):
        rows = []
        for slide in range(2, 7):
            for label in ("背景", "个体", "团队", "机制", "行动"):
                rows.append({
                    "path": f"/slide[{slide}]/shape[@id={100 + len(rows)}]",
                    "text": label,
                    "type": "shape",
                    "format": {"color": "background1" if label == "背景" else "#254AA5"},
                })
        findings = _generic_findings(rows)
        nav = [item for item in findings if item["finding_id"].startswith("d6-navigation-selection-static-")]
        self.assertEqual(len(nav), 1)
        self.assertEqual(nav[0]["severity"], "warning")
        self.assertEqual(nav[0]["suggested_route"], "manual_review")
        self.assertTrue(nav[0]["requires_user_confirmation"])
        self.assertFalse(nav[0]["deterministic"])

    def test_formula_named_template_picture_is_documented_as_sample_rule(self):
        import inspect as python_inspect
        from double6_ppt_cli.template_workflow import build_pptx_profile

        source = python_inspect.getsource(build_pptx_profile)
        self.assertIn('re.search(r"公式|equation|formula", name, re.I)', source)
        self.assertIn('obj["role"] = "sample_formula_media"', source)

    def test_officecli_html_preview_is_disabled_and_defers_to_powerpoint(self):
        class PreviewMustNotRun:
            def run(self, *_args, **_kwargs):
                self.fail("Chrome preview must not run")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = _capture_html_preview(PreviewMustNotRun(), root / "deck.pptx", root / "sheet.png")
        self.assertEqual(receipt["status"], "deferred_to_powerpoint")
        self.assertEqual(receipt["fact_source"], "powerpoint_required")
        self.assertEqual(receipt["reason"], "chrome_preview_disabled_to_avoid_keychain_prompts")

    def test_percentage_point_contract_accepts_locked_display(self):
        plan = {
            "slides": [{"notes": "88% 与 1% 相差 87 个百分点", "replacements": []}],
            "numeric_claims": [{
                "claim_id": "rc002-pp", "operands": ["88%", "1%"],
                "relation": "percentage_point_difference", "expected": "87 个百分点",
                "forbidden": ["87×"],
            }],
        }
        self.assertTrue(all(row["status"] == "OK" for row in _check_numeric_claims(plan)))
        plan["slides"][0]["notes"] = "相差 87×"
        self.assertTrue(any(row["status"] == "ERROR" for row in _check_numeric_claims(plan)))

    def test_template_plan_missing_disposition_fails_closed(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "content.json"; source.write_text("{}", encoding="utf-8")
            template = root / "template.pptx"; template.write_bytes(b"template")
            run = root / "run"
            init_run("template-fill", source, run, template)
            profile = {
                "pptx_sha256": sha256_file(run / "input" / "template.pptx"),
                "objects": [{"source_object_id": "s01:shape:2", "source_template_slide": 1, "object_type": "shape"}],
            }
            write_json(run / "artifacts" / "template_profile.json", profile)
            write_json(run / "artifacts" / "template.slide_library.json", {"slides": []})
            manifest = load_run(run)
            manifest["artifacts"].update({
                "template_profile": "artifacts/template_profile.json",
                "template_library": "artifacts/template.slide_library.json",
            })
            save_run(run, manifest)
            plan = run / "plans" / "plan.json"
            write_json(plan, {
                "schema_version": SCHEMA_VERSION,
                "template_sha256": profile["pptx_sha256"],
                "content_sha256": manifest["input"]["sha256"],
                "slides": [{"source_slide": 1, "replacements": []}],
                "object_dispositions": [], "numeric_claims": [],
            })
            fake_modules = (None, None, lambda _library, _plan: {"results": [], "summary": {}}, None)
            with patch("double6_ppt_cli.template_workflow._vendor_modules", return_value=fake_modules):
                report = check_template_plan(run, plan)
            self.assertEqual(report["status"], "fail")
            self.assertTrue(any(row.get("code") == "object_disposition_missing" for row in report["results"]))

    def test_visual_waiver_is_sha_bound_and_stales_after_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"; source.write_bytes(b"pptx-a")
            run = root / "run"
            init_run("postflight", source, run)
            current = run / "artifacts" / "current.pptx"
            set_visual_policy(run, "unavailable", "waive", "no_visual_model", True)
            gate, _receipt = resolve_visual_gate(run, sha256_file(current))
            self.assertEqual(gate, "skipped_with_user_ack")
            current.write_bytes(b"pptx-b")
            with self.assertRaises(D6PPTError) as caught:
                resolve_visual_gate(run, sha256_file(current))
            self.assertEqual(caught.exception.code, "visual_review_decision_required")

    def test_visual_unknown_requests_decision_and_skip_requires_ack(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"; source.write_bytes(b"pptx")
            run = root / "run"; init_run("postflight", source, run)
            with self.assertRaises(D6PPTError) as pending:
                resolve_visual_gate(run, sha256_file(run / "artifacts" / "current.pptx"))
            self.assertEqual(pending.exception.code, "visual_review_decision_required")
            with self.assertRaises(D6PPTError) as no_ack:
                set_visual_policy(run, "unknown", "waive", "user_requested_skip", False)
            self.assertEqual(no_ack.exception.code, "visual_waiver_confirmation_required")

    def test_visual_available_review_is_sha_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.pptx"; source.write_bytes(b"pptx")
            run = root / "run"; init_run("postflight", source, run)
            set_visual_policy(run, "available", "perform")
            render = run / "evidence" / "powerpoint_render"; render.mkdir(parents=True)
            (render / "powerpoint-render.pdf").write_bytes(b"pdf")
            (render / "slide-1.png").write_bytes(b"png")
            (run / "review" / "contact_sheet.png").write_bytes(b"sheet")
            review = record_visual_review(run, "accepted", "vision-model", "all pages reviewed")
            gate, receipt = resolve_visual_gate(run, review["pptx_sha256"])
            self.assertEqual(gate, "pass")
            self.assertEqual(receipt["page_count"], 1)

    def test_user_decline_and_explicit_skip_are_separate_waiver_paths(self):
        for reason, capability in (("user_declined_switch", "unknown"), ("user_requested_skip", "unavailable")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "source.pptx"; source.write_bytes(b"pptx")
                run = root / "run"; init_run("postflight", source, run)
                waiver = set_visual_policy(run, capability, "waive", reason, True)
                gate, _receipt = resolve_visual_gate(run, waiver["pptx_sha256"])
                self.assertEqual(gate, "skipped_with_user_ack")


if __name__ == "__main__":
    unittest.main()
