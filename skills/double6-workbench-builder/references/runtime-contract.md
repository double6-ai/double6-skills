# Double6 工作台制作器

把反复要做的事做成一个可离线打开的 `index.html`，数据只留在当前设备。常见场景：个人一周执行、选题到人工发布、销售跟进、儿童学习、备考或生活记录。从本 Skill 根目录运行 `python scripts/double6.py`（Python 3.10+）。版本、命令和 schema 以 `manifest.json` 为准。

本文是完整运行合同。命令细节和 Windows 噪音见 `references/host-integration-playbook.md`。只有路由到教育/儿童学习时再读 `references/education-rules.md`；改题目、练习或行动卡时再执行 `references/content-truth-review.md`。改儿童乐园入口、题量、题图或页面承诺时，先读并跑 `references/review-invariants.md`。改**任何场景**的题目或作答页时再读 `references/content-mines.md`，先跑 `python -B scripts/check_content_mines.py` 再给用户看页。改完页面后按 `references/visual-self-review.md` 截图并自己看图；只跑 Playwright 断言不够。什么叫好工作台、下一刀怎么切，见 `references/good-workbench.md`。本 Skill 是单人可跑的执行合同，不规定多 agent。检出或修好的问题必须追到根因并回写本 Skill（合同、检查器、运行时或审查规范）；只改某份 iteration HTML 不算解决。执行链路踩坑见 `references/execution-pits.md`。

## 不可代劳的边界

- 交付物是单个 ASCII 文件名的 `index.html`。个人数据只写该产品的 localStorage 命名空间，`data_policy.storage` 固定 `local_only`，必须能导入导出。
- 儿童、学生、客户、财务、医疗和健康默认合成或脱敏数据。真实数据必须用户明确授权、有权控制且确认本机保护；不得保存 token、密码、Cookie 或会话密钥。这些默认不占澄清轮次。
- 联网、多人、账号、发消息、公开发布、下单和支付只能标人工交接或暂不支持。`capability.mode` 只能是 `in_page`、`manual_handoff` 或 `unsupported`。
- 不要按关键词静默选场景。不要伪造用户回答、产品确认或视觉确认。不要复用上一轮 SHA。不要把 `catalog_only` / `contract_ready` 写成已经可执行。不要在用户授权前打包、覆盖宿主或公开发布。
- 测试夹具和环境变量只能用于自动化测试，不能写入生产 run。

## 怎么独立跑完

公开命令：`start`、`respond`、`propose`、`build`、`evaluate`、`cleanup`、`status`。每步先看返回 JSON 的 `state` / `next`；看待决 `decision_id` 用 `status --run <dir> --verbose`。长文本用 `--request-file`。exit code：`0` 成功；`1` 是 `evaluation_blocked`、候选失败或 JSON `status=error`，先读 JSON 再决定；`2` 是 ContractError，读 stderr JSON 的 `error`。不要把非零一律重试。`SAFE_DELETE_FAIL_CLOSED` 是 Windows 噪音，不要当失败。

### 1. 保存原话

```bash
python scripts/double6.py start --run <run_dir> --request-file request.txt
```

场景已经明确时同时传 `--route-file`。`evidence_spans` 必须是当前规范化请求里的逐字连续片段。缺路由也会创建 run，进入 `scene-discovery`，一次问清「谁使用、反复完成什么、期望什么结果」。合法 `primary_domain` / `scene_profile_id` 只从这次 `start` 返回的 `route_options` 里选，不要猜，也不要把完整能力目录丢给用户。

路由文件最小字段：`primary_domain`、`evidence_spans`；知道场景时再加 `scene_profile_id`。可选：`profile_id`、`auxiliary_domains`、`classifier`。

### 2. 普通澄清最多五问，必要授权单列

同一 `scene_session` 里，普通需求和偏好澄清最多五问，场景厘清计入；已明确的不重复问。授权、身份及不可逆动作所需的必要确认单列，不消耗偏好额度。运行时按已知 `decision_id` 分类，宿主不得把普通偏好伪装成授权问题绕过上限。`question_count` 记录普通澄清，`authorization_question_count` 记录边界确认；旧 run 的计数保守保留，不倒扣历史。必要确认缺失时暂停相关动作，集中询问，继续其它已授权且不依赖答案的工作。五问后普通低风险项采用已展示且适用的默认值，不得伪造回答或默认批准真实数据及外部动作。`switch_scene` 新开会话并将两类计数归零。

