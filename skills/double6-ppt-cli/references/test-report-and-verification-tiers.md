# 验证档位与完整测试报告

本文档沉淀 `double6-ppt-cli` 0.2.2 的测试反馈，以及 0.2.3 对这些反馈的实现：

1. **验证档位（native / portable）**：PowerPoint 从硬性必需改为可分档可选；
2. **隔离环境完整测试报告**：原生 generate 全闭环实测结论，以及公开可用性优化清单。

相关契约仍以 [delivery-gates.md](delivery-gates.md)、[authoring-contract.md](authoring-contract.md)、[machine-contracts.md](machine-contracts.md) 为准；本文负责产品能力说明与维护决策记录。

---

## 1. 验证档位：PowerPoint 可选（0.2.2 起）

### 1.1 为什么要双档

0.2.1 及更早版本把 Microsoft PowerPoint + `osascript` 写成默认必需验证目标。结果是：

- 无 PowerPoint / WPS 的机器无法 `finalize`；
- 本机已装 PowerPoint，但终端未获「辅助访问」时会得到 `-1719`，流程 fail closed；
- LibreOffice / WPS 在合同里始终不能替代 PowerPoint，作者只能停在 `verified_with_warnings` 之前。

0.2.2 起，`verify` 支持双档：

| 档位 | 命令 | 何时使用 | 交付状态上限 |
|---|---|---|---|
| **native** | `--verify-tier native` 或 auto 且环境可用 | 本机 PowerPoint + `osascript` 可完成原生自动化 | `pass` / `local_delivered`（无其它 warning 时） |
| **portable** | `--verify-tier portable` 或 auto 自动降级 | 无 PowerPoint / 无 `osascript` / 辅助访问被拒，且用户未强制 native | **至少** `pass_with_warnings` |

默认：

```bash
python scripts/d6ppt.py verify --run <run> --verify-tier auto
```

- auto：优先 native；PowerPoint 不可用或可证明的自动化失败（如缺少 app、缺 `osascript`、`powerpoint_accessibility_denied` / error `-1719`）时降级 portable。
- 强制 native：环境不可用则 fail closed，**不会**偷偷改 portable。
- 强制 portable：即使已安装 PowerPoint 也跳过原生门禁（用于受限 CI / 无 GUI 环境）。

### 1.2 各档门禁对比

| Gate | native | portable |
|---|---|---|
| OOXML 完整性 + OfficeCLI `validate` | 必需 | 必需 |
| 当前 SHA 重新 `inspect`；blocking findings = 0 | 必需 | 必需 |
| PowerPoint Save As / 重开 / 改字 / 移动 / 持久化 / 导出 | **必需** | **不做**（`powerpoint_roundtrip=skipped_portable_tier`） |
| 全页渲染 + contact sheet | PowerPoint 导出 | 有 LibreOffice + `pdftoppm` 时用 LibreOffice；否则 `not_available` |
| OfficeCLI 持久化改字/移动探针 | 由 PowerPoint 批处理完成 | **必需**（独立 edit probe） |
| 视觉门 | PowerPoint 渲染页 + 模型复核或用户豁免 | LibreOffice 渲染页 + 模型复核或用户豁免 |
| LibreOffice 兼容 | 仅 `--compatibility libreoffice` 附加 | 可作渲染事实源；不等于 native |

### 1.3 交付声明（必须诚实）

portable 成功交付时：

- `verification_tier = portable`
- `powerpoint_status = skipped_portable_tier`
- 状态通常为 `pass_with_warnings` / `delivered_with_warnings`
- `compatibility_statement` 必须写明：未在本机 Microsoft PowerPoint 完成原生 roundtrip；已完成 OOXML + OfficeCLI 校验与改字探针。

**不允许**把 portable 写成「已通过 PowerPoint 验证」。

### 1.4 视觉与 portable 渲染

- portable 在解析视觉门**之前**先产出 `evidence/portable_render/`（含 `slide-*.png`、`pdf/*.pdf`）与 `review/contact_sheet-portable.png`。
- native 使用 `review/contact_sheet-native.png`。两档都必须写完整 `evidence/render_manifest.json`；清单把当前 PPTX、档位、渲染器、PDF、页面和 contact sheet 的 SHA 绑定在一起。
- `visual-review` 可绑定 PowerPoint 页或 portable（LibreOffice）页；`fact_source` 分别为 `powerpoint` / `libreoffice_portable`。
- 没有模型视觉能力时，仍可按原合同写 `visual_review_waiver.json`（`--user-ack`）；结果只能是 `skipped_with_user_ack`。

