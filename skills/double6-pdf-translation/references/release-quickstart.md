# 运行说明

从已安装 skill 目录运行，`python` 指向按[依赖说明](runtime-dependencies.md)创建的新环境。用户输出和回执使用全新绝对路径。可设置 `PAPER_TRANSLATION_WORKSPACE` 控制锁和缓存的位置。

## 先核输入

```bash
python scripts/paper_translation_workflow.py inspect-input \
  --input /absolute/source.pdf --output /absolute/new/INPUT_PREFLIGHT.json \
  --receipts /absolute/new/receipts
```

该动作核真实页框、可见/隐藏字形和扫描覆盖，不改源文件、不自动选择 OCR 或模型。不给 `--catalog-url` 时不探测模型库存。结果可能是 `needs_source_review`，须检查 `blockers` 和 `todos`。新扫描的完整作品、源角色和手写资格需要具名源图审阅；如进入新翻译，显式给定 `--fresh --source-review`、`--model` 和 LM Studio 兼容的 `--catalog-url`。未配置库存时不探测任何默认本机服务。其它服务的新翻译身份通过对应路线的冻结合同核定。

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

## 资源上限

`inspect-input`、`candidate`、`collect`、`review` 等重任务动作都接受：

| 参数 | 环境变量 | 默认（macOS / Linux） |
|---|---|---|
| `--task-memory-mib` | `PAPER_TRANSLATION_TASK_MEMORY_MIB` | 3072 / 4096，且默认不超过物理内存 25% |
| `--job-timeout-seconds` | `PAPER_TRANSLATION_JOB_TIMEOUT_SECONDS` | 120 / 300 |
| `--memory-metric` | `PAPER_TRANSLATION_MEMORY_METRIC` | `rss` / `pss` |

无 FREEZE 的动作（`inspect-input`、`review`、`run-reviewed-scan` 等）优先级为：命令行 > 环境变量 > 平台默认。显式内存上限最多为物理内存 50%，越界直接报 `resource_limit_invalid`。

带 FREEZE 的动作（`candidate`、`collect`、`resume-latex`）以冻结的 `resource_contract` 为唯一权威预算：

- 实际执行的内存上限、单作业时限和计量口径全部取自冻结合同；合同未写 `memory_metric` 时按原始含义 `rss` 解释（旧 3 GiB/120 s 合同）。这类旧合同在 Linux 上按逐进程 RSS 相加计量，fork 子进程的共享页会被重复计入，视具体作业可能超出预算而被停止；建议按下方 Linux 建议合同重新冻结。
- 命令行或环境变量给出的值必须与冻结值相同；不同（无论更大还是更小）即以 `resource_override_conflicts_with_freeze` 拒绝，退出码 2，不启动任何重任务。要换预算请重新冻结。
- 冻结内存超过物理内存 50% 时报 `task_memory_limit_exceeds_host_authorization`。
- Linux 建议冻结 `{"task_rss_bytes": 4294967296, "per_job_seconds": 300, "concurrency": 1, "memory_metric": "pss"}`；`doctor` 输出本平台的 `recommended_resource_contract`。
- 回执的 `resource_limits` 记录实际执行的上限（`source` 为 `freeze`），`resource_contract_frozen` 记录冻结原文。

输入预检本身在有界子进程中运行（1.5 GiB RSS／60 秒，最多解析 5 页；页数超限时只读页数即返回），回执的 `preflight_guard` 记录其状态与峰值。
Linux 默认按 PSS 计量：后端 fork 出的子进程与父进程共享只读页，逐进程 RSS 相加会重复计算共享页。回执记录 `resource_limits`、`memory_metric`、`peak_task_memory_bytes` 和 `peak_task_rss_sum_bytes`；FREEZE 中的 `resource_contract` 仍要求并发 1，并在边界内（512 MiB–64 GiB、30–7200 秒）。

## 结构化预检与错误码

`inspect-input` 报告和 `candidate`/`collect` 的 `WORKFLOW_INPUT_PREFLIGHT.json` 使用同一结构：`status`（`ok`/`blocked`，扫描事实报告另有原状态）、`error_code`、`warnings` 和 `findings[]`（`code`、`severity`、`message`、`details`）。任何动作被预检或合同校验拦下时，标准输出是同形 JSON，退出码 2；不再打印原始 traceback。

