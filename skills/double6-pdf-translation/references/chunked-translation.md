# 长文档分块翻译（`chunked-candidate`，2.0.0-rc.9）

`candidate` 只接受完整的 1–5 页文档（FREEZE 页门 `page_limit_exceeded`）。超过一个有界任务能力的长文档
（单任务 120 s、5 GiB RSS、重任务并发 1）改用 `chunked-candidate`：按页范围切成一串有界块，**每块是一次普通
`candidate`**（`digital_pdf` 或 `scanned_ocr` 原路线、原有全部门），全部完成后按原页序合并为一份输出。
分块不放宽任何门、不降阈值、不删公式、不遮挡正文；单份 `candidate` 的命令行、页门和输出不变。

## 用法

```bash
python scripts/paper_translation_workflow.py chunked-candidate \
  --input long.pdf --freeze FREEZE.json --route digital_pdf|scanned_ocr|per_chunk \
  --model <model> --base-url <endpoint> [--target-language en] \
  --output out/ --receipts receipts/        # 必须是新目录
# 中断后在同一目录续跑：
python scripts/paper_translation_workflow.py chunked-candidate ...同上... --resume
```

### parent FREEZE

与 `candidate` 的 FREEZE 相同（输入身份、完整作用域证据、模型指纹、资源合同、实现闭包等逐项核对），另外：

| 字段 | 要求 |
|---|---|
| `pages` | 从 1 开始的完整连续页，1–500 页（`CHUNKING_CONTRACT['max_document_pages']`），且等于实际页数 |
| `chunking_contract` | 逐字等于 `chunked_translation.CHUNKING_CONTRACT`；改任何一项都要重新冻结 |
| `route` / `routing_contract` | `digital_pdf` → `DIGITAL_ROUTING`；`scanned_ocr` → `OCR_ROUTING`；`per_chunk` → `PER_CHUNK_ROUTING` |
| `implementation_refs` | 必须包含 `scripts/chunked_translation.py`（建议同时包含 `chunked_workflow.py`、`ocr_route.py`） |
| `source_cache_contract` | 不支持（拒绝） |

每块的 FREEZE 由 parent 派生（`out/chunks/<id>/attempt-N/freeze/FREEZE.json`）：输入 = 块 PDF（逐 sha）、`pages`
= 1..k、作用域证据指向 parent FREEZE 与计划、块路线及其既有路由合同、`document_term_context_ref`。资源合同、
模型、实现闭包与 parent 相同，所以每块受同一冻结预算约束。

`document_term_context_ref` 指向块级上下文 `freeze/CHUNK_TERM_CONTEXT.json`：整份文档术语上下文原样 + 本块页范围
（`chunk`）+ `document_context_ref`（整份上下文的 sha）+ `reference_region_open_at_start`（见下）。`_execute-digital`
与渲染逐 sha 核对。

## 流程

1. **整份输入预检**（有界子进程，60 s、1.5 GiB，最多 500 页）：逐页分类（原生文字 / 扫描 / 稀疏 / 无文字层）、源语言。
   `digital_pdf` 路线要求全部原生文字页，否则在任何重任务前退出码 2。
