---
name: double6-deep-research
version: 2.3.0
description: 面向开放全景、固定对象比较和有界决策问题，使用宿主已有搜索与网页读取能力完成多来源深度研究并交付完整、可读、可核验的报告。用于用户要求深入调研某一主题、比较多个对象、形成有证据的决策建议、梳理某领域截至当前的研究进展或核验一组复杂事实，也适用于英文 deep research、landscape review、evidence-based comparison 请求；不用于无需多来源综合与证据审计即可完成的轻量请求，例如任务状态查询、简单事实查询或单页内容摘要。
metadata:
  openclaw:
    homepage: https://github.com/double6-ai/double6-skills/tree/main/skills/double6-deep-research
    emoji: "🔎"
    requires:
      anyBins:
        - python3
        - python
        - py
---

# Double6 Deep Research

目标是回答用户的问题并交付一份真正可读的完整报告。来源数量、ledger 大小、字段数量和
validator 通过都不能代替报告质量。

## 1. 冻结任务合同

把用户请求拆成明确的问题清单，记录：

- 研究对象、时间范围、地域和排除项；
- 每个必须回答的问题；
- 用户需要的输出形态、比较维度和决策用途；
- 哪些结论需要当前信息，哪些可以使用稳定历史材料。

有关键歧义且不同解释会改变报告时再提问；否则采用保守假设并在报告中说明。报告语言和
格式跟随用户请求；用户未指定时使用其提问语言。

买车、选课、选工具或其它要做决定的问题，先问清最多三个会改变结论的条件，例如地点、
时间范围和预算或备选对象。用户已经写明的不要再问。问完或沿用用户原话后，把这些条件写进
`request_snapshot.md` 或报告里的 `## 假设`；英文可以用 `## Assumptions`。并在
`research_record.json` 里设置 `decision_task: true` 和最多三条 `decision_assumptions`。
假设不能写成官方事实。

成本、时延、部署、采用、风险等用户明确要求的维度必须分别成为可检查的问题，不能合并成
“应考虑这些因素”的泛化清单。

## 2. 制定自适应研究计划

先写 `research_plan.md` 并在对话里贴出，再开始搜索或打开网页。计划要有三块，标题跟随用户语言：

- 要回答的问题（`## 要回答的问题` 或 `## Questions`）：逐条写下即将研究的问题；
- 准备查的来源（`## 准备查的来源` 或 `## Sources`）：每类问题准备打开的来源类型；
- 会标成未知的内容（`## 会标成未知的内容` 或 `## Unknowns`）：打不开或对不上的对象、数字和维度会怎样标出。

问号用全角或半角都可以，检查时会忽略空格和标点。

用户没有反对再动手。每轮检索结束后，用一两句话追加到 `research_log.md`：打开了什么、还缺什么。
对话里也发这句进度。不要等全文写完才第一次告诉用户在查什么。

为每个问题先冻结覆盖合同：需要哪些来源类型、是否必须有利益关系独立的证据、必须执行
哪些时效性／反证／遗漏检查，以及需要覆盖哪些对象和比较维度。优先一手来源；比较胜负、
行动建议、风险、真实采用等结论不能只依赖利益相关方自述。

不要预先规定统一来源总数。开放全景通常需要比固定比较更多来源，但是否充分取决于：

- 每个重要问题是否已经有证据；
- 关键对象和反例是否覆盖；
- 来源是否足以区分事实、厂商自述和推断；
- 继续搜索是否仍会改变主要结论。

不得把预设来源数量、搜索工具单批返回上限、耗时或完成若干轮当作充分性证明。

## 2.5 开放全景：先铺广度，再逐格挖深

先判断任务类型并写进 `research_record.json` 的 `task_type`：

- `open_landscape`：全景、格局、版图、综述、研究进展、state of / landscape / overview 这类没有给定对象清单的问题；
- `fixed_comparison`：用户已经给定要比较的对象；
- `bounded_decision`：要在有限选项里做决定。

开放全景最常见的失败不是写错，而是停得太早：几次搜索拿到一份看起来完整的综合摘要，打开
排在前面的页面，就把"没有新东西"当成饱和。搜索工具返回的综合答案只是地图，不是证据，也不
说明覆盖已经完整。开放全景按下面做：

1. **发现轮先于冻结**。在冻结问题清单前，用至少两种不同措辞（含另一种语言或行业术语）做发现
   检索，只为列出领域的分段和实体，不急着取证。
