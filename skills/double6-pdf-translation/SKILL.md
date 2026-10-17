---
name: double6-pdf-translation
description: 论文和PDF英译中执行。先读 configs/default-routes.json，按源证据直接调用已有命令。清晰单栏扫描先预检和源图确认；审过再准备用单配置；冻住了只重出PDF。电子PDF和已核过的LaTeX走原路线。全文、实际PDF、复制和冷重建必须保留。旧的整篇强翻译流水线不是当前入口。
metadata:
  version: "2.0.0-rc.2"
  development_revision: "110-unpublished"
  source_contract_revision: "111-20261017"
  release_status: "local-prepublication-candidate"
  default_routes: "configs/default-routes.json"
  entry_point: "scripts/paper_translation_workflow.py"
---

# PDF 中文翻译

## 当前合同

先读 [configs/default-routes.json](configs/default-routes.json)。按源证据判断输入和任务，直接调用 [scripts/paper_translation_workflow.py](scripts/paper_translation_workflow.py) 里已经存在的动作。从已安装的 skill 目录用独立 Python 环境执行；安装和模型配置见下文。直接使用已有动作。

路线名称仍是 `110-unpublished`，本页已同步源项目第 111 轮（2026-10-17）的开工合同。旧长说明、旧默认命令、并发 3/4 和历史模型参数不作为当前入口；历史原件保存在本地来源核对报告中，不加入公开运行包。

| 输入和任务 | 直接调用 |
| --- | --- |
| 清晰单栏扫描，还没审过 | `inspect-input`。具名看过源图之后，才进入既有 OCR、source-plan 和全文审校 |
| 扫描已经审过，确需按原配置再准备 | `run-reviewed-scan --config` |
| 同一份冻结合同，只是重出 PDF | `trial-render`。不重复准备，不探测模型 |
| 电子版 PDF | `collect`，固定参数 `--route digital_pdf`，再走既有源组审校和 candidate |
| 已经核过的 LaTeX | `candidate`，固定参数 `--route latex_verified` |

扫描这条不能套到所有 PDF。隐藏文字层要单独决定走不走，不能悄悄换模型，也不能悄悄改页面尺寸。

## 必须留下的结果

- 完整源组和角色都要有人确认过的依据。分组提案不能当成已经确认。
- 全文语义要审。漏译、误译、重复、语义变了，必须改，包括只出现一次的句子。改完对照源段，在实际 PDF 上重核内容和样式、链接。
- 要有实际中文页，以及左边原文、右边译文的双语页。
- 核对实际字形、字体、样式、链接和保护区域。刊头的颜色和字重能按源复原就复原；做不到就写明没复原。
- 用普通阅读器打开，整段中文要能真实复制出来。
- 材料冻住后，在新目录冷重建一次。
- 只有源、译文、实际成品和适用标准都没变，才沿用旧结论。
- 页面保持输入的原始尺寸，不把原页静默放大或换一套包装。

## 明确不自动做

- 不自动判断是不是完整作品、有没有手写、隐藏识别层能不能用。
- 不自动确认分组、角色、几何、跨页或空白页。
- 不把重复填路径、重复准备省下的几秒，写成省下了人第一次读源的时间。人的操作时间要单独记，机器耗时不能代替。
- 本目录仍是未发布草稿。上游历史本地分发包为 `2.0.0-trial.2`，其发布接受不自动延续到本目录；严格验收和阅读接受都要另记。
- 多栏、复杂表格、公式、差扫描、手写页，没有这页范围里的实测，就不能写成已经支持。

## 细节放在哪

命令参数见 [references/input-preflight-and-reviewed-run.md](references/input-preflight-and-reviewed-run.md)。结构、字号和源页锚点见 [references/adaptive-flow-contract.md](references/adaptive-flow-contract.md)。整页验收见 [references/quality-and-delivery-contract.md](references/quality-and-delivery-contract.md)。译法见 [references/academic-translation-policy.md](references/academic-translation-policy.md)。电子版和 LaTeX 的原步骤见 [references/release-quickstart.md](references/release-quickstart.md)。

资源按当前路线：一次只跑一个任务，任务进程树上限 3GiB，单次作业 120 秒，扫描新输入默认最多 2 页。模型服务另计，上限 40GiB。先做一页，确认内存正常再扩大。

## 安装、配置与恢复

使用 macOS/Linux、Python 3.12。从 skill 目录执行 `bash scripts/setup_venv.sh /absolute/new/venv`，随后用该环境的 Python 运行 `scripts/paper_translation_workflow.py`。详见 [运行依赖](references/runtime-dependencies.md)。

新翻译必须显式提供 `--base-url`、`--model` 及所需凭据；不自动选本机服务或替换模型。库存预检需显式给定 `--catalog-url`。运行目录可通过 `PAPER_TRANSLATION_WORKSPACE` 指定；输入、输出及回执用绝对路径，输出选全新目录。联网获取源码、字体或模型须明确授权并记录来源。

主入口电子 PDF 与可信 LaTeX 的完整输入限 1–5 页。LaTeX 保护拒绝后的完整单元修订和断点恢复见 [恢复说明](references/latex-recovery.md)。`preflight` / `deliver` 仍使用严格门；有限交付只适用于具名接受的精确 PDF 及披露的限制。缺少语义、视觉、阅读器或重建证据时保留未验证。

许可原文见 [LICENSE](LICENSE)，依赖及来源见 [运行依赖](references/runtime-dependencies.md)，维护差异见 [MODIFICATIONS.md](MODIFICATIONS.md)。
