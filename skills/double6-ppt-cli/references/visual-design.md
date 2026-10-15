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

| 预设 | 上游 style | visual style | 底色 | 主色 | 强调色 | 适用 |
|---|---|---|---|---|---|---|
| `consulting`（别名 `business`） | consulting-decision | swiss-minimal | #FFFFFF | #1F3A5F | #3C7A78 | 结论先行的分析、建议、决策材料 |
| `investor-pitch` | investor-pitch | swiss-minimal | #F7F6F3 | #22344F | #3C7A78 | 融资路演、商业计划 |
| `product-launch` | product-launch | editorial | #F8F7F4 | #16181C | #B08D57 | 新品发布、产品介绍（深浅节奏） |
| `operating-review` | operating-review | data-journalism | #FFFFFF | #1F3A5F | #2F6E9E | 经营复盘、数据报告、季度回顾 |
| `academic` | academic-research | swiss-minimal | #FAFAF7 | #263B4F | #8A5A44 | 学术报告、答辩 |
| `training` | workshop-teaching | soft-rounded | #FFFDF8 | #3D4A3F | #B08A50 | 培训、课程、工作坊 |
| `neutral` | — | — | 待填 | 待填 | 待填 | 有品牌规范时自行填写 |

所有预设的起始值共用：正文 #1E2733、次要文字 #5B6573、分隔线 #D9DDE2；字号阶梯（px）display 64 / title 34 / subtitle 24 / body 18 / label 14 / caption 12。用户给了品牌色时以品牌为准。

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

## 5. 反模式（出现即返工）

1. 整页 bullet 列表、白底黑字、无任何视觉元素（“Word 文档式”页面）。
2. 内容挤在左上，下半页大面积空白（上重下空）。
3. 颜色没有角色：同一语义在不同页用不同颜色、颜色与 style 的 Color Behavior 无关。
4. 原生图表沿用 Office 默认蓝橙，或系列色与 deck 调色无关。
5. 对称卡片网格泛滥：每页都是 3 张一样的卡片。
6. 字号超过 7 档，或同一角色在不同页字号不同。
7. 中文孤字换行（如“算/法”）、文字压线、文字溢出卡片。
8. 装饰性图标墙、混用多个图标库、图标与含义无关。
9. 超出 executor-base 用量的重阴影、发光（Office 2007 风格）。

## 6. 质量门与视觉复核

- compile 会自动嵌入 `data-icon` 图标、把调色写进原生图表和表格（见 SKILL.md）。
- `inspect` 的视觉指标（`visual_metrics`）检查对比度、留白平衡、非文字元素、字号档数、Office 默认图表色、中文孤字等，详见 [visual-quality.md](visual-quality.md)。
- 模型视觉复核用 8 维评分表；未达到通过线（均值 ≥3.5，且每一维 ≥3）时不得 finalize 为 `pass`。
