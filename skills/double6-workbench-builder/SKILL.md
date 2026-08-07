---
name: double6-workbench-builder
description: 把普通用户反复要做的真实事情构建成离线优先、严格单文件、个人数据留在当前设备的本地工作台。用户提到个人工作台、学习台、备考台、任务面板、记录与复盘工具，或想把重复流程做成可保存恢复的页面时应使用；联网、多人协作、账号、支付和发布属于独立外部流程。
---

# Double6 工作台制作器

这是项目本地 workflow，不是共享 Skill。活动版本、命令与 schema 以 `manifest.json` 为准；本文定义流程语义与不可突破的边界。儿童学习场景的专属细则见 `references/education-rules.md`（路由命中时必读）。

## 不可突破的边界

### 交付与数据

- 交付物是可离线打开的单个 `index.html`（文件名固定使用 ASCII，不使用中文文件名）；个人数据只写入该产品唯一的 localStorage 命名空间（`data_policy.storage` 固定为 `local_only`），并启用导入导出。
- 儿童、学生、客户、财务、医疗和健康任务默认使用合成或脱敏数据（`synthetic_or_redacted`）。只有用户明确授权、有权控制数据且确认本地保护条件时，才允许录入真实数据；不得保存 token、密码、Cookie 或会话密钥。这些安全默认不占澄清轮次。
- 联网数据、多人协作、账号操作、消息发送、公开发布、下单和支付只能标为人工交接或暂不支持；capability mode 只能是 `in_page`、`manual_handoff` 或 `unsupported`。发布由独立宿主流程执行，并以真实链接和内容校验回执为准。
- 公开发布（云托管）与本机部署（磁盘持久化、局域网访问）是两个不同的方向，都超出单文件交付本身；用户主动提出其中任一方向时，宿主按对应的独立流程直接执行，不要求额外的授权前置。
- 用户想在手机长期使用或分享时，候选须说明"先备份、确认无真实隐私数据、取得明确授权后再走独立宿主发布流程、拿到真实链接和回执后才可添加到主屏幕"。页面不得自行上线、发送或公开数据。

### 模块与内容

- 每个工作台选择 4–15 个核心模块。需要新增、删减或保留哪些能力，必须在澄清阶段问清楚；首页只呈现用户确认后的内容，并让每个已确认模块可直接进入，不能在页面底部再用"更多入口""完整能力"补一份未确认的模块清单。能安全采用的设备、本地保存与通用内容默认值直接采用，不要求用户逐项确认。
- 每个核心模块必须同时具备两层：无需用户先录数据即可操作的内置内容（内部合同名 `starter`）和用户自有记录。内置内容至少包含真实动作、模板、题目、计算器、生成器或参考卡之一，并声明动作结果、手机交互、状态和来源边界；空数组、占位卡、纯说明和只有 CRUD 空表都不算能力。
- 每个核心模块还必须绑定一种真实交互表面：`action_checklist`、`record_ledger`、`stage_board`、`metric_log`、`review_journal` 或 `reward_economy`，并实现合同声明的增删改查、状态变化、刷新恢复和导入导出。
- 凡能力语义包含出题、练习、测验或错题，默认直接提供可作答的通用自编题，不得为"是否需要题目"再问用户。每题至少有题干、选项或输入控件、答案、即时对错、解析、知识点、难度和来源标签；教育与备考内容包各至少 12 题，且不得标为"演示"。只有用户明确指定教材、真题、考纲、地区或版本时才询问来源。
- 通用题不等于随意编题。宿主对年级适配、知识点、答案或安全边界没有把握时，必须先联网检索与该问题匹配的可靠来源：课程对齐优先课程标准或用户指定教材，词义/用法查权威词典，科学与安全事实优先一手机构或学术/科普权威来源；不要把所有题目都伪装成来自官方课程标准。记录实际采用来源的 URL、核验日期和"自编通用/未对齐指定教材"的边界。检索后仍不能决定，应在 `clarifying` 状态向用户询问具体来源、范围或期待答案；不得擅自猜测、伪造来源，也不得静默删掉该类题。教育场景另见 `references/education-content-research-policy.md`。
- 儿童学习场景的星星经济、参考内容包、各学段题量、口算生成器、功能说明卡与家长回顾等专属细则，统一见 `references/education-rules.md`。

