---
name: double6-ppt-cli
version: 0.2.6
description: 基于 ppt-master 与 iOfficeAI/OfficeCLI 两个开源项目，生成、套用模板、读取、检查和闭环修复原生 PPTX；“可编辑”重点指保留原生对象与稳定身份，方便 Agent 多轮定位、修改和复查。适用于从 Markdown、文本、结构化材料与本地授权图片制作演示文稿，复用常规 PPTX 模板，或质检和受限修复已有 PPTX；不负责 PDF/DOCX 内容解析、联网搜图、图片式 PPT、HTML slides、TTS 或视频。
metadata:
  openclaw:
    homepage: https://github.com/double6-ai/double6-skills/tree/main/skills/double6-ppt-cli
    emoji: "📊"
    requires:
      anyBins:
        - python3
        - python
        - py
---

# Double6 PPT CLI 0.2.6

> 安装说明：从 [GitHub / skills.sh](https://github.com/double6-ai/double6-skills/tree/main/skills/double6-ppt-cli) 安装可获得完整 vendored PPT Master。ClawHub 包因网关体积限制省略了 `pptx_animation_presets.json` 与 `presetShapeDefinitions.xml`；需要原生 SVG 生成完整能力时，请改用 GitHub 安装。

## 项目定位与开源依赖

本 Skill 使用了两个开源项目，并在其上增加 Double6 的集成代码、工作流约束、状态记录和质量门：

- [ppt-master](https://github.com/hugohe3/ppt-master) `v4.8.0`（MIT）：精简内核随 Skill 一同提供，承担原生生成、模板分析与模板填充能力。
- [iOfficeAI/OfficeCLI](https://github.com/iOfficeAI/OfficeCLI) `v1.0.144`（Apache-2.0）：作为固定版本的外部运行依赖，承担 PPTX 结构读取、检查、确定性操作和 portable 验证；其二进制不包含在 Skill 包内。

本 Skill 所说的“可编辑 PPTX”，重点是方便 Agent 多轮编辑。输出保留原生 DrawingML 对象，并通过稳定对象身份、inspection map、补丁计划、前后 package diff 和验证回执，让 Agent 能在后续轮次定位同一对象、继续修改并重新检查。文件也可以在 PowerPoint 中人工编辑；当前可编辑性验收主要衡量 Agent 重复编辑的可靠性。

默认闭环是：`模板分析/原生创作 → 生成副本 → inspect → 确定性修复 → 验证（native PowerPoint 或 portable OfficeCLI） → 可选视觉复核 → finalize`。`issues=0`、OOXML validate 或预览非空都不能替代视觉结论。

## 开始前

1. 运行 `python scripts/d6ppt.py doctor --json --mode <generate|postflight|template-fill> --verify-tier <auto|native|portable>`。doctor 会按目标模式和档位报告能力；PowerPoint 缺失只会阻断 native 档。
2. OfficeCLI 必须是 `1.0.144`；其它版本 fail closed。只有用户授权安装后才运行 `bootstrap --runtime-dir <path> --yes`，禁止全局安装和自动升级。
3. Microsoft PowerPoint 与 `osascript` 是 **native 档**必需验证目标。PowerPoint 已打开其它演示文稿时返回 `powerpoint_busy`，绝不强关用户文件。
4. 本机没有 PowerPoint、`osascript` 不可用，或系统拒绝辅助访问（error `-1719`）时，`verify` 默认自动降级为 **portable 档**：OOXML + OfficeCLI 校验与改字探针，可选 LibreOffice 渲染。用 `--verify-tier native` 强制要求 PowerPoint；用 `--verify-tier portable` 跳过 PowerPoint。
5. LibreOffice 在 portable 档可作渲染事实源；在 native 档仅 `verify --compatibility libreoffice` 时做附加兼容性检查，不能替代 PowerPoint。
6. macOS 上 auto/native 运行目录必须位于用户可直接访问的项目目录，禁止放在 `/private/tmp`；显式 portable 档不调用 PowerPoint，可在隔离临时目录运行。普通用户目录并不自动向 PowerPoint 开放递归访问，PowerPoint 仍不得直接打开 run/cleanroom 文件。
7. `inspect` 不调用 Chrome/Chromium 预览，避免隔离 profile 触发钥匙串弹窗。native 档视觉事实源由 PowerPoint 导出产生；portable 档可由 LibreOffice 渲染补齐。
8. 交给 PowerPoint 打开的所有副本必须先进入真实系统账户的 `/Users/<account>/Library/Containers/com.microsoft.Powerpoint/Data/tmp/d6ppt/`。真实 home 由系统账户数据库解析，禁止依赖隔离 `$HOME` / `Path.home()`；run 与证据只通过普通文件复制读写。
9. roundtrip、另存、重开、改字、移动、保存、持久化核验与 PDF 导出合并为一次 PowerPoint 批处理会话。禁止让 PowerPoint 打开 `process/tmp/opencode/diag` 或其它诊断文件，也不得代用户点击文件访问授权。

## 三种模式

### 原生生成

`init --mode generate --source <content> --design <neutral|academic|business|training> --verify-tier <auto|native|portable> --out <run>` 会生成 `spec_lock.md`、`design_spec.md`、`svg_output/` 与语义清单示例。填完草稿并按 [authoring-contract.md](references/authoring-contract.md) 准备稳定对象身份，再依次 `compile → inspect → repair → verify → finalize`。设计包提供颜色、字号与工作结构，不会替 Agent 自动完成版式；需要复用现成版式时使用 template-fill。

### 模板填充

1. `init --mode template-fill --source <organized-content> --template <template.pptx> [--contract <content-contract.json>] --out <run>`。
2. `template-analyze --run <run>` 提取主题、母版、版式、逻辑页和递归对象画像，并生成计划草稿。
3. 用户确认要替换的图片先用 `template-asset-import --run <run> --asset <image.png|jpg> --name <safe-name>` 冻结到 run；不得让计划引用可变的外部路径。
4. 编辑计划：每个选中模板页的每个对象必须标为 `keep_design`、`replace_content`、`update_navigation`、`remove_sample`、`preserve_attribution` 或 `manual_review`。图片替换还必须在根级 `image_edits` 中写明 `plan_slide`、唯一 `source_object_id`、冻结 `asset_name`/SHA、对象 fingerprint 与 `user_confirmed: true`。带内部跳转的导航必须用根级 `navigation_targets` 把确认标签映射到逻辑输出页，并用 `navigation_source_targets` 覆盖底板、首页图标等其它实际点击区；旧模板跳转指向未选源页时必须在 check-plan 阶段报告，不能拖到 Apply。未知、未处置、无动作映射或未确认图片都会阻断。
5. `template-check-plan --run <run> --plan <plan.json>`。结构化 source 含 `slides[]` 时，内容槽默认执行严格同页来源检查：逐字或抽取可由同页源字段证明时自动通过；不能证明的扩写必须用 `content_binding.mode=user_confirmed_paraphrase` 绑定 `source_refs` 并取得用户确认。跨页借文、无来源扩写和伪造 page number 阻断 Apply。报告无 error 后仍必须把具体计划交给用户确认；只有 `status=confirmed` 才能 `template-apply`。
6. Apply 使用 vendored PPT Master Fill Native，不把模板转成 SVG；图片只重定向目标 slide 上已确认 picture 的私有关系，不改模板、母版、布局、几何、裁切或其它共享图片。确认导航在一次性 vendor 输入副本中移除旧跳转，生成后按 `navigation_targets` 重建到逻辑输出页；当前章节取不晚于当前页的最近章节起始页。只有每页能从原模板证明唯一的“1 个选中样式 + 重复未选中样式”时，才把原模板的底板与文字样式移到当前章节；样式不唯一则 fail closed。原模板不改。输出画像和回执保留模板/内容/输出/图片 SHA、来源对象映射、导航链接、选中态与 package diff。
7. Apply 后先运行 `package-clean --run <run>`，再 `inspect`。它只移除未被 presentation/custom show/可见 slide 引用的非逻辑 slide parts、相应 content-type override，以及未被 XML 使用的 slide-jump relationship；不可达 slide 之间即使形成循环也可整体清理。任何仍有外部入边的非逻辑 slide 保留并转人工复核，media、master、layout、theme、notes 与 live slide XML 永不由该命令删除或改写。

### 已有 PPTX 质检与修复

`init --mode postflight --source <deck.pptx> [--template <template.pptx>] [--contract <content-contract.json>] --out <run>`。`inspect` 会生成稳定 inspection map，并报告 OfficeCLI 问题、小字、空白与结构漂移。业务专属的残留文字、数字显示、模板角色和非逻辑页示例标记必须由 content contract 声明，通用检查器不内置某个案例的词、导航标签或数字。`patch-plan` 只纳入确定性叶子操作；图片必须用 `--confirm-finding <id>` 单独确认。然后运行 `patch` 并重新 `inspect`。

## 视觉策略

- 默认需要视觉检查。声明可用：`visual-policy --capability available --decision perform`；PowerPoint（native）或 LibreOffice（portable）导出逐页图片后，由视觉模型检查并用 `visual-review` 写 SHA 绑定回执。`render_manifest.json` 同时绑定当前 PPTX、档位、渲染器、PDF、逐页 PNG 与 contact sheet；任一文件变化都会使视觉回执失效。
- 能力未知或不可用时返回 `visual_review_decision_required`，先询问是否切换视觉模型。
- 用户拒绝、没有视觉模型或明确跳过时，运行 `visual-policy --capability <unknown|unavailable> --decision waive --reason <user_declined_switch|no_visual_model|user_requested_skip> --user-ack`。
- 有效豁免不阻断交付，但最终只能是 `pass_with_warnings`，并明确写“未进行模型视觉质量检查”。PPTX SHA 改变后旧复核和旧豁免失效。没有裸 `--skip`。
- portable 档未渲染出逐页页面时，必须用户视觉豁免或切换到可渲染环境，不得假装视觉已通过。

## 安全边界

- 原文件永不覆盖；所有修改只写 run 副本并保留前后 package diff。
- 自动修复只限唯一稳定叶子路径、当前 SHA、DrawingML ID/type、内容指纹、finding、来源对象与理由全部匹配的 `set_property` / `remove_leaf`。
- 业务语义文本不会仅因“像公式”成为可删除模板残留；只有 content contract 或模板对象身份与媒体 SHA 明确证明后，才可进入对应处置。
- 不自动删除母版、版式、组合对象、共享关系或语义图片；不做模糊删除、大面积重排、审美重做和跨页扩散。
- `package-clean` 不是通用 OOXML 垃圾回收器：只处理已证明未使用的 slide 关系和不可达非逻辑 slide；仍被 live XML、自定义放映或其它保留 part 引用的对象 fail closed。
- 补丁后必须证明未点名页文本、母版、版式、主题和备注未变。失败即 `patch_scope_violation`。
- schema 1.0 仅做内存兼容读取，禁止回写历史证据。

详细合同见 [delivery-gates.md](references/delivery-gates.md)、[repair-policy.md](references/repair-policy.md)、[machine-contracts.md](references/machine-contracts.md)、[licenses-and-upstreams.md](references/licenses-and-upstreams.md) 与 [test-report-and-verification-tiers.md](references/test-report-and-verification-tiers.md)（native/portable 双档说明与完整测试报告）。