2. **画全景地图**。把领域拆成分段（例如：整机/零部件/模型/应用；技术路线；地区；上下游；
   研究方向/产业化/政策），每个分段列出实体（公司、产品、项目、机构、论文方向）。分段与实体
   写进计划，并在 `landscape.segments`、`landscape.entities` 登记。问题清单按分段展开，而不是只把
   用户原话拆成两三条宽问题。实体不能只来自第一页搜索结果；要包含反例、非头部、其它地区和
   新进入者。
3. **按分段设深度目标**。每个回答过的问题至少要有两个实际打开并在回答章节引用的来源，其中至少
   一个不是被研究对象自己；主要实体至少有一个打开的正文支撑。范围越大、分歧越多，目标越高：
   数据有多个口径时把各口径都找到；关键数字尽量追到原始出处。这些是底线，不是充分证明，也
   不能拿"凑够了"当停止理由。
4. **多轮、多面向检索**。每轮在 `research_rounds[].queries` 记录真正发出的查询和面向
   `facet`：`core_terms`、`synonym_or_language`、`source_type`（论文、监管文件、财报、
   调查、标准、专利、开源仓库等）、`region_or_market`、`time_window`、`entity_specific`、
   `adversarial`、`citation_snowball`。开放全景在完成前至少覆盖四种面向。
5. **引用滚雪球**。二手报道里提到的报告、论文、数据库、财报、监管文件，要追到原始出处；
   原始出处又引用的关键来源和新实体，再追一层。用 `citation_snowball` 面向登记这类查询，并在
   来源上可选写 `discovered_via` 说明是从哪个来源追来的。
6. **记录新信息率**。每轮写 `new_source_ids`（这轮新打开并登记的来源）和
   `new_material_findings_count`（这轮新增、写进报告的实质发现数：新实体、新口径、改变或收窄
   结论的事实）。只要上一轮还在产生新实体或新口径，就继续扩展，而不是进入收尾。
7. **饱和要有新阅读**。最后一轮 `adversarial_saturation_check` 必须真的用至少两种新面向检索，
   新打开至少两个此前没读过的来源，并且 `new_material_findings_count` 为 0，才可以说饱和。
   只重读旧来源、只看搜索摘要、或者只发一条反证查询，都不算。
8. **覆盖表**。报告里放一张覆盖表（标题写进 `landscape.coverage_table_section`），每个分段
   一行：主要实体、证据强度、主要来源和仍然未知的地方。读者借它看出哪里查得深、哪里薄。

防灌水：来源数量本身不是深度。只出现在书目里、正文没用到的来源，同一发布者大量重复的转载，
以及不改变任何结论的链接，都不能当成进展；检查程序会对这些情况给出警告。每新增一个来源，都
要能说出它在报告里支持了哪句话、补了哪个分段或口径。

## 3. 研究并持续补最高缺口

只使用宿主已经提供且用户允许的搜索、网页、浏览器或材料读取能力。不要配置 provider、
读取 credential、启动自建 runtime，或执行与研究交付无关的外部操作。

权限边界：先确认用户允许访问的网页和本地材料；本地读取仅限这些材料与交付目录，写入仅限该目录中的报告、审阅和验证文件。不要把研究文件散落到用户的项目根目录；由用户或当前任务指定一个单独的交付目录。validator 只读该目录、计算候选 SHA-256 并写入 validation_receipt.json，不联网、不读凭据，也不写其它路径。

按以下职责循环研究：

1. 按问题而不是按网站收集材料；
2. 打开正文，区分全文、实质章节、元数据和不可访问状态；
3. 记录来源标题、发布者、URL、访问日和支持范围；时效性来源同时记录发布日期；
4. 对日期、价格、百分比、排名和建议所依赖的事实保存精确证据；
5. 完成主体覆盖后，按覆盖合同检查缺少的来源角色、对象、维度、更新材料和反证；
6. 再用不同策略执行对抗性饱和检查，主动寻找会改变、收窄或推翻主要结论的证据；
7. 最后一轮仍改变主要结论时继续研究，直到新的饱和检查不再产生实质变化，或如实交付
   `partial`／`blocked`；
8. 开放全景每轮结束时对照全景地图找最薄的分段和实体，下一轮优先补它们，并换用还没用过的检索
   面向和引用滚雪球，而不是重复同一组关键词。

如果 WebFetch 或浏览器打开的只是导航页、目录页、登录页、脚本壳或错误页，不得标记为
`full_text`。优先寻找同一官方站点的正文子页、官方 PDF、仓库中的原始 LICENSE／文档或
其它能直接支持该 claim 的权威材料；替代来源只能支持它实际覆盖的较窄结论。搜索结果
摘要可以帮助定位正文，但不能补足正文证据。