### 文案与标识符

- 内部标识符不得进入用户可见文案：学段 ID（如 `primary-transition-2-to-3`）、能力 ID（`CAP-XX-XX`）、模块 ID（如 `education-math`）、surface 类型名、`starter`、`action`、`question` 等内容类型字段只能出现在源码、合同与数据属性中。孩子与成人可见的文案里只允许出现友好名称；静态验收与浏览器验收都会扫描可见文案，命中即判候选失败。
- 治理文案与使用者文案分层：来源边界、未对齐教材声明只能出现在已声明边界的功能说明卡或家长回顾区，不得以"通用内容；有自己的材料时再替换"这类元文案打断主流程；主流程文案使用产品语言（如"可反复练习，进度只保存在这台设备上"）。
- 候选不得携带其他场景的代码与标记：渲染产物只注入当前产品已确认模块所需的脚本；非个人生活场景的候选中不得出现 `life-*` 模块代码、热量/收支等指标标记，静态验收命中即判失败。

### PWA 与首屏

- 候选必须是"PWA 就绪"的单文件：浏览器标签页 favicon 与添加到主屏幕的图标默认和首页标题旁的品牌块一致——当前视觉模板的 motif emoji 置于模板主色圆角块上，九套模板各一套离线渲染 PNG（`references/app-icons.json`，64 favicon/180/192/512/maskable，由治理脚本 `render_app_icons.py` 渲染）。只有用户明确要求时，才经 `design_brief.icon_override` 换用另一套模板 motif 或 `double6_brand` 品牌图标（源自 `references/page-icon.svg`）；非法取值以 ContractError 拒绝。同时内嵌 data-URI manifest（名称、短名称、standalone 显示、主题色与背景色、三张 PNG 图标）和 Apple 主屏元数据（apple-touch-icon 必须用 PNG，SVG 在 iOS 无效）。
- 只声明元数据：不得注册 service worker，不得声称"已可安装"或"已上线"。真实安装提示只在独立发布流程提供 https 入口后出现；file:// 或局域网打开时浏览器忽略 manifest 属正常行为。内嵌 manifest 与主屏图标不代表已发布或可安装。
- 每个首页都必须把"今天要处理"放在工作流最前：只汇总带日期、尚未完成且到期日为今天或更早的行动；过期项显示为"已顺延到今天"但保留原始日期，并能在卡片上直接完成。没有待办时只能引导用户从已确认的首要模块开始，不能伪造任务或逾期记录。
- 首屏同时提供导出备份与导入恢复；本地记录达到 30 条时提示导出。含 `entry_type + amount` 的已确认财务流水可额外导出 CSV。

### 移动交互

- 题目在手机上采用单题流：大触控选项或合适的数字/文本键盘、提交后即时反馈、解析与错题记录、下一题、刷新后续做；不得把桌面题表缩小后塞进手机。数字答案题必须使用页面内自绘数字键盘（0–9、删除、清空），不得用 `input[type=number]` 调起系统键盘顶掉页面；答对给予明确的庆祝动效（星星飘落），答错给予轻微抖动与正确答案提示，动效不得遮挡作答区。
- 移动端输入字号不小于 16px；数字字段使用数值键盘。手机和平板统一使用可纵向滚动的左侧导航栏：每项必须是彩色 emoji 加可见的精简文字，竖屏采用上 emoji、下文字的纵向堆叠（电脑横屏保持左 emoji、右文字），文字可以在窄屏适度缩小和换行，但不得隐藏成只剩图标；导航必须列出首页、全部已确认模块和数据入口，不能截断前四项，也不能遮挡正文。
- 可使用浏览器本机朗读辅助，但不得承诺未实现的语音或智能判定能力。

## 六步流程

