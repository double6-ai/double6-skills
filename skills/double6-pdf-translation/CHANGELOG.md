# 变更记录

## 2.0.0-rc.9 本地发布候选 · 2026-10-23

- 输入预检拒绝后的下一步提示（2026-10-24，未改版本号）：`candidate` 输入预检以 `page_limit_exceeded` 或 `non_digital_pages` 拒绝时，stdout 与持久化回执 `WORKFLOW_INPUT_PREFLIGHT.json` 增加同一个结构化 `guidance`（`input_preflight_guidance_v1`，中文），只依据稳定错误码与预检已核实的页数/页型：整份页数在分块上限（500 页）之内且路线为 `digital_pdf`/`scanned_ocr` 时指向只读 `inspect-input`（最多 20 页）与既有 `chunked-candidate`，须先核对、再按整份重新冻结 parent FREEZE 与分块合同；超过 500 页、`latex_verified` 路线或页数未核实时不承诺路线；全部非原生页均为整页扫描图像时指向显式 `candidate --route scanned_ocr` 与既有 `inspect-input`/`prepare-scan`，并写明仍需原始具名源组/角色、人工复核及 1–5 页、Tesseract 引擎与公式/版式准入门；无文字层矢量页或未知页型、损坏/加密/其它错误、另有 error 级发现或非 `candidate` 动作不给路线；正常原生页不加提示。提示 `auto_switch=false`、`executed=false`：不自动切换路线、不分块、不执行任何入口；拒绝码、退出码 2、原 findings 文字与页数/页型字段不变，不放宽任何门。测试：`tests/test_input_preflight_guidance.py`。
- 下一步提示保留已请求的翻译方向（2026-10-24，未改版本号）：`guidance` 增加 `target_language`（即本次 `candidate` 经 argparse 校验的 `--target-language`，默认仍为 zh），接受该参数的执行入口命令原样带上它（`chunked-candidate … --target-language en|zh`、`candidate --route scanned_ocr --target-language en|zh`）；`inspect-input`、`prepare-scan` 不接受该参数，不加。`inspect-input` 固定按目标 zh 判定源语言，中译英长文档提示因此不再把它列为可运行的核对命令，扫描提示注明这一限制。目标语言未知或与预检实际使用的目标语言冲突时不给提示。拒绝码、退出码、默认目标语言与语言门不变。测试：`tests/test_input_preflight_guidance_direction.py`。
- 文档（2026-10-24，未改版本号）：README 第 5 行的当前候选版本说明由 `2.0.0-rc.2` 更正为 `2.0.0-rc.9`，与 `SKILL.md` `metadata.version` 和 `configs/default-routes.json` `candidate_version` 一致；只改说明文字，不改版本、发布状态、路线或代码。
- 凭据不进入子进程命令行（2026-10-24，未改版本号）：翻译服务凭据的唯一入口为环境变量 `LOCAL_TRANSLATION_API_KEY`（`scripts/credential_env.py`）。此前远端凭据以 `--openai-api-key` / 适配器 `--api-key` 放进电子 PDF 后端与 `qwen-cli` 适配器的命令行，进而进入同机进程列表、后端 DEBUG 日志、`CalledProcessError` 与 tenacity 重试日志，以及 `qwen-cli` 路线的翻译缓存库（命令串是缓存身份的一部分）。现在：
  - 电子 PDF 后端改由其原生配置环境变量 `PDF2ZH_OPENAI_API_KEY` 接收（PDFMathTranslate-next 2.8.2 `config/main.py` 的 `PDF2ZH_` 前缀与嵌套字段展开）；`qwen-cli` 适配器改为从继承的 `LOCAL_TRANSLATION_API_KEY` 读取，`--api-key` 仅为兼容保留。后端命令与适配器命令串不再含凭据，因此上述日志、异常与缓存库里也没有凭据。
  - 启动后端前清除继承的 `PDF2ZH_OPENAI_API_KEY`、`LOCAL_TRANSLATION_API_KEY`、`OPENAI_API_KEY`、`PDF2ZH_DEBUG`，再只放入该后端需要的一个变量（`PDF2ZH_DEBUG` 会让后端把含凭据的完整配置写进日志）。
  - 远端缺凭据：稳定错误 `remote_backend_requires_explicit_api_key`，在启动任何子进程或代理之前；兼容代理路线此前因地址已换成代理而跳过这项检查，现按原上游地址检查。回环地址仍用 `local-no-auth` 占位。
  - 缓存身份：`qwen-cli` 命令串仍含端点、模型与提示词；电子 PDF 后端的 OpenAI 翻译器缓存身份加入 `base_url`（此前只有模型、提示词等，不同服务同名模型的译文会被复用）。凭据不入缓存身份。既有缓存条目因此不再命中电子 PDF 路线，会重新请求。
  - 旧 LaTeX 直连（`pdf2zh_skill`，未随本仓库分发）：后端缺失时返回结构化错误 `latex_direct_backend_unavailable`，不启动子进程，端到端记 not_run；已安装且需要凭据时经本进程 `127.0.0.1` 转发器保留显式上游地址/模型/凭据，子进程命令行只含一次性令牌；转发器起不来报 `latex_direct_credential_forwarder_unavailable`。这条路线因依赖缺失无法在本仓库核实，不属于主路径失败。
  - `doctor` 只读 `LOCAL_TRANSLATION_API_KEY`（不再采用 `OPENAI_API_KEY`），结果新增 `credential`（来源与是否存在，不含值）；远端缺凭据时记 blocker `remote_backend_requires_explicit_api_key` 且不发请求。
  - 纵深防御（不是修复本身）：回执的命令行脱敏也处理 `--api-key VALUE` 这类“参数名 + 下一项”形式。
  - 边界：环境变量对同一用户的其它进程可见（`/proc/<pid>/environ`），不是保密隔离边界；不宣称完全隔离。扫描路线断点的参数指纹（`scanned_raster/checkpoint.py`）仍对含 `--api-key` 的参数求哈希（只存哈希、不存值），为保持续跑兼容未改。
  - 兼容代理背后的真实上游进入缓存身份（PR #25 review-1）：经本机 HY-MT 兼容代理时后端只看到 `http://127.0.0.1:<port>/v1`，同一端口、同一模型先后代理到不同真实上游时，第二个服务只收到健康检查、文本命中缓存并返回第一个服务的译文。现在本项目代理声明它实际转发到的上游身份（`scripts/upstream_identity.py`：规范化上游地址、上游模型、传输方式；去掉 userinfo 与凭据类查询参数，不含凭据）：`GET <base_url>/double6/upstream-identity` 与每个响应头 `X-Double6-Upstream-Identity`。电子 PDF 后端的 OpenAI 翻译器在任何缓存读写前取得它并加入缓存身份 `upstream_identity`，之后逐个响应核对，代理重启或端口被换到另一上游时失败关闭、不写缓存；`qwen-cli` 适配器命令串（即其缓存身份）在回环端点是本项目代理时追加 `--upstream-identity`，适配器同样逐次核对。模型、方向、提示词仍各自隔离，仅凭据轮换仍复用缓存。直连与非回环端点不变（不探测，地址本身即上游）。代理路线的既有缓存条目因此不再命中，会重新请求。
  - 测试：`tests/test_credentials_out_of_argv.py`（真实子进程 argv/环境哈希、真实适配器与 vendored 翻译器对本机记录服务的 Authorization 哈希、合成缓存库扫描、失败/超时/重试日志、回执与 WORKFLOW_INTERNAL_ERROR、缓存身份、doctor、LaTeX 直连接口与拒绝），`tests/test_upstream_identity_cache.py`（真实本机上游、真实兼容代理同端口换上游/凭据轮换/模型/方向/提示词/运行中换上游、qwen-cli 同类），辅助 `tests/credential_probe_backend.py`。
- 公式上/下标层级与可读版保真（PR #25 第二项，2026-10-24，未改版本号）：
  - 主版式压平：BabelDOC 段落切分按字距在基字与紧随的小字号上/下标之间补入合成空格（无源字形编号），角标判定“前一字符不是空格”因此不成立，`V_n^max` 的 `max` 成为基线上的普通样式片段（`<style>max</style>`），译后排在基线（doc 13：源 `max` 抬高 3.72 pt、`n` 降低 2.40 pt，成品 0.0 / −0.07）。现在：合成空格后、基字已是公式、字号 < 基字 0.79 且框中心竖向偏移 ≥ 0.15 字号的字符按角标并入公式（`styles_and_formulas.py`）；源文自带的空格字形、正文字体基字、同基线小字号文字不受影响。
  - 成品层级门（两个翻译方向通用）：新增 `scripts/formula_structure_check.py`，在源 PDF 与主版式成品上提取“数学字体基字 + 竖向偏移的小字号字形”上/下标关系，按整份文档匹配（容忍平移、缩放、重新分页），层级压平/翻转/偏移不足/丢失即综合质量 `formula_script_structure_lost`（high → fail，退出码 3，回执列页与样例）。读不了成品记 not_evaluated、不判通过（与渲染残留门同例）。
  - 可读版：此前 `final_readable.pdf` 由主版式的 `pdftotext -layout` 文本经 reportlab STSong-Light（不嵌入）重排，丢失 †、∆、ϕ、∂、−、组合附加符与矩阵括号分件（doc 18：U+2020 17→0 等 11 个码位），二维公式散开，标题取输出目录名（"out"）。现在含数学字形/上下标关系、或重排会丢字符的页，整页矢量复制主版式成品页（逐字形保留，并核对文字层一致），纯文字页仍重排并逐码位核对；标题取原文件名。不能保真时在写出前拒绝、不留下文件：`readable_page_mapping_unknown`、`readable_math_page_repair_conflict`、`readable_math_source_structure_lost`、`readable_codepoint_loss`、`readable_vector_copy_mismatch`、`readable_math_source_missing`（原文含数学结构而没有主版式成品可复制，例如后端失败；`final_pdf_manifest.json` 记 `status=refused` 与 `reason_code`；综合质量记待办 `readable_math_fidelity_refused`，不判 pass）。
  - 可读版按原文判定数学页（PR #25 review-3）：此前只用主版式页自身的数学证据决定矢量页，且仅在存在这样的页时才做原文结构核对；主版式已把 `V^2` 压成同基线 `V2`、数学字体/符号也已丢失时，该页被当作普通文字页重排，以 `status=ok` 写出损坏的可读版。现在只要提供源 PDF，就先在源 PDF 上逐页取数学证据：原文含数学时必做源↔主版式上/下标结构核对，任何页丢失层级即 `readable_math_source_structure_lost`（`evidence=script_relations_lost`）；原文与主版式页数相同时逐页比对，原文数学页在主版式整页不剩数学证据也同码拒绝（`evidence=main_layout_math_evidence_missing`）；页数不同（重新分页，逐页对应未知）时按整份判断，主版式不剩任何数学证据即拒绝，不按普通无数学页重排。源或主版式的数学证据取不到、结构核对抛错或未完成：新码 `readable_math_structure_unverifiable`（记 `stage`）。都在写出前拒绝、不留下文件。原文无数学的普通正文重排与数学页矢量复制不变。
  - 显式提供但不可用的输入不按“无数学”处理（PR #25 review-4）：此前 `if source_pdf and Path(source_pdf).is_file()` 把显式传入但不存在的原件路径直接跳过，原文核对被省略，压平的 `V2` 以 ok 重排写出。现在 `source_pdf` 不是 None 而不存在、不是普通文件、无读取权限或 stat/打开抛 OSError 时，写出前拒绝 `readable_math_structure_unverifiable`（`stage=source_pdf_unavailable`，不抛异常）；无效字节仍在 `source_page_evidence` 阶段同码拒绝。显式传入的主版式成品不可用（含无效字节）按“没有可复制的主版式”处理：原文含数学 → `readable_math_source_missing`，没有原件可核对 → `readable_math_structure_unverifiable`（`stage=math_source_pdf_unavailable`），原文无数学照常重排。存在矢量页而显式传入的修复前译文不可用 → `readable_math_structure_unverifiable`（`stage=original_markdown_unavailable`）。`pdf_translation_artifacts.render_qa_repaired_pdf` 原样传入输入 PDF 与主版式成品路径，不再先用 `is_file()` 折成 None。`source_pdf=None` 的独立普通 Markdown 调用不变。
  - 测试：`tests/test_pr25_review4_unavailable_source.py`（用户 review-4 两例原样搬入，及目录、无读权限、stat 抛错、无效字节、主版式成品/修复前译文不可用、独立入口、流水线调用方）；`tests/test_pr25_review3_readable_source_math.py`（用户 review-3 三例原样搬入，及原文数学页在主版式失去数学、多页只丢一页、原文无数学正文、重新分页两向、结构核对抛错/未完成、原文/主版式证据取不到等相邻边界）；`tests/test_formula_structure_fidelity.py`（真实段落夹具 `tests/fixtures/formula_scripts/`、角标相邻边界、普通中英文正文、层级门正反例与矩阵/闭括号/脚注边界、可读版矢量页/重排页/各拒绝码、综合质量接入）。
  - 边界：层级门只覆盖上/下标关系；求和上下限（叠放在运算符正下/上方）、分式、正文字体脚注号、正文字体闭括号后的上标不在其范围内。
