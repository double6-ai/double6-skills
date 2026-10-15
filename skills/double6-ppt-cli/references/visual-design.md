# 视觉设计指引（generate 模式必读）

本 Skill 的转换管线（SVG → 原生 DrawingML）可以承载完整的 PPT Master 视觉表达。决定成品好不好看的是 **Agent 作稿时的设计决策**。本文是这些决策的入口；详细规范在 vendored 的 PPT Master v6.7.0 设计子集中（路径均相对 `vendor/ppt-master-core/skills/ppt-master/`）。

> 上游文档中链接到未 vendor 文件（`workflows/`、生图/搜图、brands 等）的部分请忽略；本 Skill 的流程以 SKILL.md 为准。

## 1. 作稿顺序

1. `init --design <preset>` 选一个风格预设（见 §2），它会写好统一调色、字号阶梯和图标库。
2. 读该预设对应的 style 文件 `templates/styles/<style_id>/templates/design_spec.md`（沟通方法、页面角色、图表规范、视觉默认值），以及 `references/visual-styles/<visual_style>.md`。
3. 读 `references/executor-base.md` 的 **Page Expression Core**（设备菜单、版式结构、页面配方、配色与阴影默认值）。
4. 在 `design_spec.md` §IX 为每页写一行 `- Composition: page job → 版式结构 → 设备`，再动手画 SVG。
5. 需要现成构图时，参考 `templates/layouts/presentation_core/templates/*.svg`（20 种：封面、hero、editorial split、三卡、KPI 仪表、流程时间线、数据故事、图表洞察、表格总结……）和 `templates/layouts/report_core/`。只借构图，不要原样照抄占位文字。
6. 图表先看 `templates/charts/`（36 种）和 `references/executor-chart.md`；表格看 `templates/tables/` 和 `references/executor-table.md`。
7. 复杂形状（箭头、chevron、callout、括号等）用 `scripts/preset_shape_svg.py`，布尔合并用 `scripts/shape_boolean_svg.py`。

## 2. 风格预设（`--design`）

预设从大胆到雅致都有，没有“克制配色”这类硬规则。配色行为按所选上游 style 走。

| 预设 | 上游 style | 主题 | 底色 | 主色 | 强调色 | 第二强调 | 图片取向 |
|---|---|---|---|---|---|---|---|
| `consulting`（别名 `business`） | consulting-decision | 浅 | #FFFFFF | #051C2C | #2251FF | #00A9F4 | 建筑/城市/工作场景，深蓝 duotone |
| `investor-pitch` | investor-pitch | 浅 | #FFFFFF | #2B1C8F | #FF5A3C | #8B7CF6 | 产品使用场景，满版 + 靛蓝 scrim |
| `product-launch` | product-launch | 深 | #0A0A0D | — | #F2B544 | #FF6A3D | 深底产品大图、大裁切、出血 |
| `operating-review` | operating-review | 浅 | #FFFFFF | #0F2A4A | #F26B38 | #3D7DCA | 运营/团队照片，冷色 duotone |
| `academic` | academic-research | 浅 | #FBFAF6 | #1F3B4D | #C0582B | #6E8F72 | 实地/风景/航拍，自然色 |
| `training` | workshop-teaching | 浅 | #FFFBF3 | #124E5C | #FF8A3D | #5BB5C8 | 协作人物、暖光、圆角裁切 |
| `neutral` | — | — | 待填 | 待填 | 待填 | 待填 | 有品牌规范时自行填写 |

spec_lock 还会写入 `gradient_from/to`、`on_accent`、`on_primary`（自动算出的高对比文字色）、`chart_series`（相邻系列 ΔE ≥ 25）和 `imagery`。字号阶梯（px）：mega 200 / hero 120 / display 64 / title 40 / subtitle 28 / body 22 / label 15（caption 同 label）。正文不小于 14pt。用户给了品牌色时以品牌为准。

## 3. 配色与样式（以上游 style 为准）

- 配色行为以所选 style 的 `V. Visual System Defaults → Color Behavior` 与 `references/executor-base.md` 的 everyday effects 为准（如 60-30-10 起始比例、强调色用于焦点、同色相渐变、按编码需要决定色相数）。预设只给一组起始色值，可按 style、品牌或内容调整（例如 product-launch 可深浅交替，creative 类风格可使用更多色相）。
- spec_lock `## colors` 是全 deck 的颜色锚点；新增的反复使用的颜色应作为具名角色写进 spec_lock，保持上游意义上的调色一致性。
- 正文对比度 ≥ 4.5:1（大字 ≥ 3:1）。
- 有 deck 调色时，原生图表系列色取自 spec_lock `chart_series`（compile 自动写入）；不要沿用 Office 默认蓝橙配色。直接在数据上标注，弱化网格与图例。
- 阴影、渐变、发光的用量遵循 executor-base（resting 阴影 0.06–0.10，每页 2–3 个浮起对象以内）。
- 字号不超过 7 档（§2 阶梯即可）；kicker、标签、页码用 label/caption 档。
- 图标默认一个库（`tabler-outline`），统一尺寸（32–48px）与处理方式；图标服务于含义。