2. **计划**（有界任务 `chunk-plan`，冻结资源合同）：
   - 每块页数上限：电子 4 页、扫描 2 页（实测电子约 17 s/页 + 固定开销，5 页 83 s；扫描另加 OCR 约 8 s/页）。
   - 安全边界：在上限往前 1 页内选边界。hard 信号（不在此切）：表格跨页（上页表格到底、下页表格在顶）、
     续表/续图题注（“Table 2 (continued)”“续表”）与“continued on next page”、行尾开放运算符（`=`、`+`、`≤`…；
     连字符断词不算）。表格探测失败按“不安全”处理。段落未结束是软信号：尽量避开，避不开时切开并在
     `CHUNK_PLAN.json.cross_chunk_continuations` 记录（含上下文 sha）。页眉页脚（上下 12% 带、在 ≥30% 页面重复的行）不参与判断。
   - `per_chunk`：原生文字页 → `digital_pdf`，扫描页 → `scanned_ocr`，稀疏/无文字层页并入相邻段；每块只含一种路线。
   - 写出每块源 PDF（`plan/chunks/cNNN.pdf`，sha 登记）、原文目录/页码标签/内部链接、整份文档术语上下文
     `DOCUMENT_TERM_CONTEXT.json`（与单份 candidate 相同的 `prepare_source` / `write_glossary` / `enrich_quality_artifacts`）。
   - 参考文献区跨块延续：在整份源文上用残留检查同一套标题判定（`render_residue_check.reference_region_open_pages`）
     算出每页开始时参考文献区是否已打开，写入 `CHUNK_PLAN.json.reference_region_open_at_page_start` 与每块
     `reference_region_open_at_start`（二分出的子块按其起始页取值）。块从参考文献区中间开始时，该块的渲染残留检查以
     “区已打开”起算——与整份文档一次检查时相同；区内仍按同一套逐条规则剔除或计数（strong 条目剔除、weak 需正面证据、
     正文照常计数），不是放宽。单份翻译不传此状态，报告逐字不变。实测（arXiv 2501.00659 p9 单独成块）：不带入时整页
     按无标题文献判 `exceeds_document_fraction` → high 0.751；带入后 ok 0.2262。