- 后端失败根因上浮、确定性失败不重试（PR #25 第三项，2026-10-24，未改版本号）：
  - 问题：块的 PDF 后端在排版阶段按设计拒绝（如 17 号文档 c001：原文保留降级第 1 页 14 > 页上限 12，整份 17 ≤ 19；或 arXiv 2501.00659 c002 第 8 页可读下限溢出）后，子任务只报笼统的 `ValueError: PDF backend failed or changed route`（`input_or_contract_invalid`），外层任务状态 `failed`、无错误码，`classify` 判为瞬时，同参数原样重试 1 次（必然再失败），续跑时又重跑 2 次；整份回执只写 `error_code=transient`。
  - 现在：子任务从**本尝试**输出目录内的排版回执与 `render_manifest.json` 取稳定原因码与细节（`typesetting_source_fallback_cap_exceeded`、`typesetting_readable_floor_overflow`、`typesetting_writeback_failed`、`pdf_backend_timeout`），连同本尝试身份写 `BACKEND_FAILURE_ROOT_CAUSE.json`；父任务按 argv 与 launch nonce 核对回执与证据 sha 后才采信，核对不了或没有结构化证据即 `root_cause_unavailable`（写明 `problem`），不猜。确定性根因（含子任务自身的合同/输入拒绝）不重试，续跑在同一输入与配置下不重跑；`root_cause_unavailable` 仍按瞬时失败重试 1 次（本地 5xx/断连实测没有结构化证据）。根因写入块结果、`CHUNKED_RUN_STATE.json` 与整份回执（`root_cause`、`root_causes`、`deterministic_failures_not_reexecuted`）；完成块的质量门/可读版原因码上浮到 `chunks[].quality_reasons`。单份 `candidate` 回执同样带 `error_code`/`root_cause`，状态与退出码不变。
  - 不变：页/整份上限、正文翻译、公式与全部质量门；资源停止二分、身份竞态重试、`cleanup_unconfirmed` 停止调度；冻结的分块合同 `CHUNKING_CONTRACT` 逐字不变（既有 FREEZE 仍有效）。
  - 测试：`tests/test_pr25_review5_failure_root_cause.py`（根因提取与各种不可信证据、子任务→父任务真实结构化行与回执核对、伪造/过期/他尝试/被改动回执、确定 vs 非确定成对分类、首次与续跑编排、身份变化后重跑、cleanup_unconfirmed 与资源二分不变）。
- 文字 QA 按目标语言选择、双语产物按真实方向命名与标注（PR #25 第四项，2026-10-24，未改版本号）：
  - 问题：`collect_issues` 不看目标语言，中译英时把正确的英文译文报成“疑似大段英文未翻译”与 `must_translate`，并据此生成英→中残留替换计划；`build_standard_bilingual_output` 固定写出 `<stem>.en-left.zh-right.dual.pdf` 与 `layout=en_left_zh_right`，中译英的“中文源左、英文译右”被标成英左中右；`quality_report.md` 的检查项固定写“疑似大段英文未翻译”；双语视觉检查与交付门的提示写死“中文侧/英文侧”；Round38 候选单语页固定 `.zh.mono.pdf`。
  - 现在：文字 QA 目标语言取调用方参数 > `source_manifest` > `render_manifest`（渲染清单新记 `target_language`/`source_language`/`direction_basis`），都没有时沿用默认英译中并标 `legacy_default_en_to_zh`；中译英改查英文译文中的中文残留（`疑似大段中文未翻译`），译法含汉字的英译中术语/实体策略不参与，不做英→中残留替换；渲染清单“缺少中文可复制文本”只对中文目标；`quality_report.md` 写明文字 QA 目标语言，中译英检查项为“疑似大段中文未翻译”并新增 `chinese_residue_count`；独立入口 `check_translation.py` 新增可选 `--target-language`，写出的术语/实体策略同样按目标过滤。双语文件名/清单按调用方声明的方向：英译中不变，中译英 `zh-left.en-right` / `zh_left_en_right`，未知方向中性 `source-left.translation-right` / `source_left_translation_right`；清单新增左右角色、语言与标注；页序不变。
  - 不变：英译中的英文正文残留负例、中译英渲染中文残留门、URL/专名/参考文献/公式窄保护、全部门限与上限。
  - 测试：`tests/test_pr25_review6_direction_qa.py`（四个方向成对正负、默认/未知/冲突合同、参考文献与保护值、术语策略、双语名称/清单/左右页内容、LaTeX 副本、CLI、路线合同调用方）。
- 文字 QA 参考文献区只豁免有条目结构证据的文献条目（PR #25 第七轮复核，2026-10-24，未改版本号）：
  - 问题：`strip_zh_reference_lines`（中译英）在 References/参考文献标题之后只凭任意年份/DOI 等就把整行当文献剔除，且区域不再结束；含“2024 年”的普通未译中文正文因此不计入中文残留。英译中的 `strip_role_passthrough_lines` 同样只凭 `(2024)`/DOI/et al. 剔除。
  - 现在：两个方向共用同一判定，复用渲染残留检查（`render_residue_check`）已验证的逐条规则：参考文献区按条目切块（编号/作者开头起新块，续行与悬挂缩进并入），strong 条目剔除，weak 只在编号连续等正面证据下剔除，正文与未知块计数；中文条目按 GB/T 7714 结构（编号/作者开头 + 年份 + 文献类型标识/出处），第一人称/叙述句一律不算条目。区域在附录类标题或 Markdown 标题处结束，之后的正文/附录照常计数。剔除仍要求原逐行文献标记，豁免只比修复前更窄。
  - 不变：真实文献条目、保护值与专名的窄保护；全部门限、阈值与其它检查。
  - 测试：`tests/test_pr25_review7_reference_entries.py`（区内正文含年份/DOI 计数与真实条目放行成对、未知块、weak 编号序列、附录/标题章节恢复、第二个参考文献标题、英译中同一合同、豁免只收窄）。
- 文字 QA 参考文献条目须有作者角色证据（PR #25 第八轮复核，2026-10-24，未改版本号）：
  - 问题：`zh_reference_entry_class` 把编号与作者开头当作可互换的开头证据，`[4] 实验在 2024 年完成，……doi.org/…` 这类编号普通叙述凭“编号 + 年份 + DOI”成为 strong 被整段剔除；中文叙述只有第一人称窄否决。
  - 现在：编号只是可选前缀，年份/DOI 都不算出处。中文条目须有作者段（中文人名列表/“等”/机构作者，或 GB/T 西文作者著录、英文作者列表）+ 题名字段，年份与出处（类型标识后接 `.`/`//`、卷(期):页、出版地: 出版者、英文出处）须在题名字段之后；中文叙述按结构否决（逗号连接的多个分句、句中句号、第一人称）。英译中一侧同理：编号/年份/DOI 之外须有作者开头、作者列表、et al./缩写人名或机构作者结构，否则不算条目。未知仍计数，剔除仍要求原逐行标记（只收窄）。
  - 不变：真实条目（含悬挂缩进、机构作者、全角标点）、章节恢复、全部门限与其它检查。
  - 测试：`tests/test_pr25_review8_numbered_entries.py`（编号叙述与真实编号条目成对、两个方向、编号连续不能替代作者证据、章节恢复与悬挂缩进保留）。
- 新增长文档分块翻译 `chunked-candidate`（基线 item 5）。此前 `candidate` 只接受完整 1–5 页（FREEZE 页门 `page_limit_exceeded`），一份不能在一个有界任务（120 s、5 GiB RSS、重任务并发 1）内完成的长文档无法翻译。现在把文档按页范围切成一串有界块，每块是一次**普通** `candidate`（`digital_pdf` 或 `scanned_ocr` 原路线、原门），再按原页序合并。详见 `references/chunked-translation.md`。
  - 划分：电子块 ≤4 页、扫描块 ≤2 页；安全页边界（跨页表格、续表/续图题注、“continued on next page”、行尾开放运算符不切；段落未结束为软信号，避不开时记录到 `cross_chunk_continuations`）；`per_chunk` 路线按页类别把原生文字页送 `digital_pdf`、扫描页送 `scanned_ocr`。
  - 每块：块级 FREEZE（块 PDF 身份、1..k 页、parent FREEZE 与计划作为作用域证据、同一冻结资源合同）+ 块级上下文 `CHUNK_TERM_CONTEXT.json`（整份文档术语表/专名，sha 绑定）；单块单任务预算 = FREEZE 资源合同（120 s、5 GiB RSS、并发 1）。
  - 资源停止（任务超时、整任务时限、内存、后端内部超时 `backend_timeout`）二分到单页，单页仍超限 `chunk_page_exceeds_task_budget`；瞬时失败重试 1 次；门拦截与质量 fail 不重试；任一块无产物 → `chunk_failed`（退出码 2），不合并、不交付部分结果。
  - 合并（有界任务）：按页序拼接、逐页核对（页数/尺寸/旋转/图片指纹 vs 该块实际后端输入）、恢复目录/页码标签/内部链接并在写出的文件上核对、跨块字体与术语一致性；合并综合质量取最差的一块（OCR 封顶保留），永远不好于最差的一块。
  - 续跑 `--resume`：先回收遗留的本任务进程树（无法核实即失败关闭），已完成块的块 PDF、FREEZE、上下文、产物、质量、回执逐 sha 一致才复用。
  - 参考文献区跨块延续：整份源文上算出每页开始时参考文献区是否已打开，块从区中间开始时该块的渲染残留检查以“区已打开”起算（与整份一次检查相同；区内逐条规则不变）。
  - 尝试后核查：每次尝试后按启动 nonce 扫描存活进程，回收并复查；无法核实 → `chunk_cleanup_unconfirmed`、停止调度后续块。
