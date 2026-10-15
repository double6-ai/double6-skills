# double6-ppt-cli 变更记录

## 0.4.0（2026-10-15）

正式版，合并了下面 0.4.0-exp.1 至 exp.3 的全部开发内容：

- **PPT Master v4.8.0 → v6.7.0**（commit `b4efe3d`，官方 asset SHA `40424d97…`）：随 Skill 提供 173 个文件的精简内核，版本由 BOM 和 UPSTREAM_LOCK 锁定，不再需要设置 `D6PPT_PM6_ROOT`。
- **generate** 改走 PPT Master v6.7.0 的原生生成路径。
- **template-fill** 改用 v6.7.0 roundtrip 后端（`pm6_template`）：
  - 形状 ID、占位符继承、段落属性和项目符号都保持原生；
  - 沿用 v4.8 的分析/检查/计划契约；
  - 支持讲者备注、切换效果，以及段落内的混合格式。
- **文本适配按 PowerPoint 实测校准**：
  - 缩字直接写进 run 的字号，不依赖 normAutofit fontScale；
  - 按角色设缩字下限；
  - 内容明显超出可用高度，或会压到下方卡片、指标框时，计划检查报 ERROR；
  - 估算与 Win11 + PowerPoint 16 的实测误差在 0.1pt 以内。
- 新增 Windows/macOS 一键 PowerPoint 验证脚本（`scripts/verify/`），以及 11 个真实模板、共 14 组的回归测试。
- OfficeCLI 固定版本仍为 `1.0.157`。

### 0.4.0-exp.3（开发过程记录）

- 根据 Win11 + PowerPoint 16 实测修正文本适配：
  - 缩字一律显式写入 run 的 `sz`，`normAutofit` 不再写 fontScale/lnSpcReduction（实测 PowerPoint 重算时会把 fontScale 重置为 100%）；
  - 缩字下限：比例 0.7 / 0.85，标题不小于 20pt，正文不小于 12pt；
  - 多段文字在原字号下超过可用高度 1.6 倍，或到下限仍放不下，计划检查报 ERROR；
  - 文本框下方的卡片、指标框等形状会缩小可用高度（避免文字压到这些形状上）；
  - 度量引擎重新校准：行高 1.2 倍字号，第一段不计 spcBef，安全余量为高度 ×1.06、宽度 ×0.97。11 个实测文本框的估算与 PowerPoint 误差在 0.1pt 以内（之前在需要 552pt 的地方只估了 340pt）。
- 验证脚本：增加「文字压到其他形状」检测；PowerPoint 重算后字号或 fontScale 与我方不一致即判失败；用例增至 5 个并写明预期结果；有失败时退出码为 1。
- 新增回归测试 `test_powerpoint_calibration.py`，使用 PowerPoint 实测数据（`tests/fixtures/powerpoint_win11/`）。

### 0.4.0-exp.2（开发过程记录）

- **template-fill 迁移到 PPT Master v6.7.0 roundtrip**（`scripts/double6_ppt_cli/pm6_template/`）：
  - 导入 → 对象原生回传（cloned_passthrough）→ 导出后按 cNvPr id 原生改写 txBody；形状 ID、占位符继承、段落属性、项目符号都保持原生。
  - 用真实字体度量做中英文换行（Linux 用 fontconfig；Windows/macOS 扫描系统字体目录），结果映射到原生 normAutofit/spAutoFit/缩字；估算会溢出时 check 阶段报 ERROR。
  - 分析/计划草稿/检查沿用 v4.8 契约：Double6 维护的 v4.8 只读模块移植（`pm6_template/fillnative/`，MIT），包括 SmartArt 读取、图表编辑能力、合并单元格拓扑、选择器（slot_id/shape_id/shape_name）、`paragraphs`、复用集中度告警。
  - 讲者备注（`notes`：替换 / `"keep"` / 省略时删除模板示例备注）和切换效果（`transition`：保留 / 替换 / `none`）。
  - 同一段落内混合格式：未改动的段落原样保留全部 run、换行和字段；改动段落保留公共前后缀所在 run 的样式。
