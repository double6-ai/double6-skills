# double6-pdf-translation

将英文论文或 PDF 译为简体中文，尽量保留源版式，生成中文单语和源左译右双语 PDF，并保留完整审校证据。

当前副本使用 `paper-translation` 的 `110-unpublished` 路线，并已同步第 111 轮（2026-10-17）的当前开工合同；执行先读 [SKILL.md](SKILL.md) 和唯一路线配置。支持电子 PDF、有限可信 LaTeX 和需要人工源组/角色确认的清晰单栏扫描；每份成品都需要语义、页面、样式、链接、阅读复制和重建核验。候选版本为 `2.0.0-rc.9`，软件发布、每份 PDF 的技术核验、用户接受和严格交付分别登记。

```text
请使用 $double6-pdf-translation 将这个 PDF 翻译成准确、可读的简体中文，并尽量保持原始版式。先确认输入范围、模型配置和必要审校，再生成中文单语与双语 PDF。
```

macOS/Linux、Python 3.12 的独立安装方式：

```bash
bash scripts/setup_venv.sh /absolute/new/venv
/absolute/new/venv/bin/python scripts/paper_translation_workflow.py --help
```

完整步骤见 [SKILL.md](SKILL.md)、[运行说明](references/release-quickstart.md) 和 [运行依赖](references/runtime-dependencies.md)。上游许可保留在 `LICENSE` 和各 `vendor` 子目录；变更及许可范围见 [MODIFICATIONS.md](MODIFICATIONS.md)；公开发布动作需另行授权。