| 退出码 | 含义 |
|---|---|
| 0 | 成功；`candidate` 的质量结论为 `pass`/`warn`/`unverified` |
| 1 | 其它失败（如资源超限停止、后端失败），见 `status`/`stop_reason`/`exception` |
| 2 | 被输入预检或合同校验拦下（`status: blocked`，见 `error_code`/`findings`），不产生译文 |
| 3 | 生成候选的动作（`candidate` 各路线、`resume-latex`、`revise-latex`、`preserve-roles` 等）：译文照常写出，但综合质量判 `fail`；结果 JSON 含 `quality_gate: fail`、`quality_fail_summary`、`quality_fail_reasons`（检查项、页码、残留比例与逐页等级）、`render_residue_pages` 和 `output_files` |

| 错误码 | 级别 | 含义 |
|---|---|---|
| `input_not_found` / `not_a_pdf` / `input_too_large` | error | 文件不存在、不是 PDF、超过 100 MiB |
| `pdf_truncated_or_corrupt` | error | 无法打开、缺少文件尾或修复后 0 页 |
| `encrypted_user_password_required` | error | 需要打开密码；不猜测、不破解 |
| `permissions_restricted` | warning | 所有者权限限制（禁止修改/复制等）；请确认有权翻译 |
| `page_limit_exceeded` | error | 超出当前路线页数（电子 PDF 1–5 页；扫描预检 `--max-pages`，默认 2、最大 20） |
| `non_digital_pages` | error | 电子 PDF 路线遇到扫描图像页、文字转曲页或路由判为需复核的页 |
| `source_language_matches_target` | error | 源文主要语言已经是目标语言（英译中时源文为中文，中译英时源文为英文） |
| `target_language_unsupported` | error | `--target-language` 不是 `zh`（英译中）或 `en`（中译英） |
| `target_language_route_unsupported` | error | `--target-language en` 只支持 `candidate --route digital_pdf`；`latex_verified` 与 `collect` 的译者固定译成简体中文 |
| `zh2en_inline_object_math_unsupported` | error | 中译英：中文正文行内的变量/公式由 Form XObject 文字或矢量路径字形绘制，无法随英文重排（`details.pages` 列出每页计数） |
| `source_language_mixed` / `source_language_unknown` | warning / info | 中英混合或可抽取文字过少 |
| `page_load_failed` | error | 部分页面无法解析 |
| `resource_limit_invalid` | error | 资源参数越界 |
| `resource_override_conflicts_with_freeze` | error | 命令行/环境变量的资源值与 FREEZE 冻结合同不同；请去掉覆盖或重新冻结 |
| `task_memory_limit_exceeds_host_authorization` | error | 内存上限超过物理内存 50% |
| `preflight_guard_stopped` | error | 输入预检子进程超出 1.5 GiB／60 秒预算被停止 |
| `input_or_contract_invalid` | error | FREEZE 或其它输入合同不符，`message` 给出原因 |

## 渲染英文残留检查

每次渲染都会写 `render_residue_check.json`：逐页比较源与成品可抽取的拉丁词数，残留率 ≥0.6 的页为高风险，≥0.3 为中风险；整体残留率 ≥0.5 或存在高风险页时 `comprehensive_quality` 判 `fail`，`quality_report.md` 顶部同步写明。按 skill 规则本就不翻译的内容不计入残留率，源与译文两侧同样剔除，并在报告中逐页记录剔除词数（`excluded_source_words`、`excluded_source_breakdown`）和参考文献段所在页（`excluded.reference_section_pages`）：