```bash
python scripts/double6.py respond --run <run_dir> --event-file event.json
```

`event_id` 必须唯一；`turn_index` 从 `1` 起严格递增（`start` 已占用 `0`）。`decision_id` 只用于 `answer`。用户指定教材、真题或考纲时，另传 `--sources-file`。

普通回答：

```json
{
  "event_id": "event-1",
  "turn_index": 1,
  "raw_text": "按推荐",
  "intent": "answer",
  "decision_id": "<当前 missing 的 decision_id>",
  "normalized_value": "按推荐"
}
```

`normalized_value` 写成 `按推荐` / `recommended` / `use_recommendation` 时，运行时会改成该题的 `recommended_value`。场景厘清必须由宿主给出 route，不能只回一句话：

```json
{
  "event_id": "event-1",
  "turn_index": 1,
  "raw_text": "给孩子做小学一升二学习台",
  "intent": "answer",
  "decision_id": "scene-discovery",
  "normalized_value": {
    "request": "给孩子做小学一升二学习台",
    "route": {
      "primary_domain": "education-learning",
      "scene_profile_id": "scene.education-learning.primary-transition-1-to-2",
      "evidence_spans": ["小学一升二"]
    }
  }
}
```

允许的 `intent`：`answer`、`approve_product`、`revise_product`、`approve_visual`、`reject_visual`、`switch_scene`、`renderer_revised`。

### 3. 按快照提案

状态到 `intake` 后，默认不要手写整份产品合同：

```bash
python scripts/double6.py propose --run <run_dir> --from-snapshot
```

需要改标题或产品 ID 时再加 `--title` / `--product-id`。只有用户改了模块、能力、边界或主流程，才写 `--product-file`；字段见 `references/product.schema.json`，模块和 starter 仍必须来自当前 `recommendation_snapshot`。理解稿只展示 4–15 个已选模块和开箱内容，完整能力图谱不得进入成品。

### 4. 展示理解稿，绑定当前 SHA

把返回的完整 `conversation_text` 给用户看。用户同意后，从**当前** `product.json` 现读 `presentation.content_sha256`，再 `respond`：

```json
{
  "event_id": "event-2",
  "turn_index": 2,
  "raw_text": "确认，开始制作",
  "intent": "approve_product",
  "presented_content_sha256": "<现读的 content_sha256>"
}
```

确认后改标题、模块、内容、扩展事项或边界，`build` 会失败，必须重新提案、展示和确认。这仍不证明用户在宿主 UI 里看过理解稿。修订用 `revise_product`，同一工作台必须保留 `product_id`。

### 5. 构建并让用户看见页面

```bash
python scripts/double6.py evaluate --run <run_dir> --preflight
python scripts/double6.py build --run <run_dir>
```

环境没就绪先修，不要先让用户做视觉确认。把候选路径交给用户自己打开。Agent 自己点页面、截图或回归时，用无头 Playwright / `evaluate`，不要接管用户正在用的 Chrome。截图之后必须把 PNG 当图像打开并写出视觉 finding，见 `references/visual-self-review.md`；只报 Playwright 字号、可点和 `data-*` 不算视觉检查。默认仍把候选路径交给用户自己打开。用户已经明确把视觉判断交给当前会话（「你觉得可通过就通过」「不要总是让我看」）时，监督会话必须自己截图、打开 PNG、按 `references/good-workbench.md` 七个判定问题判定；七问都是「是」才可用**这一次** `build` 返回的 `candidate_sha256` 写视觉确认，并留下 `agent-as-user` 回执。七问有「否」或「说不清」就不能过，不要再把同一页丢回用户。未获这项授权时，仍只有用户看过当前页才能确认：

```json
{
  "event_id": "event-3",
  "turn_index": 3,
  "raw_text": "这个页面可以",
  "intent": "approve_visual",
  "presented_candidate_sha256": "<现读的 candidate_sha256>"
}
```

不要用旧 SHA，不要替用户点头。拒绝时把 `intent` 改成 `reject_visual`，SHA 仍绑定当前候选。

### 6. 验收

视觉确认后再 `evaluate`。通过即 `local_delivered`。考公、记账等专用今晚板自己带 `data-today-workboard`、首页主动作、房间入口和备份控件，不得再插通用「今天要处理」板；`evaluate` 按这块骨架验收，不清掉开箱种子也不把种子当成脏数据。静态或候选质量失败时保留产品确认，用新 build 修复。缺 Playwright/Chromium 是 `evaluation_blocked`，环境好了直接重试同一个 `evaluate`，不要重建或再要一次视觉确认。`--skip-browser` 只做静态预检，绝不交付。