- 实测发现并如实记录（第 1 轮证据，提交 86a6f61）：本机墙钟多次跳变（`/proc/stat` btime 02:43→03:19 共 +481 s）。既有 `bounded_execution` 以墙钟推算的 create_time 核对启动身份，跳变时把仍在运行的任务根进程判为“PID 已复用”并抛错，**未回收**该进程树；分块编排随即启动下一块，两棵重任务树重叠运行（违反重任务并发 1 / 不留孤儿），其中一次下一块被系统内存压力门停止。第 2 轮加入尝试后核查后，这种情况在下一块启动前回收并核实；身份核验错误按瞬时失败重试一次。第 1 轮共 4 次“PID 已复用”遗留树（nist48 c011a；arxiv2610 c001、c010 第 2 次、c017），其中 3 次与下一块重叠（nist48 c011a/c011b；arxiv2610 c001/c002，03:06:18 人工结束 c001 的进程组；arxiv2610 c010/c011）；c017 是最后一块，没有重叠，自行退出。arxiv2610 外层 `peakmem` 整树合计读到 5.172 GiB，是 c010 遗留树（约 2.47 GiB）与 c011（约 2.85 GiB）同时在跑的相加值；按块回执，单任务峰值最高 3,252,244,480 B（3.03 GiB），单任务最长 113.0 s，没有单个任务超过 5 GiB。
- 第 2 轮实测（提交 95d43ce）：虚拟机多次暂停（btime 前跳 +1054 s 至 +4701 s，uptime 不走）。nist48 c005 身份竞态按瞬时失败重试后完成；但 nist48 c008a、circ150 c001、arxiv2610 c001 的尝试后核查认出存活 nonce，回收却把根进程判为 pid_reused 而不发信号，只能失败关闭、停止调度，遗留树跑到自行退出（单个孤儿，未与下一块重叠）。修复：`reclaim_owned_tree` 对带本次启动 nonce、记录身份读作 pid_reused 的进程以观测 create_time 刷新身份后回收；无 nonce 的复用号码仍不发信号；成对测试 `tests/test_chunk_clock_step_reclaim.py`。另有两次单任务用时 121.64 s / 123.96 s：整机冻结期间采样线程不运行，冻结后第一个采样即停止，回执记 `deadline_met=false`（见限制）。
- 第 3 轮实测（提交 17e7bbd）：真实运行中再遇墙钟跳变（btime +39 s、+36 s、+1937 s、+672 s、+77 s），nist48 c009a / c008aa、arxiv2610 c009 / c015 的身份竞态均由尝试后核查以 nonce 认出并回收（`root_state=pid_reused`，核实确认），重试后完成，未与下一块重叠、未留孤儿。nist48-rerun 仅因第 1、16、48 页非原生电子页被路线门拦截（rc 2）；arxiv2610 c012 / c013 / c016 为图表区原生回写超出可读下限（与第 1 轮相同块，页内既有门）；circ150 由 OCR 门拦截；arxiv2501 合并完成，p8 渲染残留高 → 质量失败（rc 3，合并质量 = 最差块）。单任务最高 3.282 GiB；nist48-rerun c008a 用时 157.02 s：整机冻结 88 s（独立采样器同期停顿 93 s、uptime 照走）后第一个采样即 `task_timeout` 停止，回收已核实，回执记 `deadline_met=false`。
- CI 修正（提交 17e7bbd）：有界 `chunk-plan` 以运行目录为 cwd，CI 的全新 `PAPER_TRANSLATION_WORKSPACE` 尚不存在时整份退出 1；现先建运行目录，被普通文件占用则失败关闭。成对测试。
- 非分块 `candidate` 路径同样受墙钟跳变影响：回归中 ocr-zh-03 一次因“PID 已复用”失败关闭（单次 candidate 不重试），新目录重跑与 bd220a1 逐像素相同。
- PR #21 review-1（P1，同一 rc.9 普通提交系列）：尝试后核查与续跑回收把“查询失败”误当“已清理”。旧 `_live_owner_nonces` 把
  `Process.environ()` 的 AccessDenied 静默丢弃，nonce 集合为空即 `post_attempt_guard` confirmed=true；`reclaim_stale` 在根已退出、
  原组已空、脱组孤儿仍在时同样因 nonce 扫描漏掉孤儿而记 `already_gone`。修复：
  - 守卫/续跑逐张 launch 回执整树核实（`launch_receipt_recovery_scan_v2`），复用既有恢复扫描与 `reclaim_owned_tree`；归属未知
    不发信号、`unverified` 非空、稳定 `reason_codes`；无法核实即失败关闭并停止后续块。全机 nonce 扫描只作记录。
  - 同类相邻缺口：`launched_members` 运行期组外进程 environ/create_time 查询失败不再静默跳过（记 `ownership_unknown_during_run`，
    最终回收转恢复扫描核实）；恢复扫描 ppid 查询失败计为归属未知；带本次 nonce 但因墙钟回拨看起来早于根进程的后代按 nonce
    认定；僵尸与其它用户进程不计为未知；回执缺字段/核实抛错记 `receipt_verification_error`。
  - 不变：5 GiB / 120 s / 重任务并发 1、质量门、OCR 与中文路线、时钟跳变带有效 nonce 的回收、无 nonce PID 复用不发信号、原 34 项独立测试。
  - 测试 `tests/test_pr21_review1_guard_query_failures.py`：审稿 4 例（root/orphan × 正常/environ 拒绝）、run_bounded 真实脱组孤儿正反例、
    恢复扫描逐项查询失败正反例、resume 失败关闭/正常续跑，以及 PR #19 第 10 轮真实多跳父链的加固副本（标记原子发布、只读完整 JSON、
    启动后全程 try/finally；真实覆盖未知时接受严格 unconfirmed 且 unverified 非空）。原文件属于原 34 项，未改动。
  - CI（提交 7b84c5a，pdf Linux smoke 499 passed / 1 failed / 1 skipped）：`test_chunk_clock_step_reclaim.py` 的无 nonce 负例在 runner 上得到
    严格 unconfirmed（机器上另有属性读不到的同用户进程 → 归属未知，未发信号、无关进程存活）；该例与本轮相关正例改为接受严格
    unconfirmed（原因只能是归属未知、unverified 非空、未知项不是本例进程，并以警告输出明细），安全断言不变。这也意味着在存在这类
    进程的主机上，守卫会保守地停止后续块（不会误杀）。
- PR #21 review-2（同一 P1 的相邻情形）：42bd58c 的 `_recovery_scan` 在“按墙钟早于根进程”分支读 nonce 失败后
  `except: pass` 再 `continue`，把未知直接丢掉——墙钟回拨 + environ 读不到时，真实所属的脱组孤儿仍在写，却得到
  already_gone=1 / confirmed=true / unverified=[]（审稿 Mac 与本机均复现）。review-1 文档写的“不能识别”与代码不符，已更正。修复：
  - 新增 `scripts/launch_clock.py`（进程启动单调证据：Linux starttime 滴答 + boot_id；macOS ri_proc_start_abstime + bootsessionuuid）；
    `bounded_launch` 在回执写入 `start_evidence`；`reclaim_owned_tree` 对没有证据的身份在根仍存活时现场读取并固定。
  - `_recovery_scan` / `launched_members`：早于根进程且读不到 nonce → 仅当单调证据证明其早于根进程启动才排除，否则归属未知
    （`code=older_than_root_nonce_unreadable`）；nonce 匹配但 status 读不到的旧进程仍按所属（此前同样被丢弃）。
  - `_verify_receipt`：单调读数与回执一致的“看似复用”根进程记 `root_identity_clock_shifted`；预检发现、仍存活的归属未知不会因回收端
    再扫一次没看到而消失；`reclaim_stale` / `post_attempt_guard` 输出 `detail_codes`。
  - 不变：时钟回拨带有效 nonce 的回收、较早无 nonce 无关进程不误杀、原 34 项与原 4 个守卫用例的输入与断言、5 GiB / 120 s / 并发 1、
    质量门、OCR/中文/分块续跑。review-1 自己的 FakeTable 用例 `older-unreadable` 参数断言的正是被丢弃的行为，已移除并由新用例取代。
  - 测试 `tests/test_pr21_review2_clock_rollback_unknown.py`（18 项）。
- 版本号：2.0.0-rc.9。
- realmodel-r1 真实模型评测后续修复（2026-10-23）：
  - 可读下限溢出降级 `overflow_source_fallback`：缩字到可读下限（不低于下限）、框内折行、既有扩框都放不下时，只对短的、结构已确认的
    片段（表头/表格单元格、目录项/页码标签、图内标签）保留原文字形（原位置原字号，不裁切不重叠）；正文与含糊片段照旧整份失败。
    准入：结构角色（或通用短行几何上落在已检测表格区/图内节点）、源文 ≤40 字符且 ≤6 个英文词/≤16 个汉字、单句、无公式无占位符、
    单行、源字形可直通、译文非空且 ≤80 字符。上限：每页 max(3, 20% 段落)、每份 max(4, 10% 段落)，超限整批撤销并失败。
    每条降级写入排版回执，综合质量记 pending → 最多 unverified，永不 pass。
  - 渲染残留：References 标题区内的作者-年份条目（题名含普通动词、无出处的网页/预印本条目、URL 碎行）按条目结构剔除并在回执中计数；
    参考文献页上的正文段、只提到 “References” 的普通页、看似引用的未翻译正文照常计数；阈值不变。
- PR #23 review-1 修复（2026-10-23）：
  - 参考文献剔除收窄：`title_verb_waiver` 先用条目结构证明（纯作者名单 → 题名字段 → 含年份的其余字段，`entry_fields`），
    普通动词只允许出现在已证明的题名字段内；作者字段/其余字段出现正文动词、代词、句首词即不豁免。以作者开头的叙述正文
    （含带编号的）照常计数；阈值不变。
  - 原文保留降级的整份上限：分块翻译时块内只执行按页上限，整份上限 max(4, ceil(10% × 原始整份段落数)) 与按页上限
    （原始页码）在合并时统一执行；分母取自各块排版回执记录的原始每页段落数，每块的最低额度不会放大整份上限。超限 →
    `overflow_source_fallback_cap_exceeded`，回执缺失/不完整 → `overflow_source_fallback_receipt_incomplete`，均整份阻断
    （exit 2，不交付合并结果）；首次运行、续跑复用、不同块大小结论相同。单份翻译出现推迟作用域的回执 →
    `overflow_source_fallback_cap_scope_mismatch`，失败关闭。