1. `start` 只保存用户原话和已选择的路由。未提供路由时只返回完整场景目录，不创建 run；新运行只接受当前版本，旧运行保留作历史记录而不混入新状态机。路由文件中的 `evidence_spans` 必须逐字摘自用户原话——校验器做逐字包含比对，概括、改写或编造的片段会以 ContractError 拒绝。
2. 状态为 `clarifying` 时用 `respond` 逐次记录关键答案，最多询问三个会改变工作对象、核心动作、数据/来源边界或验收结果的问题。每个问题必须给出推荐值、推荐原因和"按推荐"的可用回答；宿主把"按推荐"标准化为该题的 `recommended_value`。儿童学习场景的澄清顺序与默认值见 `references/education-rules.md`。
3. 状态为 `intake` 时，根据不可变的 `recommendation_snapshot` 提交产品合同并调用 `propose`。理解稿同时展示 4–15 个默认模块、每个模块的 starter 数量/类型与确认前可加入的可选模块；不得只在隐藏推理或内部产品 JSON 中列清单。
4. 把返回的完整 `conversation_text` 展示给用户。`approve_product` 只能绑定当前理解稿 SHA：从当前 run 的 `product.json` 现读 `presentation.content_sha256`，复用旧值或拿错字段都会以 ContractError 拒绝。确认回执还会绑定不含回执自身的完整产品内容 SHA。确认后只要标题、主能力、模块、内容、扩展事项或边界发生变化，`build` 必须失败并要求重新提案、展示和确认。这仍不独立证明用户在任何宿主 UI 中看过它。
5. 产品确认后调用 `build`，只生成一个推荐候选。建议紧接着调用 `evaluate --preflight` 或 `status --environment`；环境未就绪时先修好，不要让用户先做视觉确认。必须先让用户查看当前候选；只有绑定当前候选 SHA 的 `approve_visual` 才能进入验收，`reject_visual` 也必须绑定该 SHA。候选 SHA 取自当前 `build` 返回的 `candidate_sha256`，同样必须现读现用。
6. 视觉确认后调用 `evaluate`。通过即为 `local_delivered`；静态或候选质量失败时保留产品确认并用新 build ID 修复。仅缺 Playwright/Chromium 等环境时状态为 `evaluation_blocked`——这是环境问题，不代表候选质量失败；环境就绪后直接重试同一个 `evaluate`，不得强制重建、再次视觉确认、新建 run 或改动已确认的产品合同。`evaluate --skip-browser` 只返回静态预检通过，绝不交付。若反馈需要 renderer/CSS 源码修订，维护者修订后以 `renderer_revised` 事件回到 `ready_to_build`，新 build 自动生成新候选 SHA。

公开 CLI 为 `start`、`respond`、`propose`、`build`、`evaluate`、`cleanup`、`status`。`start --clone-from <已确认 run>` 只可复用同版本、内容未变且不含真实数据授权的产品确认；候选、视觉确认与评估证据不会复制。`cleanup --run` 恢复事务 journal，并报告受宿主限制而保留的 staging。

## Windows 与受限宿主环境

- 事务 journal 会在数据全部落盘后标记为 `committed`；受限宿主拦截删除时，残留 journal 或 staging 只会产生 warning，不能把已提交数据报成 CLI 失败。旧 run 可调用 `cleanup --run` 恢复。
- 以进程 exit code 为唯一成败判据。stderr 中出现 `SAFE_DELETE_FAIL_CLOSED` 是 Windows 沙箱无回收站导致的噪音，只要 exit code 正常即为成功，不要据此重试、判失败或中断流程。
- 浏览器验收使用 Playwright 与 Chromium。先执行 `evaluate --preflight`；可设置 `DOUBLE6_BROWSER_PYTHON` 和 `DOUBLE6_CHROMIUM_EXECUTABLE`。Windows 会自动尝试 `.venv\Scripts\python.exe`、常见 Chrome 安装路径及 `%LOCALAPPDATA%\ms-playwright`，仍缺失时预检会给出安装指引。
- 宿主 CLI 操作、浏览器验收守则与本机服务器扩展守则见 `references/host-integration-playbook.md`。

## 视觉反馈合同