- vendor 新增上游 `pptx_to_svg.py`（173 文件，逐字节一致，BOM 已更新），版本由 BOM 锁定；不再需要 `D6PPT_PM6_ROOT`（仅作开发覆盖）。
- 修复：`_normalize_txbody_paragraph_order` 把交错的 `a:r`/`a:br` 排序打乱，并且会改写母版/版式（T1 版式 26/32 字节漂移的根因）。现在只调整 pPr/endParaRPr 的位置，也只处理幻灯片部件。
- doctor：template-fill 能力改为检查 roundtrip 入口和 `pm6_template` 包。
- 新增 PowerPoint 实机一键验证脚本 `scripts/verify/`（Windows COM / macOS AppleScript）。

### 0.4.0-exp.1（开发过程记录）

- **PPT Master v4.8.0 → v6.7.0**（commit `b4efe3d`，官方 asset SHA `40424d97…`），172 文件精简内核，BOM 已重建。仅适用于 generate。
- template-fill 暂未迁移：调用时报 `template_fill_not_migrated`；`doctor --mode template-fill` 结果为 fail。
- 新增 `native_markers.py`：
  - 默认按 JSON-first 处理（bounds 自动写入 metadata）。
  - 旧表格自动升级为 semantic-table.v2，并保持 v4.8 配色。
  - receipt 中记录为 `normalize_native_markers`。
- design_spec 模板新增 `- Relationships:` 行；compile 会检查占位符，并把 v6 质量报告中的错误展开到 `details.errors`。
- 修复：semantic manifest 无法匹配图片（`p:pic`），新增 role `image`。
- 已知行为差异：
  - 水平条形图顺序反转（可用 `axes.category.reverse:false` 恢复）。
  - compile 约慢 1 秒。
  - waterfall 在 LibreOffice 下不显示。

## 0.3.0

上游更新 + 全新 Linux 环境（portable 档）端到端实测修复。

- **OfficeCLI pin 1.0.144 → 1.0.157**（commit `b65272a`）。最低兼容版本仍为 1.0.144（非 pin 版本只报 warn）。LICENSE/NOTICE 不变。
- **PPT Master 维持 v4.8.0**。v6.7.0 已删除 Template Fill Native，迁移需单独立项。另记录上游历史重写（标签现指向 `5da13a0`，内容一致）。
- 修复：
  - doctor/bootstrap 不再因缺少 Pillow 崩溃。
  - `d6ppt.py` 缺依赖时自动 re-exec 到运行时 venv。
  - 全局 `--runtime-dir` 不再被子命令覆盖为 None；bootstrap 可省略 `--runtime-dir`。
  - 单行 tspan 的 shape id 丢失问题由 adapter 修复。
  - `wrap="none"` 文本框加宽，修复 LibreOffice 下 CJK 文字误折行。
  - 尚无 PPTX 时 verify 给出明确错误 `current_pptx_missing`，不再 traceback。
  - visual-policy 的 `perform` 决策给出准确的 next_steps。
  - scaffold 错误列出 `remaining_fields`。
  - PPT Master 转换警告（如图例被省略）写入 `evidence/compiler_warnings.json`，并在 inspect 中报出。
  - 模板中的无文字装饰形状默认归类为 `keep_design`。
  - postflight 按 descr 中的 role 判定字号阈值，并检测 run 级小字号。
- 新增 `test_e2e_regressions.py`；authoring-contract 增加实测要点。

## 0.2.13