- PR #23 review-2 修复（2026-10-23）：排版回执一致性核对。声明计数 `source_fallback_count`、`source_fallback_cap.count`、
  逐条数组 `source_fallbacks`、回执状态、上限状态、作用域与原始分母必须相互一致；损坏、无法解析、缺字段或自相矛盾的回执
  不再被折算成 0 条降级，综合质量记 `overflow_source_fallback_receipt_incomplete`（blocker，失败关闭）。分块合并要求每块
  恰好一份可核对回执，并按 SHA-256 重新读取核对（续跑复用时同样执行）；有任何问题时整份上限状态为 `incomplete`，
  不会再返回 `none`，整份阻断（exit 2，不交付）。没有旧格式兼容规则。
- layout-r1 版面修复（realmodel-r1 评测问题 #3、#4、#5，2026-10-23）：
  - 句首/句尾、标题边缘残留英文碎片（#3）：版面检测框比实际文字行窄时，框外字符此前只落在几何行框 `fallback_line` 里，
    成为单独的未翻译碎片段（如 “The Arti…t.”、“Executive S执行摘要”）。现在同一物理行（同一 `fallback_line`、同一 XObject、
    非竖排）的字符统一归入完整覆盖该行的正文类版面框；没有完整覆盖时，仅当唯一候选框纵向覆盖该行 ≥60% 才归入。
    行内混有非正文标签（表格单元格、图内标签等）的不改动。同类正文框嵌套时字符归外层框。
  - 目录/表目录被并成一段（#5）：上述嵌套框此前按 R 树顺序把一行分给内层框，表目录只剩 3 行，达不到目录拆分的 4 行门槛，
    4 条表名与页码并成一段。现在保持 4 行、每条独立且页码分开。
    真实运行复核时另发现：目录拆行后的 “Table N …” 条目又被表题规则改标为 `table_caption`，页码因此不拆；
    词间距贴近阈值时目录标题读作 “Table ofContents”，导致 “Executive Summary 1” 的页码不拆。现在目录拆行产生的条目
    不再被改标为表题（无目录拆行证据的表题不变），目录标题匹配不依赖词间空格。
  - 表头/表格行被并成一格（#5）：表格区内的单行行段落，按全表各行共同的列间空白（所有行的文字片段都不跨越的竖向空隙，
    且至少两行跨越该空隙）拆成单元格；有数据单元格跨过空隙的位置不拆，表格区外的行不拆。
  - 链接/样式行内段的行距过小导致重叠（#4）：直通原字形的字符单元此前用墨迹高度计行高，整行全为原字形（如引用、蓝色链接）
    时行距约为正常的一半，与下一行重叠。现在行高取 max(墨迹高度, 字号)；纯中文行行距不变。
  - 不变：质量门、残留门、分块与续跑、溢出降级上限与回执核对、参考文献剔除、进程回收、5 GiB / 120 s / 并发 1。
  - 新增 `tests/test_layout_line_fragments.py`（5 个回归 + 6 个反例）与 `tests/fixtures/layout_fragments/`（NIST AI 100-1 页面片段，美国联邦政府作品）。
  - PR #24 评审 review-1 收窄（P1、P2）：
    - 嵌套正文框此前不论内容一律归外框，外框把左右两栏一起框住时两栏被合成一段、阅读顺序交错（P1）。现在只在“同一文字流的重复检测”
      证据齐全时才归外框：内框覆盖外框宽度 ≥60%、外框里没有与内框并排的其他正文框、且至少一条物理行连续地跨过内框左右边缘。
      按物理行统一归属时，行碰到横向分离的两个正文框、或不同归属之间隔着 ≥1.5 个字号的空白（栏间空白），一律不合并。
    - 表格行拆分此前把“各行对齐的空白”当作列证据，已有单元格框的单列表格（如 “New York USA”）被拆成逐词碎片（P2）。现在落在
      版面检测单元格框里的段落不拆，单元格框横跨的空白不是列边界；对齐空白之外还须有可信列证据之一：同表某行在此处已是两个独立段落、
      有竖直表格线穿过、或两个单元格框在此分界。只有对齐空白时不拆。
    - 新增 `tests/test_pr24_review1_layout_boundaries.py`（评审原测试，仅改路径）与 `tests/test_layout_boundaries_adjacent.py`
      （4 个反例 + 4 个正例）；原 11 个版面用例不变。
  - PR #24 评审 review-2：review-1 收窄后，17b 表 2 表头只在一处有“他行已分段”的证据，表头被并成 “均差* 校正 p” 与
    “下限 上限 拒绝原假设”，译后 Adj./Upper/Reject 偏离源列 +8.14/−5.00/−11.38 pt。源 PDF 的数据行本身就是列证据：
    “-0.018 0.000”“-0.027 -0.008 TRUE” 是一行里相邻的值，左锚点与表头字段左锚点相差 ≤0.15 pt。现在数据行里两个相邻的值记号
    （数字、布尔量、常见占位符）在共有空白处分开、且右侧的值与另一行片段在同一列锚点上（左/右/中线 ≤2 pt）时，该空白算列证据；
    词与词之间的对齐空白仍不算，单元格框内的值不拆。表 2 的 7 个表头字段与数据列重新一一对应。
  - 新增 `tests/test_table_value_columns.py`（17b 表 2 真实几何正例 + 合成正例 + 3 个反例）与夹具
    `tests/fixtures/layout_fragments/arxiv2512.18979-p5-table2-header.json`。

## 2.0.0-rc.8 本地发布候选 · 2026-10-22

- 新增扫描件 / 混合 PDF 的常规 OCR 路线 `candidate --route scanned_ocr`（基线 item 4）。原 `digital_pdf` 路线遇到扫描页一律在预检以 `scanned_pdf_route_required` 拒绝，`scanned_raster` 只能整页重绘、不产生可翻译文字层；现在可把扫描页 OCR 重建为带文字层的数字 PDF，再走**原有**数字后端、全部质量门和严格验收。
  - 引擎：Tesseract 5.5.0（Apache-2.0）+ tessdata_fast `chi_sim`/`eng`/`osd` 4.1.0（Apache-2.0），本机运行、免费、无 API、无密钥。缺少引擎时 `doctor` 报 `ocr_engine_status=missing`，只影响本路线，不影响 `digital_pdf` 主路线；本路线以 `ocr_engine_unavailable`（退出码 2）拒绝。
  - 流程：`ocr_route.py` 在既有有界执行（`run_bounded`，操作名 `ocr-reconstruct`）下运行，tesseract 子进程计入本任务 RSS、按 PID + create_time / nonce / 父链核验并回收；重建 PDF（扫描页 = 清理后的背景 + 可见文字层，数字页原样复制）→ 对重建 PDF 做数字预检（要求 digital）→ `_execute-digital --ocr-manifest --ocr-manifest-sha256` 绑定 OCR 清单 → 原数字后端与全部门。OCR 与翻译共用同一冻结合同：120 s 时限、RSS 任务上限（本版调为 5 GiB，见下条）、重任务并发 1。
  - 质量：`comprehensive_quality` 在 OCR 路线上封顶为 `unverified`（`cap_ocr_quality`，原值记在 `quality_status_before_ocr_cap`）；OCR 生成的文字层不是质量验收，仍需独立质量包。
  - 失败关闭（退出码 2，稳定错误码，见 `references/ocr-route.md`）：页面 < 0.97×最低 DPI（`ocr_resolution_too_low`）、有格线或列间隙表格（`ocr_table_unsupported`；格线检测在 OSD 之前）、公式/数学符号（`ocr_formula_unsupported`）、识别不确定（`ocr_low_confidence`：单页 > 2 行或 > 3% 字符不确定；某行有可读词置信度 < 50 时须多遍识别一致才采用）、语言不符、无扫描页、方向无法确定、倾斜 > 1°、竖排、文字压在图形/印章上、页内原生与扫描混排、分块扫描、矢量化文字等（共 17 个错误码）。不靠删公式、遮挡正文、降阈值或只记风险来过门。
  - 多遍核对：弱行第 2 遍按行裁切 psm 7，前两遍不一致时第 3 遍 1.5 倍放大；任意两遍一致即采用（一致不等于正确，见限制）。正文行字号上限防止乱码行被画成大号标题（本轮实测 “L,拒收方式: USER R” 被当成标题导致回写失败）。
- **RSS 任务内存上限 3 GiB → 5 GiB（5,368,709,120 B；用户决定，PR #20 第 2 轮）**。计量口径仍为 RSS（任务进程树逐进程 RSS 之和），120 s、并发 1 不变，其它资源门（进程数、系统内存压力、swap 增长、Codex 熔断、时限、整树回收与身份核验）不变。
  - 单一来源 `scripts/resource_limits.py::RSS_TASK_LIMIT_BYTES`（`RSS_CONTRACT` 为对应合同）。这是**所有路线共用**的 RSS 上限，不是 OCR 专用：macOS 平台默认（未冻结时）由 3 GiB 调为 5 GiB，`doctor` 在 macOS 上推荐的合同随之变化；`scanned_ocr` 推荐冻结合同为 `RSS_CONTRACT`。`configs/default-routes.json`、命令行帮助、SKILL.md、release-quickstart、ocr-route 同步。
  - 不变：Linux 平台默认仍为 4 GiB **PSS**／300 s（不是 RSS 上限）；平台默认最多物理内存 25%（16 GiB 的 Mac 默认被夹到 4 GiB），冻结值最多 50%（5 GiB 需要 ≥ 10 GiB 物理内存，否则 `task_memory_limit_exceeds_host_authorization`）；旧 FREEZE 里的 3 GiB/120 s 合同（`LEGACY_CONTRACT`）照常接受并**按冻结值 3 GiB 执行**，要用 5 GiB 须重新冻结。`examples/` 中的历史发布样本记录保留当时的 3 GiB 值。
  - 原因与实测：pdf2zh 后端进程树 RSS 合计 2.5–3.3 GB（写时复制共享页按 RSS 重复计入；PSS 2.25–2.85 GiB），3 GiB 下真实扫描件 en-01 三次全被内存门停止、en-03 三次停两次。5 GiB 合同下（新冻结合同、新运行目录）en-01、en-03 各 3/3 通过，en-02、zh-01、zh-02、zh-03 各 1/1 通过；后端 RSS 合计峰值最高 3,336,155,136 B，距 5 GiB 余 2,032,553,984 B（约 1.89 GiB，37.9%）。数字路线英译中 7 份、中译英 17/18 在 5 GiB 合同下与基线逐像素相同，05/16 照旧失败关闭。