- 自动重建只承诺真正生效且能映射到已登记模板的颜色反馈；它会保留 renderer 与内容结构并切换 palette。视觉模板通过不等于 palette 已通过；只有绑定当前候选 SHA 的用户反馈才能记录为接受。
- 构图、密度、字体、资产、场景辨识或交互反馈如果需要改 renderer/CSS，状态必须变为 `renderer_revision_required`，由维护者修改源代码后以 `renderer_revised` 事件恢复到 `ready_to_build`；禁止只改 metadata、换 build ID 或空跑三轮。`renderer_revision_required` 是 run 的状态标记，不是第八个状态机节点。
- 候选使用 `references/vivid-social-template-system.json` 中九套去重模板、九个特定场景 renderer 和一个通用回退 renderer（`generic_dashboard`，未精确命中时使用）。场景不由制作器按关键词自动决定：调用方必须先从路由目录选择主场景、可选子场景，并附用户原话证据；制作器只校验选择合法、生成对应推荐快照。辅助领域不得触发特定 renderer。已登记场景若缺 renderer、四个首屏槽位（hero、primary_surface、progress、supporting_panel）或候选锁漂移，构建必须失败。首屏不得再叠加与模块卡片重复的纯文本快捷入口清单。

## 事件与产品合同

- 事件只保留 `event_id`、递增 `turn_index`、未经改写的 `raw_text`、`intent`，以及确认场景所需的 SHA。运行时不读取或保存 provenance、宿主 session、trace、数据库回执、可见回复回查或置信度字段。允许的 intent：`answer`、`approve_product`、`revise_product`、`approve_visual`、`reject_visual`、`switch_scene`、`renderer_revised`。
- 测试夹具、临时事件和环境变量只能用于自动化测试，禁止写入生产 run、伪造用户回答、产品确认或视觉确认；任何由测试通道产生的确认都不得进入交付状态。
- 产品文件必须包含 `product_id`、`title`、`facts`、`outcomes`、`work_objects`、`core_flow`、`capabilities`、`recommendation_plan`、`data_policy`、`device_target`（固定为 `responsive_both`）、`design_brief` 和 `boundaries`。`references/product.schema.json` 是宿主提案前对照的产品合同 schema。
- 教育、课堂和备考任务若声称采用指定教材、真题或考纲，必须登记用户提供或官方可核验的来源；否则只能使用通用内容（`generic_non_claimed`）。
- `references/scene-capability-starters.json` 与 `references/education-stage-starters.json` 是 starter 内容合同。产品中的 starter 必须来自不可变推荐快照，调用方不得自行删空、替换或伪造。
- 用户明确提出且需要在模块内长期打卡的周期事项使用 `module_extensions`：每项必须绑定已选模块、真实用户事件证据、标题、结果和 1–7 的星期值，并完整进入理解稿。它与不可变内置内容分层保存，不能靠改内容包或把需求塞进描述文本冒充已实现。
- blocked 决策必须进入 `unsupported` 边界，不能静默默认。

## 候选数据安全

- 导入前必须确认，导入后可立即撤销；清空与删除必须二次确认。
- 导入文件最大 2 MB，每个模块最多 500 条记录。已知字段按类型归一化，未知字段保守保留在导出文件的 `legacyImport.unmapped` 中。
- 外部记录 ID 不可信：不符合安全格式时重新生成；所有进入 HTML 属性或 script 的动态值必须转义，禁止把导入内容直接拼进 `innerHTML`。
- 存储失败时不得丢失表单输入；验收必须先按真实表面填写全部必填字段，再触发保存故障并逐字段比较前后值，不能只填第一个文本框，也不能为了通过测试改变产品主模块。导出、恢复、旧简易 `{value, checked}` 数据兼容和未知字段保留都必须经过浏览器验收。

## 验证

发布门位于相邻治理包：

```bash
PYTHONDONTWRITEBYTECODE=1 python -B workflows/double6-workbench-governance/scripts/validate_release.py
```

活动门的 60 秒预算只验证核心发布合同：内容包与 starter 完整性、理解稿/产品/候选 SHA 确认链与同 run 重建、儿童教育内容包（题库、口算生成器、星星经济、参考内容包与点读）、PWA 就绪元数据、导航与内部标识符泄漏扫描、周期事项、数据导入导出与完整浏览器交付；逐项明细以治理包测试为准。完整 16 领域浏览器矩阵仅是治理包中的手动诊断，用于内容包大改或专项排障，不阻塞每次发布。

打包、安装目录覆盖、SMB 上传、重启、共享晋升和外部发布都需要用户另行授权。