3. **逐块执行**：每次尝试先在 `CHUNKED_RUN_STATE.json`（原子替换）登记 `started`，再以普通 `candidate` 运行
   （同一进程内调用；重任务仍是独立的有界子进程树，拥有式计量、PID + create_time + nonce + 父链核验回收）。
   - 资源停止（`task_timeout`、`whole_job_deadline_exceeded`、`task_memory_limit`、`backend_timeout`）：块二分（id 追加 `a`/`b`），
     直到单页；单页仍超限 → 该块 `chunk_page_exceeds_task_budget`（带实测），不放宽限制。`backend_timeout` = 后端在本任务时限内
     的内部超时（块 `out/render_manifest.json` 的 `errors` 含 `error_type=timeout`）。实测（NIST AI 100-1，4 页块）：后端 110 s
     内部超时后任务以 `owned_descendants_after_command` 结束，原先按瞬时失败重试，第二次靠翻译缓存在 74–114 s 内完成；
     现在与任务超时同样二分，不依赖缓存。
   - 瞬时失败（内部错误等）重试 1 次；预检/路由/OCR 门拦截（`blocked`）与综合质量 `fail` 是确定结果，不重试。
   - 后端未产出候选时的根因（`scripts/failure_root_cause.py`，协议 `backend_failure_root_cause_v1`）：子任务
     `_execute-digital` 只读**本尝试**输出目录内的结构化产物——排版回执 `_backend_working/<stem>/typesetting_writeback_report.json`
     与 `render_manifest.json`——得到稳定原因码与细节，连同本尝试身份（launch nonce、块 FREEZE 引用、输出目录、开始时间）和
     证据 sha 写 `out/BACKEND_FAILURE_ROOT_CAUSE.json`；父任务按该次有界任务 argv 的 `--output-dir`/`--freeze` 与 launch 回执
     nonce 逐项核对回执和证据 sha 后才采信（`root_cause.verified=true`）。不做日志关键字匹配，不读其它尝试的回执。
     | 原因码 | 来源 | 处理 |
     |---|---|---|
     | `typesetting_source_fallback_cap_exceeded` | 排版回执 `source_fallback_cap.status=revoked_cap_exceeded`（细节：scope、页、count、cap、整份计数/上限） | 确定，不重试 |
     | `typesetting_readable_floor_overflow` | 排版回执 `failures[].reason=hard_readable_floor_overflow`（细节：页、段数） | 确定，不重试 |
     | `typesetting_writeback_failed` | 排版回执其它写回失败 | 确定，不重试 |
     | 子任务自身的合同/输入拒绝（如 `input_or_contract_invalid`） | 子任务结构化 stdout 全文（未截断、sha 一致、退出码 2）；锁/I/O 码除外 | 确定，不重试 |
     | `pdf_backend_timeout` | `render_manifest.errors` 的 `timeout` | 资源停止，二分（同 `backend_timeout`） |
     | `root_cause_unavailable` | 证据缺失、不可读、早于本尝试、不在本尝试目录内、回执身份/sha 不符（`problem` 写明） | 不猜：按既有瞬时失败重试 1 次 |
     本地 5xx/断连实测后端没有写出任何结构化证据（只在日志里），因此记 `root_cause_unavailable` 并按瞬时失败重试，不把
     任意非零退出当作确定性失败。根因写入块 `CHUNK_RESULT.json`、`CHUNKED_RUN_STATE.json`（每次尝试 `root_cause`，块
     `failure.root_cause` / `first_root_cause`）与整份回执（`root_cause` = 按页序第一块，`root_causes` = 全部失败块）。
     质量门/可读版的原因码（`quality_fail_reasons` 的 id、公式层级门、可读版 `reason_code`）随完成块上浮到 `chunks[].quality_reasons`。
   - 尝试后核查（`post_attempt_guard`，协议 `launch_receipt_recovery_scan_v2`）：每次尝试结束后，对本尝试**每张** launch 回执
     做整树核实：先只读预检（与回收同一套恢复扫描——环境变量 `PAPER_TRANSLATION_BOUNDED_OWNERS` 里的本次 nonce、本次进程组、
     逐环核验身份的父链），只有“扫描完整、无所属存活、无归属未知、根已退出或号码已复用、原进程组已空”才记为已无残留；
     否则按 `reclaim_owned_tree(discovery_failed=True)` 回收并核实（已知可信根/成员按 PID + create_time 回收，带有效 nonce 的
     时钟跳变按 nonce 刷新身份）。属性查询失败（environ/ppid/create_time 的 AccessDenied 等；僵尸与其它用户进程除外）的进程
     记为归属未知、**不发信号**、写入 `unverified`（稳定原因码 `reason_codes`，如 `ownership_unknown`、
     `descendant_enumeration_incomplete`、`receipt_verification_error`）；有任何一项 → 该块 `chunk_cleanup_unconfirmed`，
     **停止调度后续块**，整份失败关闭。全机 nonce 扫描只作记录（`live_after_attempt`），不作“已清理”的依据（PR #21 review-1：
     旧实现把读不到环境的进程静默丢弃，nonce 集合为空即 confirmed=true）。记录 `POST_ATTEMPT_GUARD.json`。
     实测原因：Linux 上 psutil 的 create_time 由 btime 推算，墙钟跳变（本机一次 +37 s）后既有身份核验把仍在运行的任务根进程
     判为“PID 已复用”而抛错、未回收，该树与下一块重叠运行（下一块被系统内存压力门停止）。
   - 进程树无法核实已回收（`owned_tree_cleanup_unconfirmed`）：不重试、不二分，失败关闭，并停止调度后续块（重任务并发 1）。
   - 其它失败（门拦截、重试后仍失败、单页超预算）后其余块照常执行，一次看到全部失败块。
   - 块完成登记后删除后端字体子集化临时件（`_backend_working/*/temp_subset_{input,output}_mono.pdf`，单块可达数百 MB），
     删除前在 `CHUNK_PRUNED.json` 记录路径、字节数、SHA-256。
4. **合并**（有界任务 `chunk-merge`）——只有所有块都有产物时才运行：
   - 核对块顺序与覆盖（每页恰好一次）和每个产物的 sha；按页序拼接主版式译文（`<stem>.chunked.<lang>.mono.pdf`）
     与 QA 可读件（`final_readable.pdf`，每块一个书签）。
   - 逐页核对：块页数、合并页数、页面尺寸/旋转与原文一致，图片指纹与该块实际送入后端的源（电子块 = 块 PDF；
     扫描块 = OCR 重建源）一致——检出缺页、重复页、错位。
   - 恢复原文内部链接（拆块会丢掉跨块链接）、目录、页码标签，并以写出的文件核对每条内部链接都在。
   - 跨块一致性：各块主要目标语言字体相同；文档级术语表里带译法的术语，在出现源术语的每一块译文里都用同一译法。
