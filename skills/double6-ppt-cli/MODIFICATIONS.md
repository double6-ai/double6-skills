# Modifications to PPT Master v4.8.0

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