### 1.5 LibreOffice / WPS

- **LibreOffice**：native 档仍非默认 gate；portable 档可作渲染事实源。
- **WPS**：当前合同**未接入**，不得声称「WPS 已验证」。

### 1.6 实测结论（0.2.2 隔离环境）

在修复「先出 portable 渲染页再解析视觉门」「LibreOffice PDF 子目录查找」之后：

| 路径 | 结果 |
|---|---|
| 单元测试 | 52 passed |
| generate `compile → inspect` | 通过 |
| `verify --verify-tier portable` + 视觉豁免 | `pass_with_warnings`，可 `finalize` |
| portable 渲染 + `visual-review` | `accepted`（`fact_source=libreoffice_portable`） |
| `verify --verify-tier native` / `auto` | 本机 PowerPoint 权限可用时，原生 roundtrip **通过** |
| postflight（无 object map） | edit probe = `not_automated`（warn），属预期 |

---

## 2. 完整测试报告：原生 generate 路线

### 2.1 测试范围与素材

- **模式**：`generate`（**不使用** template-fill；不提供模板 pptx）。
- **素材**：本地下载目录中的论文 PDF 抽取文本（先 LitLLMs，后 ACL 2024 *Can LLM Summarizers Adapt…*）。
- **环境**：独立测试目录（与主仓库 worktree 分离）。
- **闭环**：`init → authoring → compile → inspect → verify → visual-review → finalize`。

### 2.2 两轮设计对比

| 轮次 | 设计投入 | 结果 |
|---|---|---|
| 第一轮（流水线冒烟） | 极简平铺 SVG（标题+几行字+色块卡） | 能 compile/verify/finalize，但观感接近线框稿 |
| 第二轮（完整测试） | 按学术组会 design/spec_lock：页眉页脚、双色顶栏、卡片色带、CORE MESSAGE、结论条 | 6 页可交付；PowerPoint native 验证 + 视觉通过 |

**结论**：compile **不会**自动美化版式。原生 generate 的视觉质量几乎完全取决于 Agent 按 PPT Master 设计合同写的 SVG；vendor 内模板/可视化目录在 generate 路径**不会自动套用**。

### 2.3 第二轮交付摘要

- 产物：约 6 页原生可编辑 PPTX，OfficeCLI outline/validate 正常。
- `verify --verify-tier auto`：本机可走 **native PowerPoint**。
- `visual-review`：PowerPoint 页 accepted。
- `finalize`：`delivered_with_warnings`。
- inspect：0 blocking；大量 `d6-small-font` warning（页脚/眉题 12–14px 在 PowerPoint 中落成约 9–11pt）。

### 2.4 Authoring 现场问题（Agent 必读）

以下问题在完整测试中真实触发，对应 [authoring-contract.md](authoring-contract.md)：

1. **缺少 `spec_lock.md` / `pptx_structure.mode`**  
   SVG quality gate 直接 `svg_quality_failed`（legacy implicit baseline 已禁止）。

2. **字号 recurrence**  
   未在 spec_lock 声明的字号重复超过 2 次会 fail closed（例如结果页 28px 数字需 `stat: 28`）。

3. **semantic `match.text` 必须逐字相等**  
   引号、空格、全角空格、句子截取不一致 → `ambiguous_object_mapping` / `candidates=0`。

4. **嵌套 group 违反 top-level 契约**  
   postflight-sensitive 文本若在嵌套 `<g>` 内，semantic 阶段报 `structure_contract_violation`；需解包或改 `preferred_structure`。

5. **PowerPoint / 视觉门顺序**  
   0.2.2 早期 portable 在视觉门之前若不先渲染，会以 `visual_review_decision_required` 中断且无页面可审；已改为 portable 先渲染再解析视觉门。

---

## 3. 优化清单（建议优先级）

### P0 — 降低 Agent 与用户失败率

| 项 | 现状 | 建议 |
|---|---|---|
| generate 骨架 | 无 `spec_lock` 必炸 | `init --mode generate` 自带 `spec_lock.md` 草稿（`pptx_structure.mode: flat` + 默认学术字号） |
| semantic 匹配 | 仅 exact text（或 group_contains） | 优先 `data-d6-source-id` / SVG `id`；失败信息打印候选文本与文件路径 |
| doctor / verify 人话 | 权限、版本错误偏底层 | 对 `powerpoint_missing`、`powerpoint_accessibility_denied`、OfficeCLI 版本给出可执行修复步骤 |
| 完整包 vs ClawHub 残缺 | 需读文档才知道 | `SKILL.md` / `doctor` 明确：完整原生生成用 GitHub/skills.sh；ClawHub 省略大 vendor 数据文件 |