5. **合并综合质量**（`merged-N/comprehensive_quality.json`）：取最差的一块（`fail > unverified > pass`，缺失或未知状态按
   `fail`）；任何合并/术语/字体核对为 high → `fail`；有待定项时 `pass` 降为 `unverified`。**永远不好于最差的一块**
   （代码内断言）。OCR 块的封顶（`unverified`）按回执保留。

## 结果与退出码

| 情况 | `status` / `error_code` | 退出码 |
|---|---|---|
| 全部块完成，合并质量 `pass`/`unverified` | `candidate` | 0 |
| 全部块完成，合并质量 `fail`（任一块 fail 或合并核对 high） | `candidate`，`quality_status=fail` | 3 |
| 任一块没有产物（门拦截、确定性后端失败、单页超预算、重试后仍失败、清理无法核实 `chunk_cleanup_unconfirmed`） | `blocked` / `chunk_failed`（`findings[0].details.chunks` 列出每块原错误码与根因；`root_cause` / `root_causes` 上浮），**不合并、不交付部分结果** | 2 |
| 合并任务未完成 | `blocked` / `chunk_merge_failed` | 2 |
| 续跑前遗留进程树无法核实已回收 | `blocked` / `owned_tree_cleanup_unconfirmed` | 2 |
| 预检/FREEZE/合同问题 | 与 `candidate` 相同（`page_limit_exceeded`、`input_or_contract_invalid` 等） | 2 |

回执：`receipts/WORKFLOW_CHUNKED_CANDIDATE.json`（续跑为 `WORKFLOW_CHUNKED_CANDIDATE.invocation-N.json`）列出每块页范围、路线、
尝试次数、每次尝试的墙钟时间、峰值内存、停止原因、清理结论、块质量；`receipts/invocation-N/` 下是该次调用的输入预检、
`chunk-plan`、`chunk-merge` 有界任务回执与续跑回收报告；每块完整回执在 `out/chunks/<id>/attempt-N/receipts/`。

## 续跑（`--resume`）

- 同一 `--output`/`--receipts`；FREEZE、输入、路线、目标语言、模型、服务地址、分块合同必须与第一次完全相同，否则拒绝。
- 先对本次运行目录下所有 launch 回执逐张做与尝试后核查相同的整树核实/回收（`reclaim_stale`）；回执读不了、缺字段、
  归属未知、枚举不完整或回收未核实，任何一项即失败关闭（`owned_tree_cleanup_unconfirmed`，`STALE_RECLAIM.json` 的
  `unverified` 非空、带 `reason_codes`），不续跑。
- 上次 `started` 未结束的尝试记为 `abandoned`，新尝试用新目录（`attempt-N+1`）；旧目录保留作证据。
- 已完成块只有在块 PDF、块 FREEZE、主版式译文、QA 可读件、综合质量、渲染清单、块回执（扫描块另含 OCR 重建源）的
  sha 全部一致时才复用；任何一个变化 → 记录 `invalidated.changed` 并重跑该块。
- 每次调用的合并输出写到新的 `merged-N/`，不覆盖上一次。
- 已登记的确定性失败（`failure.deterministic=true`，根因已核实）不重跑：续跑时比对登记的输入与配置身份（块 PDF、页范围、
  路线、整份运行身份、计划、该尝试的块 FREEZE、决定排版结果的实现文件 sha），一致即保留原失败、首个根因与全部尝试记录
  （块记 `not_reexecuted_by_invocations`，整份回执列 `deterministic_failures_not_reexecuted`），整份仍 `chunk_failed`、
  不部分交付；任何一项变化则照常重跑。`root_cause_unavailable` 等非确定失败续跑时照常重跑。

## 限制

