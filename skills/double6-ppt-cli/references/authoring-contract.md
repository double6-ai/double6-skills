# Authoring contract v0.2

## 输入边界

支持 Markdown/TXT、结构化 JSON/YAML、本地已授权图片、已经整理好的 PPT Master SVG 项目，以及普通 `.pptx` 模板的原生分析/填充。不包含任意 PDF/DOCX 内容解析、网页抓取、在线搜图或生图。

文本或结构化材料先通过 `init` 固化进 run。Agent 在 `authoring/project/` 中完成内容规划和 SVG authoring；编译器不会替 Agent 猜测事实、观点层级或视觉审美。

generate 项目还必须提供 `authoring/project/spec_lock.md`，且包含 `## pptx_structure` 段与 `mode: flat`（自由版式）或 `mode: structured`（模板结构）。`init --mode generate --design <profile>` 会创建待确认草稿；未填字段或仍为 draft 时，`compile` 会返回可执行的下一步。

同时必须提供 `authoring/project/design_spec.md`，且包含 **精确标题** `## IX. Content Outline`。PPT Master 的 communication-trace 门禁会检查该 section：其中每页必须有 `### Slide NN`（或具体页码）块，并在块内写一行 `- Audience move: ...`。缺少该 section 会导致 `svg_quality_failed`。

Authoring 结构约束（quality gate + semantic contract）：

1. 根级可见 `<g>` 必须写 `data-pptx-bounds`，且 bounds 要覆盖文字实际墨迹（含 font-size 度量），否则 `svg_quality_failed`。
2. 同一段落的多行文案用一个 `<text>` + 正 `dy` 的 `<tspan>`；语义独立的文本框保持独立。
3. 需要 `preferred_structure` 为 `top_level`/`placeholder` 的对象，其 `source_selector.id` 必须指向 **SVG 根级直接子 group**，由 adapter 去分组；嵌套在更深 wrapper 内的 group 会 `unsafe_source_flatten`。
4. 不要把卡片/流程步骤包进额外的 `cards`/`flow` 包装 group 再要求 flatten——包装层本身应去掉，或改成不参与 flatten 的 `data-pptx-role="decoration"`。

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

## 原生 chart / table

`compile` 默认启用 `--native-charts-and-tables`。真正的原生对象必须是根级：

```xml
<g id="chart" data-pptx-bounds="64 200 600 300" data-pptx-shape-id="1002"
   data-pptx-replace-with="chart">
  <metadata type="application/json">{"type":"bar","categories":["A","B"],"series":[{"name":"S1","values":[1,2]}]}</metadata>
</g>
```

并在 semantic manifest 使用 `preferred_structure: native_chart` + `match.drawingml_id: 1002`。普通示意图 group **不会**变成原生 chart；缺 JSON metadata 会在 vendor 阶段 fail closed。

## 多行文本与居中

- 同一段落的多行文案：所有 `<tspan>` 的 `x` 必须**等于**父 `<text>` 的 `x`；居中用 `text-anchor="middle"`，不要给每行不同 x。
- 未在 `spec_lock.md` `## typography` 声明、且出现次数 > 2 的字号会被质量门阻断；请声明干净阶梯（避免 20/22 这类无感差值）。
- `data-pptx-bounds` 必须覆盖真实墨迹宽度；中文混排请按质量门同宽算法估宽，或预留足够留白。

## generate 模式能力边界

`init --design <profile>` 只给颜色/字号/工作结构，**不自动套版式**。要好看请：1) 自己设计完整 SVG 版式；或 2) 改用 template-fill 复用现成模板。vendored ppt-master 精简核不包含上游 `workflows/` 版式库。
