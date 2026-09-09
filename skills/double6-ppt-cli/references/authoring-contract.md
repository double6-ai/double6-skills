# Authoring contract v0.2

## 输入边界

支持 Markdown/TXT、结构化 JSON/YAML、本地已授权图片、已经整理好的 PPT Master SVG 项目，以及普通 `.pptx` 模板的原生分析/填充。不包含任意 PDF/DOCX 内容解析、网页抓取、在线搜图或生图。

文本或结构化材料先通过 `init` 固化进 run。Agent 在 `authoring/project/` 中完成内容规划和 SVG authoring；编译器不会替 Agent 猜测事实、观点层级或视觉审美。

generate 项目还必须提供 `authoring/project/spec_lock.md`，且包含 `## pptx_structure` 段与 `mode: flat`（自由版式）或 `mode: structured`（模板结构）。`init --mode generate --design <profile>` 会创建待确认草稿；未填字段或仍为 draft 时，`compile` 会返回可执行的下一步。

## PPT Master adapter

- 源目录默认是 `authoring/project/svg_output/`，使用 vendored PPT Master `v4.8.0` 精简内核编译。
- `compile` 默认启用 `--native-charts-and-tables`。需要原生 chart/table 时，按 PPT Master 上游 marker 合同在 SVG 中提供数据；不满足 marker 合同则 fail closed，不把普通形状冒充原生对象。
- title、subtitle、body 和 postflight-sensitive text 必须在源阶段顶层化。深度适配器可依据 `source_selector.file + id` 对 SVG 根节点下、没有 transform/style/clip 等继承语义的安全 group 做选择性去分组；任何不安全属性、嵌套 group 或歧义 selector 都 fail closed。适配只发生在 `build/ppt-master-project/`，不会改写 authoring source。编译后的语义层若发现敏感对象仍嵌套在 group 内，会拒绝生成 object map。
- 可整体拖动的 motif 保留 group；decorative 对象不进入文本修复主路径。
- notes 放在 PPT Master `notes/` 中，并在 semantic manifest 的 `notes` 元数据中声明；它们不伪装成 slide shape。

## 稳定身份

每个需追踪对象都必须有稳定 `source_id`、slide、role、editable、postflight_sensitive、preferred_structure 和 source_selector。优先在 SVG 元素写 `data-pptx-shape-id="<2..4294967295>"`，并在 semantic manifest 使用同值 `match.drawingml_id`；这是 vendored PPT Master 支持的稳定身份。文本内容不能作为唯一身份；文本匹配至少要加显式 ordinal。重复、缺失或歧义一律中止编译，错误回执会列出来源文件和当前页候选对象。

真实 placeholder 使用 `p:ph` 写入 title/body 语义；对象 `cNvPr.name` 写为 `d6:<source_id>`。object map 同时绑定 source、semantic manifest、compiler output 和最终 PPTX SHA。

跨目标应用往返对字体要求更严格时，可在 manifest 的 `defaults.roundtrip_font_family`、`defaults.placeholder_font_family` 或对象的 `compiler_overrides.font_family` 中显式固定已通过 `doctor` 与系统字体解析检查的字体。`roundtrip_font_family` 覆盖整份 deck 的文本 run，placeholder/object override 再做窄范围覆盖；三者都会同时写入 latin/eastAsia/complex-script run properties，避免 LibreOffice Save As 从主题字体漂移。没有显式声明时不擅自改字体，也不得把系统找不到但“常见”的字体当作已可用。

## 最小语义清单

```json
{
  "schema_version": "2.0",
  "objects": [{
    "source_id": "slide-001-title",
    "slide": 1,
    "role": "title",
    "editable": true,
    "postflight_sensitive": true,
    "preferred_structure": "placeholder",
    "placeholder": "title",
    "source_selector": {"file": "svg_output/01.svg", "id": "title"},
    "match": {"drawingml_id": 1001}
  }]
}
```

对应 SVG 元素示例：`<text id="title" data-pptx-shape-id="1001" ...>标题</text>`。角色可使用 `footnote` 与 `page_mark`；inspect 默认允许二者低至 9pt，项目也可在 content contract 的 `inspection_rules.font_min_pt_by_role` 覆盖阈值。
