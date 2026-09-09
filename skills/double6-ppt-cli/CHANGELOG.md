# double6-ppt-cli 变更记录

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