### P1 — 设计与 inspect 一致性

| 项 | 现状 | 建议 |
|---|---|---|
| small-font warning 噪声 | 页脚/眉题合法小字号被大量 warning | spec_lock 增加 `role: footnote/page_marks` 豁免；或统一 px→pt 并在文档写清换算 |
| 渲染产物清单 | contact sheet 曾出现「manifest 记了文件却不存在」 | native/portable 统一 `{pdf, pages[], contact_sheet}` 三件套：要么齐全要么不记路径 |
| generate 设计资产 | vendor 模板/目录不自动用 | `init --mode generate --design academic` 之类 design pack；文档写明「要现成版式走 template-fill」 |

### P2 — 能力面扩展

| 项 | 现状 | 建议 |
|---|---|---|
| WPS | 未接入 | 若要支持，单独能力探测 + 档位，勿与 LibreOffice 混称 |
| postflight 身份 | 无 object map 则 edit probe `not_automated` | 增强 inspection map 身份策略，或 postflight 后自动尝试 patch-plan |
| Portable 置信度沟通 | 有声明但偏长 | delivery 打印一行：`tier=portable · no PowerPoint roundtrip · visual=…` |

---

## 4. 与公开发布的关系

- **GitHub / skills.sh**：完整 vendored PPT Master，适合原生 generate 与 portable/native 验证。
- **ClawHub**：为网关体积限制省略最大 vendor 数据文件；**完整原生生成请勿依赖 Cl­awHub 包**。
- OfficeCLI 固定 `1.0.144`，仍为外部依赖；本 skill 不随包分发二进制。
- PowerPoint「可选」不等于「推荐跳过」：有条件时应优先 native，portable 是诚实降级。

## 4.1 0.2.3 落地结果

- `doctor --mode ... --verify-tier ...` 按档位判定能力，并逐文件校验 vendor BOM；PowerPoint 缺失只阻断 native。
- `init --mode generate --design ...` 生成 spec/design 草稿、SVG 目录和语义清单示例。
- SVG 可用 `data-pptx-shape-id`，semantic manifest 用 `match.drawingml_id`；匹配失败会返回来源文件和页内候选。
- `footnote` / `page_mark` 使用独立字号阈值；业务规则、样例标记和模板角色从 content contract 读取。
- 显式 portable 优先于旧 native 回执；portable 探针和渲染声明按实际结果生成；verification 与 delivery 都输出 `tier_result`。
- PowerPoint/LibreOffice 渲染统一使用 SHA 绑定的 render manifest，视觉回执不能混用另一档或旧图。

---

## 5. 版本与变更

| 版本 | 内容 |
|---|---|
| 0.2.1 | 公开精简包首发；PowerPoint 仍为默认必需 |
| 0.2.2 | `verify --verify-tier auto\|native\|portable`；portable OfficeCLI/LO 路径；visual 可绑 portable 页；finalize 接受 `skipped_portable_tier`；文档补齐 `spec_lock` 要求；修正 portable 渲染顺序与 PDF 路径 |
| 0.2.3 | 分档 doctor、generate/design 骨架、稳定 DrawingML ID、角色字号阈值、声明式案例规则、完整 vendor 校验、render manifest 与动态 portable 声明 |

本轮代码级变更范围以本报告和公开仓库历史为准。

---

## 6. 维护者检查清单（下次发版前）

- [x] `python -m unittest discover -s scripts/tests` 全绿（58 项，含 `test_verify_tier.py` / `test_inspector_bindings.py` / `test_portable_render_reuse.py`）
- [x] 无 PowerPoint / 辅助访问环境下的 portable 路径可 `finalize`，并保留 warning
- [x] auto/native 选择、强制 portable 优先级和 native fail-closed 有回归测试
- [x] generate 初始化会创建骨架，未确认草稿的错误信息可直接照做
- [x] `visual-review` 通过同一 render manifest 覆盖 PowerPoint 与 LibreOffice 事实源
- [x] README / SKILL.md / ClawHub 安装边界一致
- [x] 0.2.4：inspect 局部 import 与 portable 重渲染死锁已修复，并有回归测试

## 7. 0.2.4 隔离环境三模式实测

