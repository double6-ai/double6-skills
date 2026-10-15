# 版式配方（generate 模式）

配方已经做成 CLI，不必手写坐标。每个配方读取 run 的 spec_lock 调色和字号阶梯，把一页的 JSON 内容渲染成完整 SVG，同时更新 `semantic_manifest.json`、spec_lock 的图标清单和 `page_rhythm`。产出的页面按构造就能通过确定性检查：对比度、字号档数、孤行、图表配色、正文字号。

```bash
d6ppt recipe list                                    # 全部配方：类型、必填/可选字段、是否卡片式
d6ppt recipe show big_number                         # 单个配方的字段
d6ppt recipe deck  --run <run> --plan plan.json      # 整套 deck：按 pages 顺序写 01.svg…NN.svg（会替换现有页）
d6ppt recipe apply big_number --run <run> --page 3 --data '{"value":"64%","label":"前20%门店毛利占比"}'
```

`plan.json` 的格式：

```json
{"footer": "华东区零售渠道重组", "audience": "集团管理层", "lang": "zh",
 "pages": [{"recipe": "cover_photo", "image": "hero", "title": "…", "subtitle": "…", "kicker": "BOARD DECISION"},
           {"recipe": "big_number", "title": "…", "value": "64%", "label": "…", "supporting": [{"value": "148", "label": "门店总数"}]}]}
```

`image` 填 `image-add --name` 用的名字。图标名必须在 `scripts/maintenance/design_icons_tabler_outline.txt` 里，否则报 `recipe_icon_missing`。命令输出的 `warnings` 必须处理：相邻两页用了同一配方、过半正文页是卡片式、同一张照片在多页重复使用。

## 字号（px，1px = 0.75pt）

mega 200 / hero 120 / display 64 / title 40 / subtitle 28 / body 22 / label 15（caption 与 label 同档）。共 7 档。正文不得小于 14pt，否则 `small_body_text` 会报错。

## 配方一览

| 配方 | 节奏 | 卡片 | 用途 |
|---|---|---|---|
| `cover_photo` | anchor | 否 | 满版照片加渐变 scrim；短标题用 hero 字号 |
| `cover_split` | anchor | 否 | 饱和渐变底加超大字标，照片从右侧出血，接缝处一个 accent 方块。适合路演和品牌感强的封面 |
| `statement_photo` | breathing | 否 | 满版照片加居中 display 金句，放在两张数据页之间 |
| `quote` | breathing | 否 | 超大引号加 display 引语，渐变底，可带照片面板。适合收尾 takeaway 或客户证言 |
| `big_number` | breathing/dense | 否 | 一个 mega 数字（200px）加结论；最多 3 个辅助数字放在一条开放基线上 |
| `section` | breathing | 否 | 章节页：hero 编号加标题，可带照片条 |
| `kpi_hero` | dense | 是 | 渐变主数字面板加右侧指标栏（不对称） |
| `kpi_photo` | dense | 否 | 满版照片，底部一排开放式大数字（价格/上市/规格） |
| `kpi_row` | dense | 是 | 整宽渐变色带，一排大数字，全排统一字号 |
| `chart_annotated` | dense | 否 | 原生图表单点高亮，加 callout 气泡和 hero 数字结论栏 |
| `table_highlight` | dense | 否 | 原生表格，推荐列加 accent 框和徽章，下方 takeaway |
| `timeline` | dense | 否 | 开放式时间轴：渐变轨道、hero 编号、图标和文字直接排在页面上，底部 takeaway 条；整组垂直居中 |
| `split_photo` | dense | 否 | 半屏照片压 hero 数字，另一半写论点；≤2 条时自动放大并编号（Q1/Q2） |
| `features` | dense | 否 | 开放式特性栏：渐变大图标圆、编号、标题、色条、说明，栏间分隔线 |
| `comparison` | dense | 是 | Avoid / Prefer 对照，Prefer 一侧用 primary 底和更大字号 |
| `agenda` | dense | 否 | 照片面板加大号编号议程 |
| `team` | dense | 否 | 无卡片团队页：大渐变首字母圆、姓名、角色，底部亮点条 |
| `closing_photo` | anchor | 否 | 满版照片收尾，display 号召语；呼应封面，但不要重复用封面照片 |

## 组合原则

- 正文页以非卡片构图为主：卡片式（`kpi_hero` / `kpi_row` / `comparison`）不超过正文页的一半。
- 每 2–3 张数据页插一张 breathing 页（`statement_photo` / `quote` / `big_number` / `section`）。
- 指标少、结论强时用 `big_number`，不要用卡片网格。流程类用 `timeline`，不要画方框。
- 照片按语义取：封面和结束页用场景照，`split_photo` 用细节或质感照；同一张图不要在多页重复。

## 推荐序列（6 页）

- 咨询：cover_photo → big_number → chart_annotated → table_highlight → timeline → closing_photo
- 路演：cover_split → split_photo → kpi_hero → chart_annotated → team → closing_photo
- 发布：cover_photo → statement_photo → features → big_number → kpi_photo → closing_photo
- 经营复盘：cover_photo → kpi_hero → chart_annotated → table_highlight → split_photo → closing_photo
- 学术：cover_photo → split_photo（问题）→ timeline（方法）→ chart_annotated → big_number（发现）→ closing_photo
- 培训：cover_photo → agenda → timeline → comparison → split_photo → quote