`start --clone-from <已确认 run>` 只能复用同版本、内容未变且不含真实数据授权的产品确认；候选、视觉和评估证据不会复制。旧 run 用 `cleanup --run` 恢复残留 journal。

## SHA 现读现用

| 事件 | 绑定字段 | 从哪里读 |
| --- | --- | --- |
| `approve_product` | `presented_content_sha256` | 当前 `product.json` → `presentation.content_sha256` |
| `approve_visual` / `reject_visual` | `presented_candidate_sha256` | 最近一次 `build` 返回的 `candidate_sha256` |

## 产品规则（跑流程时必须守）

- 每个工作台 4–15 个核心模块。先按已确认场景推荐，再让用户采用、删减或调整；不要先甩完整能力目录。首页只放最终确认内容。
- 全部 35 个场景走同一条 `compile_composition`。16 个正式 pack 都必须登记 `execution_projection`，由 `today_module_ids`、`lifecycle_module_ids`、`attention_module_ids`、`next_action_fields`、`blocker_fields` 和 `completion_events` 派生首页的「今天先做什么 / 整体到哪了 / 哪里受阻 / 下一步是什么」，不得在各 renderer 另写一套互相漂移的通用逻辑。已登记 pack 保持精确模块范围，其余按已选模块派生。场景之间只按 `catalog_only` / `contract_ready` / `executable_ready` / `release_ready` 区分深度。当前 16 个 `executable_ready` 场景是个人一周执行、个人生活工作台、选题到人工发布、线索到下一次跟进、减脂日常、班主任班务日常、考公刷题、四级冲刺、家庭今晚家务、月度记账、店铺今晚订单、研究今晚结论，以及宝宝、一升二、二升三、三升四；`release_ready` 仍为 0。减脂日常打开就记下今天的体重、三餐和有没有练；热量是自己填的估计，不保证瘦下来。激励是每日一句鼓励或正向暖心诗词，不是儿童关卡，也不是完全不需要。班主任打开就看见今天的班务、考勤和待跟进，家校消息仍是人工发。开箱合成对象必须跨这三块共用，至少带一条今晚例外；只用 `小A` 这类代号，禁止真名、真校、真学籍。细则见 `references/teacher-tonight-content.md`。家庭今晚打开就看见谁做饭、谁洗碗、要买什么，能勾掉；待当面说不是已发送。考公打开就选行测、申论或面试。技能先给出三科框架；第二步可接入本站题库和打判。接上后首页不再写施工中，改写打判不是官方分、不保证上岸。未接打判时才写打判还没接上。个人一周只服务「同时有日常、又有几件必须自己盯的真事」的人：首页要同时看见这几件的进展，今天有动作的动手，没有动作的也不掉出视野；不得写成每天只推一件。成人开箱不得再要求先填一条空记录。儿童学段都走 `child_playground_v2`：不写教材对齐、不用邻年级顶替、不把惩罚当掌握、幼儿默认家长陪同。家长区「重置今日」只撤销当天身体充电打卡，不等于清空全部。家庭任务默认关闭，打开后不加星星、不改掌握。打卡月历只表示这天有没有本机记录，不是掌握，也不推进学习日。一升二学科页分学一学 / 练一练 / 题库；填空按原文顺序排空并高亮当前空，空位不显示答案。儿童学习默认带激励循环：答对得星、连击、今天三站奖励、小卖部和徽章墙；奖励绑定通用可执行 atom，不新增儿童学习内容 atom；冻结页 SHA `5b31d9fc` 不原位改写。加深衍生场景时：先读该场景社媒吸收报告，再补 atom 或 pack，最后才改成熟度。
- 个人生活工作台固定装配 `personal-today`、`personal-habits`、`life-inspiration`、`life-mood`、`life-finance`、`life-food`、`life-movement`、`life-reading`、`life-vocabulary`。首页一次完成今日 Top 1、心情和一个习惯/目标打卡，侧栏仍保留九个逐模块入口。成人事实投影只从完成日期、用户目标和本地流水计算去重连续天数、剩余量、目标进度与里程碑；建议日均只能写成「剩余量 ÷ 剩余天数」的目标等分。21 天目标和奖励由用户自填，只做本地庆祝，不改健康、掌握或结果真值。
- 四级冲刺固定装配 `exam-goal`、`exam-today`、`exam-practice`、`exam-errors`、`exam-materials`、`exam-mock`、`exam-pomodoro`、`exam-review`。考试日期由用户填写；题库只有 18 道原创可判分题和 6 道人工复核写作/翻译题，错题回炉保留原错题事实，写作与翻译不得伪造自动评分。专注计时按时间戳恢复；没有合适英文语音时必须显示「朗读不可用」。只引用教育部教育考试院考试大纲和 CET4 考核结构，题目明确非真题、不保证通过。
- 成人主题只读 `references/adult-theme-system.json`。多个主题是设计阶段的候选，不是成品功能；每个候选页面必须在 `design.current.adult_theme_id` 锁定并只编译一个主题。最终 HTML 不生成主题选择器、切换脚本或 UI 偏好 localStorage 键。未知主题或资产 SHA 不匹配时构建失败，不把不完整主题带进成品。主题只改变 CSS token、原创插画、空间布局和状态表达，不得改变业务导出字节、连续天数和完成事实。儿童冻结主题和 SHA 不受成人 registry 影响。
- 能力图谱只是构建供给。编译结果只保留 selected scope。只有 `executable_ready` atom 可进入可执行绑定。
- 每个页面的主活动必须是做这件事，不能只是记这件事。开箱内容必须能当场答题、判断、排期、演算、对照或生成待核验草案。空表、占位卡、纯说明和“请自己再记一条”不算能力。内容丰富度是一等指标：已选房间都要在侧栏里，点进去都有能做的活；不得靠收目录假装干净。侧栏点进去也必须立刻能做事，不能只剩「查看内置示例详情」。考公第一题必须像行测练习，不能是小学生近义词；记账演算必须标明收入、支出，不能写数值 1 / 数值 2。使用者看得见的文案不能是「内置内容 / 自有记录」。改完必须自己走每一个侧栏并写下用户没点名的问题；只修点名项不算解决。记录表单只能作残留，不能摊成「完整操作区」。开箱卡顶不能写「先从这里开始 / 可反复练习」，要说打开就能做、今晚就能做。开箱卡不能写「小任务 / 可编辑模板 / 完成这一项 / 标记已查看」，动作是勾掉、按这个改、看过了。手机开箱动作条不得吸底挡住选项。科目写去做题时必须打开对应考点的那一题，不能只打开做题房第一题。申论必须能当场写问题、原因、对策，不能只看提纲或把写作塞进残留记录表。手机第一屏必须看见问题写作框。记账开箱不得预填晚饭流水；首页空账，金额自己填。记账首页隐私条不得把税/银行免责再贴一遍。选题参考、读书进度等外部事实走可核验只读 API 或官方导出；未拿到真实响应前标 `contract_only` / `manual_handoff`，不得假装已接入微信读书或热点接口。
- 每个核心模块必须有开箱内容（真实动作、模板、题目、计算器、生成器或参考卡）和一种真实表面：`action_checklist`、`record_ledger`、`stage_board`、`metric_log`、`review_journal` 或 `reward_economy`。
- 含出题/练习/测验的能力默认提供可作答通用题，不要再问「要不要题」。儿童学习与四级冲刺各至少 12 题，不得标「演示」。考公框架台默认只有几道自编练习，完整题库和打判是第二步再接入。指定教材、真题或考纲时才问来源；答不上来就停在 `clarifying`，不要编来源或删题。
- 内部 ID（`CAP-XX-XX`、模块 ID、`starter` 等）不得进入用户可见文案。非个人生活场景不得泄漏 `life-*` 或热量/收支标记。
- 第一次打开且还没有自有记录时，显示可关掉的短说明：先做首页那一件、数据只在这台设备、换电脑前先导出；电脑 Chrome 可用应用窗口打开，但不得写成已经安装。不得注册 service worker，不得声称已可安装或已上线。
- 用户数据是 `double6_workspace_v1`（`schemaVersion: 4`）。保存、导入导出、剪贴板和本地提醒使用 `ready / broken / declined / stale` 四态。导入最大 8 MB、每模块最多 2000 条；空间不够改用 IndexedDB，不假装已经上云。导入/清空前自动写本机恢复点，导出不含恢复点。
- 外部操作确认后的唯一诚实状态是 `not_executed`。奖励不能改写掌握、业务真值或完成证据。页面不得把本机勾选、草稿或 CSV 写入写成已经发到学校、家长群、平台或云端。
- 跨场景套模板时扫描邻域词和假提交语气。改运行时或场景页后跑 `python -B scripts/check_domain_remnants.py`。坏 JSON 或写入失败必须把存储恢复成导入前的字节；记录型 CSV 只给记账流水、店铺订单和考勤，且只出现在成人设置，不得上首页。