| 模式 | 主题/素材 | 档位 | 结果 |
|---|---|---|---|
| generate | 企业 AI 代码评审落地策略（business design） | native PowerPoint | compile → inspect 0 blocking → visual accepted_with_warnings → `delivered_with_warnings` |
| template-fill | 3 页极简模板 + 入职 30-60-90 结构化 JSON | portable | analyze → check-plan → apply → portable visual → `delivered_with_warnings` |
| postflight | 对 generate 交付物做质检 | portable | inspect 0 blocking → portable visual → `delivered_with_warnings`；无确定性叶子修复时 `no_safe_patch` 属预期 |

现场踩坑（已修复或写入 authoring contract）：

1. 脚手架 `design_spec.md` 缺 `## IX. Content Outline` 会直接 quality fail。
2. 嵌套 wrapper group 不能作为 flatten 选择器目标。
3. inspect `read_json` 局部 import 导致崩溃。
4. portable verify 重渲染使视觉回执失效，形成无法 finalize 的死锁。

## 8. 0.2.4 第二轮压测（无需改代码）

| 轮次 | 模式 | 素材 | 结果 |
|---|---|---|---|
| R5 | generate / training | 非技术同事 AI 素养工作坊 | 一次 compile 通过；native PowerPoint visual accepted；`delivered_with_warnings` |
| R6 | template-fill | 腾讯研究院 10 页研究简报模板（213 objects）+ 结构化 JSON | analyze→check-plan（0 error）→apply→inspect 0 blocking→portable visual→`delivered_with_warnings` |

结论：0.2.4 修复后，真实复杂模板与 training design 均可稳定走通；剩余 warning 以模板自带小字号与 text_capacity 为主。

## 9. 0.2.5 图片替换 + 导航压测

| 能力 | 结果 |
|---|---|
| TOC 侧栏模板（每页 3 个填充导航钮） | analyze/check-plan 通过 |
| 图片替换（SHA 锁定资产） | apply 成功；新媒体 part + 关系重定向 |
| 内部跳转重建 | 9 条 link + 9 条 selected/unselected 状态 |
| package-clean | 删除 3 个孤儿 slide part 与 9 条未引用跳转关系 |
| apply 失败清理 | 新增：vendor 后失败会删除不完整输出，允许同 run 重试 |

现场约束（Agent 必读）：

1. 导航对象必须是带 **显式 solidFill** 的形状；纯文本框无 fill 会 `navigation_style_ambiguous`。
2. 每个逻辑页必须能证明 **恰好 1 个 selected 样式 + 重复 unselected 样式**；侧栏 TOC 是推荐形态。
3. `navigation_targets` 的 label 必须等于 `update_navigation` 后的新文案。
4. 每个带旧 `hlinksldjump` 的对象都要有 `navigation_source_targets` 覆盖其源模板目标页。

## 10. 0.2.5 postflight 确定性 patch 压测

| 步骤 | 结果 |
|---|---|
| 故意埋错 | `学完你会什么？`、`半天五个模块` |
| content contract `text_rules` | 2 条 deterministic `set_property` + replacement |
| inspect | 2 blocking；`suggested_operation=set_property` 且带 `suggested_value` |
| patch-plan | 2 patches；small-font 等 28 项跳过（manual_or_non_leaf） |
| patch | 2 ops 成功；仅 slide2/3 变；master/layout/theme 未变；OfficeCLI validate pass |
| re-inspect | **0 blocking**；文案已恢复 |

结论：有 object map / 叶子路径 + 合同声明 replacement 时，确定性文本修复闭环可用。无合同时 `no_safe_patch` 仍是正确 fail-closed。

## 11. 十维压测（0.2.5）

| # | 案例 | 维度 | 结果 |
|---|---|---|---|
| c01 | academic design generate | 设计档 | init/scaffold/compile 通过 |
| c02 | neutral draft | 负向 | `authoring_incomplete`，下一步可执行 |
| c03 | 伪 chart 结构 | 负向 | fail-closed（selector/质量门） |
| c04 | numeric_claims | 合同 | 命中 operand/expected findings |
| c05 | SAMPLE_TOKEN remove_leaf | 确定性删除 | patch 后 reinspect 干净 |
| c06 | 篡改冻结资产 | 负向 | check-plan 阻断（含 plan 级 error） |
| c07 | 导航无选中态样式 | 负向 | `navigation_style_ambiguous` 且不残留输出 |
| c08 | spec 仍为 draft | 负向 | `authoring_scaffold_incomplete` |
| c09 | expected_slide_count | 合同 | 5 vs 3 finding |
| c10 | portable 全闭环 | 交付 | visual 门顺序正确后 `delivered_with_warnings` |

注意：c10 的视觉门必须 **先 verify 产出 render → visual-policy/review → 再 verify**；先 review 会因无 render 清单失败。

