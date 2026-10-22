# 变更记录

## 2.0.0-rc.8 本地发布候选 · 2026-10-22

- 新增扫描件 / 混合 PDF 的常规 OCR 路线 `candidate --route scanned_ocr`（基线 item 4）。原 `digital_pdf` 路线遇到扫描页一律在预检以 `scanned_pdf_route_required` 拒绝，`scanned_raster` 只能整页重绘、不产生可翻译文字层；现在可把扫描页 OCR 重建为带文字层的数字 PDF，再走**原有**数字后端、全部质量门和严格验收。
  - 引擎：Tesseract 5.5.0（Apache-2.0）+ tessdata_fast `chi_sim`/`eng`/`osd` 4.1.0（Apache-2.0），本机运行、免费、无 API、无密钥。缺少引擎时 `doctor` 报 `ocr_engine_status=missing`，只影响本路线，不影响 `digital_pdf` 主路线；本路线以 `ocr_engine_unavailable`（退出码 2）拒绝。
  - 流程：`ocr_route.py` 在既有有界执行（`run_bounded`，操作名 `ocr-reconstruct`）下运行，tesseract 子进程计入本任务 RSS、按 PID + create_time / nonce / 父链核验并回收；重建 PDF（扫描页 = 清理后的背景 + 可见文字层，数字页原样复制）→ 对重建 PDF 做数字预检（要求 digital）→ `_execute-digital --ocr-manifest --ocr-manifest-sha256` 绑定 OCR 清单 → 原数字后端与全部门。OCR 与翻译共用 120 s 时限、3 GiB RSS、重任务并发 1，均未放宽。
  - 质量：`comprehensive_quality` 在 OCR 路线上封顶为 `unverified`（`cap_ocr_quality`，原值记在 `quality_status_before_ocr_cap`）；OCR 生成的文字层不是质量验收，仍需独立质量包。
  - 失败关闭（退出码 2，稳定错误码，见 `references/ocr-route.md`）：页面 < 0.97×最低 DPI（`ocr_resolution_too_low`）、有格线或列间隙表格（`ocr_table_unsupported`；格线检测在 OSD 之前）、公式/数学符号（`ocr_formula_unsupported`）、识别不确定（`ocr_low_confidence`：单页 > 2 行或 > 3% 字符不确定；某行有可读词置信度 < 50 时须多遍识别一致才采用）、语言不符、无扫描页、方向无法确定、倾斜 > 1°、竖排、文字压在图形/印章上、页内原生与扫描混排、分块扫描、矢量化文字等（共 17 个错误码）。不靠删公式、遮挡正文、降阈值或只记风险来过门。
  - 多遍核对：弱行第 2 遍按行裁切 psm 7，前两遍不一致时第 3 遍 1.5 倍放大；任意两遍一致即采用（一致不等于正确，见限制）。正文行字号上限防止乱码行被画成大号标题（本轮实测 “L,拒收方式: USER R” 被当成标题导致回写失败）。
- vendored BabelDOC `pdf_creater.py`：字体子集化 / 清理保存辅助进程改用 spawn 上下文。fork 出的辅助进程按 RSS 计入父进程约 2.5 GB 的共享页，任务 RSS 合计曾测到 5.9 GB；spawn 子进程只计自身。数字路线输出不变（回归像素比对见 PR）。
- 已知限制（如实列出）：
  - 内存余量小：后端进程树（工作流 + `_execute-digital` + pdf2zh 父进程约 319 MB + pdf2zh 子进程 2.0–2.6 GB）RSS 合计 2.5–3.26 GB，贴近 3 GiB。本轮真实扫描样本中 en-01 三次都被 `task_memory_limit` 停止，en-03 三次过一次；RSS 合计重复计入写时复制共享页，PSS 峰值 2.25–2.85 GiB。未放宽限额；可选方案（按 PSS 计 3 GiB、RSS 3.5 GiB、或缩小 pdf2zh 闲置父进程）列在 PR 中待决定。
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