- **扫描页上下标 / 叠排分式在覆盖原图之前拒绝（PR #20 review 1，P1）**。此前 300 dpi 栅格页上的 `x²` 被 OCR 读成 `x?`，文字门看不到数学证据，原像素被覆盖、重建 PDF 写成 `x?`。新增图像几何门（`ocr_route.line_script_evidence` / `fraction_bar_evidence`）：逐行连通域 → 基线与 x 高 → 抬高/压低的小字形，只有 OCR 在同一词里确实读出的引号、撇号、`*`、`°`（抬高）或词尾逗号/分号（压低）且形状吻合时才算标点；叠排分式按“短细横线 + 上下紧贴字形”判定。命中则整页以既有稳定错误码 `ocr_formula_unsupported`（`details.evidence = image_geometry`）拒绝，错误码集合不变。复用电子路线 `_math_like_glyphs` 的字号比/基线偏移思路与框线门的二值化、OpenCV 连通域，无新依赖。真实扫描 en-01..03、zh-01..03 结论不变，拒绝样例错误码不变。已知局限：脚注上标号与上标序数词同样被拒；单字母/数字后的撇号不作解释；上标与相邻字形粘连时会漏判；汉字行里紧贴汉字的小号上下标按汉字笔画放过（详见 `references/ocr-route.md`；后两条已在 review 2 修正/收窄，见下条）。
- **汉字旁的数学上下标在覆盖原图之前拒绝（PR #20 review 2，P1）**。此前汉字行里最近 OCR 词是汉字的小字形被当作汉字笔画放过：`估计量甲²…` 被读成 `甲-`、`估计量甲₂…` 被读成 `甲,` 并覆盖原图。现在不再按“最近词是汉字”跳过，改看汉字方块规则性（小部件能否与紧邻的 1–2 个簇拼成 0.75–1.1 字高的方块，且高 ≤ 0.4 字高）与标点形状（汉字行标点高 ≤ 0.4、抬高记号宽 ≤ 0.26 字高，汉字之间的 `，` 照常可作解释，记号按个数分给各自的词）；新增粘连上下标检测（拉丁行：高出升部线的边缘墨迹、边缘纯下标列；汉字行：边缘纯下标列、高出汉字顶端 ≥ 0.12 字高的边缘纯上标列）与带圈序号检测（`①` 被 OCR 改写为 `中`）。命中照旧以 `ocr_formula_unsupported`（`details.evidence = image_geometry`，带可疑框）拒绝，错误码集合不变，其它门不变。真实扫描 en-01..03、zh-01..03 结论不变，拒绝矩阵不变；中文标点、常用字、`［1］` 式序号原样通过。剩余漏判按实测写在 `references/ocr-route.md`（粘连且高出汉字顶端 < 0.12 字高的汉字行上标等）。
- vendored BabelDOC `pdf_creater.py`：字体子集化 / 清理保存辅助进程改用 spawn 上下文。fork 出的辅助进程按 RSS 计入父进程约 2.5 GB 的共享页，任务 RSS 合计曾测到 5.9 GB；spawn 子进程只计自身。数字路线输出不变（回归像素比对见 PR）。
- 已知限制（如实列出）：
  - 内存：后端进程树（工作流 + `_execute-digital` + pdf2zh 父进程约 319 MB + pdf2zh 子进程 2.0–2.6 GB）RSS 合计 2.5–3.3 GB。3 GiB 合同下 en-01 三次都被 `task_memory_limit` 停止、en-03 三次过一次（这些历史结果保留原值）；上限调为 5 GiB 后均通过，余量约 1.89 GiB。pdf2zh 闲置父进程（约 319 MB）未缩小。
  - 严格页门会拒绝很多真实中文公文页（miit 794 号文 9 页中只有 p2、p6 可用，其余因低置信或表格拒绝）。
  - 多遍一致不等于正确：例如“接入”被两遍都识别为“撑人”并采用；“（三）”误识为“(=)”保留；孤立的不确定短行（“用。”→“Fil.”）仍可能写出。这些都在 `comprehensive_quality=unverified` 之下交付，需人工复核。
  - 不支持：上列失败关闭的版面；长文分块。繁体、手写未测试，不作支持声明。
- 版本号：2.0.0-rc.8。

## 2.0.0-rc.7 本地发布候选 · 2026-10-22

- 新增中译英（基线问题 F4）：`candidate --route digital_pdf` 加 `--target-language en`（默认 `zh` 英译中，命令行与回执逐字不变）。
  - 根因一：输入预检固定以中文为目标，中文源文一律 `source_language_matches_target` 退出码 2。现在按目标语言判断（同语言两方向都拒绝），不支持的目标语言报 `target_language_unsupported`。
  - 根因二：工作流与后端写死 `--target-language zh`、`--lang-out zh`。现在透传目标语言，中译英时以 `--lang-in zh --lang-out en` 调用后端。
  - 根因三：提示词与默认术语表只有英译中版本（如 “AI Index => 人工智能指数” 会要求输出中文）。新增中译英默认提示词（自定义提示词不替换）；中译英时不注入译法含汉字的术语条目。
  - 根因四：中文源文抽取按英文间距规则补空格，两端对齐的汉字被切成“所 示 。忽 略”，污染请求与缓存键。汉字间隙 < 0.5 字高时不补空格，表格单元格间的大间隙照旧。
  - 根因五：英文排版沿用中文框。单行段落（标题、图注）先借右侧空白再缩字；到可读下限仍放不下时借右侧、下方空白；英文按整词宽度断行（原式重复计入当前字符宽度，造成 “c|ontext” 断词）。只在拉丁目标语言生效，英译中排版不变。
  - 根因六：最短长度过滤按英文设计，“样本量”“荣誉组”等短中文标签被跳过、作为中文残留留在译文里；紧凑标签的英文启发式对汉字不适用。中译英时含汉字的短段落照常翻译、含汉字的紧凑标签放行；不含汉字的段落（公式碎片、英文专名、数字）保留原字形不送翻译。
  - QA：新增渲染中文残留检查 `render_chinese_residue`（页 ≥0.30 高、≥0.10 中，全文 ≥0.25 高；源页 <100 汉字不按比例评估，见下方评审修正）。
- 评审第 1 轮修正（PR #19 @ feb0694，反例测试 `tests/test_pr19_review_boundaries.py`）：
  - 本地 Qwen（`--translator-mode auto` 选中 CLI 适配器）忽略目标语言：英译中的译名修补把英文译文里的 “Stanford University” 改回“斯坦福大学”，重试提示要求“译成简体中文”。现在目标语言经 `--target-language` 传给适配器（未传时按系统提示词是否为中译英默认提示词推断），中译英时不做英译中修补、重试要求译成英文、文档级术语只注入译法不含汉字的条目。英译中命令行与行为不变。
  - 模型把短中文正文原样返回会被当作“受保护内容”写回：原样分类只认拉丁字母。中文源时去掉占位符/URL/引用等受保护片段后仍含汉字即判未翻译（`ordinary_same_as_input`，拒绝写回）；英译中分类不变。渲染残留检查：短页（<100 汉字）中整行中文源句（≥12 字）逐字出现在译文里判 high；所有页都短时按整份文件合计评估（≥24 汉字）。
  - 英文扩框只看段落、字符和图片，会越过矢量表格线：扩框现在同时受矢量路径（表格线、单元格/节点边框）、Form XObject 与版面表格区域限制，不借越线获得“放得下”。只在拉丁目标语言生效。
  - `--route latex_verified`、`collect` 与 `--target-language en` 组合：两者的译者固定译成简体中文，现在在预检和任何模型调用前以 `target_language_route_unsupported`（退出码 2）拒绝；后端遇到中译英 + HY-MT 兼容代理/原生传输时报 `target_language_backend_unsupported`。
  - 行内对象公式（失败关闭，不是修复）：中文正文行内的变量/公式若由 Form XObject 文字（Word/WPS 公式，例如 arXiv:2510.26803）或字形大小的填充矢量路径（MathJax/网页打印公式，例如中文维基 Transformer 页）绘制，排版引擎无法让它们随英文重排，会与译文压叠或被丢弃。预检按结构证据检测（清空 Form XObject 内容流前后的文字差集、字形大小的填充路径，且中心落在同一文本块的中文行内部），中译英时以 `zh2en_inline_object_math_unsupported`（退出码 2）在翻译前拒绝。成品兜底：源文保留字形与译文压叠（`retained_glyph_overlap_high`）、矢量路径公式字形成批丢失（`vector_glyph_loss_high`，每页少 ≥3 个且 ≥25%）都判 `fail`（退出码 3），不再只记中风险。
- 评审第 2 轮修正（PR #19 @ f14bb7e，反例测试 `tests/test_pr19_review2_sparse_math.py`）：上一轮的预检要求每页 ≥3 个行内对象、成品门要求压叠 ≥10 字符或矢量字形少 ≥3 个，中文正文行内只有 1–2 个矢量公式字形或 Form XObject 变量（如单个 M）时两道门都放行，“少于 3 个由成品检查兜底”的说法不成立。
  - 预检：中文正文行内定位到 **1 个**行内结构对象即以 `zh2en_inline_object_math_unsupported` 拒绝；整页被包进 Form XObject 时改用原页中文行定位矢量字形，不把 Form 内正文当作行内对象（此处理在第 3 轮改为逐个 Form 分类，见下条）。
  - 成品门（绕过预检时的独立兜底）：逐个核对源页已定位的结构对象——矢量字形在原位（±1.5pt）找不到即“丢失”，与译文字形相交超过 30% 即“压叠”；Form XObject 变量在原位找不到同字符即“丢失”，与其它字形相交超过 50% 即“压叠”。任何一个都判 high（`inline_object_damage_high`，退出码 3），不依赖整页净计数和字体名。源文保留字形与 Noto 译文压叠的阈值也从 10 个字符降为 1 个。
- 评审第 3 轮修正（PR #19 @ 82fb369，反例测试 `tests/test_pr19_review3_wrapped_form.py`）：第 2 轮的整页 Form 处理只要页内存在 Form 且清空全部 Form 后找不到中文行，就把 Form XObject 字形整体置空；无损地把整页再包进一层 Form 后，嵌套在里面的行内 Form 变量会被这一层包装隐藏，预检与成品门同时放行。
  - 预检改为逐个 Form 归类：对每个 Form（含嵌套层级）单独清空其内容流，求它负责绘制的字形；这些字形里有同一行的 ≥2 个汉字即为“正文 Form”（`body_forms`），否则为“行内 Form”（`inline_forms`）。只清空行内 Form 来求中文行与 Form XObject 字形差集，外层正文包装不再导致内层变量被丢弃；矢量字形仍按（正文 Form 保留后的）中文行定位。成品门复用同一函数，因此同样修正。
  - 回归：纯正文整页 Form、单层/双层包装、页面正文与 Form 正文混排（有/无嵌套变量）、包装页内的矢量字形、包装页内的图形与正文行外公式均有测试。
- 评审第 4 轮修正（PR #19 @ 9bff9ee，反例测试 `tests/test_pr19_review4_chinese_formula_form.py`）：第 3 轮只要 Form 自己绘制同一行 ≥2 个汉字就当作正文 Form；带中文下标/短标签的行内公式 Form（如 “M最大”）因此被当成正文，变量 M 从预检和成品门两边的证据里消失（原页与整页包装后都是 ok）。
  - 带中文行的 Form 再按结构判断是否“嵌在中文宿主行里”（`_hosted_in_cjk_line`）：宿主行由 **Form 之外**的汉字构成（同一行 ≥2 个汉字）；Form 绘制的文字须同时满足：(1) 纵向中心落在宿主行的纵向带内；(2) 总高 ≤ 1.6 个宿主字高（单行）；(3) 宽度 ≤ max(4 个宿主字高, 宿主行汉字跨度的一半)；(4) 与宿主行最近汉字的水平间隙 ≤ 1.5 个宿主字高（或与之重叠）。四条都满足即为行内 Form（计入 `hosted_cjk_forms`），其中的拉丁/数学字形照常作为行内对象；否则为正文载体（整页外壳、正文块、图注块、行外标签、多行旁注、与左栏同高的右栏行）。逐个 Form（含嵌套层级）判定，不按“含中文”一刀切。
  - 语料复核：05、16、17、18 及全部英文文档的行内对象计数与第 3 轮相同（16 号没有带中文行的 Form）。
