# SPDX-License-Identifier: AGPL-3.0-only
# Double6 Skills，2026-10-17：基于paper-translation维护源码整理；变更见Skill根目录MODIFICATIONS.md。
"""repair pdf runtime：从原入口拆出的同一实现。"""
from __future__ import annotations
from build_visual_repair_pdf_context import *

def build_visual_repair_pdf(
    *,
    source_pdf: Path,
    translated_pdf: Path,
    output_pdf: Path,
    tracking_payload: dict[str, Any] | None = None,
    audit_payload: dict[str, Any] | None = None,
    gate_payload: dict[str, Any] | None = None,
    repair_profile: str = "full",
) -> dict[str, Any]:
    from repair_pdf_ai_adoption import repair_ai_index_economy_corporate_ai_adoption_visible_labels
    from repair_pdf_ai_chart_geometry import repair_ai_index_chart_labels_from_source_bboxes
    from repair_pdf_ai_chart_text import repair_ai_index_chart_labels_from_text_layer
    from repair_pdf_ai_charts import copy_ai_chart_regions, repair_ai_chapter_highlights_title, repair_ai_chart_titles_after_passthrough, repair_ai_page17_chart_axis_labels_after_passthrough, repair_ai_research_contents_page, repair_toc_page, repair_visible_strings, tracking_chart_repairs
    from repair_pdf_ai_economy_overview import repair_ai_index_economy_contents_visible_labels, repair_ai_index_economy_timeline_visible_labels
    from repair_pdf_ai_frontmatter import repair_ai_contents_page_labels, repair_ai_contents_title, repair_ai_cover_title_wrap, repair_ai_index_cropped_patents_running_headers, repair_ai_page4_closing_and_signature, repair_ai_page9_acknowledgement_width, repair_ai_running_headers, repair_cover_year
    from repair_pdf_ai_investment import repair_ai_index_economy_investment_chart_visible_labels
    from repair_pdf_ai_jobs import repair_ai_index_economy_jobs_visible_labels
    from repair_pdf_ai_language import repair_ai_index_language_section_visible_residue
    from repair_pdf_ai_links import repair_ai_contents_page_numbers, repair_ai_footer_links, repair_ai_page17_text_styles, repair_ai_page19_sector_heading_and_orphan, repair_ai_page6_citation_passthrough, repair_ai_page6_link_lines
    from repair_pdf_ai_medicine import repair_ai_index_medicine_visible_labels
    from repair_pdf_ai_misc import repair_ai_index_inference_paragraphs_from_text_layer, repair_ai_index_invalid_question_benchmark_chart, repair_ai_index_technological_proximity_body, repair_ai_missing_fixed_chart_labels
    from repair_pdf_ai_responsible_culture import repair_ai_index_responsible_ai_cultural_language_gap_visible_labels, repair_ai_index_responsible_ai_transparency_visible_labels
    from repair_pdf_ai_responsible_policy import repair_ai_index_responsible_ai_policy_making_visible_labels, repair_ai_index_responsible_ai_privacy_fairness_visible_labels
    from repair_pdf_ai_responsible_security import repair_ai_index_responsible_ai_security_safety_jailbreak_visible_labels, repair_ai_index_responsible_ai_security_safety_visible_labels
    from repair_pdf_ai_responsible_tables import repair_ai_index_responsible_ai_academia_chart_labels, repair_ai_index_responsible_ai_benchmark_tables, repair_ai_index_responsible_ai_dimension_tables, repair_ai_index_responsible_ai_organization_view_chart_labels
    from repair_pdf_ai_rosters import repair_ai_contributor_list_pages, repair_ai_contributor_rosters
    from repair_pdf_ai_science import repair_ai_index_science_visible_labels
    from repair_pdf_ai_technical import repair_ai_index_author_panel_caption_fragments, repair_ai_index_mobility_panel_title_band, repair_ai_index_technical_performance_highlight_residue, repair_ai_index_technical_performance_section_headings, repair_ai_index_technical_performance_toc_headings
    from repair_pdf_nature import repair_nature_header_footer_passthrough, repair_nature_inline_bold_labels, repair_nature_page13_publication_metadata, repair_nature_page14_backmatter, repair_nature_page1_abstract, repair_nature_page1_doi_open_passthrough, repair_nature_page1_footer_rule_passthrough, repair_nature_page1_publisher_badge_passthrough, repair_nature_page1_title_wrap, repair_nature_page2_numbered_question_list, repair_nature_section_headings, repair_nature_table1_structured, repair_nature_table2_structured, repair_nature_tables
    if repair_profile not in {"full", "targeted"}:
        raise ValueError(f"unsupported repair_profile: {repair_profile}")
    if not translated_pdf.exists():
        return {"version": 1, "status": "skipped", "reason": "missing_translated_pdf", "repairs": []}
    source_name = source_pdf.name.lower()
    if "latextrans" in source_name:
        return {"version": 1, "status": "skipped", "reason": "latex_direct_case_not_pdf_visual_repair", "repairs": []}
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(translated_pdf, output_pdf)
    fitz = visual_layout._load_fitz()
    repairs: list[dict[str, Any]] = []
    tracking = tracking_payload if isinstance(tracking_payload, dict) else {}
    with fitz.open(str(source_pdf)) as source_doc, fitz.open(str(output_pdf)) as doc:  # type: ignore[attr-defined]
        if "ai_index_report_2026" in source_name:
            is_cropped_batch = bool(re.search(r"pages_\d+_\d+", source_name))
            if is_cropped_batch:
                repairs.extend(repair_ai_index_technological_proximity_body(fitz, doc))
                repairs.extend(repair_ai_index_chart_labels_from_text_layer(fitz, doc))
                repairs.extend(repair_ai_index_chart_labels_from_source_bboxes(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_author_panel_caption_fragments(fitz, doc))
                repairs.extend(repair_ai_index_mobility_panel_title_band(fitz, doc))
                repairs.extend(repair_ai_index_technical_performance_highlight_residue(fitz, doc))
                repairs.extend(repair_ai_index_technical_performance_toc_headings(fitz, doc))
                repairs.extend(repair_ai_index_technical_performance_section_headings(fitz, doc))
                repairs.extend(repair_ai_index_language_section_visible_residue(fitz, doc))
                repairs.extend(repair_ai_index_responsible_ai_dimension_tables(fitz, doc))
                repairs.extend(repair_ai_index_responsible_ai_benchmark_tables(fitz, doc))
                repairs.extend(repair_ai_index_responsible_ai_organization_view_chart_labels(fitz, doc))
                repairs.extend(repair_ai_index_responsible_ai_academia_chart_labels(fitz, doc))
                repairs.extend(repair_ai_index_responsible_ai_policy_making_visible_labels(fitz, doc))
                repairs.extend(repair_ai_index_responsible_ai_privacy_fairness_visible_labels(fitz, doc))
                repairs.extend(repair_ai_index_responsible_ai_cultural_language_gap_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_responsible_ai_transparency_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_responsible_ai_security_safety_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_responsible_ai_security_safety_jailbreak_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_economy_contents_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_economy_timeline_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_economy_investment_chart_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_economy_corporate_ai_adoption_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_economy_jobs_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_science_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_medicine_visible_labels(fitz, source_doc, doc))
                repairs.extend(repair_ai_index_invalid_question_benchmark_chart(fitz, doc))
                repairs.extend(repair_ai_index_inference_paragraphs_from_text_layer(fitz, doc))
                repairs.extend(repair_ai_index_cropped_patents_running_headers(fitz, doc))
            elif repair_profile == "targeted":
                repairs.extend(repair_ai_contributor_list_pages(fitz, source_doc, doc, pages={8}))
                repairs.extend(copy_ai_chart_regions(fitz, source_doc, doc, pages={17, 19}, redact_existing_text=True))
                repairs.extend(repair_ai_chart_titles_after_passthrough(fitz, doc, pages={17, 19}))
                repairs.extend(repair_ai_page17_chart_axis_labels_after_passthrough(fitz, doc, pages={17, 19}))
                repairs.extend(repair_ai_page17_text_styles(fitz, doc))
                repairs.extend(repair_ai_page19_sector_heading_and_orphan(fitz, doc))
            else:
                if source_doc.page_count >= 1 and doc.page_count >= 1:
                    repairs.extend(repair_cover_year(fitz, source_doc[0], doc[0]))
                    repairs.extend(repair_ai_cover_title_wrap(fitz, doc[0]))
                if source_doc.page_count >= 2 and doc.page_count >= 2:
                    repairs.extend(repair_ai_contents_page_numbers(fitz, source_doc[1], doc[1]))
                    repairs.extend(repair_ai_contents_page_labels(fitz, doc[1]))
                    repairs.extend(repair_ai_contents_title(fitz, doc[1]))
                    repairs.extend(repair_ai_footer_links(fitz, source_doc[1], doc[1]))
                repairs.extend(repair_ai_page6_citation_passthrough(fitz, source_doc, doc))
                repairs.extend(repair_ai_page6_link_lines(fitz, doc))
                repairs.extend(repair_ai_page4_closing_and_signature(fitz, doc))
                repairs.extend(repair_ai_contributor_rosters(fitz, source_doc, doc))
                repairs.extend(repair_ai_contributor_list_pages(fitz, source_doc, doc))
                repairs.extend(repair_ai_page9_acknowledgement_width(fitz, doc))
                for page_number in [14, 15]:
                    if source_doc.page_count >= page_number and doc.page_count >= page_number:
                        repairs.extend(repair_toc_page(fitz, source_doc[page_number - 1], doc[page_number - 1], page_number))
                if source_doc.page_count >= 14 and doc.page_count >= 14:
                    repairs.extend(repair_ai_research_contents_page(fitz, doc[13]))
                if doc.page_count >= 15:
                    repairs.extend(repair_ai_chapter_highlights_title(fitz, doc[14]))
                repairs.extend(repair_visible_strings(fitz, doc, tracking_chart_repairs(tracking), pages={17, 18, 19, 20}, rule="chart_label_visible_repair", fontsize=7.0))
                repairs.extend(repair_ai_missing_fixed_chart_labels(fitz, doc))
                repairs.extend(repair_visible_strings(fitz, doc, AI_INSTITUTION_REPAIRS, pages={14, 15, 17, 18, 19, 20}, rule="institution_label_visible_repair", fontsize=7.0))
                repairs.extend(copy_ai_chart_regions(fitz, source_doc, doc))
                repairs.extend(repair_ai_chart_titles_after_passthrough(fitz, doc))
                repairs.extend(repair_ai_page17_chart_axis_labels_after_passthrough(fitz, doc))
                repairs.extend(repair_ai_page17_text_styles(fitz, doc))
                repairs.extend(repair_ai_page19_sector_heading_and_orphan(fitz, doc))
                repairs.extend(repair_ai_running_headers(fitz, doc))
        elif "exploring ais performance" in source_name:
            if repair_profile == "targeted":
                repairs.extend(repair_nature_page1_abstract(fitz, doc))
                repairs.extend(repair_nature_page1_publisher_badge_passthrough(fitz, source_doc, doc))
                repairs.extend(repair_nature_section_headings(fitz, doc))
                repairs.extend(repair_nature_table2_structured(fitz, doc))
            else:
                repairs.extend(repair_nature_page1_title_wrap(fitz, doc))
                repairs.extend(repair_nature_page1_doi_open_passthrough(fitz, source_doc, doc))
                repairs.extend(repair_nature_page1_footer_rule_passthrough(fitz, source_doc, doc))
                repairs.extend(repair_nature_page1_abstract(fitz, doc))
                repairs.extend(repair_nature_header_footer_passthrough(fitz, source_doc, doc))
                repairs.extend(repair_nature_section_headings(fitz, doc))
                repairs.extend(repair_nature_page2_numbered_question_list(fitz, doc))
                repairs.extend(repair_nature_page13_publication_metadata(fitz, doc))
                repairs.extend(repair_nature_page14_backmatter(fitz, doc))
                repairs.extend(repair_nature_inline_bold_labels(fitz, doc))
                repairs.extend(repair_nature_tables(fitz, doc))
                repairs.extend(repair_nature_table1_structured(fitz, doc))
                repairs.extend(repair_nature_table2_structured(fitz, doc))
        if repairs:
            doc.saveIncr()
    status = "repaired" if repairs else "ok"
    risky_rules = sorted({str(item.get("rule") or "") for item in repairs if str(item.get("rule") or "") in RISKY_REPAIR_RULES})
    safe_for_auto_delivery = bool(repairs) and not risky_rules
    return {
        "version": 1,
        "status": status,
        "source_pdf": str(source_pdf),
        "input_translated_pdf": str(translated_pdf),
        "output_pdf": str(output_pdf),
        "repair_count": len(repairs),
        "repair_profile": repair_profile,
        "text_layer_policy": "visual_repair_page_or_region" if repairs else "unchanged",
        "delivery_safety_status": "safe_for_auto_delivery" if safe_for_auto_delivery else "needs_human_visual_review" if repairs else "unchanged",
        "safe_for_auto_delivery": safe_for_auto_delivery,
        "risky_rules": risky_rules,
        "delivery_note": (
            "visual_repaired_pdf contains redaction/region replacement candidates and must not be selected as delivery until visual review accepts it."
            if risky_rules
            else "visual_repaired_pdf is intended for visible-quality delivery; repaired regions may have limited searchable text fidelity."
        ),
        "audit_input_status": (audit_payload or {}).get("status") if isinstance(audit_payload, dict) else None,
        "gate_input_status": (gate_payload or {}).get("status") if isinstance(gate_payload, dict) else None,
        "repairs": repairs,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a visible-quality repaired mono PDF for PDF direct outputs.")
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--translated-pdf", required=True)
    parser.add_argument("--tracking")
    parser.add_argument("--audit")
    parser.add_argument("--gate")
    parser.add_argument("--output-pdf", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repair-profile", choices=["full", "targeted"], default="full")
    return parser

def main(argv: list[str] | None = None) -> int:
    from repair_pdf_drawing import load_json
    args = build_parser().parse_args(argv)
    manifest = build_visual_repair_pdf(
        source_pdf=Path(args.source_pdf),
        translated_pdf=Path(args.translated_pdf),
        output_pdf=Path(args.output_pdf),
        tracking_payload=load_json(Path(args.tracking)) if args.tracking else {},
        audit_payload=load_json(Path(args.audit)) if args.audit else {},
        gate_payload=load_json(Path(args.gate)) if args.gate else {},
        repair_profile=args.repair_profile,
    )
    manifest_path = Path(args.manifest)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest.get("status"), "output_pdf": manifest.get("output_pdf"), "repair_count": manifest.get("repair_count", 0)}, ensure_ascii=False))
    return 0 if manifest.get("status") in {"ok", "repaired", "skipped"} else 1


SCRIPT_INTERFACE = "internal-module"
SCRIPT_INTERFACE_REASON = "由兼容入口调用的职责模块，不提供独立命令。"