- 合并后的主版式件是各块后端输出的页拼接：块内排版与单份 candidate 相同；跨块边界上未结束的段落由两块分别翻译
  （计划会尽量避开，避不开的记录在 `cross_chunk_continuations`）。
- 术语一致性检查只覆盖文档级术语表里带确定译法的术语；没有译法的候选术语只做出现统计。
- 目录/页码标签/内部链接按原文恢复（指向原页）；外部 URI 链接由各块后端保留。
- 每块单任务预算即冻结资源合同；整份文档没有总时限（块数 × 单块时间），也不并行（重任务并发 1）。
- 单页超过单任务预算时不能翻译（失败关闭，记录实测），需要另行处理该页。
- 归属判定只认正面证据（本次 nonce、本次进程组、已核验父链）；一个后代若离开进程组、清除该环境变量并在被观测前成为孤儿，
  仍无法识别（`WHOLE_TREE_ASSUMPTIONS`）。反过来，创建于本任务之后、环境读不到的同用户进程（非僵尸）会被计为归属未知而
  失败关闭——在 macOS 上若有这类常驻进程，守卫会保守地停止后续块（不会误杀）。
- 墙钟回拨后看起来早于根进程的进程（review-2 更正：此前文档写“不能识别”，实际代码在 42bd58c 及以前是把它静默丢弃、
  仍报 confirmed）：带本次 nonce 即所属并回收；读不到 nonce 时，只有单调启动证据（launch 回执的 `start_evidence`：
  Linux `/proc/<pid>/stat` starttime 滴答 + boot_id，macOS `ri_proc_start_abstime` + `kern.bootsessionuuid`；回执没有时仅在
  根进程仍存活且身份一致时现场读取）证明它在同一次开机内启动早于根进程，才排除；否则记为归属未知
  （`reason=ownership_unknown`，`code=older_than_root_nonce_unreadable`），不发信号、`unverified` 非空，守卫与续跑失败关闭、
  停止后续块。create_time 看似复用但单调启动读数与回执一致的根进程记为 `root_identity_clock_shifted`（不当作已退出）。
  代价：没有单调证据时（旧回执/手写身份且根已退出、或其它平台），任何读不到环境的同用户旧进程都会让守卫 unconfirmed；
  新回执在 Linux/macOS 上带证据，这类早于根进程启动的无关旧进程按证据排除，不受影响。
- 既有有界执行（`bounded_execution`）的启动身份仍按 PID + create_time 核对。Linux 上 create_time = btime + 启动 jiffies，
  虚拟机暂停/墙钟校正会让 btime 前跳（实测 +198 s 至 +4701 s），任务运行中会因“PID 已复用”被拦截：该尝试按瞬时失败重试一次；
  尝试后核查以启动 nonce（环境变量）认出仍存活的进程树，回收时对“带本次 nonce 且记录身份读作 pid_reused”的进程以观测
  create_time 刷新身份后回收（无 nonce 的复用号码仍绝不发信号）；仍无法核实即 `chunk_cleanup_unconfirmed`，停止调度。
  macOS 上 create_time 在进程创建时记录，不随墙钟重新推算。
- 资源门靠周期采样执行：整机冻结（虚拟机暂停期间 uptime 仍在走、采样线程不运行）时无法在冻结中途停止任务。实测两次：
  nist48 c011（第 1 轮）121.64 s、c008（第 2 轮）123.96 s，冻结后第一个采样即以 `task_timeout` 停止、回收 0.12–0.17 s，
  回执如实记 `deadline_met=false`；第 3 轮 nist48-rerun c008a 157.02 s（冻结 88 s）同理。
- 非分块的单次 `candidate` 没有“身份竞态按瞬时失败重试一次”，墙钟跳变时该次运行失败关闭（需重跑）。
- 块按顺序逐个执行（重任务并发 1），不做并行翻译。
- 外层 `peakmem` 之类的整树合计计量会把重叠的两棵任务树相加（第 1 轮 arxiv2610 曾读到 5.172 GiB）；合同计量的是单个
  有界任务（同次实测单任务峰值最高 3.03 GiB）。