不得把搜索 snippet、研究者摘要、导航页或自己写的“来源快照”冒充官方正文。需要保存
快照时，必须是宿主实际取得的页面或文档内容，并记录 SHA-256。

价格、百分比、日期、名次、带小数或千分位的数字，以及单独出现的三到六位数字，只有在当次
打开并保存的正文里能找到，才能写进报告。年份如果只是研究截止日、来源发布日或访问日，
并且已经写在记录里，不必再从页面摘录里找。原句和摘录之间的空格、全角半角不影响核对。
关键句另外保存页面原句 `evidence_quote`，这句必须出现在对应来源的 `snapshot_path` 里，
数字也必须出现在这句原话里。页面里没有，就写成“这次没核到”或“未知”，不要改挂到邻近页面。
否定句可以直接写页面上没有这个数字，例如“法律条文里没有写 1.13”。

比较数字时用 Markdown 表格。检查的是表里每一个格子，包括第一列和表头，不要求章节标题里
出现“比较”。没打开的格子写“未知”“未核到”“这次没核到”“未打开”“不适用”“无”“N/A”
或 unknown。自己的计算写“假设”或“推算”。写了未知的格子里不要再留一个具体数字。只讲口径、
没有表格的章节可以保留。

题面附件、表格和冻结情景里的数字是给定假设，不是已经打开的网页。它们可以写进报告的
方法或假设，并在来源记录里使用 `content_origin=user_provided_material`、
`stakeholder_relation=user_provided`。税率、官方价格、法规、产品参数和论文数字仍要打开
正文后才能写成 `host_opened_page` 或 `downloaded_document`。搜索摘要不能写成
`full_text`，也不能自造 `search_result` 这类来源状态。

## 4. 先完成报告，再整理最小审计记录

报告结构由问题决定，但至少包括：

- 执行摘要：直接回答最重要的问题；
- 范围、时间点和方法；
- 按用户问题组织的主体分析；
- 必要的对象比较、冲突证据和决策建议；
- 不确定性、限制和仍未知事项；
- 可点击或可定位的来源。

不要把 source ledger、检索过程或内部字段机械展开成正文。每个章节都要形成读者可以理解
和使用的结论；建议要区分来源事实、跨来源推断和本报告的政策／行动判断。

对明确要求的量化或决策维度，给出可比数据及口径；公开数据未定位时逐项写明未知边界、
已检查的来源范围和可执行的本地测量方案，不能用模型单价或定性框架冒充任务成本、时延、
部署状态或真实采用证据。

读者只看 `final_report.md`。研究没做完时，在执行摘要前面加一节，用白话列出每个未闭合问题和
下一步。标题用 `## 还没查完`；英文可以用 `## Still open` 或 `## Open questions`。如果标题
不同，把报告里的原标题写进 `report_sections.unresolved`。问题原文不必连标点都一致，下一步
也可以换一种说法，但这一节不能只重复问题、不说接下来查什么。做完的报告不必写这一节。

审计记录仍放在 `research_record.json`。常见同义词可以由检查程序归一，不必为了用词重写报告：
`fact` 视为 `current_fact`，`calculation` 视为 `quantitative`，`unchanged` 视为 `none`，
`official` 视为 `official_document`，`news` 视为 `journalism`。写进检查名单的
`omission_scan` 会从检查里去掉，不记成已经做完的覆盖检查。`survey`、`benchmark` 和
`search_result` 仍然不合格，因为它们会把没打开的材料说成正文。

交付目录只需：

```text
request_snapshot.md
research_plan.md
research_log.md
final_report.md
research_record.json
snapshots/                 # 引用了价格、百分比或其它关键数字时必须保存对应正文
validation_receipt.json    # 运行最小 validator 后生成（含 depth_metrics：查询数、面向、逐轮新信息率）
independent_review.json     # 完成独立审阅后生成
```

`research_record.json` 使用 schema v2。字段名和用词照下面抄，不要改名，也不要自造类型。
完整通过时的停止理由见 [report-quality.md](references/report-quality.md)。部分完成不用
手写一份和检查程序计算结果相同的停止理由；检查程序会把算出的缺口写进
`validation_receipt.json` 的 `question_coverage`。

开放全景另加两块，字段名照抄：

```json
"task_type": "open_landscape",
"landscape": {
  "coverage_table_section": "## 覆盖表",
  "segments": [{"segment": "整机厂商", "question_ids": ["Q1"]}],
  "entities": [{"name": "某公司", "segment": "整机厂商", "source_ids": ["S001"]}]
}
```

