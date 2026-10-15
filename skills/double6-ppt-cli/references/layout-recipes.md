# 版式配方（generate 模式）

画布 1280×720，边距 M=64。字号用 spec_lock 阶梯：hero 112 / display 60 / title 36 / subtitle 24 / body 18 / label 14 / caption 12（px）。颜色只用 spec_lock 角色：`primary`、`accent`、`accent2`、`gradient_from/to`、`surface`、`on_accent`、`on_primary`。每个配方都在 0.5.0 的 6 个参考 brief 上验证过（`visual-metrics` 全部通过）。

装饰性矩形要加 `data-pptx-role="decoration"`，并带唯一 `id`。原生图表/表格的 metadata `name` 必须等于外层 `<g id>`。

## 页眉
kicker：一根 48×6 的 accent 圆角条，加 label 级大写文字，放在 y≈62。标题用 title 档 bold，放在 y≈110，最多 2 行，用平衡折行避免孤行。

## 封面
- **cover_photo**：满版照片（`--treat cover=1920x1080` 并加 duotone 或 tint），从左到右叠一层渐变 scrim（0.85 → 0）。左下依次放 kicker、display 标题、subtitle，右下角放署名药丸。
- **cover_gradient**：`gradient_from → gradient_to` 渐变底，右侧放一张圆角照片卡（或大图标），用一个 accent 圆部分压住卡片角。适合没有好照片的 pitch。

## 节奏页
- **statement_photo**：满版照片加 0.55 黑 scrim，居中 display 金句和 subtitle，上方一根 accent 短条。放在两张数据页之间。
- **section**：章节页。巨型编号（hero，accent 色）加标题，可带半屏照片。

## 数据
- **kpi_hero**：左边 540 宽的渐变色块，里面是 hero 级主数字、label，右上角一个 22% 透明的 accent 圆；右边一栏放其余指标（display 数字、label、tint 圆底图标，行间分隔线）；底部是 accent 竖条加 takeaway。
- **kpi_row**：整宽渐变色带（深色主题用 surface），等分各列，列间用 20% 白色分隔线。整排数字统一一个档位（hero、display 或 subtitle，以最长值能放下为准），标签在下。色带填满到页脚，下面接 takeaway。
- **chart_annotated**：原生图表占左侧 740 宽。单系列柱图用 `point_colors` 只高亮一根（`chart_series[0]`），其余用 `chart_series[3]`；折线图用 `lineMarker`，末点高亮。高亮点上方放 callout 药丸（accent 填充，on_accent 对比度不够 4.8 时改用 primary）。右栏依次是 label、hero 级结论数字、accent 短条和 body 解读。
- **table_highlight**：原生表格，行高 72，字号 18。推荐列加 5px accent 描边框，顶部放“推荐 / Recommended”药丸徽章；表格下方是箭头图标加 takeaway。
- **comparison**：两栏对比。左栏 surface 底加 × 图标、引语；右栏 primary 底加 ✓ 图标、引语字号放大到 subtitle。

## 流程与列表
- **timeline**：一条 8px 渐变轨道（primary → accent），节点是空心圆。每步配 display 级编号（最后一步用 accent），下方卡片放图标、月份（subtitle bold）和说明。卡片高度按内容计算，整组垂直居中。
- **split_photo**：照片占半屏（可放左或右），照片上压一个 hero 数字和说明（底部渐变 scrim）。另一半是页眉加 2–3 个要点，每个要点由 tint 圆底图标和文字组成，用分隔线隔开。
- **features**：三张卡片，顶部是渐变或照片色块，里面放大图标和一个装饰圆（圆必须在卡内）；卡片下半部放标题、accent 短条和说明。
- **agenda**：左边半屏照片配“议程”标题；右边是 display 编号（第一项用 accent）、标题和图标，行间分隔线。
- **team**：渐变圆形首字母头像（或圆形裁切照片），下面是姓名和角色；底部一条 tint 药丸写团队亮点。

## 结束
- **closing_photo**：满版照片加底部 scrim，左下是 accent 短条、title/display 的行动号召和受众信息。照片要和封面呼应，但不要重复使用同一张。

## 推荐序列（6 页）
- 咨询：cover_photo → kpi_hero → chart_annotated → table_highlight → timeline → closing_photo
- 路演：cover_gradient → split_photo → kpi_hero → chart_annotated → team → closing_photo
- 发布：cover_photo（深色）→ statement_photo → features → kpi_row → kpi_row → closing_photo
- 培训：cover_photo → agenda → timeline → comparison → split_photo → closing_photo