- 评审第 5 轮修正（PR #19 @ 905dbf3，测试 `tests/test_pr19_review5_mixed_form.py`）：第 4 轮的宿主行判据用高、宽、间隙上限决定带中文的 Form 是不是行内公式，超出上限就当作正文；带中文分母的竖式分数（M/总数）、超宽公式、间隙大的公式、带上下限的求和都因此漏掉变量，两道门都 ok。这一轮把默认值反过来：**只有正面确认为正文的 Form 才算正文**。
  - 每个 Form（含嵌套）只按**自身**内容（扣除内层 Form）分类：container（自身不画内容，如整页外壳，只递归看内层）、object（自身不画汉字）、body、mixed。
  - body 准入：自身画汉字，且没有任何数学证据。数学证据包括：数学符号或希腊字母；数学或斜体字体；孤立的单个拉丁字母（两侧紧邻处没有拉丁字母或数字）；字号与 Form 自身汉字字号之比超出 0.75–1.33 的拉丁字母；分数线（细横线，正上方和正下方紧邻处都有 Form 自身的字形）。普通英文单词和数字（Transformer、MIMO、2024）不算。
  - mixed（有数学证据）时：数学证据落在宿主中文正文行里（Form 之外、字号不小于页面主体 0.75 倍的中文行；或 Form 自身至少 4 个汉字的正文行，用来覆盖公式与正文画在同一内容流的情况），判 **needs_review**：以 `zh2en_inline_object_math_unsupported`（exit 2，`details.pages[].reasons` 含 `mixed_form_needs_review`）拒绝，数学字形和分数线逐个计入成品门 `inline_object_damage`（分数线类型 `form_rule`）。不在任何正文行里的（图内标签等）记为 `standalone_mixed`，不计入、不拦截。尺寸不再作为忽略已定位证据的理由。
  - 行为变化：整页包装后，正文里的文字层公式（如 `M×N`）与正文同在一个 Form 内容流中，改判 needs_review（原页不变）。第 4 轮正例里图注的孤立变量 N、旁注的孤立字母 a 现在判 needs_review，并作为反例单独测试；第 4 轮正例的这两处改为年份/编号。（第 6 轮撤销：包装改判与年份/编号替换都已撤回，第 3、4 轮正例按原样恢复，见下一条。）
  - 语料复核：全部 22 个可打开的语料文档（含 48 页英文长文）逐页行内对象计数与第 4 轮相同，17、18 与英文文档没有新增拦截。
  - 不在中文行内的小图标、行首项目符号、行外图形 XObject、文字层公式不受影响；17、18 号及全部英文语料定位数为 0。
- 评审第 6 轮修正（PR #19 @ f90dce4，测试 `tests/test_pr19_review6_text_runs.py`；第 3、4 轮正例先按 905dbf3 原样恢复，只改键名 `hosted_cjk_forms`→`needs_review_forms`）。每个结论都先用真实后端端到端回放（905dbf3 与预检旁路两条路径，本地回放答案）核对成品，再定判定：
  - 撤销第 5 轮“整页包装后文字层公式改判 needs_review”。新增**页面等价 Form**（`page_equivalent_forms`，计入 `body_forms`）：某个 Form 连同内层画出了整页的全部文字与路径（页面内容流与外壳什么都不画）时，它自身的内容按页面级内容对待，内层 Form 照常逐个分类。证据：原页与包装后后端收到的请求逐字相同、成品逐像素相同。包装不再改变任何判定（原页、单层、双层包装三者一致，有测试）。
  - 文字层公式（页面级或页面等价 Form 自身绘制，如中文行里的 `M×N`）：预检照旧不拦，但逐个记入 `text_layer_math`。真实后端把这个 `M×N` 整个丢掉（原页与包装后都丢），905dbf3 却以退出码 0 交付。新增成品门 `text_layer_math_loss`：按字符多重集核对这些字形在译文页里是否仍在，少一个即判 high（退出码 3）。按字符计数可能漏判（英文单词里的同一字母会掩盖变量丢失），不会因为重排误判；17、18 号成品分别核对 13、61 个字形，0 丢失。
  - 第 4 轮正例（图注 N、旁注 a 的那一页）保持拒绝，原始输入逐字保留，断言改为拒绝：真实后端成品里，N 从“（ N 为阵元数）”被挪到行尾（“( is the number of elements)N”），a 落在 Form 裁剪框外只剩一个点。两个字母都是整行中文画完后另起一段、用另一种字体补画的。
  - 孤立字母/斜体词的准入（复用规则，有配对正反例）：拉丁字形与同行中文同属一个**按视觉顺序绘制的文本流**时不算数学证据。条件是：同一 Form 同一视觉行的字符按 x 排序后绘制顺序严格递增，与最近的汉字字号相同；孤立单字母还须与该汉字同一字体，斜体/数学字体的字形只有作为多字母单词（斜体物种名、书名）时才准入。数学符号与希腊字母始终是数学证据。证据：同字体同文本流的“（N 为阵元数）”“A 公司”“方案 B”与按视觉顺序绘制的斜体 *Homo sapiens*，成品都在原位；事后补画的同样字母被挪到行尾或丢失，另一字体的单字母仍拒绝。
- 评审第 7 轮修正（PR #19 @ d11bafa，评审用例 `tests/test_pr19_review7_text_layer_counter.py`、`tests/test_pr19_review7_monitor_permissions.py` 先原样加入，只改路径；回归 `tests/test_pr19_review7_fixes.py`）：
  - `text_layer_math_loss` 漏判（第 6 轮的整页字符计数）：英文单词里的字母（如 expressions 里的 x）会顶替丢失的行内变量 x。现在**逐实例核对**：源页每个文字层数学字形须在译文页匹配到一个同字符、且本身是数学实例的字形，每个译文字形只用一次。数学实例：数学符号/希腊字母（任何位置）；整段都是严格数学字体（CMMI 等，不含普通斜体）的 token 里的字母；独立字母（按空白/控制字符、>0.2 字号的间隙、字号突变、数学字体切换切分 token，去掉首尾标点后所在连续字母串只有它一个，且两侧不是 `.` `-` `'` 等单词连接符，如 `x`、`x,`、`(p<0.001)`、`Appendix B.`）。英文单词内部的字母一律不算。a/A/I 本身是英文单词：只有与源字形同一字体名、且源字形有区别性样式（粗体/斜体/数学字体）或它嵌在不同字体的重排英文里时才算保留。匹配不到即判丢失（high，退出码 3），失败样本带原因（`only_inside_words`、`ambiguous_english_word_letter`、`absent`）。不按原坐标核对位置（译文会重排）。`text_layer_math` 条目增加 `font`/`size`/`flags`。
  - 证据：评审的两个负例（原页、整页包装）由通过改为判失败，两个正例仍通过；17、18 号第 6 轮成品重新核对 13、61 个字形，0 丢失（17 号的 `(p<0.001)`、`Appendix B.`、保留原粗体的 `A` 需要上述切分与字体证据，整页计数之外的初版判据曾把它们误判为丢失，按渲染与 token 核查后修正）；s3 两例仍判丢失 M、×、N。真实后端（Linux 本地回放，无模型）对评审的斜体 x 页：x 以 Times-Italic 留在原坐标、与英文重叠，重叠门判失败（退出码 3），与评审 macOS 结论一致；同一成品去掉 x 后新门判丢失（有测试，成品按逐字符几何存为 JSON）。
  - macOS 监控崩溃：`snapshot` 用 `psutil.process_iter(["pid","name","memory_info"])`，取非本任务进程名称时 C 扩展抛出 `SystemError`（KERN_PROCARGS2），异常发生在迭代器内部、循环体之前，原 `except` 接不住，入口在 PDF 已生成后以退出码 1 结束，没有 stdout 和最终回执。现在非本任务进程的 Codex 遥测逐进程隔离：迭代器不带属性，`next()` 受保护（出错即结束本次扫描并在样本里记 `unowned_scan.complete=false`），名称与内存逐进程在 `try` 里取（NoSuchProcess/ZombieProcess/AccessDenied/PermissionError/SystemError/OSError 只跳过该进程并计数）。本任务进程树的发现改为按 `psutil.pids()` 逐个检查，不再依赖迭代器。
  - 本任务进程计量不可靠时结构化停止（不吞错误、不关监控）：本任务进程取内存失败（进程消失除外）→ `owned_process_monitor_unavailable`；进程树无法枚举 → 同一错误码；采样本身抛异常 → `resource_monitor_unavailable`；基线取不到则不启动任务。三者都走资源门同样的路径：终止并清理本任务进程树，写失败回执（稳定 `failure_code`），工作流结果 `status=stopped`、`error_code` 即 `stop_reason`，退出码 1。所有资源门（任务内存、进程数、系统内存压力、swap 增长、Codex 熔断、时限）不变。工作流入口对未预期的内部错误也输出结构化 JSON 并写 `WORKFLOW_INTERNAL_ERROR.json`（`error_code=internal_error`，退出码 1）。
  - Linux 证据：注入同样的 `SystemError`（只对非本任务进程）后，d11bafa 在基线采样处以退出码 1 结束、stdout 为空，复现评审的崩溃；修复后完整跑完（退出码 3，质量门失败），stdout 与 `WORKFLOW_CANDIDATE.json` 都已写出。未注入时 3 GiB RSS 合同下一次运行被内存门停止（后端 fork 的瞬时子进程按 RSS 重复计入共享页，峰值 4.38 GB），重跑两次与 d11bafa 一样峰值约 2.6–2.7 GB、正常完成——这是采样时机，不是本次改动引起的。