- 参考文献段：按几何阅读顺序（行框坐标；检测到双栏时先左栏后右栏，通栏行切分区段）而非内容流顺序确定。整行标题为 References / Bibliography / Works Cited / 参考文献 等，其后到结束标题之间的区域内**逐条**判断，规则与无标题参考文献相同（见下文 strong / weak）：只剔除 strong 条目和有正面证据的 weak 条目，区域内的普通正文和缺证据的 weak 条目照常计入；
- 结束标题：Appendix / Appendices / Supplementary / 附录 等，以及加粗、字号更大或前有段距的字母编号标题（如 `A Proof of the Main Theorem`、`A.1 …`、`B Additional Results`）；其后的正文照常计入；
- 正文否决（区域内与无标题都适用）：块内出现指标枚举（`%`、`±`、`accuracy of 92.3`、`41.3 BLEU`、`F1 of …` 等）、两个以上短小数、三个以上年份、两个以上叙述式引用（`Smith et al. (2020)`）之一即否决；第一人称（we/our）、谓语动词（is/are/was/has…、proposed/showed/trained/achieved…）、句首连接词（We/This/However…）、分号合计 ≥2 也否决。被否决的块按正文计数；
- 无标题参考文献（`reference_entries_headingless`，宁可误报不可漏判）：没有 References 标题时，只有同时满足以下全部条件的连续条目段才剔除，否则照常计数：
  - 逐块分类：strong = 行首 `[n]`/`n.` 编号或作者开头（`Surname, X.`、`X. Surname`、作者列表后紧跟年份）+ 年份 + 出处信号（会议/期刊/出版社/DOI/arXiv/页码/卷号/`. In …`），且虚词比例 ≤0.30、不超过 90 词/8 行、未被否决；weak = 只缺年份或出处之一的条目、栏首/页首的残段，或栏底被截断的编号条目头；其它块（包括被否决的正文）立即打断连续段；
  - **weak 默认计数**（第四轮）：只有正面证据才剔除——`numbered_sequence`（带编号、≤40 词，紧邻的带编号条目与之连续；栏底被截断且虚词比例 ≤0.15 的条目头不限词数），或 `continuation`（栏首/页首、无编号也无作者开头，紧接在一个已剔除且未以句号结束的条目之后，左边距不在 strong 条目边距之外）。抽取器不提供“参考文献”角色标注，所以不使用角色信号；
  - 至少 3 条 strong，strong 占条目 2/3 以上，strong 条目虚词比例均值 ≤0.27，strong 条目首行左边距一致（同栏相差 ≤3pt）；
  - 位于文档末尾或节末：段后直到文档结束或下一个附录类标题之间只有页码等极短组；
  - 源文侧全文的无标题剔除量不超过源文英文词总数的一半，超过则整段退回计数（`exceeds_document_fraction`）；译文侧只在源文已接受的页上接受（`no_matching_source_run`）；
  - 每个候选段都写入 `excluded.headingless_runs`（`source`/`target`）：页码、strong/weak 条目数、剔除词数、`accepted`、`reason`、首末条目预览和逐条决定 `entries_detail`（`class`、`decision` = excluded/counted、`reason`、词数、预览）；References 标题区域的逐条决定写入 `excluded.reference_region_entries`；
- 译文侧剔除上限：每页译文剔除词数不得超过源文同页剔除词数 ×1.2 + 20，超出部分加回计数（`target_exclusion_capped_words`），防止译文把未翻译正文排成“参考文献”样式来规避检查；
- 等宽字体代码；
- URL、DOI、邮箱、arXiv 编号；
- 方括号编号引用（如 `[12]`、`[3–5]`）、作者-年份括号引用和 `et al.`。

综合质量判 `fail` 时（任何检查、任何路线），生成候选的动作退出码为 3（译文文件仍保留，便于人工检查）。阈值是启发式的：按本版本测试语料标定（未翻译直通残留率 1.00，正常译文 0.04–0.14，含大量英文图框标签的图页 0.34），只评估源文拉丁词 ≥50 的页。它只是最小版成品检查，不替代逐页人工核对。

已知局限（不是只会偏严）：
- 漏判路径仍存在：
  - 未翻译的英文若排成完整的 strong 文献条目（编号或作者开头、年份、出处信号，不含指标、谓语动词和第一人称），无标题时还需位于文末、左边距一致、不超过全文英文词一半，会被剔除；References 标题之后同样格式的条目也会剔除；
  - weak 条目若带 `[n]`/`n.` 编号且与紧邻条目编号连续、不超过 40 词（或位于栏底被截断且虚词比例 ≤0.15），会作为 `numbered_sequence` 剔除；
  - 紧接在未结束的已剔除条目之后的栏首/页首残段会作为 `continuation` 剔除，即使其内容其实是正文；
  - 这些剔除都逐条列在 `entries_detail` / `reference_region_entries` 中，复核时请查看。
