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

- 源目录默认是 `authoring/project/svg_output/`，使用 vendored PPT Master `v6.7.0` 内核编译。
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

对应 SVG 元素示例：`<text id="title" data-pptx-shape-id="1001" ...>标题</text>`。角色可使用 `kicker`、`label`、`caption`、`footnote` 与 `page_mark`；inspect 默认允许它们低至 9pt，项目也可在 content contract 的 `inspection_rules.font_min_pt_by_role` 覆盖阈值。

## 原生 chart / table

`compile` 默认启用 `--native-charts-and-tables`。真正的原生对象必须是根级：

```xml
<g id="chart" data-pptx-bounds="64 200 600 300" data-pptx-shape-id="1002"
   data-pptx-replace-with="chart">
  <metadata type="application/json">{"type":"bar","categories":["A","B"],"series":[{"name":"S1","values":[1,2]}]}</metadata>
</g>
```

并在 semantic manifest 使用 `preferred_structure: native_chart` + `match.drawingml_id: 1002`。普通示意图 group **不会**变成原生 chart；缺 JSON metadata 会在 vendor 阶段 fail closed。

### PPT Master v6.7.0 补充（0.4.0）

- **JSON 为准（默认）**：编译时 adapter 会在 build 副本上给没有 authority/基线的 marker 加 `data-pptx-native-authority="json"`，并把 `data-pptx-bounds` 写入 metadata 的 x/y/width/height。SVG 子元素只作预览。缺 bounds 时报 `native_marker_invalid`。如要使用上游的 SVG-first 校验（fallback 哈希 + 完全对齐），在 semantic `defaults.native_marker_authority` 中设为 `"author"`，并自行运行上游 `stamp_native_fallbacks.py`。
- **表格 schema v2**：未写 `schema` 的表格会自动升级为 `ppt-master.semantic-table.v2`，并补上 v4.8 默认配色（深蓝表头、白底、斑马纹、18px）。在 v2 中未设置颜色表示无填充；自行写 v2 时请显式给出颜色。
- **条形图顺序**：v6 的水平 bar 按 payload 顺序**自上而下**排列（v4.8 为自下而上）。需要旧顺序时写 `"axes":{"category":{"reverse":false}}`。
- **空值**：line 系列允许 `null` 表示断点（v4.8 会报 "value is not numeric"）。
- **waterfall 等 chartEx 类型**：以 `cx:chart` 输出，PowerPoint 2016+ 可显示；LibreOffice 预览为空白，视觉复核需在 PowerPoint 中进行。
- **组合图次坐标轴**：`plots[].secondary` 不受支持，两组数据共用同一数值轴。
- 图片（`p:pic`）可在 semantic manifest 中用 role `image` 追踪。
- v6 检查器会对缺少根 `data-pptx-page-role` 和未分组的顶层元素给出 **warning**（不阻断）。

## design_spec §IX Relationships（v6 硬性要求）

每个 `### Slide NN` 块必须有一行 `- Relationships: …`，写明本页内容单元之间的关系，没有则写 `none`。缺失时 v6 质量门会阻断编译。0.3.x 的旧项目需补上这一行。

## 多行文本与居中

- 同一段落的多行文案：所有 `<tspan>` 的 `x` 必须**等于**父 `<text>` 的 `x`；居中用 `text-anchor="middle"`，不要给每行不同 x。
- 未在 `spec_lock.md` `## typography` 声明、且出现次数 > 2 的字号会被质量门阻断；请声明干净阶梯（避免 20/22 这类无感差值）。
- `data-pptx-bounds` 必须覆盖真实墨迹宽度；中文混排请按质量门同宽算法估宽，或预留足够留白。

## generate 模式的视觉设计

`init --design <preset>` 写入统一调色、字号阶梯和图标库，但不会替 Agent 画版式。版式由 Agent 按 [visual-design.md](visual-design.md) 设计：vendored 设计子集包含 style、版式库（presentation_core / report_core）、图表与表格模板、线性图标和形状脚本。上游 `workflows/` 不在 vendor 内，以本 Skill 的流程为准。