- **P0 bootstrap 自举**：`cli.py` 改为子命令延迟导入；全新环境无需 lxml 即可 `bootstrap`/`doctor`。
- **Windows fonts**：doctor 扫描 `%WINDIR%\Fonts` 与 LocalAppData 字体目录。
- **`render-import` 子命令**：登记外部渲染（PowerPoint COM 等）PDF/逐页图/联系表，绑定 SHA 后走 visual 闭环。
- **source_files[].sha256 自动填充**：缺失时按当前 SVG 计算并回写；不匹配仍 fail。
- **compile 错误 details** 提升 project-level issues，避免只报 `svg_quality_failed`。
- 文档：`body` 必填、px↔pt=0.75 对照表、render-import 用法。

## 0.2.12


- **Windows 兼容（来自真实 Windows 测试反馈）**：
  - `powerpoint.py` 不再顶层硬依赖 `pwd`；Windows 可 import 全 CLI。
  - `bootstrap` 使用 `Scripts/python.exe`。
  - vendor BOM 校验容忍 CRLF/LF；新增 `.gitattributes` 保护 vendor 树。
  - OfficeCLI 优先 `officecli.cmd`；`.js` 入口前置 `node`；控制台输出 bytes + 多编码回退（GBK/UTF-8）。
  - run 清单路径统一 `rel_posix`（正斜杠）。
  - `doctor` 区分「Windows 不支持 native 自动化」与「未安装 PowerPoint」，并探测 OfficeCLI/node 可启动性。
- 文档：tspan x 约束、字号阶梯、generate 版式边界。

## 0.2.11


- 澄清平台边界：安装与 portable 档不要求 macOS；仅 native PowerPoint 验证依赖 macOS + Microsoft PowerPoint + osascript。
- README / SKILL.md / doctor 文案避免用户误判「必须苹果系统」。

## 0.2.10


- 同步发布 0.2.9 依赖策略到 GitHub / ClawHub（ClawHub 仅含 .clawhubignore 后的必要文件）。

## 0.2.9


- OfficeCLI 版本策略放宽：bootstrap **只下载 pin `1.0.144`**；运行时接受 pin 与更新 1.x（`warn` + 风险提示 + 可选 bootstrap 对齐），不再因「非精确等于 1.0.144」一刀切 fail closed。major 错误或过旧才 fail。
- runtime lock 不再包含 skill 版本，避免 skill 升级导致 OfficeCLI 缓存目录漂移；doctor 会回退扫描 `~/.cache/double6-ppt-cli/*`。
- ppt-master 继续以 vendored BOM 校验为准（不跟随上游自动升级）。
- 新增 `classify_officecli_version` 与回归测试。

## 0.2.8


- LibreOffice 兼容门：text/notes/visual/edit-probe 通过而 object identity 漂移时改为 `pass_with_warnings`（LO Save As 常见重编号），不再硬失败。
- 明确 WPS 边界：非验证档；`wpscli ppt2pdf` 可作诊断 PDF，`ppt2photo` 可能需会员；禁止声称 WPS 已验证。
- 记录 OfficeCLI 必须锁定 `1.0.144`（自动升级会导致 doctor fail closed）。

## 0.2.7


- 修复 Fill Native 改字后 `a:p` 子节点顺序错误（`endParaRPr` 出现在 `a:r` 之前）导致 OfficeCLI `validate` 失败：apply 后在 Double6 侧按 ECMA-376 顺序规范化 `a:p` 子节点，不改 vendor 树。
- 互联网模板压测（python-pptx 官方测试语料 3 个 PPTX）：`test.pptx` / `no-core-props.pptx` / `test_slides.pptx`（含图片/表格/group）template-fill 全闭环通过；`test_slides` 图片替换 2 处成功。
- 新增回归：`test_txbody_order.py`（共 62 项）。

## 0.2.6


- `semantic` 对 `preferred_structure: native_chart|native_table` 增加 name 回退：`match.drawingml_id` 未命中时，按 `source_selector.id` 匹配 `cNvPr@name`（vendor 原生图表常不保留 `data-pptx-shape-id`）。
- 原生 chart/table 映射失败时错误信息包含 marker/JSON metadata 提示。
- `authoring-contract.md` 补充 `data-pptx-replace-with="chart|table"` + `<metadata type="application/json">` 合同与 fallback 几何要求。
- 新增回归：`test_native_chart_semantic.py`（共 61 项）。

