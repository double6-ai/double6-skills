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

## colors
- bg: {{BG}}
- primary: {{PRIMARY}}
- accent: {{ACCENT}}
- text: {{TEXT}}

## typography
- font_family: {{FONT_FAMILY}}
- title_family: {{FONT_FAMILY}}
- body_family: {{FONT_FAMILY}}
- title: {{TITLE_SIZE}}
- body: {{BODY_SIZE}}
- footnote: {{FOOTNOTE_SIZE}}
- page_mark: {{PAGE_MARK_SIZE}}

## icons
- library: [fill or none]
- inventory: [fill or none]

## page_rhythm
- P01: [fill after authoring the first page]

## pptx_structure
- mode: flat

## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
