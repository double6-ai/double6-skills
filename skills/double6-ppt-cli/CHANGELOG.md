# double6-ppt-cli 变更记录

## 0.2.2

- `verify` 增加双档：`--verify-tier auto|native|portable`。本机无 PowerPoint、`osascript` 不可用或系统拒绝辅助访问时，auto 自动降级 portable（OfficeCLI 持久化改字探针 + 可选 LibreOffice 渲染）。
- portable 先产出 LibreOffice 逐页渲染与 contact sheet，再解析视觉门；`visual-review` 可绑定 portable 页面。
- portable 交付状态至少 `pass_with_warnings`，声明明确未执行 PowerPoint 原生 roundtrip。
- `finalize` 接受 `powerpoint_status=skipped_portable_tier`。
- 文档补全 generate 所需 `spec_lock.md`（含 `pptx_structure.mode: flat`）。

## 0.2.1

- 首次以 v0.2.1 精简包内容发布到 GitHub `double6-ai/double6-skills`，并同步 skills.sh 与 ClawHub。
- 保留模板填充同页槽位来源门、受限 `package-clean`、PowerPoint 优先验证与 vendored PPT Master v4.8.0。
- 公开包不含本地评测报告、运行产物、`__pycache__` 与治理元数据；OfficeCLI 仍作为外部固定依赖由用户自行安装。
- ClawHub 包因网关 multipart 体积限制省略两个最大 vendor 数据文件；完整包以 GitHub / skills.sh 为准。
