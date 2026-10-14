# 实验性：基于 PPT Master v6.7.0 roundtrip 的模板填充后端

默认后端仍为 vendored v4.8.0 Template Fill Native。启用实验后端：

- `D6PPT_TEMPLATE_BACKEND=pm6`
- `D6PPT_PM6_ROOT=<ppt-master v6.7.0 的 skills/ppt-master 目录>`（不 vendor）
- `D6PPT_PM6_PYTHON=<含 PM6 依赖的 python>`（可选）
- `D6PPT_PM6_TEXT_MODE=native|svg|svg-restore`（默认 native）

native：SVG 不改文字，对象原生回传（cloned_passthrough），导出后按 cNvPr id 重写原生 txBody，并用真实字体度量做 CJK/拉丁换行与 normAutofit/缩字；溢出在 check 阶段为 ERROR。
处置/来源绑定/导航重建/SHA 绑定图片/OfficeCLI 校验沿用现有 wrapper。测试：`tests/test_pm6_template.py`（集成测试需 D6PPT_PM6_ROOT）。
