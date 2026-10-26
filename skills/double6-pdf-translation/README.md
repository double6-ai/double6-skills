# double6-pdf-translation

PDF英译中与中译英，尽量保留原版式，生成单语与源左译右双语PDF。正式版本为 **2.1.0**。

默认 `translate` 自动处理电子、扫描、混合和长文档：分页、保存进度并支持恢复。少量不可靠OCR或公式按完整段落保留原图，无法可靠处理的坏页保留原页，继续后页；原文保留位置和问题写入独立附件。正式PDF不加入执行者批注或审校提醒。

```text
请使用 $double6-pdf-translation 将这个 PDF 翻译成准确、可读的简体中文，并尽量保持原始版式。
```

适用macOS/Linux、Python 3.12。先读 [SKILL.md](SKILL.md)，安装并运行：

```bash
bash scripts/setup_venv.sh /absolute/new/venv
export LOCAL_TRANSLATION_API_KEY='你的API凭据'
/absolute/new/venv/bin/python scripts/paper_translation_workflow.py translate --input /absolute/source.pdf --output /absolute/new-output --target-language zh
```

中译英用 `--target-language en`；中断后同命令加 `--resume`。默认模型为智谱coding plan `glm-5.3-flash`，支持显式模型和端点；详情见[默认路线](configs/default-routes.json)。凭据不进入命令参数或PDF。

复杂表格、多栏、密集公式和低质量扫描仍可能保留原文，无法承诺逐页完整翻译或像素级复现。无效鉴权/额度、损坏输入、全局资源异常等严重问题会停止并保存进度。每页沿用资源上限。软件发布不代表每份译文通过语义审校或用户验收；详见[续译策略](references/translation-continuation.md)。显式严格路线继续保留。

安装与资源说明见[运行依赖](references/runtime-dependencies.md)和[严格路线运行说明](references/release-quickstart.md)。上游许可保留在 `LICENSE` 和各 `vendor` 目录；变更范围见 [MODIFICATIONS.md](MODIFICATIONS.md)。