每个研究轮次可加：`"queries": [{"query": "实际查询", "facet": "core_terms"}]`、
`"new_source_ids": ["S001"]`、`"new_material_findings_count": 3`。`strategy_types` 可以额外
使用 `citation_snowball` 和 `query_diversification`。

问题编号用 `question_id`，例如 `Q1`，不要用 `id` 或 `0`。正文方括号只引用 `source_id`，
例如 `[S001]`，不要把问题编号写进方括号。`report_sections` 的值必须是报告里逐字存在的
标题。没打开的页面不要登记成来源。

来源材料类型 `source_kind` 只能是：`official_document`、`scholarly_research`、
`independent_evaluation`、`industry_analysis`、`user_or_adoption_evidence`、
`journalism`、`other`。利益关系 `stakeholder_relation` 只能是：`first_party`、
`independent`、`interested_third_party`、`user_provided`、`unknown`。取证方式
`content_origin` 只能是：`host_opened_page`、`downloaded_document`、
`user_provided_material`。不在名单里的材料用 `other` 或 `unknown`。优先写上面的规范名；`official` 和 `news`
会按同义词收成 `official_document` 和 `journalism`。不要写 `survey`、`benchmark` 或
`search_result`，这三项会把没打开的材料说成正文。

部分完成照这个最短记录填写。已闭合的问题把 `status` 改成 `answered`，并删去
`current_evidence` 和 `next_step`。至少保留一个未闭合问题：

```json
{
  "schema_version": 2,
  "research_status": "partial",
  "research_as_of": "2026-09-22T10:00:00+08:00",
  "report_sections": {
    "executive_summary": "## 执行摘要",
    "scope_and_method": "## 范围与方法",
    "limitations": "## 限制与未知事项",
    "sources": "## 来源"
  },
  "questions": [
    {
      "question_id": "Q1",
      "question": "用户要求回答的问题",
      "status": "partially_answered",
      "answer_section": "## Q1：报告里的逐字标题",
      "current_evidence": "目前已经打开并确认的证据",
      "next_step": "还要打开什么才能闭合",
      "coverage_requirements": {
        "required_source_kinds": ["official_document"],
        "independent_evidence_required": false,
        "required_checks": ["freshness"],
        "required_objects": [],
        "required_dimensions": []
      }
    }
  ],
  "sources": [
    {
      "source_id": "S001",
      "title": "来源标题",
      "publisher": "发布者",
      "url": "https://example.com/body",
      "accessed_at": "2026-09-22",
      "access_status": "full_text",
      "content_origin": "host_opened_page",
      "source_kind": "official_document",
      "stakeholder_relation": "first_party",
      "question_ids": ["Q1"]
    }
  ],
  "key_claims": [],
  "research_rounds": [
    {
      "round_id": "R1",
      "round_type": "main_research",
      "focus": "主体研究",
      "target_question_ids": ["Q1"],
      "strategy_types": {"Q1": ["primary_sources"]},
      "checks_completed": {"Q1": []},
      "objects_checked": {"Q1": []},
      "dimensions_checked": {"Q1": []},
      "conclusion_impact": {"Q1": "changed"},
      "material_findings": ["本轮写入报告的发现"]
    }
  ]
}
```

问题状态只能是 `answered`、`partially_answered`、`unanswered`、`unsupported`。
`required_checks` 和 `checks_completed` 只能是 `freshness`、`counterevidence`、
`omitted_objects`、`omitted_dimensions`。`primary_sources`、`independent_validation`、
`omission_scan`、`user_material` 只放在 `strategy_types`，不要放进检查名单。
`access_status` 只能是 `full_text`、`substantive_sections`、`metadata_only`、
`unavailable`。研究轮次 `round_type` 只能是 `main_research`、`coverage_gap_check`、
`adversarial_saturation_check`。`conclusion_impact` 只能是 `changed`、`strengthened`、
`narrowed`、`none`。这轮没有改变结论时写 `none`。写成 `unchanged` 时检查程序会归一。部分完成至少要有一轮
`main_research`；没做完的缺口检查写在对应问题的 `next_step`，不要编造已经执行的轮次。

没有需要单独登记的关键句时，`key_claims` 保持空数组。要登记时，`claim` 必须是报告里的原句，
`claim_type` 只能是 `current_fact`、`quantitative`、`comparative`、`recommendation`、
`risk`、`adoption`、`background`。优先使用这些词。写成 `fact` 或 `calculation` 时，检查程序会归一，不必为此重写报告。

```json
{
  "claim_id": "K1",
  "claim_type": "current_fact",
  "claim": "与 final_report.md 逐字相同的句子",
  "question_ids": ["Q1"],
  "source_ids": ["S001"],
  "evidence_locator": "支持该句的章节或表格",
  "evidence_quote": "打开页面中包含该数字的原句；没有价格或百分比时可省略"
}
```