- 评审第 8 轮修正（PR #19 @ a2ab530，评审用例 `tests/test_pr19_review8_discovery_cleanup.py` 原样加入只改路径，回归 `tests/test_pr19_review8_owned_cleanup.py`）：
  - 缺陷：取得可信启动身份后，若 `root.children()` 或 PID 列表查询失败（`OwnedDiscoveryError`），`discover()` 只返回此前的成员缓存；首次发现就失败时缓存为空，`.cancel` 文件拦不住已 exec 的任务，`stop_children([])` 什么也不做，回执却报告 `owned_tree_alive=[]`、`observed_owned_identities=[]`。Linux 端到端复现（a2ab530，首次发现失败注入）：工作流 3.4 秒返回 stopped，实际 3 个任务进程仍在运行、输出继续增长。
  - 修复：`OwnedDiscoveryError` 携带已核验的启动身份（nonce、父 PID、根 PID + create_time、进程组）与已确认成员；`run_bounded` 始终保留它们。新增 `reclaim_owned_tree`，不依赖全机进程枚举的后备回收：已确认成员逐个按 PID + create_time 核验后 SIGTERM，超时 SIGKILL；`bounded_launch` 以 setsid 新建进程组（pgid == 根 PID），整组发信号前核对组长：create_time 相符才视为本次的组；组长 PID 被其它进程复用即判原组已空（内核在组内仍有进程时不会复用该 ID），不发信号；组长已退出时先 `killpg(pgid, 0)` 探测，并在每次整组发信号前再次核对组长 PID 未被复用；组长状态无法查询时不发信号、记为未核实。
  - 独立核实与回执：运行结束时再做一次核实，回执 `cleanup` 字段给出 `verified_dead`（每个 PID 的 create_time 与证据 dead/zombie/pid_reused）、`unverified`（still_alive / state_unknown / group_not_empty / group_state_unknown / group_leader_identity_unverifiable）、`process_group`（pgid、组长状态、发过的信号、`empty_verified` 由 `killpg(pgid,0)==ESRCH` 核实）、`alive_before`、`signalled`、`signal_errors`、`not_covered`、`passes`；另有 `launch_identity`。无法确认时 `status=cleanup_unconfirmed`、失败回执 `failure_code=owned_tree_cleanup_unconfirmed`（`metadata.stop_reason` 保留原停止原因），工作流 `error_code=owned_tree_cleanup_unconfirmed`、退出码 1。正常完成路径同样核实进程组为空。资源门与预算未改。
  - 测试检查真实进程死亡（PID + create_time，`os.kill(pid,0)` 交叉核对）、停止后写文件不再增长、回执完整：首次发现失败（PID 列表失败、`children()` 失败两种）、已采样若干次后失败、根进程已退出而同组孙进程仍在写、中间进程退出后被重新挂接的同组孙进程；负例：同时运行的无关进程（自己的会话、与测试同组）不被回收；伪造身份（PID 指向无关进程但 create_time 不符）不发任何信号；信号被拒时报告 `cleanup_unconfirmed` 并列出未核实对象。
- 评审第 9 轮修正（PR #19 @ 244a721）。评审用例 `tests/test_pr19_review9_cleanup_boundaries.py` 原样加入（只改路径），回归测试见 `tests/test_pr19_review9_whole_tree.py`：
  - 缺陷：所属枚举失败时，若子进程 setsid 脱离了启动进程组且从未被发现，它不在已确认成员里，原进程组也已空。第 8 轮只在 `not_covered` 写一句备注，回执却给出 `cleanup.confirmed=true`、`unverified=[]`，该子进程仍在写文件。
  - 修复（整树核实与已确认成员/原进程组分开记录）：
    - 回执新增 `cleanup.tree_scope`，字段为 `known_members_reclaimed`、`original_group_empty_verified`、`enumeration_failed_during_run`、`whole_tree_verified`、`basis`、`reason`、`recovery_enumeration.scans`、`assumptions`；另有 `cleanup.recovered_members`。`not_covered` 字段删除。
    - 运行期间只要有一次所属枚举失败，回收时就做恢复扫描：信号前、信号后各一次，结束时再做一次核实。
    - 恢复扫描先用 `psutil.pids()`，失败再用独立的完整枚举（Linux 读 `/proc`，其它 POSIX 用 `ps -A`）。
    - 只回收正面核验为本次任务的进程：create_time 不早于根进程，且满足下列之一：
      - 环境里带本次启动 nonce（`PAPER_TRANSLATION_BOUNDED_OWNERS`）；
      - 仍在本次启动进程组内（组长 PID 未被复用）；
      - 父进程链连到已核验成员。
    - 归属读不到的同用户新进程不发信号，记为 `ownership_unknown`。
    - 以下三种情况都判 `whole_tree_verified=false`：恢复扫描不完整（`descendant_enumeration_incomplete`）、存在归属未知进程（`ownership_unverifiable`）、所属进程仍存活（`owned_process_still_alive`）。此时 `unverified` 写入 `{"scope": "whole_tree", ...}` 条目，`status=cleanup_unconfirmed`，`error_code=owned_tree_cleanup_unconfirmed`，退出码 1。
    - 正常运行（没有枚举失败）不做扫描，行为不变。
  - 第 8 轮测试 `test_root_exited_descendant_in_group_reclaimed` 不再要求"必须发过组信号"，只断言安全结果：真实死亡、停止写入、原进程组为空、无关进程存活。逐 PID 终止后组已空时不发组信号是正确行为。只有组回收才能覆盖的场景（同组成员从未被发现、完整枚举也失败）另写测试，验证该成员真实死亡。
- 评审第 10 轮修正（PR #19 @ 0e74710）：恢复扫描的祖先链改为逐环核实身份。评审用例 `tests/test_pr19_review10_reused_ancestor.py` 原样加入（只改路径），回归测试见 `tests/test_pr19_review10_ancestry_identity.py`。
  - 缺陷：`_recovery_scan` 直接把缓存的已知成员当作祖先起点，没有核对这些 PID 当前的 create_time。如果旧成员的 PID 被一个无关的新进程复用，这个新进程的孩子（ppid 等于旧号码、出生晚于旧时间）会按 ancestry 被判为所属。之后发信号前只核对孩子自己的身份，挽回不了错误的父链。
  - 修复：
    - 已知成员只有当前 PID 的 create_time 与记录一致（存活或僵尸）时才能作祖先起点。已复用、已退出或无法查询的旧号码记入 `rejected_ancestors`，不授予归属。
    - 每一跳在判定时重新核实父进程的 PID + create_time，并要求子进程出生不早于该父进程。
    - 父链指向被拒号码（或父进程身份在扫描中发生变化）、又没有独立 nonce/进程组证据的进程，连同其后代，记为 `ownership_unknown`：整树未核实，`cleanup_unconfirmed`，绝不发信号。
    - 复用号码上的新进程作为普通候选，按自身证据判定。
    - 最终核实扫描同样带上已知身份。
    - 有效的同身份多跳父链、本次 nonce 和脱组后代的回收都保持不变；没有关闭祖先链，也没有扩大回收范围。
  - 测试：
    - 模拟进程表的用例，用 spy 截获 `_signal_pid`、`os.kill`、`os.killpg`，不真的发信号。正例：多跳有效父链、带 nonce 的孩子。负例：复用的根、复用的已知中间成员、已退出成员、身份无法查询的成员。负例断言候选不含无关孩子，且它们没有收到任何信号。
    - 真实进程用例：三跳脱组、无 nonce、无进程组证据的父链被回收，运行期间新起的无关进程存活。
- 新增 `tests/test_zh2en_translation.py` 与 `tests/fixtures/zh2en/`（arXiv:2512.18979、2510.26803 CC BY 4.0，arXiv:2601.14329 CC0 1.0 的真实逐字符几何与正文），仓库不提交 PDF。
- 已知局限：行内公式由 Form XObject 或矢量路径绘制的中文 PDF 不支持中译英（预检拒绝）；另一字体（如 Times）的孤立单字母（Word 里常见的“A 公司”写法）与事后补画的字母仍判 needs_review（拒绝）；文字层公式由后端丢弃时只能在成品门判失败（退出码 3），无法修复；`text_layer_math_loss` 不核对位置，后端把变量留下但挪了位置时由重叠门而非本门判定，未与其它字形重叠的挪位不会被本门发现；以正文字体孤立重排的 a/A/I 变量没有字体证据，判丢失（可能误判，失败关闭）；译文里本来就有的同字符独立字母（如 “type x”）可以顶替丢失的变量，仍可能漏判；Codex 熔断只能基于成功读到的非本任务进程，读不到的进程不计入（扫描不完整会记在资源回执里）；所属进程树枚举失败时，后备回收只覆盖已确认成员与启动进程组；离开该进程组（自行 setsid/setpgid）的后代靠回收时的恢复扫描（启动 nonce / 父进程链）发现，扫描也失败时整次清理报告为 `cleanup_unconfirmed`（`tree_scope.whole_tree_verified=false`）；同时离开进程组、清掉 `PAPER_TRANSLATION_BOUNDED_OWNERS`、且在被观察到之前父进程已退出的后代无法识别（正常路径同样如此，回执 `tree_scope.assumptions` 写明）；以 setuid 等方式换了用户的后代不在恢复扫描的归属判定范围内；归属读不到的同用户新进程会让结果保守地变为未确认；父链指向已复用/已退出/无法核实的旧成员号码、又无 nonce/进程组证据的进程同样保守地记为归属未知（极少见的情况下会让实际已清理的运行报告为未确认）；读取 ppid 与核实父进程身份之间仍有极短的竞态窗口（每跳在判定时重新核实，不能完全排除）；组长已退出、组也已空之后，在探测与发信号之间该 ID 被新进程组复用的极短竞态窗口无法完全排除（每次发信号前都重新核对组长）；后备回收只在 POSIX 上可用；正文 Form 的英文译文超出 Form 裁剪框时会被截断（第 6 轮证据：右栏“…number of”、续表标签只剩“Table”），现有成品门不检测；Type3 字体源文不沿用粗体；中文参考文献按残留计数；图片内中文不翻译；本版本译文验证使用本地回放答案，未用真实模型验证。
- 未改动：扫描 OCR、长文档分块。

## 2.0.0-rc.6 本地发布候选 · 2026-10-22

- 修复双栏数学论文行内公式丢失/错位（基线问题 P1，例如译文“即设 ,对所有 ,。我们将其记为 。”）：
  - 根因：行切分遇到上下标、大括号、CMEX 定界符等高字形时，相邻两条视觉行在纵向重叠，被合成同一个 `PdfLine`；折行两侧的行内公式字符被归成一个跨两行、外框覆盖整行的“公式”，随后 `merge_overlapping_formulas` 把同一 `PdfLine` 里其余公式全部并入。译文请求里只剩一个 `{vN}`，其余位置留下空洞，排版时这块公式按原位置散落，与译文重叠。
  - 公式分组在保守判定的栏内折行处断开（回到栏左缘、上一字形在栏右侧、并落到其下方）；行内分式、居中多行公式不受影响。
  - 禁止跨折行合并公式，也禁止合并中间夹着正文的两个不相邻公式（会改写阅读顺序；同时修正了参考文献中 `35:16344–16359` 被打乱成 `35 16359, 2022 16344: –` 一类的错序）。
  - 下标/上标里的逗号（如 `M_{i,j}`）不再把公式拆成三段。
  - 行内分式线等零高度线段现在归入所属公式，随公式移动，不再留在原处划过译文。
- 新增真实论文（arXiv CC BY 4.0：2501.00659、2610.21231、2610.21759）段落几何夹具与回归测试 `tests/test_inline_math_wrap.py`；夹具来源与许可见 `tests/fixtures/inline_math/README.md`，仓库仍不提交 PDF。
- 版本统一为 2.0.0-rc.6（SKILL.md、默认路线配置、输出中的 `skill_version`）。本改动原以 rc.4 提交（PR #17），在 rc.5（表格与图内文字，PR #18）合入 main 后合并到其上并改为 rc.6；rc.4 未单独发布。两者没有共用的运行时代码文件。
- 未改动：表格/图内文字抽取、中译英、扫描 OCR、长文档分块。

## 2.0.0-rc.5 本地发布候选 · 2026-10-18

