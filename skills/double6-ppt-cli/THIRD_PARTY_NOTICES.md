# Third-party notices

## PPT Master

Source: `https://github.com/hugohe3/ppt-master`
Version: `v6.7.0`
Commit: `b4efe3ddf237a97a42880164759162f8e2412f2f`
License: MIT

The vendored lean core (generate path + roundtrip import entry `pptx_to_svg.py` for template-fill) is stored in `vendor/ppt-master-core/`. Every file is byte-identical to the official v6.7.0 release asset `ppt-master-skill-v6.7.0.zip` (SHA-256 `40424d9784fa25f771da8b312258c3c67a168925122aa6bb7faf6848e77ceee9`). Upstream removed Template Fill Native in v5.0.0, so it is not included. The original MIT license is retained at that root and in `licenses/PPT_MASTER_LICENSE` (unchanged SHA-256 `80cefc…`). The exact source paths, hashes and rationale are in `vendor/ppt-master-core/BOM.json`.

Since double6-ppt-cli 0.5.0 the vendor tree also carries a **visual-design subset** (BOM category `design_subset`): design references, 15 styles, visual-styles/modes, the `presentation_core` and `report_core` layout libraries, chart/table templates, 435 curated `tabler-outline` icons and the `preset_shape_svg.py` / `shape_boolean_svg.py` / `icon_sync.py` / `svg_position_calculator.py` authoring scripts, byte-identical to the same release asset.

## Tabler Icons (via PPT Master)

Source: `https://github.com/tabler/tabler-icons` v3.46.0 (commit `8ac7d81b72ece11072ef25ea9fd92e80c6f3c9fc`), MIT, Copyright (c) 2020-2026 Paweł Kuna. A curated 435-icon subset of PPT Master's `templates/icons/tabler-outline/` is vendored (list: `scripts/maintenance/design_icons_tabler_outline.txt`). License text: `licenses/TABLER_ICONS_LICENSE`; upstream notice: `vendor/ppt-master-core/skills/ppt-master/templates/icons/THIRD_PARTY_NOTICES.md`.

## OfficeCLI

Source: `https://github.com/iOfficeAI/OfficeCLI`
Version: `v1.0.157`
Commit: `b65272a18aef891941451705ff93e8a287f3eb72`
Package: `@officecli/officecli@1.0.157`
License: Apache-2.0

OfficeCLI is installed into a user-cache runtime and is not included in this Skill. Its license and NOTICE are retained in `licenses/` for attribution and audit. The unrelated `officecli@0.2.x` package is explicitly excluded.

## Preset shape data

The PPT Master subset includes Open XML preset-shape data with Apache-2.0 and MIT provenance. The original license and NOTICE files remain under `vendor/ppt-master-core/skills/ppt-master/scripts/pptx_shapes/data/`.


## PPT Master v4.8.0 template_fill_pptx (ported)

`scripts/double6_ppt_cli/pm6_template/fillnative/` contains modified copies of the read-only modules of PPT Master v4.8.0 `scripts/template_fill_pptx/` (commit `53c9c2a5e9f1a49096324fba4f95833649c6a0f4`), MIT License, Copyright (c) Hugo He; license text in `licenses/PPT_MASTER_LICENSE`. Each file keeps an origin header.

## Apache POI test data

`scripts/tests/fixtures/poi_smartart.pptx` is copied unchanged from Apache POI `test-data/slideshow/SmartArt.pptx` (Apache License 2.0, https://github.com/apache/poi).
