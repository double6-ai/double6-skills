# 视觉质量门（0.5.0）

generate 模式交付前必须通过本门：**确定性检查无 error** 且 **8 维 rubric 均分 ≥ 3.5、每维 ≥ 3**。
配色的"好"以所选上游 PPT Master style 自身的 Color Behavior 为准（见 `references/visual-styles/`），
本门不设饱和度、色相数量或逐页换色限制；只做客观的颜色检查（对比度、存在 deck 调色时图表不得用 Office 默认色）。

## 1. 流程

1. 按 `references/visual-design.md` 完成设计并 `compile`、`verify` 渲染。
2. `d6ppt visual-metrics --run <run>`：读取当前渲染页与 PPTX，输出确定性检查结果；有 error 先修。
3. 视觉模型逐页看渲染图与 contact sheet，按下表 1–5 分打分，写成 JSON：
   ```json
   {"hierarchy":4,"color":4,"whitespace":4,"alignment":4,"imagery":3,"data_viz":4,"consistency":4,"polish":4}
   ```
4. `d6ppt visual-review --run <run> --status accepted --reviewer <model> --notes <要点> --rubric rubric.json`。
   generate 模式下缺少 `--rubric` 报 `visual_rubric_required`；rubric 不达标或检查有 error 报 `visual_quality_failed`，
   结果写入 `review/visual_quality.json`，需修改后重新渲染、重新评审。`verify` 的视觉门只接受通过的评审记录。
5. 打分要诚实：不确定时按低档给分，并在 notes 写明问题页与修改方向。

## 2. Rubric（8 维，1–5 分）

| 维度 | 5 分 | 3 分 | 1 分 |
|---|---|---|---|
| `hierarchy` | 每页一个结论标题，重点数字/句子一眼可见 | 有主次但重点不突出 | 所有文字同权重 |
| `color` | 完全遵循所选 style 的颜色角色；强调色只落在要点；图表跟随 deck 调色 | 调色一致但角色模糊 | 默认 Office 色或颜色与内容无关 |
| `whitespace` | 留白有意图，内容占满版式区域且视觉重心稳定 | 局部拥挤或局部空洞 | 上重下空 / 塞满 |
| `alignment` | 统一边距与栅格，元素严格对齐 | 少量错位 | 随意摆放 |
| `imagery` | 图标/形状/图片服务语义且风格统一 | 有装饰但与内容弱相关 | 纯文字或风格混杂 |
| `data_viz` | 图表/表格直接标注结论、突出关键系列；无图表页则评版式中的数据呈现 | 数据正确但无重点 | 默认样式、难读 |
| `consistency` | 跨页 motif、字号角色、页眉页脚一致 | 少量不一致 | 每页像不同 deck |
| `polish` | 无溢出、孤字、压线、错位，可直接交付 | 小瑕疵 | 明显缺陷 |

## 3. 确定性检查（`visual_quality.compute_visual_metrics`）

| code | 规则 | 级别 |
|---|---|---|
| `low_contrast` | 文字颜色与其框内主背景色 WCAG 对比度：正文 ≥ 4.5，≥18pt 或 ≥14pt 粗体 ≥ 3.0 | error |
| `top_heavy` | 页面下 40% 区域内容占比 < 5%（上重下空） | error |
| `near_empty_page` | 与背景不同的像素 < 4% | error |
| `no_non_text_element` | 每页至少一个非文字元素（色块卡片、色带、图标、线条、图表、表格、图片） | error |
| `too_many_font_sizes` | 全 deck 显式字号 > 7 种 | error |
| `office_default_chart_colors` | 存在 spec_lock 调色时，图表系列仍用 Office 默认色（4472C4/ED7D31/A5A5A5/FFC000/5B9BD5/70AD47） | error |
| `orphan_line` | 折行后末行过短：中文段末行只剩 ≤1 个汉字或 ≤6 个字符的拉丁/数字片段（如“4%”）；英文段末行只剩一个 ≤6 字符的单词 | error |
| `cjk_latin_space` | 中文与数字/拉丁字母之间手动加了空格（如“11 月 11 日”） | error |
| `chart_series_indistinct` | 同一图表相邻系列色 CIE76 ΔE < 25 | error |
| `image_credit_missing` | `images/` 中的图片在 credits.json 缺少许可/作者/来源（compile 阶段报错） | error |

注：LibreOffice 渲染时会在中文与拉丁字符之间自动加间距（即使源文本没有空格），PowerPoint 不会。这是渲染器的行为，不算 `cjk_latin_space`。

## 4. 参考 brief 与回归

- `assets/visual-briefs/briefs.json`：6 个参考 brief（中英各 3），覆盖 6 个 `--design` 预设。
- 每次改动设计资产、预设或编译行为后：按 SKILL.md 正常流程生成 6 套 deck，跑检查与 rubric，
  与上游 PPT Master 同 brief 产出（A）及上一版本（B）对比。目标：均分 ≥ 3.5、每维 ≥ 3、无检查 error。
- 模板填充保真回归：`scripts/tests/test_visual_quality.py::TemplateFillFidelityRegression`
  断言非文字设计形状 spPr 字节不变、几何不变、替换文字保留原 run 样式。

## 5. 发布前盲评（A/B）流程

1. 选 6 个参考 brief，分别产出：本版本（X）、上一发布版（Y），可加上游 PPT Master（A）作参照。
2. 渲染为同分辨率 PNG contact sheet，文件名随机化（如 `s-7f3a.png`），映射表单独保存，评审者不可见。
3. 至少 2 位评审（可含一个视觉模型，模型不得看到文件名映射或生成日志），每个 brief 两两对比：选更好的一份，并按第 2 节打 8 维分。
4. 汇总：X 对 Y 的胜率 ≥ 50% 且 X 的 rubric 均分不低于 Y；任一 brief 出现维度 < 3 必须修复或在发布说明中列为已知问题。
5. 结果（映射表、分数、胜率、评审备注）存入发布记录；未通过不得发布。