## 4. 页面构图速查（摘自 executor-base）

| 内容关系 | 推荐结构 |
|---|---|
| 一个焦点结论 | 居中单列或主色场域 + 大标题，留白 40–60% |
| 平行 2–4 项 | 三列 / 编号节点 + 连线 / chevron 条，不要千篇一律的等宽卡片 |
| 主证据 + 结论 | 3:7 不对称分栏：图表占大块，旁边放 takeaway 和大数字 |
| 指标概览 | KPI 卡（指标名 + 大数字 + 变化），3–4 个 |
| 对比 | 对称分栏或表格，用一处强调标出差异（如深色高亮列） |
| 流程 / 路线 | 时间线基线 + 节点，或比例条（如资金用途） |
| 封面 / 章节 / 结束 | 主色场域或深色底 + 几何 motif + 大标题；结束页呼应封面 |

每页至少有一个非文字视觉元素（色块、卡片、图标、图表、线条节点等）；数据页之后安排一张更“透气”的页面。

## 4b. 让 deck 好看：版式配方与图片

“能交付”不等于“好看”。参照上游最佳示例和 Keynote、McKinsey/BCG、Pitch/Gamma 一类专业 deck，用下面的手段建立视觉节奏。这些手段已经做成 `d6ppt recipe` 命令，见 [layout-recipes.md](layout-recipes.md)。正文页以非卡片构图为主：

- **大胆的字号对比**：每页一个主角。mega（200px）或 hero（120px）大数字或 display 标题，配 label 级说明，不要所有文字一样大。
- **大数字 hero**：关键指标做成渐变色块里的巨型数字，其余指标放在旁边一栏（不对称）。
- **满版照片**：封面、章节页、结束页用满版照片加渐变 scrim（底部 0.6–0.85 黑），文字压在 scrim 上。
- **分屏**：照片占半屏，另一半放论点；照片上可压一个大数字。
- **标注式数据图**：高亮一个数据点（point_colors），其余用浅色，加 callout 气泡和旁边的结论大数字。
- **高亮表格**：推荐列加强调色描边框和“推荐”徽章。
- **渐变、纹理与叠层**：渐变时间轴、色块上的半透明圆、渐变首字母头像。
- **节奏**：深浅页、照片页与数据页交替；连续两张数据页之间插一张透气的 statement/照片页；结束页呼应封面。

### 图片（royalty-free，必须带署名元数据）

1. 搜图：`image-search --query "<关键词>"`（Openverse，仅 cc0 / pdm / by / by-sa 且允许商用与修改）。
2. 入库：`image-add --run <run> --name <safe> --openverse-id <id>`，或用 `--url/--file` 加 `--license unsplash|pexels|cc0|… --creator --source-url --license-url`。实在找不到合适图片时用 `--placeholder`，会生成明确标注的占位图，finalize 时产生警告。
3. 处理：`--treat "cover=1920x1080,focus=0.5x0.4,duotone=#051C2C,#2251FF,fade=0.2"`。可用 crop/cover、focus、duotone、tint、blur、grayscale、brightness、contrast、round、circle、fade。
4. SVG 里用 `<image href="../images/<name>.jpg" .../>` 引用。署名用小号深色药丸标签放在角落，例如 “Photo: 作者 · 许可”。
5. compile 会检查 `images/credits.json`，缺署名直接报 `image_credit_missing`。finalize 会写 `delivery/IMAGE_CREDITS.md`。

## 5. 反模式（出现即返工）

1. 整页 bullet 列表、白底黑字、无任何视觉元素（“Word 文档式”页面）。
2. 内容挤在左上，下半页大面积空白（上重下空）。
3. 颜色没有角色：同一语义在不同页用不同颜色、颜色与 style 的 Color Behavior 无关。
4. 原生图表沿用 Office 默认蓝橙，或系列色与 deck 调色无关。
5. 对称卡片网格泛滥：每页都是 3 张一样的卡片。
6. 字号超过 7 档，或同一角色在不同页字号不同。
7. 孤行换行：中文末行只剩 1 个字，或只剩一个短拉丁/数字片段（如“4%”）；文字压线、溢出卡片。中文与数字/英文之间不要手动加空格（“11月11日”，不是“11 月 11 日”）。
8. 稀疏卡片：卡片很大、内容很少，下半截空着。
9. 图表系列色太接近（ΔE < 25），分不清。
10. 装饰性图标墙、混用多个图标库、图标与含义无关。
11. 超出 executor-base 用量的重阴影、发光（Office 2007 风格）。

## 6. 质量门与视觉复核

- compile 会自动嵌入 `data-icon` 图标、把调色写进原生图表和表格（见 SKILL.md）。
- `inspect` 的视觉指标（`visual_metrics`）检查对比度、留白平衡、非文字元素、字号档数、Office 默认图表色、孤行、中文与数字间的空格、图表系列可分辨度、图片署名等，详见 [visual-quality.md](visual-quality.md)。
- 模型视觉复核用 8 维评分表；未达到通过线（均值 ≥3.5，且每一维 ≥3）时不得 finalize 为 `pass`。