- 误报路径：被否决的真实条目（标题含 `It's`、多个年份或谓语动词）、缺出处信号且无编号的条目、作者名格式特殊的条目会计数；无标题参考文献超过全文一半、不在文末或左边距不一致时整段计数，可能判 medium/high。

## 中译英（`--target-language en`）

`candidate --route digital_pdf` 加 `--target-language en` 把中文电子版 PDF 译成英文（默认 `zh` 为英译中，命令行与回执不变；`latex_verified`、`collect` 报 `target_language_route_unsupported`）。后端以 `--lang-in zh --lang-out en` 调用，默认提示词换成中译英版本（自定义提示词不替换），英译中方向的默认术语表（译法含汉字的条目）不注入提示词；本地 Qwen CLI 适配器同样收到目标语言，不做英译中译名修补。HY-MT 兼容代理与 LM Studio 原生传输只会译成中文，中译英时报 `target_language_backend_unsupported`。

预检（只在中译英时）：中文正文行内只要有 1 个由 Form XObject 绘制的非中文字形或字形大小的填充矢量路径（Word/WPS 公式、MathJax/网页打印公式），以 `zh2en_inline_object_math_unsupported` 拒绝。这是失败关闭而不是修复：这类对象无法随英文重排，会与译文压叠或被丢弃。整页（或多层）被包进 Form XObject 时逐个 Form 归类：自身不绘制中文行的为行内 Form；绘制中文行、但作为单行小对象紧邻嵌在 Form 之外的中文宿主行里的（带中文下标/短标签的公式，如 “M最大”）也是行内 Form；其余为正文 Form。只有行内 Form 的非中文字形计入，外层正文包装不会隐藏嵌套在内的行内变量（`details` 中有 `body_forms`/`inline_forms`/`hosted_cjk_forms` 计数）。

排版差异（只在中文源 → 非 CJK 目标时生效，英译中逐像素不变）：
- 抽取中文源文时，字距调整/两端对齐造成的汉字间隙不补空格（间隙 < 0.5 字高）；表格单元格之间的大间隙照常补空格；
- 不含汉字的段落（公式碎片、英文专名、数字）保留原字形，不送翻译；含汉字的短标签（表头“样本量”、组名）照常翻译；
- 英文译文按整词宽度断行；单行段落（标题、图注）放不下时先借用右侧空白，到可读下限仍放不下时再借用右侧、下方空白。

成品检查改为渲染中文残留检查（`render_chinese_residue`）：逐页比较源/译文可抽取汉字数，页残留率 ≥0.30 为高风险、≥0.10 为中风险，整体 ≥0.25 或存在高风险页判 `fail`（退出码 3）。源页汉字少于 100 时不按比例评估，但整行中文源句（≥12 字）逐字留在译文里判高风险；所有页都短时按整份文件合计评估。以下结构性问题同样判 `fail`：源文中文正文行内已定位的结构对象（矢量公式字形、Form XObject 变量）在成品原位丢失或与译文字形压叠，任何一个即判（`inline_object_damage_pages`，规则 `inline_object_damage_high`）；源文保留字形（非 Noto 字体）与英文译文字形压叠的页，1 个字符即判（`retained_glyph_overlap_pages`，规则 `retained_glyph_overlap_high`）；字形大小的填充矢量路径比源页少 ≥3 个且 ≥25% 的页（`vector_glyph_loss_pages`，规则 `vector_glyph_loss_high`）。

已知局限：
- 行内公式由 Form XObject 或矢量路径绘制的中文 PDF 不支持（预检拒绝，见上；只要定位到 1 个即拒绝）。定位依赖“对象中心落在中文行文字范围内、字形大小”的结构规则：中文行内的小图标也会被拒绝（误拦），不在行内的对象不检测；
- Type3 字体的源文（如网页打印 PDF）英文无法沿用粗体；
- 中文参考文献不剔除，按残留计数；图片里的中文不翻译（需要 OCR）。