续跑时不要整篇重写。用户要求补缺口，或上一份报告已经是 `partial` 时，在新的记录里写：

```json
"continuation": {
  "mode": "gap_fill",
  "frozen_question_ids": ["Q1"],
  "open_question_ids": ["Q2"]
}
```

已经闭合的问题保持 `answered`，对应句子不要改写。报告里用 `## 本次只补这些缺口` 列出仍要补的
问题；英文可以用 `## Gaps to fill`。只打开这些缺口还缺的正文。

## 5. 停止与完成

只有同时满足以下条件才可标记 `complete`：

- 原始问题清单全部在报告中得到明确回答；
- 每个问题要求的来源类型、独立证据、检查、对象和维度全部覆盖；
- 没有未关闭的高优先级证据缺口；
- 已执行覆盖缺口和对抗性饱和检查；
- 开放全景还要：全景地图每个分段都有实体和打开的正文，覆盖表齐全，检索覆盖至少四种面向并
  做过引用滚雪球，最后一轮饱和检查确实读了新来源且没有新的实质发现；
- 最后一次饱和检查没有再改变、收窄或推翻主要结论；
- 关键结论及引用出现在对应问题的论证章节中且可核验；
- 报告从头到尾完整可读；
- 能解释为什么继续搜索不太可能改变主要结论。

否则：

- 已有可用证据但问题未完全闭合时交付 `partial`。每个未闭合问题写上 `current_evidence` 和 `next_step`。缺口由检查程序计算，不要另写一份相同的停止理由；
- 授权、工具、访问或核心证据条件使研究无法继续时交付 `blocked`，列出阻塞条件和解除条件；
- 不要把诚实的 `partial`／`blocked` 伪装成完整报告，也不要把它们当作 validator 失败。

运行最小底线检查：

```bash
# macOS / Linux
python3 <skill-dir>/scripts/validate_research_bundle.py <bundle-dir>

# Windows PowerShell / CMD
py -3 "<skill-dir>\scripts\validate_research_bundle.py" "<bundle-dir>"
```

脚本需要 Python 3.10 或更高版本，只使用标准库；Windows 没有 `py` launcher 时把命令中的
`py -3` 换成可用的 `python`。它按 `complete`、`partial`、`blocked` 分别检查状态合同，
检查逐问题来源与检查覆盖、饱和停止、关键引用、比较表、已保存页面中的数字、读者稿开头的
未完成项、计划、进度、续跑范围、候选文件哈希和独立复核记录。合法的部分交付返回校验成功
并保留 `partial`／`blocked` 标签。脚本不重新上网，只核对这次保存下来的正文里有没有那个
数字；覆盖要求是否合理或报告是否优秀，仍由独立复核判断。

所有路径都使用宿主原生绝对路径或 bundle 内相对路径。不要假定 `/tmp`、POSIX 路径或
`cygpath` 一定存在；Windows 工具要求盘符路径时，先用宿主提供的路径转换能力取得
`C:\...` 形式，再读取文件。`snapshot_path` 必须留在 bundle 目录内。

## 6. 独立审阅

完整报告必须由未参与生成的 reviewer 从头到尾阅读。Reviewer 使用未继承生成对话的新鲜
上下文，只接收原始请求、候选产物和核验来源。Reviewer：

- 逐项核对原始问题是否回答；
- 核验全部关键结论，并抽检普通事实；
- 检查覆盖要求是否合理、是否提前停止，以及明显遗漏、过时信息、错误对象、错误价格和
  不受支持的建议；
- 只评价，不修补候选报告。

先运行 validator 并取得候选文件 SHA-256，再把复核结果和这些哈希保存为
`independent_review.json`，随后再次运行 validator。最小格式、独立性标准和宿主示例见
[report-quality.md](references/report-quality.md)。报告和 validator 完成但尚无独立审阅时，
交付标签只能是 `complete_draft`；只有独立 reviewer 给出 `0 blocker / 0 major`、确认研究
深度充分且饱和检查可信、全部问题覆盖和全部关键 claim 核验通过，并且候选文件哈希未变化时，validator 才会产生
`reviewed_pass`。宿主没有隔离 reviewer 时如实交付未复核草稿，不能由生成者自评为通过。

Validator 通过、来源很多或文件很大都不能替代独立审阅结论。

隐私、授权和失败关闭边界见
[privacy-and-fail-closed.md](references/privacy-and-fail-closed.md)。
