# Delivery gates v0.2

## 验证档位

`verify` 默认 `--verify-tier auto`：

1. **native（默认优先）**：本机 Microsoft PowerPoint 与 `osascript` 可用时，执行原生 roundtrip、改字/移动持久化与 PowerPoint 渲染。
2. **portable（降级）**：PowerPoint 缺失、`osascript` 不可用，或自动化被系统辅助访问权限拒绝（如 error `-1719`）时，且用户未强制 `--verify-tier native`，自动改走 portable 档。
3. **强制档位**：`--verify-tier native` 在 PowerPoint 不可用时 fail closed；`--verify-tier portable` 跳过 PowerPoint，即使已安装。

portable 档仍必须通过：OOXML 完整性、OfficeCLI `validate`、inspect findings 清零、OfficeCLI 持久化改字探针、视觉门（有 LibreOffice+pdftoppm 时产出逐页渲染与 contact sheet；否则需用户视觉豁免）。portable 交付状态至少为 `pass_with_warnings`，并写明未执行 PowerPoint 原生门禁。

## 默认必需 gate

1. OOXML ZIP/XML 完整，核心 part 存在，OfficeCLI `validate` 通过。
2. 当前 SHA 已重新 `inspect`；所有 error findings 关闭，warning 进入交付声明。
3. **native 档**：Microsoft PowerPoint 完成 Save As、关闭、重开、改字、移动对象、保存、再次打开与持久化核验。**portable 档**：OfficeCLI 完成持久化改字/移动探针；不声称 PowerPoint 原生 roundtrip。
4. **native 档**：PowerPoint 导出 PDF/逐页 PNG/contact sheet；页数、备注、图表、表格、对象数量和全部 DrawingML 身份守恒。**portable 档**：有 LibreOffice 时用 LibreOffice 渲染作视觉事实源；缺失时依赖用户视觉豁免。
5. 视觉门为 `pass`，或存在绑定当前 PPTX SHA 的用户豁免并记为 `skipped_with_user_ack`。
6. 无未重放 patch；补丁 scope invariant 证明未点名页文本以及 master/layout/theme/notes 未变。
7. 模板模式还必须满足内容合同、同页槽位来源、模板对象处置完整、计划确认、母版/版式/主题计数不漂移；`inspect` 报告含模板示例的非逻辑 slide parts 时，必须先以 `package-clean` 关闭该 finding。

macOS 运行目录不得位于 `/private/tmp`。`inspect` 阶段不启动 Chrome/Chromium；OfficeCLI HTML preview 只记为 `deferred_to_powerpoint`，不能替代 native 档的 PowerPoint 事实渲染，但在 portable 档可由 LibreOffice 渲染补齐。

普通用户目录不会自动向 PowerPoint 的 AppleScript 打开动作递归授权。交给 PowerPoint 的所有输入、roundtrip 副本和 PDF 输出必须位于真实系统账户的 `Library/Containers/com.microsoft.Powerpoint/Data/tmp/d6ppt/`；真实 home 用系统账户数据库解析，不得使用被 cleanroom 改写的 `$HOME` / `Path.home()`。`process/tmp/opencode/diag` 与所有 staging root 外路径 fail closed。

另存、重开、改字、移动、保存、持久化核验与 PDF 导出合并为一次 PowerPoint 批处理会话。批处理完成后把 PPTX/PDF 复制回 run，再在 PowerPoint 外栅格化；禁止点击或代用户批准文件访问权限对话框。AppleEvent 总超时为 600 秒以上，异常路径必须关闭测试副本并清理真实容器内的当前 session 子目录。

`visual_review.json` 由 `visual-review` 写入，至少绑定当前 PPTX、渲染 PDF、contact sheet 和每页 PNG SHA；事实源可以是 PowerPoint 或 portable 档的 LibreOffice。视觉拒绝不能 finalize。

视觉不可用时必须先提醒用户切换；用户明确拒绝、没有视觉模型或明确跳过后才能写 `visual_review_waiver.json`。有效豁免允许交付，但状态为 `pass_with_warnings` / `delivered_with_warnings`，声明必须包含“未进行模型视觉质量检查”。

LibreOffice 不是默认 native gate。在 portable 档可作为渲染事实源；显式 `verify --compatibility libreoffice` 时仍运行附加 Save As/reopen 和视觉差异检查。
