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

远端服务的凭据只经环境变量 `LOCAL_TRANSLATION_API_KEY` 提供（回环地址可不提供，使用 `local-no-auth` 占位；远端缺凭据在启动子进程前报 `remote_backend_requires_explicit_api_key`），不要写进命令行参数；规则与边界见[翻译服务凭据](runtime-dependencies.md#翻译服务凭据)。未写 `--model` 和 `--base-url` 时用 `configs/model-profiles.json` 的默认档案（智谱 `glm-5.3-flash`，`https://open.bigmodel.cn/api/coding/paas/v4`）；上面示例里的显式模型和地址仍然优先。

`FREEZE.json` 须由 agent 按实际输入准备：完整1–5页、源范围证据、模型指纹、入口/规则/标准和实现引用、资源合同及各路线保护策略。实际校验字段见 `scripts/paper_translation_workflow.py` 的 `validate_freeze`，严禁抄旧样本 SHA。电子 PDF 完成源组和整段审校后再 `candidate --route digital_pdf`；可信 LaTeX 使用 `candidate --route latex_verified`、完整本地可信源和显式编译器。低层脚本提供修复工具，不自动授予最终接受。

## 审校与交付

对实际单语和双语完整页面核语义、字形、样式、图片公式、链接、整段复制及冷重建。生成后 `review` 收集审阅包，再使用精确绑定的审校与接受材料执行 `preflight` 或 `deliver`。有限交付入口只用于具名、精确 SHA、披露限制的已接受产物。任何语义/视觉/阅读器缺口均保留未验证，不以技术成功替代用户接受。

旧工作区冻结合同绑定旧代码和资产。安装副本中重新冻结受影响的引用并重新核验，不能改 SHA 后声称旧接受自动延续。当前副本的公开发布准备状态由本地发布报告登记，不自动获得软件发布接受。

## 资源上限

`inspect-input`、`candidate`、`collect`、`review` 等重任务动作都接受：

| 参数 | 环境变量 | 默认（macOS / Linux） |
|---|---|---|
| `--task-memory-mib` | `PAPER_TRANSLATION_TASK_MEMORY_MIB` | 5120（macOS，RSS）/ 4096（Linux，PSS），且默认不超过物理内存 25% |
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
| `page_limit_exceeded` | error | 超出当前路线页数（电子 PDF 1–5 页；扫描预检 `--max-pages`，默认 2、最大 20；`chunked-candidate` 1–500 页） |
| `non_digital_pages` | error | 电子 PDF 路线遇到扫描图像页、文字转曲页或路由判为需复核的页 |
| `source_language_matches_target` | error | 源文主要语言已经是目标语言（英译中时源文为中文，中译英时源文为英文） |
| `target_language_unsupported` | error | `--target-language` 不是 `zh`（英译中）或 `en`（中译英） |
| `target_language_route_unsupported` | error | `--target-language en` 只支持 `candidate --route digital_pdf` / `scanned_ocr`；`latex_verified` 与 `collect` 的译者固定译成简体中文 |
| `zh2en_inline_object_math_unsupported` | error | 中译英：中文正文行内的变量/公式由 Form XObject 文字或矢量路径字形绘制，无法随英文重排（`details.pages` 列出每页计数） |
| `source_language_mixed` / `source_language_unknown` | warning / info | 中英混合或可抽取文字过少 |
| `page_load_failed` | error | 部分页面无法解析 |
| `resource_limit_invalid` | error | 资源参数越界 |
| `resource_override_conflicts_with_freeze` | error | 命令行/环境变量的资源值与 FREEZE 冻结合同不同；请去掉覆盖或重新冻结 |
| `task_memory_limit_exceeds_host_authorization` | error | 内存上限超过物理内存 50% |
| `preflight_guard_stopped` | error | 输入预检子进程超出 1.5 GiB／60 秒预算被停止 |
| `input_or_contract_invalid` | error | FREEZE 或其它输入合同不符，`message` 给出原因 |
| `chunk_failed` | error | `chunked-candidate`：至少一块没有产物（`details.chunks[]` 给出每块页范围、状态和原错误码）；不合并、不交付部分结果 |
| `chunk_page_exceeds_task_budget` | error | `chunked-candidate`：资源停止的块已二分到单页，单页仍超出冻结的单任务预算（`details.chunks[].measurements` 给出实测） |
| `chunk_merge_failed` | error | `chunked-candidate`：有界合并任务未完成 |
| `chunk_cleanup_unconfirmed` | error | `chunked-candidate`（`details.chunks[]` 内的块错误码）：某块尝试结束后仍有本尝试的进程存活且无法核实已回收；停止调度后续块，整份 `chunk_failed` |

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

预检（只在中译英时）：中文正文行内只要有 1 个由 Form XObject 绘制的非中文字形或字形大小的填充矢量路径（Word/WPS 公式、MathJax/网页打印公式），以 `zh2en_inline_object_math_unsupported` 拒绝。这是失败关闭而不是修复：这类对象无法随英文重排，会与译文压叠或被丢弃。每个 Form XObject（含嵌套）只按自身内容分类：整页外壳等自身不画内容的 Form 只递归看内层；自身不画汉字的 Form，字形落在中文行内即为行内对象；自身画汉字的 Form 只有在没有任何数学证据（数学符号/希腊字母、数学或斜体字体、孤立单字母、与汉字字号明显不同的拉丁字母、分数线）时才算正文。有数学证据且落在中文正文行里的 Form 判 needs_review 并拒绝（`details.pages[].reasons` 含 `mixed_form_needs_review`），其数学字形与分数线计入成品门；不在正文行里的（图内标签）不计入。普通英文单词和数字不算数学证据；与同行中文同属一个按视觉顺序绘制的文本流（绘制顺序与 x 顺序一致、同字号，单字母还须同字体）的字母和斜体多字母单词也不算。页面等价 Form（整页外壳）自身的内容按页面级内容对待，包装不改变判定。页面级文字层的数学字形不拦截，由成品门 `text_layer_math_loss` 逐个核对是否仍在译文中（须匹配到同字符的独立字母、数学字体字形或数学符号，英文单词里的字母不算；有歧义的 a/A/I 须有字体证据），丢失即退出码 3。资源监控：非本任务进程的查询错误逐进程跳过；本任务进程无法计量时以 `owned_process_monitor_unavailable`/`resource_monitor_unavailable` 停止并清理进程树，写失败回执，退出码 1。进程树枚举失败时按已核验的启动身份（根 PID + create_time、启动进程组）回收并独立核实，回执 `cleanup` 列出已核实退出与未核实的对象；无法确认时 `status=cleanup_unconfirmed`、`error_code=owned_tree_cleanup_unconfirmed`。枚举失败后整树是否已核实单独记在 `cleanup.tree_scope`（`whole_tree_verified`、`reason`）；整树无法核实时同样是 `cleanup_unconfirmed`，`unverified` 非空。

排版差异（只在中文源 → 非 CJK 目标时生效，英译中逐像素不变）：
- 抽取中文源文时，字距调整/两端对齐造成的汉字间隙不补空格（间隙 < 0.5 字高）；表格单元格之间的大间隙照常补空格；
- 不含汉字的段落（公式碎片、英文专名、数字）保留原字形，不送翻译；含汉字的短标签（表头“样本量”、组名）照常翻译；
- 英文译文按整词宽度断行；单行段落（标题、图注）放不下时先借用右侧空白，到可读下限仍放不下时再借用右侧、下方空白。

成品检查改为渲染中文残留检查（`render_chinese_residue`）：逐页比较源/译文可抽取汉字数，页残留率 ≥0.30 为高风险、≥0.10 为中风险，整体 ≥0.25 或存在高风险页判 `fail`（退出码 3）。源页汉字少于 100 时不按比例评估，但整行中文源句（≥12 字）逐字留在译文里判高风险；所有页都短时按整份文件合计评估。以下结构性问题同样判 `fail`：源文中文正文行内已定位的结构对象（矢量公式字形、Form XObject 变量）在成品原位丢失或与译文字形压叠，任何一个即判（`inline_object_damage_pages`，规则 `inline_object_damage_high`）；源文保留字形（非 Noto 字体）与英文译文字形压叠的页，1 个字符即判（`retained_glyph_overlap_pages`，规则 `retained_glyph_overlap_high`）；字形大小的填充矢量路径比源页少 ≥3 个且 ≥25% 的页（`vector_glyph_loss_pages`，规则 `vector_glyph_loss_high`）。

文字 QA 与术语策略按本次目标语言选择（`render_manifest.json` 记录 `target_language`/`source_language`/`direction_basis`）：中译英不把正常英文译文当“疑似大段英文未翻译 / must_translate”，改查英文译文里成段保留的中文（≥6 个汉字 `疑似大段中文未翻译`，较短片段记 low 待术语策略确认），参考文献标题后的文献条目与保护值不计；译法含汉字的英译中默认术语/实体策略不参与中译英 QA，也不做英→中残留替换。英译中的英文残留检查不变。目标语言优先取调用方参数，其次 `source_manifest.json`、`render_manifest.json`；三者都没有时沿用 CLI 默认英译中（`basis=legacy_default_en_to_zh`）；记录了 zh/en 以外的值报 high `QA 目标语言不受支持` 且不做语言残留检查；记录互相矛盾报 high `QA 目标语言记录不一致`。

双语产物命名（左页恒为源文页、右页恒为译文页，页序不随方向变化）：

| 方向 | 标准双语文件名 | `bilingual_pdf_manifest.json` 的 `layout` | 左/右语言 |
|---|---|---|---|
| 英译中（默认） | `<源文件名>.en-left.zh-right.dual.pdf`（不变） | `en_left_zh_right` | `en` / `zh` |
| 中译英 | `<源文件名>.zh-left.en-right.dual.pdf` | `zh_left_en_right` | `zh` / `en` |
| 方向未知（直接调用且未传方向） | `<源文件名>.source-left.translation-right.dual.pdf` | `source_left_translation_right` | `unknown` / `unknown` |

清单另记 `left_role=source`、`right_role=translation`、`left_label`/`right_label`（如“中文原文”/“英文译文”，未知时“原文”/“译文”）与 `direction_basis`。LaTeX 直连的双语副本按清单记录的方向命名；Round38 结构化候选单语页为 `.round38-structured-candidates.<目标语言>.mono.pdf`。`--bilingual-layout en-left-zh-right` 是历史取值名，两个方向都表示“源左译右”。扫描栅格路线只接受英译中，其双语清单显式声明 `en→zh`（文件名 `bilingual_scanned.pdf` 等不变）。

已知局限：
- 行内公式由 Form XObject 或矢量路径绘制的中文 PDF 不支持（预检拒绝，见上；只要定位到 1 个即拒绝）。定位依赖“对象中心落在中文行文字范围内、字形大小”的结构规则：中文行内的小图标也会被拒绝（误拦），不在行内的对象不检测；
- Type3 字体的源文（如网页打印 PDF）英文无法沿用粗体；
- 中文参考文献不剔除，按残留计数；图片里的中文不翻译（需要 OCR）。

## 扫描件 / 混合 PDF：`candidate --route scanned_ocr`（rc.8）

需要本地 Tesseract 5.x 与 `chi_sim`、`eng`、`osd` 语言数据（例如 Debian/Ubuntu：`apt install tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim tesseract-ocr-osd`）。缺失时只有这条路线报 `ocr_engine_unavailable`（退出码 2），`doctor` 的 `ocr_engine` 字段只作提示，不阻断电子路线。

FREEZE 的 `route` 为 `scanned_ocr`，`routing_contract` 须逐字等于 `paper_translation_workflow.OCR_ROUTING`，不得带 `source_cache_contract`，`implementation_refs` 应包含 `scripts/ocr_route.py`。推荐资源合同：`{"task_rss_bytes": 5368709120, "per_job_seconds": 120, "concurrency": 1, "memory_metric": "rss"}`（`resource_limits.RSS_CONTRACT`；rc.8 由 3 GiB 调为 5 GiB）；OCR 与后端共享同一单任务时限。

回执：`receipts/ocr/OCR_MANIFEST.json`（逐页渲染图、识别文字、背景图、行明细、每个 tesseract 进程身份）、`receipts/ocr-reconstruct/`（有界执行资源采样与回收结论）、`receipts/reconstructed-input/`（重建源电子预检）、`receipts/candidate/`（后端）。`WORKFLOW_CANDIDATE.json` 的 `ocr` 字段汇总引擎身份、逐页结论、重建源 sha256；`ocr_stage` 指出停在哪一步。支持/拒绝矩阵与错误码见 [ocr-route.md](ocr-route.md)。

## 长文档分块：`chunked-candidate`（rc.9）

超过 5 页或一个有界任务做不完的文档用 `chunked-candidate`（参数与 `candidate` 相同，另有 `--resume`；`--route` 可取 `digital_pdf`、`scanned_ocr`、`per_chunk`）。parent FREEZE 的 `pages` 为完整 1..N（N ≤ 500），`chunking_contract` 逐字等于 `chunked_translation.CHUNKING_CONTRACT`，`implementation_refs` 包含 `scripts/chunked_translation.py`；`per_chunk` 的 `routing_contract` 为 `PER_CHUNK_ROUTING`。每块派生自己的 FREEZE，以普通 `candidate` 运行，受同一冻结资源合同约束；合并质量不好于最差的一块，任一块没有产物即 `chunk_failed`（退出码 2）。设计、回执、续跑与限制见 [chunked-translation.md](chunked-translation.md)。


## 资源合同、方向检查与退出码

资源按当前路线：一次只跑一个任务；进程树内存上限与单作业时限按平台默认（macOS 5GiB RSS／120 秒，Linux 4GiB PSS／300 秒，且默认不超过物理内存 25%；rc.8 起 RSS 上限由 3GiB 调为 5GiB），可用 `--task-memory-mib`、`--job-timeout-seconds`、`--memory-metric` 或对应环境变量 `PAPER_TRANSLATION_TASK_MEMORY_MIB`、`PAPER_TRANSLATION_JOB_TIMEOUT_SECONDS`、`PAPER_TRANSLATION_MEMORY_METRIC` 显式调整（显式值最多物理内存 50%）。带 FREEZE 的动作（`candidate`、`collect`、`resume-latex`）以 FREEZE 中冻结的 `resource_contract` 为唯一预算：命令行/环境变量只能与冻结值相同，不同即以 `resource_override_conflicts_with_freeze` 拒绝（退出码 2），要换预算请重新冻结；合同未写 `memory_metric` 时按 `rss` 解释（Linux 上 RSS 相加会重复计入共享页，旧合同视作业可能超出预算，建议重新冻结），Linux 建议冻结 `{"task_rss_bytes": 4294967296, "per_job_seconds": 300, "concurrency": 1, "memory_metric": "pss"}`（`doctor` 输出 `recommended_resource_contract`）。回执的 `resource_limits` 记录实际执行的上限。扫描新输入默认最多 2 页。模型服务另计，上限 40GiB。先做一页，确认内存正常再扩大。

输入预检与失败统一输出结构化 JSON：`status`、`error_code` 和 `findings`（每项含 `code`/`severity`/`message`/`details`）；被预检拦下时退出码为 2。错误码含 `encrypted_user_password_required`、`pdf_truncated_or_corrupt`、`page_limit_exceeded`、`non_digital_pages`、`source_language_matches_target` 等，`permissions_restricted` 为警告。支持英译中（默认 `--target-language zh`）与中译英（`--target-language en`，电子 PDF 路线）：源文主要语言已经是目标语言时 `candidate` 直接拒绝（`source_language_matches_target`），不会静默输出原文；中译英成品改做渲染中文残留检查，源文保留字形与译文压叠、矢量公式字形丢失同样判失败；行内公式由 Form XObject/矢量路径绘制的中文 PDF 以 `zh2en_inline_object_math_unsupported` 预检拒绝，`latex_verified`/`collect` 加 `--target-language en` 报 `target_language_route_unsupported`。成品另做渲染英文残留检查，大面积未翻译判为高风险失败（`quality_status: fail`），此时仍写出译文，但以退出码 3 结束并在 JSON 中列出失败原因；退出码 3 由综合质量结论驱动（电子 PDF、LaTeX 及其它生成候选的动作同样适用），不只看残留检查。残留检查不计参考文献条目（按几何阅读顺序定位、逐条校验，字母附录处结束，句子式正文与指标枚举一律否决；只缺年份或出处的 weak 条目默认计数，仅在编号连续或跨页/跨栏续接时剔除；无标题时只剔除文末、左边距一致、至少 3 条带年份和出处的连续条目，且不超过全文英文词一半，候选段写入 `excluded.headingless_runs` 供审计）、等宽代码、URL/DOI/邮箱、编号与作者-年份引用。错误码表见[运行说明](references/release-quickstart.md)。

| 退出码 | 含义 |
|---|---|
| 0 | 成功；`candidate` 的质量结论为 `pass`/`warn`/`unverified` |
| 1 | 其它失败（如资源超限停止、后端失败），见 `status`/`stop_reason`/`exception` |
| 2 | 被输入预检或合同校验拦下（`status: blocked`，见 `error_code`/`findings`），不产生译文 |
| 3 | 生成候选的动作（`candidate` 各路线、`resume-latex`、`revise-latex`、`preserve-roles` 等）：译文照常写出，但综合质量判 `fail`；结果 JSON 含 `quality_gate: fail`、`quality_fail_summary`、`quality_fail_reasons`（检查项、页码、残留比例与逐页等级）、`render_residue_pages` 和 `output_files` |

## 方向、扫描和长文档路线明细

| 输入和任务 | 直接调用 |
| --- | --- |
| 中文电子版 PDF 译成英文 | `candidate --route digital_pdf` 加 `--target-language en`（默认 `zh` 为英译中）；行内公式由 Form XObject/矢量路径绘制的 PDF 预检拒绝 |
| 扫描件或扫描/电子混合 PDF（1–5 页，横排正文） | `candidate --route scanned_ocr`（可加 `--target-language en`）：本地 Tesseract 识别受支持页，重建源再走电子后端与全部质量门；表格、公式、低分辨率、低置信度、不确定方向等以稳定错误码退出码 2 拒绝，OCR 文字不作验收，综合质量最高 `unverified`。见 [references/ocr-route.md](references/ocr-route.md) |
| 超过 5 页、一个有界任务做不完的长文档（最多 500 页，电子、扫描或混合） | `chunked-candidate --route digital_pdf\|scanned_ocr\|per_chunk`：按安全页边界切成有界块（电子 ≤4 页、扫描 ≤2 页），每块是一次普通 `candidate`（原路线、原门、同一冻结资源合同），按原页序合并并恢复目录/页码标签/内部链接；任一块失败整份 `chunk_failed`（退出码 2、不交付部分结果），合并质量不好于最差的一块；`--resume` 回收遗留进程树、只复用逐 sha 核对一致的块。见 [references/chunked-translation.md](references/chunked-translation.md) |