儿童学习的奖励、题量、口算和家长回顾见 `references/education-rules.md`。用户已经指出过的入口、题量、题图、房间和内容雷见 `references/review-invariants.md`，改完必须跑 `python -B scripts/check_child_review_invariants.py`。题目排雷不限于儿童：备考、生活词汇、HR、孕期等场景的选择题也会犯标题泄题、答案总在第一项。方法见 `references/content-mines.md`，改题后跑 `python -B scripts/check_content_mines.py`。不要再靠人工一题一题扫。改减脂日常后另跑 `python -B scripts/check_fitness_tonight.py`：首页必须是今天的体重、三餐和打卡，不能把小学勾组当这个场景的主活动。改班主任后另跑 `python -B scripts/check_teacher_class.py`：首页必须是今天的班务、考勤和待跟进，开箱代号必须共用且带例外，不能套今晚一件、小学三站或真名花名册。改家庭今晚后另跑 `python -B scripts/check_household_tonight.py`：首页必须是今晚谁做什么、能勾掉、待当面说，不能是周历空表或假装已发送。改月度记账后另跑 `python -B scripts/check_finance_tonight.py`：首页必须是记今晚这笔、今日合计、凭证可勾、税待专业处理，不能是空月结台、银行余额、已申报或预填晚饭流水。改店铺订单后另跑 `python -B scripts/check_commerce_tonight.py`：首页必须是今天这几单、库存快照、待在平台回，不能是空经营台、实时库存或已发货。改研究结论后另跑 `python -B scripts/check_research_tonight.py`：首页必须能写下今晚这条带出处的结论，缺出处就标缺口，不能是空资料库或无来源已证实。改考公后另跑 `python -B scripts/check_exam_practice.py`：首页必须是行测、申论、面试三扇纸面，主动作是去做行测；三扇门要一眼分得出行测卷、申论稿纸、面试计时，不能是三颗同色按钮。接入题库后，三扇门必须进独立房间，错题再做一次必须打开同一道行测原题；打判要写明不是官方分。未接入时默认题要少，并写明打判还没接上。申论能写，面试能计时贴转写；导入必须先声明有权使用。不能冒充真题。给人看的页禁止写成走查工作台，门牌必须是考公工作台。改导入、备份或跨场景文案后再跑 `python -B scripts/check_domain_remnants.py`。版式、真值、PWA 图标、三视口和构建器强制项见 `references/content-truth-review.md`、`references/product.schema.json` 与运行时；宿主不要在入口复述这些实现细节。

