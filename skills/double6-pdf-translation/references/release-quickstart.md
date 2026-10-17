# 运行说明

从已安装 skill 目录运行，`python` 指向按[依赖说明](runtime-dependencies.md)创建的新环境。用户输出和回执使用全新绝对路径。可设置 `PAPER_TRANSLATION_WORKSPACE` 控制锁和缓存的位置。

## 先核输入

```bash
python scripts/paper_translation_workflow.py inspect-input \
  --input /absolute/source.pdf --output /absolute/new/INPUT_PREFLIGHT.json \
  --receipts /absolute/new/receipts
```

该动作核真实页框、可见/隐藏字形和扫描覆盖，不改源文件、不自动选择 OCR 或模型。结果可能是 `needs_source_review`，须检查 `blockers` 和 `todos`。新扫描的完整作品、源角色和手写资格需要具名源图审阅；如进入新翻译，显式给定 `--fresh --source-review`、`--model` 和 LM Studio 兼容的 `--catalog-url`。未配置库存时不探测任何默认本机服务。其它服务的新翻译身份通过对应路线的冻结合同核定。

## 已审扫描重建

```bash
python scripts/paper_translation_workflow.py trial-render \
  --input /absolute/source.pdf --contract /absolute/TRIAL_CONTRACT.json \
  --output /absolute/new/render --receipts /absolute/new/receipts
```

先核源、目标、字体、源组/角色、语义审校及实现 SHA。确需重新准备时才使用 `run-reviewed-scan --config /absolute/run.json`，详见[输入与重放合同](input-preflight-and-reviewed-run.md)。已有 OCR 可用 `prepare-scan` 生成待审源计划；命令的实际参数以子命令 `--help` 及 [结构合同](adaptive-flow-contract.md) 为准。缺源、遗漏、歧义、越界或证据过期时停止。

## 电子 PDF 与可信 LaTeX

```bash
python scripts/paper_translation_workflow.py doctor \
  --base-url https://your-configured-provider.example/v1 --model your-explicit-model
python scripts/paper_translation_workflow.py collect \
  --input /absolute/source.pdf --freeze /absolute/FREEZE.json --route digital_pdf \
  --base-url https://your-configured-provider.example/v1 --model your-explicit-model \
  --output /absolute/new/collect --receipts /absolute/new/receipts
```

`FREEZE.json` 须由 agent 按实际输入准备：完整1–5页、源范围证据、模型指纹、入口/规则/标准和实现引用、资源合同及各路线保护策略。实际校验字段见 `scripts/paper_translation_workflow.py` 的 `validate_freeze`，严禁抄旧样本 SHA。电子 PDF 完成源组和整段审校后再 `candidate --route digital_pdf`；可信 LaTeX 使用 `candidate --route latex_verified`、完整本地可信源和显式编译器。低层脚本提供修复工具，不自动授予最终接受。

## 审校与交付

对实际单语和双语完整页面核语义、字形、样式、图片公式、链接、整段复制及冷重建。生成后 `review` 收集审阅包，再使用精确绑定的审校与接受材料执行 `preflight` 或 `deliver`。有限交付入口只用于具名、精确 SHA、披露限制的已接受产物。任何语义/视觉/阅读器缺口均保留未验证，不以技术成功替代用户接受。

旧工作区冻结合同绑定旧代码和资产。安装副本中重新冻结受影响的引用并重新核验，不能改 SHA 后声称旧接受自动延续。当前副本的公开发布准备状态由本地发布报告登记，不自动获得软件发布接受。
