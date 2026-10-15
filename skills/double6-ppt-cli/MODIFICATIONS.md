# Modifications to PPT Master (v6.7.0 experimental; history from v4.8.0 below)

## 0.4.0-exp.1: experimental re-vendor of PPT Master v6.7.0 (generate path only)

- `vendor/ppt-master-core/` was replaced by a 172-file lean core taken byte-for-byte from the official `ppt-master-skill-v6.7.0.zip` asset (SHA-256 `40424d97…`, commit `b4efe3d`). The file set is the static import closure of `svg_to_pptx.py`, `svg_quality_checker.py`, `project_manager.py`, `project_management/cli.py` and `template_preview_pptx.py`, plus runtime-opened data, confirmed by an open-trace. Double6 still patches none of them; `attribution_guard.py` verifies the BOM.
- Template Fill Native no longer exists upstream. `template-fill` fails closed with `template_fill_not_migrated`, and `doctor --mode template-fill` reports fail. A roundtrip-based migration is prototyped separately.
- New Double6-side build-copy adapter `native_markers.py`: legacy table payloads are upgraded to `ppt-master.semantic-table.v2`, with the v4.8.0 default colours made explicit (v2 treats unset as noFill). Chart and table markers without an authority become JSON-first (`data-pptx-native-authority="json"`), with bounds taken from `data-pptx-bounds`. `semantic.defaults.native_marker_authority: author` opts out. Each change is recorded in the receipt as `normalize_native_markers`.
- `design_spec.md` scaffold gains the per-slide `- Relationships:` line that the v6 checker requires. Compile pre-checks for remaining placeholders and surfaces v6 quality-report errors in `details.errors`.
- Semantic manifest now resolves `p:pic` objects (role `image`). This was a pre-existing gap.

## History (v4.8.0)


The upstream source files in `vendor/ppt-master-core/` are retained byte-for-byte according to `BOM.json`. Double6 does not patch those 137 files. Version 0.2.0-local added the 18 Template Fill Native modules omitted by the earlier lean-copy closure, using the SHA-verified official v4.8.0 release asset. Version 0.2.1-local keeps that vendor tree unchanged and adds Double6-side slot provenance and package hygiene controls.

The integration is implemented outside the vendor tree. Version 0.2.3 keeps PowerPoint optional through explicit native/portable tiers and adds:

- a stable semantic manifest and fail-closed object mapper, including vendor-supported `data-pptx-shape-id` / `match.drawingml_id` identity;
- generated authoring/design scaffolds and neutral, academic, business, and training design profiles;
- a compiler workspace that selectively flattens only safe, explicitly selected SVG groups while preserving the authoring source;
- title/body placeholder and `d6:<source_id>` identity injection;
- an optional deck-wide roundtrip font contract, plus SHA-bound stale-artifact propagation after rebuilds;
- role-based structure checks that require postflight-sensitive text to be top-level;
- an OfficeCLI adapter with a pinned-version doctor/bootstrap contract;
- findings normalization, role-aware font thresholds, declarative content/template rules, dual repair routing and bounded patch ledger;
- OOXML, preview, LibreOffice roundtrip, edit/move and delivery gates.
- native PPTX template analysis, object disposition planning and confirmed Fill Native apply;
- SHA-bound render manifests and visual review/waiver policy, with Microsoft PowerPoint preferred and a portable OfficeCLI/LibreOffice tier;
- deterministic `set_property` / `remove_leaf` patches with protected-scope invariants.
- Chrome-free deterministic inspection plus a macOS `/private/tmp` run-directory guard, preventing Chrome Keychain prompts and repeated PowerPoint file-access prompts;
- real-account PowerPoint-container staging that ignores isolated `HOME`, rejects cleanroom diagnostic paths, combines all native validation/export work into one batch session, and copies evidence back to the run;
- explicit long AppleEvent timeout and failure cleanup. Case-specific formula, attribution, navigation, and numeric rules live in the content contract rather than generic code.
- template-fill selected-state replay that derives the active section from confirmed section starts and moves only the template's uniquely proven selected/unselected fill and text styles; ambiguous styles fail closed.
- same-slide structured-content provenance checks for template text slots, with explicit user-confirmed paraphrase bindings for exceptions;
- package-level detection and bounded cleanup of unreachable nonlogical template slides and unused slide-jump relationships, with live-slide/protected-part/relationship-closure invariants.

The upstream PPT Master `SKILL.md` is retained only because it is part of the validated lean-core dependency closure. It is not a second user-facing Skill entry and is not the Double6 routing contract.

## 0.3.0: upstream check (2026-10-15) and build-copy adapters

- The vendor tree is still unchanged (`attribution_guard.py` passes). PPT Master upstream is now at v6.7.0. We did **not** upgrade, because v5.0.0 removed `template_fill_pptx/` and `native_enhance_pptx*` (22 vendored files) and replaced them with the "Edit Native PPTX" roundtrip route (`pptx_to_svg.py --roundtrip` / `svg_to_pptx.py --roundtrip`). Migrating means redesigning Double6 template-fill on top of that route. That is planned as a separate change.
- Upstream rewrote its git history. The `v4.8.0` tag now resolves to `5da13a0…`. The 137 BOM files are byte-identical to the locked commit `53c9c2a…`, which is still reachable, and the official release asset is unchanged.
- New Double6-side workaround outside the vendor tree: the source adapter collapses `<text data-pptx-shape-id><tspan x=same>…</tspan></text>` in the **build copy** only. Without this, the v4.8.0 tspan lowering drops `data-pptx-shape-id` on single-line text. The receipt records each change as `unwrap_single_line_tspan`.