## 字号：px 与 pt

`viewBox 0 0 1280 720` 对应 13.333in×7.5in，因此 **1 SVG px = 0.75pt**。`inspect` 的小字号阈值是 **pt**：

| role | 下限 pt | 最小 px（向上取整） |
|---|---|---|
| title | 20 | 27 |
| subtitle | 16 | 22 |
| body | 12 | 16 |
| data | 10 | 14 |
| caption / label / kicker / footnote / page_mark | 9 | 12 |

`## typography` **必须保留 `body` 键**（其它角色名可扩展）。出现次数 > 2 的每个字号都要声明。

## 外部渲染证据（Windows / 自定义渲染器）

PowerPoint COM 等外部渲染完成后，登记到 run 再走 visual 闭环：

```bash
python scripts/d6ppt.py render-import --run <run>   --pdf export.pdf --pages slide-1.png slide-2.png   --contact-sheet contact.png   --tier portable --renderer powerpoint-com   --fact-source "PowerPoint desktop export"
```


## 端到端实测要点（0.3.0）

- **单行文字**：`<text data-pptx-shape-id>` 内只有一个 `<tspan x=同值>` 时，adapter 会在 build 副本中自动展开，避免 vendor 丢失 shape id。多行仍按「多行文本与居中」规则写 `tspan x/dy`。
- **不换行文本框**：compile 会把 `wrap="none"` 文本框按对齐方式加宽（CJK 12%、拉丁 4%），防止 LibreOffice 按框宽重新折行（例如「第 7 天全量运行」被折成两行）。可用语义清单 `defaults.nowrap_text_padding: false` 关闭，或传入 `{"cjk":0.1,"latin":0.03}` 自定义；对象图记录在 `nowrap_text_frames_padded`。
- **原生图表**：
  - 要生成图例，SVG fallback 里必须有可见的系列名文字。否则 PPT Master 会省略 legend，并写入 `evidence/compiler_warnings.json`，inspect 报 `native_object` 警告。
  - doughnut/pie 的数据标签不会转换。需要数值时请另放文字对象。
- **字体**：使用 `doctor` 能解析到的字体。Linux portable 档请用 `Noto Sans CJK SC` 等已安装字体；写 `Microsoft YaHei` 会被回退，导致度量偏差。
- **visual 闭环顺序**：`visual-policy` → `verify`（产出渲染）→ 查看渲染并写 `visual-review` → 再次 `verify` → `finalize`。
- **compile 前**：`authoring_scaffold_incomplete` 的 `details.remaining_fields` 会列出仍是模板占位的字段。


## 0.5.0 视觉相关编译行为

- **图标**：SVG 中的 `<use data-icon="<lib>/<name>" x y width height fill/>` 会在 build 副本中从 `authoring/project/icons/<lib>/` 或 vendored `templates/icons/` 取图，交给上游 checker 与 converter 原生嵌入；找不到时报 `icon_missing` 并列出缺失名称。vendored 清单见 `scripts/maintenance/design_icons_tabler_outline.txt`。
- **原生图表与表格调色**：compile 从 spec_lock `## colors` 读取调色。图表未写 `style.colors` 时，使用 `chart_series`（没有该字段时依次用 accent、primary、muted、line），并补 `text_color` / `axis_color` / `grid_color`；未写 schema 的表格用 primary 表头、text 正文、surface 斑马纹、line 边框。作者写了的颜色一律保留。semantic `defaults.native_palette: false` 可关闭此行为。
- **单行 `<tspan>`**：`<text data-pptx-shape-id><tspan x=同值 dy="0">…</tspan></text>` 也会被展开，避免稳定身份丢失（`ambiguous_object_mapping`）。多行段落与内联强调 run 的身份本来就能保留。
- **小字角色**：`kicker`、`label`、`caption`、`footnote`、`page_mark` 的下限为 9pt（12px）。
