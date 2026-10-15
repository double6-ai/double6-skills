# template-fill：PPT Master v6.7.0 roundtrip 后端

PPT Master 从 v5.0.0 起移除了 Template Fill Native。0.4.0-exp.2 起，template-fill 改由 `scripts/double6_ppt_cli/pm6_template/` 实现。CLI 流程和计划契约没有变化：`template-analyze → template-check-plan → 用户确认 → template-apply`。

## 流程

1. **分析**（`analyze_pptx`）：沿用 v4.8 的 slide library（`pm6_template/fillnative/`，由 Double6 维护的 v4.8 只读模块移植），包括 SmartArt/图表/表格合并拓扑和页面类型。在此基础上，每个 slot 增加：
   - `shape_id`/`shape_name`/`placeholder`；
   - `fit_context`：沿 占位符 → 版式 → 母版 → txStyles 继承链解析出的字号、边距、自动调整方式和列表级别。
   每页增加 `notes_text`、`transition`、`pictures`、`links`。
2. **检查**（`check_plan`）：保留 v4.8 全部检查项和错误码。宽度比估算 `text_capacity` 被度量版 `text_fit` 取代，旧结论保留在 `legacy_*` 字段。另外新增：
   - `cross_slide_slot`（同页来源）
   - `stale_old_text`
   - `implicit_list_levels`
   - `levels_length_mismatch`
   - `slot_is_table_or_chart`
   - `notes_invalid` / `template_notes_dropped`
   - `transition_invalid`
3. **写入**（`apply_plan`）：
   - 用 vendored `pptx_to_svg.py --roundtrip` 导入；
   - 用 `page_plan.json` 实现重排和复用；
   - SVG 文字保持不动，用 `svg_to_pptx.py --roundtrip` 导出，所有对象原样回传（`rebuilt=0`）；
   - 按 cNvPr id 改写原生 txBody，并按度量结果写入 `normAutofit fontScale/lnSpcReduction`、`spAutoFit` 增高或显式缩字（下限 0.85）；
   - 表格单元格和图表数据按 id 原生回填；
   - 处理讲者备注和切换效果。
4. 外层流程（处置、同页来源绑定、导航重建与 active 状态、SHA 绑定图片替换、计划确认门、OfficeCLI 校验）由 `template_workflow.py` 负责，与后端无关。

## 计划字段（与 v4.8 相同，另有扩展）

- 替换目标：`slot_id`，或 `shape_id`，或 `shape_name`（同页唯一）。
- 文本：`text` 中 `\n` 表示新段落，行首 `\t` 表示列表级别；也可以用 `paragraphs: [...]`。可选 `levels: [0,1,…]`，显式指定每段级别。
- 混合格式：
  - 未改动的段落原样保留，包括 run、`a:br` 和字段（例如页码）；
  - 改动的段落保留公共前缀/后缀（≥2 字符）所在 run 的样式，改动部分沿用改动起点所在 run 的样式。例如「**营业收入：** 12.5亿元」改成「**营业收入：** 14.1亿元」，加粗不会丢。
- `notes` / `speaker_notes`：
  - 字符串：替换为该文本（保留备注页母版和样式）；
  - `"keep"`：保留模板备注；
  - 省略：删除模板示例备注（与 v4.8 一致，check 阶段 WARN `template_notes_dropped`）。
- `transition`：
  - 省略或 `"keep"`：原样保留模板切换效果；
  - `"none"`：移除；
  - 效果名或 `{effect, effect_options, duration, advance_after}`：通过上游 `pptx_transitions` 写入，写完后做包级校验。

## 环境变量

| 变量 | 作用 |
|---|---|
| `D6PPT_TEMPLATE_BACKEND` | 只接受 `pm6`（默认值）；`v48` 返回 `template_fill_not_migrated`（请改用 0.3.x） |
| `D6PPT_PM6_TEXT_MODE` | `native`（默认）；`svg` / `svg-restore` 仅用于评估对比 |
| `D6PPT_PM6_ROOT` | 仅供开发：改用另一份 PPT Master 源码，正常使用不需要 |
| `D6PPT_FONT_RESOLVER` | 诊断用：`index`（强制扫描系统字体目录）或 `none`（只用启发式宽度） |

## 字体度量

- Linux 与 LibreOffice 一致，用 `fc-match`；没有安装中文字体时，中文改用启发式宽度（1em），避免按豆腐块测宽。
- Windows/macOS 扫描系统字体目录，找不到时依次回退：微软雅黑 / 苹方 / 思源黑体 / Calibri / Arial 等。
- 受字体差异影响，估算结果可能与 PowerPoint 实际渲染有偏差；可用 [powerpoint-verification.md](powerpoint-verification.md) 的脚本在实机上核对。

## 已知限制

- SmartArt、OLE、视频只读不改：check 阶段报 `non_text_content_unedited`，原样保留。
- 混合格式只按公共前后缀保留；如果改写改动了中间多个样式段，改动部分统一沿用一种样式。
- 切换效果的写入器在上游导出时校验得很严格：模板里 `p:transition` 的位置不合规（不在 `p:clrMapOvr` 之后）时，上游会拒绝导出。
- ClawHub 精简包缺少 `pptx_animation_presets.json`，带动画的模板请使用 GitHub 安装。
