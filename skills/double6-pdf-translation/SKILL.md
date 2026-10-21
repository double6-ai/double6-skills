---
name: double6-pdf-translation
description: 论文和PDF英译中执行。先读 configs/default-routes.json，按源证据直接调用已有命令。清晰单栏扫描先预检和源图确认；审过再准备用单配置；冻住了只重出PDF。电子PDF和已核过的LaTeX走原路线。全文、实际PDF、复制和冷重建必须保留。旧的整篇强翻译流水线不是当前入口。
metadata:
  version: "2.0.0-rc.5"
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
| 中文电子版 PDF 译成英文 | `candidate`/`collect` 加 `--target-language en`（默认 `zh` 为英译中），只走 `--route digital_pdf` |

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

资源按当前路线：一次只跑一个任务；进程树内存上限与单作业时限按平台默认（macOS 3GiB RSS／120 秒，Linux 4GiB PSS／300 秒，且默认不超过物理内存 25%），可用 `--task-memory-mib`、`--job-timeout-seconds`、`--memory-metric` 或对应环境变量 `PAPER_TRANSLATION_TASK_MEMORY_MIB`、`PAPER_TRANSLATION_JOB_TIMEOUT_SECONDS`、`PAPER_TRANSLATION_MEMORY_METRIC` 显式调整（显式值最多物理内存 50%）。带 FREEZE 的动作（`candidate`、`collect`、`resume-latex`）以 FREEZE 中冻结的 `resource_contract` 为唯一预算：命令行/环境变量只能与冻结值相同，不同即以 `resource_override_conflicts_with_freeze` 拒绝（退出码 2），要换预算请重新冻结；合同未写 `memory_metric` 时按 `rss` 解释（Linux 上 RSS 相加会重复计入共享页，旧合同视作业可能超出预算，建议重新冻结），Linux 建议冻结 `{"task_rss_bytes": 4294967296, "per_job_seconds": 300, "concurrency": 1, "memory_metric": "pss"}`（`doctor` 输出 `recommended_resource_contract`）。回执的 `resource_limits` 记录实际执行的上限。扫描新输入默认最多 2 页。模型服务另计，上限 40GiB。先做一页，确认内存正常再扩大。

输入预检与失败统一输出结构化 JSON：`status`、`error_code` 和 `findings`（每项含 `code`/`severity`/`message`/`details`）；被预检拦下时退出码为 2。错误码含 `encrypted_user_password_required`、`pdf_truncated_or_corrupt`、`page_limit_exceeded`、`non_digital_pages`、`source_language_matches_target` 等，`permissions_restricted` 为警告。支持英译中（默认 `--target-language zh`）与中译英（`--target-language en`，电子 PDF 路线）：源文主要语言已经是目标语言时 `candidate` 直接拒绝（`source_language_matches_target`），不会静默输出原文；中译英成品改做渲染中文残留检查，并提示源文保留字形与译文压叠的页。成品另做渲染英文残留检查，大面积未翻译判为高风险失败（`quality_status: fail`），此时仍写出译文，但以退出码 3 结束并在 JSON 中列出失败原因；退出码 3 由综合质量结论驱动（电子 PDF、LaTeX 及其它生成候选的动作同样适用），不只看残留检查。残留检查不计参考文献条目（按几何阅读顺序定位、逐条校验，字母附录处结束，句子式正文与指标枚举一律否决；只缺年份或出处的 weak 条目默认计数，仅在编号连续或跨页/跨栏续接时剔除；无标题时只剔除文末、左边距一致、至少 3 条带年份和出处的连续条目，且不超过全文英文词一半，候选段写入 `excluded.headingless_runs` 供审计）、等宽代码、URL/DOI/邮箱、编号与作者-年份引用。错误码表见[运行说明](references/release-quickstart.md)。

| 退出码 | 含义 |
|---|---|
| 0 | 成功；`candidate` 的质量结论为 `pass`/`warn`/`unverified` |
| 1 | 其它失败（如资源超限停止、后端失败），见 `status`/`stop_reason`/`exception` |
| 2 | 被输入预检或合同校验拦下（`status: blocked`，见 `error_code`/`findings`），不产生译文 |
| 3 | 生成候选的动作（`candidate` 各路线、`resume-latex`、`revise-latex`、`preserve-roles` 等）：译文照常写出，但综合质量判 `fail`；结果 JSON 含 `quality_gate: fail`、`quality_fail_summary`、`quality_fail_reasons`（检查项、页码、残留比例与逐页等级）、`render_residue_pages` 和 `output_files` |

## 安装、配置与恢复

使用 macOS/Linux、Python 3.12。从 skill 目录执行 `bash scripts/setup_venv.sh /absolute/new/venv`，随后用该环境的 Python 运行 `scripts/paper_translation_workflow.py`。详见 [运行依赖](references/runtime-dependencies.md)。

新翻译必须显式提供 `--base-url`、`--model` 及所需凭据；不自动选本机服务或替换模型。库存预检需显式给定 `--catalog-url`（不给则不探测库存，`inspect-input` 照常输出事实）。运行目录可通过 `PAPER_TRANSLATION_WORKSPACE` 指定；输入、输出及回执用绝对路径，输出选全新目录。联网获取源码、字体或模型须明确授权并记录来源。

主入口电子 PDF 与可信 LaTeX 的完整输入限 1–5 页。LaTeX 保护拒绝后的完整单元修订和断点恢复见 [恢复说明](references/latex-recovery.md)。`preflight` / `deliver` 仍使用严格门；有限交付只适用于具名接受的精确 PDF 及披露的限制。缺少语义、视觉、阅读器或重建证据时保留未验证。

许可原文见 [LICENSE](LICENSE)，依赖及来源见 [运行依赖](references/runtime-dependencies.md)，维护差异见 [MODIFICATIONS.md](MODIFICATIONS.md)。