- 修复表格文字与图内文字中英混排、错位（基线问题 F2/F3：USGS《Mineral Commodity Summaries 2024》第 4 页表格行名一半留英文、译文行压到下一行；第 2 页图 1 节点文字未翻译）：
  - 根因一：`compact_label`（原样保留的紧凑标签）只按字符集和尺寸判定，表头、行名、图内短语与数据集名、方法名一样被整段跳过翻译。现在在表格区域、有色填充节点（含紧贴节点的标题）和图表题注内只保护名称/标识符：含小写实词、功能词、冒号字段名、图表题注或多词标题式短语的标签照常翻译；单个首字母大写词只在与可翻译文字同栈/同行时随上下文翻译；全大写缩写、数字、驼峰、URL、机构后缀、小写点缩写（i.i.d.）及无自然语言信号的标签继续原样保留；白底/浅灰绘图区里的图例、坐标轴文字维持原行为（图例多为方法名且排得紧，送去翻译会在硬可读下限下放不下而阻断整份文档）。
  - 根因二：图内填充节点里的多行标题/说明逐行成段，每行单独翻译或跳过。同一填充节点内同字体、同左缘、行距正常、且无同基线并列格的连续单行，现在合成一个翻译单元。
  - 根因三：译文首行按源字框下沿排版，而源字框下沿包含下伸部，单行表格行整体下移约 0.3 em（Arial 10pt 下 2.7pt）压到下一行。新增 IL 字段 `PdfParagraph.source_baseline`，单行表格/图内段落的译文首行落在原文基线上（只上移、最多半行）。
  - 根因四：带千分位的数字（26,900）不算纯数字，被送去翻译并以回退字体缩小重排；非首页的独立年份（表头 2019）被当作封面年份翻译。现在千分位数字与非首页年份原样保留。
  - 表格/图内角色中 3–4 个字母的普通词（Coal、Rate、Loss、Cost）不再因最短长度被跳过。
- 评审第 1 轮修正（PR #18 @ 33918b3）：
  - 基线锚定的上移量受正上方相邻行限制：排版前按页为每个锚定段落计算 `source_ceiling`（正上方段落、未入段字符、细表格线渲染后不会低于的位置；有锚点的上一行按「min(源基线, 框底 + 自身余量)」自上而下传递），上移后的行顶不越过它，越过即报不合身，不再出现「两行都 fit=True 却重叠」。USGS 图 1 中紧贴下划线的「净出口／净进口」行不再压线；表格行仍落在原文基线。
  - 上下文放行收窄并保护专名：单个首字母大写词只借大写起首的同类标签放行（紧挨小写文字如 dataset 的 Amazon 视为专名，继续原样保留）；借上下文放行的词标记 `context_released`，模型原样返回时保留原文字形（writeback `preserved` / `context_released_source_identity`），不记为未翻译或回退失败。自身就是自然短语的标签原样返回仍判失败。
  - 机构名规则只认法律实体后缀（Inc、Ltd、Corp、LLC、LLP、PLC、GmbH）；Group、Company、Institute、University、Lab 同时是普通名词，表头 Control Group、Treatment Group 现在照常翻译，带缩写的机构名（Meta AI）仍由缩写规则保留。
- 新增真实文档几何夹具与回归测试 `tests/test_table_figure_text.py`（USGS 公有领域；arXiv CC BY 4.0：2610.21653、2610.21759、2610.20087），来源与许可见 `tests/fixtures/table_figure_text/README.md`，仓库仍不提交 PDF。
- 版本统一为 2.0.0-rc.5（SKILL.md、默认路线配置、输出中的 `skill_version`）。本版本与 rc.4（行内公式，PR #17）相互独立，合并顺序不同时版本号需随之调整。
- 未改动：以矢量轮廓绘制的图内文字（需要 OCR）、表格整体重排、中译英、扫描 OCR、长文档分块。

## 2.0.0-rc.3 本地发布候选 · 2026-10-17

- 修复 `inspect-input` 不带 `--catalog-url` 时子进程参数含 `None` 导致的 TypeError；有界执行回执和失败收据保留脱敏、截断后的真实错误消息，不再只记异常类型名。
- 资源上限可配置：`--task-memory-mib`、`--job-timeout-seconds`、`--memory-metric` 及对应环境变量；平台默认 macOS 3 GiB RSS／120 秒（不变），Linux 4 GiB PSS／300 秒，默认不超过物理内存 25%，显式值最多 50%。Linux 按 PSS 计量，避免 fork 子进程共享页被重复计入；回执记录实际峰值。后端超时随作业时限推导，120 秒时仍为 110/90。
- 新增结构化输入预检（`pdf_input_preflight.py`）：分别报告用户密码加密、所有者权限限制（警告）、截断/损坏、页数超限、非原生电子页（扫描/转曲）、源语言等；`inspect-input` 与 `candidate`/`collect` 共用同一 `findings` 结构，失败时输出 JSON 并以退出码 2 结束，不再打印原始 traceback。
- 源语言检测：源文主要为中文而目标为中文时直接拒绝（`source_language_matches_target`），不再静默输出中文。
- 新增基于实际成品的渲染英文残留检查（`render_residue_check.py`）：大面积未翻译判为高风险，综合质量 `fail`，`quality_report.md` 顶部写明。
- `candidate` 退出码区分质量失败：综合质量 `fail` 时译文照常写出，但以退出码 3 结束（预检拦截仍为 2），结果 JSON 列出 `quality_fail_reasons`（检查项、页码、残留比例与逐页等级）、`quality_fail_summary` 和 `output_files`。
- 评审修复（PR #16）：
  - FREEZE 绑定动作（`candidate`、`collect`、`resume-latex`）以冻结的 `resource_contract` 为唯一预算；命令行/环境变量与冻结值不同即以 `resource_override_conflicts_with_freeze` 拒绝，回执 `resource_limits` 记录实际执行的上限。
  - 渲染英文残留检查不再计入参考文献段、等宽代码、URL/DOI/邮箱/arXiv 编号、编号与作者-年份引用；正文已译、参考文献保留英文时不再误判失败。
  - 退出码 3 由综合质量结论驱动，覆盖 LaTeX 路线、`resume-latex`、`revise-latex`、`preserve-roles` 及其它产出综合质量的动作；`comprehensive_quality.json` 优先于 `render_manifest.json`。
  - 输入预检在页数超限时立即返回，不再逐页解析；`candidate`/`collect` 的预检移入有界子进程（1.5 GiB RSS／60 秒）。
  - 有界执行的峰值内存计入基线与收尾样本，并在启动后 50 ms 先采一次样，快作业不再记为 0。
  - PSS 快照测试改为跨平台运行，不再在非 Linux 上跳过。
- 评审修复第二轮（PR #16）：
  - 参考文献区域改按几何阅读顺序（行框、双栏、通栏区段）确定，不再依赖内容流顺序；区域内逐条校验是否为文献条目，普通正文照常计入；译文侧剔除量以源文同页剔除量为上限。
  - 字母编号附录（`A Proof …`、`A.1 …`、`B Additional Results`、`Appendix A`、`附录`）结束参考文献区域，其后正文计入残留。
  - 无标题参考文献：连续 ≥3 条严格条目（行首编号/作者缩写、年份、DOI/arXiv/卷页、会议期刊词，且虚词比例低）才剔除，普通英文正文不受影响。
  - 文档：旧合同未写 `memory_metric` 时按 RSS 计量，视作业可能超出预算，建议重新冻结。
- 评审修复第三轮（PR #16）：
  - 修复漏判：带人名、年份、编号和指标的英文实验正文曾被当作无标题参考文献整段剔除（源与译文两侧同样剔除，残留率 0.0）。
  - 新增正文否决（指标枚举、多个小数/年份/叙述式引用、第一人称、谓语动词、句首连接词），参考文献标题之后的区域同样适用。
  - 无标题参考文献改为强结构证据：编号或作者开头 + 年份 + 出处信号的 strong 条目至少 3 条、左边距一致、位于文末或节末，全文剔除量不超过源文英文词一半；译文侧只在源文已接受的页上剔除；候选段写入 `excluded.headingless_runs` 供审计。
  - 更正文档中“局限只会偏严”的说法：已知仍有漏判路径，见运行说明。
- 评审修复第四轮（PR #16）：
  - 修复漏判：3 条真实文献条目之后的 57 词英文实验叙述（无出处信息）曾被归为 weak 并随整段剔除（ok / 0.0）。
  - weak 条目默认计数，只有正面证据才剔除：编号与紧邻条目连续，或紧接未结束条目的栏首/页首续接残段；无标题段与 References 标题区域使用同一套逐条规则。
  - 审计输出逐条决定：`excluded.headingless_runs[].entries_detail` 与 `excluded.reference_region_entries`。
  - 分组修正：`2000. 标题` 这类以年份开头的续行不再被当作 `n.` 编号而拆开条目；作者名支持非 ASCII 大写字母和行尾连字符断词；`. In …` 计为出处信号。
- 版本统一为 2.0.0-rc.3（SKILL.md、默认路线配置、输出中的 `skill_version`）；新增本 skill 的 pytest 覆盖与 Linux 冒烟 CI。
- 未改动：行内公式重建、表格/图内文字抽取、中译英、扫描 OCR、长文档分块。

## 2.0.0-rc.2 本地发布候选 · 2026-10-17

- 纠正来源基线：同步源项目第 111 轮当前开工合同；五条路线仍称 110，旧长说明移入本地历史归档，不再作为公开包入口。
- 旧 rc.1 的最新版与可发布结论撤回；当前候选以 111 合同和本次实际成员重新核验。
- 电子PDF源账本改为流式身份校验，保留原规范字节序列与磁盘/内存篡改拒绝。
- 外层有界监督下的冻结缓存作业复用后端进程；CPU ONNX 不跨批预留推理缓冲，阶段结束释放可重算源解析缓存。
- 源编译器搬迁后仍完整重编译并比较源内容；历史与当前源码分别核 SHA，原生响应、失败和调用计量不改写。
- 翻译后按本次源核验事件核完整段落成员和不可变科学字形；不同已审逻辑组共享原生宿主时保留换行。
- 将既有新字体精确 Unicode 绑定用于普通电子 PDF，防止后续兼容性清理丢失空格；原始科学字体不改。
- 具名三页电子 PDF 的完整生成及冷重建保持 3 GiB／120 秒；LaTeX 完整单元独立技术审校、普通阅读复制和冷重建逐项核验，用户接受与严格交付另记。

## 2.0.0-rc.1 / 110-unpublished 本地发布候选 · 2026-10-17

- 同步源开发版的扫描输入预检、审后单配置准备、冻结重建及现有电子 PDF/可信 LaTeX 工作流。
- 保留完整源组、角色、语义、实际 PDF、字体样式、链接、阅读复制和冷重建要求。
- 随包提供必要共享执行代码，分离用户运行目录，使用 skill 内相对脚本路径。
- 移除缓存、环境、历史产物和无许可证明的旧 LaTeX 实现；精简默认安装中的 GUI 和其它模型服务商 SDK。
- 公共工作流要求明确模型与服务地址；冻结重建继续离线运行。
- 当前仅本地准备，未获得当前精确成员的新发布接受；旧工作区测试和 trial.2 发布身份不自动迁移到本候选。

- 按职责拆分五个大脚本，保留兼容入口及回调替换行为。
- 补充 LaTeX 完整失败单元审校、计量与断点恢复；原始响应和保护校验继续保留。
