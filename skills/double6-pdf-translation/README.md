# double6-pdf-translation

将英文论文或 PDF 译为简体中文，尽量保留源版式，生成中文单语和源左译右双语 PDF，并保留完整审校证据。

当前副本使用 `paper-translation` 的 `110-unpublished` 路线，并已同步第 111 轮（2026-10-17）的当前开工合同；执行先读 [SKILL.md](SKILL.md) 和唯一路线配置。支持电子 PDF、有限可信 LaTeX 和需要人工源组/角色确认的清晰单栏扫描；每份成品都需要语义、页面、样式、链接、阅读复制和重建核验。正式版本为 `2.0.0`，软件发布、每份 PDF 的技术核验、用户接受和严格交付分别登记。

2.0 产品边界：承诺阅读底线硬门（以数字 PDF 为主；不叠字；大面积未译即质量失败并说明原因；公式不压平；可读版数学保真；凭据不进命令行；失败可解释；方向感知 QA）。已知限制：复杂表格的像素级/结构级完美、多栏与栏溢出的像素级保真、脚注/引用标点几何细缝均不承诺；检到不稳定结构时稳定拒绝或标为 `unverified`。详见 [SKILL.md 的“2.0 产品边界”](SKILL.md#20-产品边界)。

```text
请使用 $double6-pdf-translation 将这个 PDF 翻译成准确、可读的简体中文，并尽量保持原始版式。先确认输入范围、模型配置和必要审校，再生成中文单语与双语 PDF。
```

macOS/Linux、Python 3.12 的独立安装方式：

```bash
bash scripts/setup_venv.sh /absolute/new/venv
/absolute/new/venv/bin/python scripts/paper_translation_workflow.py --help
```

完整步骤见 [SKILL.md](SKILL.md)、[运行说明](references/release-quickstart.md) 和 [运行依赖](references/runtime-dependencies.md)。上游许可保留在 `LICENSE` 和各 `vendor` 子目录；变更及许可范围见 [MODIFICATIONS.md](MODIFICATIONS.md)。