## 0.2.5

- `template-apply` 在 vendor 产出后、导航状态/图片重定向失败时会删除不完整的 `template-filled.pptx`，避免同一 run 被 `artifact_exists` 永久阻塞。
- 新增回归测试 `test_apply_cleanup.py`。
- 压测记录：TOC 侧栏模板可完成图片替换（SHA 锁定）与 9 条内部跳转重建；选中态样式要求每页恰好 1 selected + 重复 unselected。

## 0.2.4

- 修复 `inspect` 在存在 object map 时触发的 `UnboundLocalError: read_json`（局部 import 遮蔽模块导入）。
- 修复 portable `verify` 每次强制重渲染导致视觉回执 SHA 失效、无法 finalize 的死锁；现在优先复用当前 PPTX + portable 档位下完整的 render manifest。
- `design_spec.md` 脚手架补齐 PPT Master 质量门要求的 `## IX. Content Outline` 与 `Audience move` 占位，避免 init 后 compile 必炸。
- `authoring-contract.md` 补充：根级 `<g>` 必须声明 `data-pptx-bounds`；可 flatten 的内容组必须是 SVG 根级直接子节点；段落多行用 `tspan`。
- 新增回归测试：`test_inspector_bindings.py`、`test_portable_render_reuse.py`（共 58 项）。

## 0.2.3

- `doctor` 按 mode 与 `auto|native|portable` 档位报告能力；PowerPoint 与 `osascript` 只对 native 必需，vendor BOM 会逐文件校验 SHA 并识别 ClawHub 省略项。
- `init --mode generate --design <profile>` 生成可填写的 `spec_lock.md`、`design_spec.md`、SVG 目录和语义清单示例；compile 对未完成草稿给出下一步。
- 支持 vendored PPT Master 的 `data-pptx-shape-id` / `match.drawingml_id` 稳定身份，歧义错误列出来源文件与候选对象。
- native/portable 统一写 SHA 绑定的 `render_manifest.json`，视觉回执再绑定该清单；显式 portable 不会被旧 native 回执覆盖。
- portable 的改字探针、渲染和最终声明按实际状态生成，并增加一行 `tier_result`。
- 删除通用检查器与模板画像中的案例词、导航和数字硬编码，改由 content contract 声明；增加 `footnote` / `page_mark` 角色字号阈值。
- 回归测试扩至 56 项。

## 0.2.2

- `verify` 增加双档：`--verify-tier auto|native|portable`。本机无 PowerPoint、`osascript` 不可用或系统拒绝辅助访问时，auto 自动降级 portable（OfficeCLI 持久化改字探针 + 可选 LibreOffice 渲染）。
- portable 先产出 LibreOffice 逐页渲染与 contact sheet，再解析视觉门；`visual-review` 可绑定 portable 页面。
- portable 交付状态至少 `pass_with_warnings`，声明明确未执行 PowerPoint 原生 roundtrip。
- `finalize` 接受 `powerpoint_status=skipped_portable_tier`。
- 文档补全 generate 所需 `spec_lock.md`（含 `pptx_structure.mode: flat`）。
- 新增 `references/test-report-and-verification-tiers.md`：双档验证说明 + 隔离环境完整测试报告与优化清单。

## 0.2.1

- 首次以 v0.2.1 精简包内容发布到 GitHub `double6-ai/double6-skills`，并同步 skills.sh 与 ClawHub。
- 保留模板填充同页槽位来源门、受限 `package-clean`、PowerPoint 优先验证与 vendored PPT Master v4.8.0。
- 公开包不含本地评测报告、运行产物、`__pycache__` 与治理元数据；OfficeCLI 仍作为外部固定依赖由用户自行安装。
- ClawHub 包因网关 multipart 体积限制省略两个最大 vendor 数据文件；完整包以 GitHub / skills.sh 为准。
