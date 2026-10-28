# double6-pdf-translation

PDF英译中与中译英，尽量保留原版式，生成单语与源左译右双语PDF。正式版本为 **2.1.3**。

默认 `translate` 自动处理电子、扫描、混合和长文档：分页、保存进度并支持恢复。少量不可靠OCR或公式按完整段落保留原图，无法可靠处理的坏页保留原页，继续后页；原文保留位置和问题写入独立附件。正式PDF不加入执行者批注或审校提醒。

扫描表格优先翻译可靠单元格；默认可覆盖印章，识别不可靠或空间不足的区域局部保留。普通中文夹大写编号不按英文大写标题处理；受控OCR重建页经SHA核实后继续，不被重复的原生页判断拦住。变更记录见 [CHANGELOG](CHANGELOG.md)。

中文水平单栏公文和通知默认由执行者复核源文字，程序整段翻译、统一重排并核对保存后的实际字形和保护区。OCR修正通过只含原文的 `--source-review` 记录输入，输出框与共同字号自动计算。密集表格增加灰底和竖排字段识别，超长译文按页预算做至多两轮局部真实模型简译，按事实与实际字体从本轮回复中自动择用；签名及仍不可靠的局部保留。详见[扫描版式处理](references/scan-layout.md)；复杂彩底与跨栏按各自适用路线处理。

通知默认将名单、电话/邮箱、事项标题及路线选项分别排版，英文正文12pt/17pt，标题15.5pt/20.5pt；短节标题随下一页条目排放，落款在右侧按实际文字宽度定位。续页沿用前页已识别的文类；排版依据源角色与本轮真实译文计算，不要求逐份填写字号或坐标。

```text
请使用 $double6-pdf-translation 将这个 PDF 翻译成准确、可读的简体中文，并尽量保持原始版式。
```

适用macOS/Linux、Python 3.12。先读 [SKILL.md](SKILL.md)，安装并运行：

```bash
bash scripts/setup_venv.sh /absolute/new/venv
export LOCAL_TRANSLATION_API_KEY='你的API凭据'
/absolute/new/venv/bin/python scripts/paper_translation_workflow.py translate --input /absolute/source.pdf --output /absolute/new-output --target-language zh
```

普通翻译默认允许覆盖印章以补译章下可核实文字；需要保留印章时加 `--stamp-policy preserve`。仍需核实原文，不猜被遮挡的字。中译英用 `--target-language en`；中断后同命令加 `--resume`，恢复旧保章任务时显式加 `--stamp-policy preserve`；代码身份变更时会开启新运行。默认模型为 DeepSeek-V4.1-Flash（`deepseek-flash`），使用 `DEEPSEEK_API_KEY` 或 `LOCAL_TRANSLATION_API_KEY`；显式模型和端点优先。凭据不进入命令参数或PDF。

复杂表格、多栏、密集公式和低质量扫描仍可能保留原文，无法承诺逐页完整翻译或像素级复现。无效鉴权/额度、损坏输入、全局资源异常等严重问题会停止并保存进度。每页沿用资源上限。软件发布不代表每份译文通过语义审校或用户验收；详见[续译策略](references/translation-continuation.md)。显式严格路线继续保留。

安装与资源说明见[运行依赖](references/runtime-dependencies.md)和[严格路线运行说明](references/release-quickstart.md)。上游许可保留在 `LICENSE` 和各 `vendor` 目录；变更范围见 [MODIFICATIONS.md](MODIFICATIONS.md)。
