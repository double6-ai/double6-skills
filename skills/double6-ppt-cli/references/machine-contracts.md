# Machine contracts v2.0

新运行统一使用字符串 `schema_version: "2.0"`。schema 1.0 只允许内存迁移读取，`save_run` 必须返回 `legacy_run_read_only`。

## run_manifest / template_profile

run 支持 `generate`、`postflight`、`template-fill`，冻结输入、模板、内容合同和 SHA。`template_profile.json` 递归记录逻辑 slide、physical part、layout/master/theme、DrawingML ID/name、OfficeCLI path、类型、层级、placeholder、几何、规范化文本/hash、媒体 SHA、角色和处置。Apply 后 `output_profile.json` 再绑定模板、内容、输出 SHA 与来源模板对象。

状态：`initialized → authored → compiled → inspected|repair_needed → verified|verified_with_warnings → local_delivered|delivered_with_warnings`；不能继续时为 `blocked`。

`init --mode generate` 会生成 `authoring/project/spec_lock.md`、`design_spec.md`、`svg_output/` 与 `semantic_manifest.example.json`。可用设计配置为 `neutral|academic|business|training`。`verification_preference` 保存 `auto|native|portable`，后续未显式指定其它档位时由 verify 采用。

业务专属检查只从 content contract 读取，通用代码不维护案例词表：

```json
{
  "inspection_rules": {
    "font_min_pt_by_role": {"body": 12, "footnote": 9, "page_mark": 9},
    "text_rules": [{
      "rule_id": "remove-known-sample",
      "pattern": "SAMPLE_TOKEN",
      "severity": "error",
      "category": "template_residue",
      "operation": "remove_leaf",
      "deterministic": true
    }],
    "nonlogical_sample_patterns": ["SAMPLE_TOKEN"]
  },
  "template_profile_rules": [{
    "rule_id": "sample-picture",
    "name_pattern": "sample-equation",
    "object_type": "picture",
    "role": "sample_formula_media"
  }]
}
```

`template_profile_rules` 的角色只能是 `attribution|navigation|sample_content|sample_formula_media|content_slot|design_system|unknown`；规则必须提供 text/name pattern、对象类型或页号选择器。正则无效时 fail closed。

## template plan

计划沿用 `template_fill_pptx_plan.v1` 数据面，同时使用 `schema_version: "2.0"`。每个选中模板页对象必须有且只有一个 disposition：`keep_design`、`replace_content`、`update_navigation`、`remove_sample`、`preserve_attribution`、`manual_review`。manual、缺失动作、未更新导航和未确认图片都会使 check-plan 失败。Apply 还要求根级 `status: "confirmed"`。

结构化 source 含 `slides[]` 时，内容槽来源门默认 `strict`。每个 `replace_content` 文字槽先尝试以同一逻辑页的 title/body/source_note 等字符串证明逐字或抽取覆盖；报告保存 `plan_slide`、`slot_id`、来源 JSON Pointer 与不受支持的片段。不能由同页源内容证明的文字只能显式写：

```json
{"content_binding":{"mode":"user_confirmed_paraphrase","source_refs":["source:/slides/8/body"],"user_confirmed":true}}
```

也可用 `mode: exact|extractive` 显式绑定 `source:` JSON Pointer，或绑定 content contract 的 `contract:<content_unit_id>`。跨页引用、空 source refs、未确认 paraphrase、无来源扩写和错误页码 fail closed。非结构化 source 默认 `warn`；需要严格门时在 content contract 写 `template_slot_policy.enforcement: strict`。

图片先通过 `template-asset-import` 进入 `run/input/template_assets/`，并在 `run_manifest.template_assets` 记录名字、run-relative 路径、媒体类型与 SHA。根级 `image_edits[]` 每项必须包含 `plan_slide`、`source_object_id`、`asset_name`、`asset_sha256`、`user_confirmed: true` 和完整 `expected_fingerprint`。check-plan 要证明：输出页与来源模板页一致、对象为唯一 picture、disposition 为 `replace_content`、资产已冻结且 SHA 未变。Apply 只改目标 slide relationship，新增独立媒体 part；共享原图、其它 slide、母版、布局、几何和裁切不变，并在 `template_apply_receipt.json` 记录前后媒体 SHA 与 package diff。

若模板导航叶子对象含 `ppaction://hlinksldjump`，profile 记录其源模板页目标。根级 `navigation_targets[]` 用确认后的标签和 `target_plan_slide` 定义文字导航的新逻辑目标；`navigation_source_targets[]` 同时覆盖导航底板、首页图标等非文字点击区的“原模板目标页 → 新逻辑页”映射。每个实际携带旧跳转的叶子对象都必须得到唯一映射，文字标签映射与源目标映射还必须一致。Apply 仅在一次性 vendor 模板副本中剥离这些旧 action，避免跳向未选源页；生成后为每个输出点击对象创建独立 slide relationship 并绑定目标逻辑页。当前章节按“不晚于当前页的最近 `navigation_targets.target_plan_slide`”确定。选中态不得硬编码颜色：每张页必须从既有导航对象证明一套唯一选中 fill/text color 与一套重复未选中样式，再只移动这两套原生样式；不能证明时返回 `navigation_style_ambiguous`。链接、选中态与三次 package diff 均写入 `template_apply_receipt.json`。

`numeric_claims` 示例：

```json
{"claim_id":"rc002-gap","operands":["88%","1%"],"relation":"percentage_point_difference","expected":"87 个百分点","forbidden":["87×"]}
```

## patch_spec 2.0

```json
{
  "schema_version": "2.0",
  "pptx_sha256": "...",
  "patches": [{
    "source_id": "inspection-...",
    "officecli_path": "/slide[2]/group[@id=6]/shape[@id=36]",
    "operation": "set_property",
    "property": "text",
    "value": "背景",
    "finding_id": "d6-template-navigation-...",
    "source_template_object_id": "s02:group:6:shape:36",
    "reason": "replace sample navigation label",
    "expected_fingerprint": {"drawingml_id": 36, "object_type": "shape", "text": "导航一", "text_sha256": "..."}
  }]
}
```

白名单属性为 `text/color/fill/font/size/x/y/width/height`；操作为 `set_property/remove_leaf`。路径只能落到 slide 内顶层或组内叶子对象。

## receipts

`patch_ledger.json` 保存操作、OfficeCLI receipt、package diff、未点名页文本 hash 和 master/layout/theme/notes 语义 hash。`package_cleanup_receipt.json` 保存清理前后 SHA、失效 slide relationship、被移除的非逻辑 slide parts/content-type override、保留的入边和 live-slide/protected-part/relationship-closure 守恒。`render_manifest.json` 绑定 PPTX SHA、验证档位、渲染器和 `{pdf,pages[],contact_sheet}` 每项 SHA；缺一项就不登记。`visual_review.json` 绑定 render manifest SHA。`verification_receipt.json` 绑定 PowerPoint roundtrip 或 portable 结果、对象/备注/图表/表格守恒、视觉复核或豁免和可选 LibreOffice 兼容检查，并输出一行 `tier_result`。`delivery_manifest.json` 只能绑定当前最终 SHA，portable 探针未自动执行或渲染不可用时必须动态陈述实际状态。