## 发布与授权

发布门由维护者治理包执行，不随本 Skill 分发。打包、安装目录覆盖、SMB 上传、重启、共享晋升和外部发布都需要用户另行授权。

## 合并后的补充能力

研究阅读是独立细分场景 `scene.research-knowledge.reading-desk`，可用 `profile_id=reading-desk` 明确选择；保留原有问题—证据—报告与实验周控场景。阅读清单、三遍阅读法、读书卡、证据卡和写作大纲均为本地内容，不声称接入微信读书或外部知识库。

内容运营保留可直接写开头、来源到人工发布的对象链；同时提供多平台素材卡、选题打分、一鱼多吃、发布自检、建议的一周节奏和数据复盘。建议节奏可供参考，不构成自动排期或发布。

普通候选与儿童展示适配器均内置 CSP，阻止页面外联。儿童已审内容的构建依赖随包保存于 `references/child-learning-source/`，构建前核对原始 SHA；不能回退读取作者机器上的其它项目目录。冻结儿童基准不原位改写。

输入文件支持 UTF-8、UTF-8 BOM 与 UTF-16；CLI 强制 UTF-8 输出。Playwright 仍按需加载，缓存发现兼容 macOS、Linux、Windows 及 `PLAYWRIGHT_BROWSERS_PATH`。

旧备份或自定义方案涉及 `exam-q06`–`exam-q12` 时，按需读取 `references/legacy-exam-content.json` 核对原题。它们保留自完整 1.1.0，后续本地优化已将其移出默认框架台；不要自动加入首页或冒称正式题库。
