<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## status
- status: draft

## canvas
- viewBox: 0 0 1280 720
- format: WIDE

## communication
- primary_language: [fill]
- audience: [fill]
- objective: [fill]
- core_message: [fill]
- consumption_mode: presentation

## mode
- mode: generate

## visual_style
- visual_style: {{VISUAL_STYLE}}
- style_reference: {{STYLE_REF}}

## colors
<!-- Deck colour anchors; colour behaviour follows the selected upstream style (see references/visual-design.md §3). -->
- bg: {{BG}}
- surface: {{SURFACE}}
- primary: {{PRIMARY}}
- accent: {{ACCENT}}
- text: {{TEXT}}
- muted: {{MUTED}}
- line: {{LINE}}
- tint: {{TINT}}
- chart_series: {{CHART_SERIES}}

## typography
- font_family: {{FONT_FAMILY}}
- title_family: {{FONT_FAMILY}}
- body_family: {{FONT_FAMILY}}
- display: {{DISPLAY_SIZE}}
- title: {{TITLE_SIZE}}
- subtitle: {{SUBTITLE_SIZE}}
- body: {{BODY_SIZE}}
- label: {{LABEL_SIZE}}
- caption: {{CAPTION_SIZE}}

## icons
- library: {{ICON_LIBRARY}}
- inventory: [fill: names used, e.g. chart-line, users-group]

## page_rhythm
- P01: [fill after authoring the first page]

## pptx_structure
- mode: flat

## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
