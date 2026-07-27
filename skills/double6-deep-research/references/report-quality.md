# 最小研究记录与报告审阅

## 目录

- [`research_record.json`](#research_recordjson)
- [状态合同](#状态合同)
- [`independent_review.json`](#independent_reviewjson)
- [独立性与候选文件完整性](#独立性与候选文件完整性)
- [完整报告判定](#完整报告判定)

## `research_record.json`

schema v2 把研究完成度与复核结果分开。`research_record.json` 只记录研究本身：

```json
{
  "schema_version": 2,
  "research_status": "complete",
  "research_as_of": "2026-07-26T18:00:00+08:00",
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
      "status": "answered",
      "answer_section": "## Q1：报告中的逐字标题",
      "coverage_requirements": {
        "required_source_kinds": [
          "official_document",
          "independent_evaluation"
        ],
        "independent_evidence_required": true,
        "required_checks": [
          "freshness",
          "counterevidence",
          "omitted_objects",
          "omitted_dimensions"
        ],
        "required_objects": ["对象甲", "对象乙"],
        "required_dimensions": ["成本", "时延"]
      }
    }
  ],
  "sources": [
    {
      "source_id": "SRC_RUNPOD",
      "title": "来源标题",
      "publisher": "发布者",
      "url": "https://example.com/body-page",
      "published_at": "2026-07-20",
      "accessed_at": "2026-07-26",
      "access_status": "full_text",
      "content_origin": "host_opened_page",
      "source_kind": "official_document",
      "stakeholder_relation": "first_party",
      "question_ids": ["Q1"],
      "snapshot_path": "snapshots/SRC_RUNPOD.md",
      "snapshot_sha256": "仅在实际保存正文时填写"
    },
    {
      "source_id": "SRC_INDEPENDENT",
      "title": "独立评测标题",
      "publisher": "独立评测机构",
      "url": "https://example.net/evaluation",
      "published_at": "2026-07-21",
      "accessed_at": "2026-07-26",
      "access_status": "full_text",
      "content_origin": "host_opened_page",
      "source_kind": "independent_evaluation",
      "stakeholder_relation": "independent",
      "question_ids": ["Q1"]
    }
  ],
  "key_claims": [
    {
      "claim_id": "K1",
      "claim_type": "comparative",
      "claim": "逐字存在于 final_report.md 的关键结论",
      "question_ids": ["Q1"],
      "source_ids": ["SRC_RUNPOD", "SRC_INDEPENDENT"],
      "evidence_locator": "支持该结论的章节、表格、页码或段落"
    }
  ],
  "research_rounds": [
    {
      "round_id": "R1",
      "round_type": "main_research",
      "focus": "主体研究",
      "target_question_ids": ["Q1"],
      "strategy_types": {
        "Q1": ["primary_sources"]
      },
      "checks_completed": {
        "Q1": ["freshness"]
      },
      "objects_checked": {
        "Q1": ["对象甲", "对象乙"]
      },
      "dimensions_checked": {
        "Q1": ["成本", "时延"]
      },
      "conclusion_impact": {
        "Q1": "changed"
      },
      "material_findings": ["本轮改变报告结论的发现"]
    },
    {
      "round_id": "R2",
      "round_type": "coverage_gap_check",
      "focus": "来源角色、对象和维度缺口",
      "target_question_ids": ["Q1"],
      "strategy_types": {
        "Q1": ["independent_validation", "omission_scan"]
      },
      "checks_completed": {
        "Q1": ["omitted_objects", "omitted_dimensions"]
      },
      "objects_checked": {
        "Q1": ["对象甲", "对象乙"]
      },
      "dimensions_checked": {
        "Q1": ["成本", "时延"]
      },
      "conclusion_impact": {
        "Q1": "strengthened"
      },
      "material_findings": ["补齐的覆盖缺口"]
    },
    {
      "round_id": "R3",
      "round_type": "adversarial_saturation_check",
      "focus": "反证与结论稳定性",
      "target_question_ids": ["Q1"],
      "strategy_types": {
        "Q1": [
          "independent_validation",
          "counterevidence",
          "freshness",
          "omission_scan"
        ]
      },
      "checks_completed": {
        "Q1": [
          "freshness",
          "counterevidence",
          "omitted_objects",
          "omitted_dimensions"
        ]
      },
      "objects_checked": {
        "Q1": ["对象甲", "对象乙"]
      },
      "dimensions_checked": {
        "Q1": ["成本", "时延"]
      },
      "conclusion_impact": {
        "Q1": "none"
      },
      "material_findings": []
    }
  ],
  "stop_decision": {
    "status": "complete",
    "coverage_complete": true,
    "missing_required_source_kinds": {},
    "missing_independent_evidence": [],
    "unchecked_required_checks": {},
    "unchecked_objects": {},
    "unchecked_dimensions": {},
    "unresolved_high_priority_conflicts": [],
    "premature_stop_checks": {
      "tool_result_limit_used": false,
      "preset_source_count_used": false,
      "time_limit_used": false,
      "fixed_round_count_used": false
    },
    "remaining_high_priority_gaps": [],
    "adequacy_rationale": "逐项说明问题、对象、来源角色和反证为何已经充分。",
    "why_more_search_unlikely_to_change_conclusions": "说明最后的缺口检查结果。"
  }
}
```

schema v1 bundle 需要迁移后再使用 2.0.0 validator：

- 把顶层 `status` 改为 `research_status`；
- 增加 `research_as_of` 和 `report_sections`；
- 为每个问题增加 `coverage_requirements`；
- 为每个来源增加 `source_kind`、`stakeholder_relation` 和 `question_ids`；
- 为每个关键 claim 增加 `claim_type` 和 `question_ids`；
- 把研究轮次迁移为主体覆盖、覆盖缺口和对抗性饱和检查；
- 补齐结构化停止证明；
- 按下文补齐 `partial`／`blocked` 的结构化字段。

validator 对旧 schema 失败关闭并返回 `schema_version_invalid:expected_2`，避免把缺少新状态
和审阅合同的旧记录误判为 2.0.0 合格交付。

`research_as_of` 使用 `YYYY-MM-DD` 或带时区的 ISO 8601 时间。涉及当前状态、价格、政策、
版本或排名时，还要优先记录各来源的 `published_at`，必要时在具体 claim 附近说明更窄的
事实时间点。

`report_sections` 的值是 `final_report.md` 中逐字存在的 Markdown 标题。它让 validator
无需猜测报告语言；日语、法语或其它语言无需额外关键词表。

问题状态只能是：

- `answered`：有明确答案、必要证据和边界；
- `partially_answered`：只回答部分范围或维度；
- `unanswered`：没有实质答案；
- `unsupported`：写出了答案，但关键证据不成立。

来源 ID 使用大写字母开头，只包含大写字母、数字、下划线或连字符，例如 `S01`、
`SRC_RUNPOD` 或 `A1`。正文用 `[SRC_RUNPOD]` 形式引用。关键 claim 的原句及其全部
source IDs 必须出现在同一正文段落或同一表格行。

> **逐字节匹配要求**：validator 用子串匹配检查 claim 文本是否出现在报告中，因此
> `research_record.json` 里的 `claim` 字符串必须与 `final_report.md` 中的原句**逐字节一致**，
> 包括引号与标点样式。建议正文和 claim 统一使用 **ASCII 双引号 `"`**，避免中文花引号 `“”`
> 或全角符号——它们肉眼相似但 Unicode 码点不同（`0x22` vs `0x201C`/`0x201D`），会触发
> `key_claim_not_in_report` 校验失败。复制正文时直接取整段、不要重打标点。

`source_kind` 描述材料类型：

- `official_document`
- `scholarly_research`
- `independent_evaluation`
- `industry_analysis`
- `user_or_adoption_evidence`
- `journalism`
- `other`

`stakeholder_relation` 单独描述来源与被研究对象的利益关系：

- `first_party`
- `independent`
- `interested_third_party`
- `user_provided`
- `unknown`

因此厂商官方页可以同时是 `official_document` 和 `first_party`，不会被“官方”标签掩盖
利益关系。`question_ids` 说明该来源或关键 claim 实际服务哪些问题。

`snapshot_path` 是可选字段。没有保存正文时不要伪造；reviewer 直接打开 URL 核验关键
claim。保存快照时只能保存宿主实际取得的正文或文档，不能把研究摘要写入快照。
`metadata_only` 和 `unavailable` 来源不能支撑关键 claim。

## 覆盖要求与研究深度

每个问题在开始检索前声明 `coverage_requirements`。validator 只把与该问题绑定、
`access_status` 为 `full_text` 或 `substantive_sections`，并且在该问题回答章节实际引用的
来源计入覆盖，再根据来源记录自动推导已覆盖类型和独立来源。不在报告论证中使用的 ledger
条目不能补足覆盖；规范化后 URL 重复的来源也会被拒绝。

每个已回答或部分回答的问题必须指向一个独立的 `answer_section`。它不能复用执行摘要、
方法、限制、来源等通用章节，也不能用文档顶层标题把后续书目包进答案；不同问题默认不能
静默共享同一个回答章节。每个关键 claim 及其每条引用也必须同时出现在它所绑定问题的回答
章节中。执行摘要可以重复关键判断，但只在来源列表、方法或限制章节出现的文字和引用不能
充当关键 claim 或覆盖证据。

三类任务可按下列方式制定要求：

| 任务类型 | 来源与独立性 | 检查重点 | 对象与维度示例 |
|---|---|---|---|
| 开放全景 | 官方／论文／可靠行业分析；主要趋势需要独立证据 | 时效性、反证、遗漏类别 | 技术类别、代表对象；成熟度、采用、风险 |
| 固定比较 | 各对象的一手材料与独立评测 | 时效性、反证、遗漏对象和维度 | 用户指定对象；成本、时延、部署、限制 |
| 有界决策 | 一手事实、独立验证和真实采用材料 | 反证、遗漏选项、行动风险 | 候选方案；收益、成本、可逆性、风险 |

这些是覆盖模式，不是来源数量配额。狭窄、稳定且只有一个权威事实出口的问题可以只要求
`official_document`；比较胜负、建议、风险和真实采用不能只依赖利益相关方材料。

`required_checks` 只能包含：

- `freshness`
- `counterevidence`
- `omitted_objects`
- `omitted_dimensions`

`required_objects` 和 `required_dimensions` 没有适用项时使用空数组。完整交付时，validator
从研究轮次的 `objects_checked`、`dimensions_checked` 和 `checks_completed` 计算差集；
任何缺项都会阻止 `complete`。

关键 claim 的 `claim_type` 只能是：

- `current_fact`
- `quantitative`
- `comparative`
- `recommendation`
- `risk`
- `adoption`
- `background`

`comparative`、`recommendation`、`risk` 和 `adoption` 在 `complete` 状态下必须至少绑定一个
内容实质且 `stakeholder_relation` 为 `independent` 的来源。只有第一方材料时应缩小结论，
或交付 `partial` 并记录独立证据缺口。

## 研究轮次与饱和检查

研究轮次按职责使用：

- `main_research`：完成主体覆盖；
- `coverage_gap_check`：补来源角色、对象、维度和必要检查；
- `adversarial_saturation_check`：使用不同策略寻找反证、更新和遗漏，验证结论稳定性。

每轮必须记录：

- `target_question_ids`
- `strategy_types`
- `checks_completed`
- `objects_checked`
- `dimensions_checked`
- `conclusion_impact`

除 `target_question_ids` 外，上述字段都按问题 ID 映射；即使某问题本轮没有新增检查、对象或
维度，也要显式使用空数组。这样一个轮次覆盖多个问题时，不会把只为其中一个问题完成的
检查或结论变化误记给其它问题。

`strategy_types` 只能使用 `primary_sources`、`independent_validation`、
`counterevidence`、`freshness`、`omission_scan`、`user_material`。
`conclusion_impact` 只能是 `changed`、`strengthened`、`narrowed` 或 `none`。

完整交付要求每个问题按 `main_research → coverage_gap_check →
adversarial_saturation_check` 的顺序经过上述三种职责。最后一次饱和检查必须重新完成该问题
的全部 `required_checks`，使用至少一种反证、独立验证、时效性或遗漏策略，并且不能与主体
轮策略完全相同；其影响必须为 `none`。饱和检查后如有其它轮次再次改变、加强或收窄结论，
必须重新执行饱和检查。轮次数本身不是停止依据。

## 状态合同

`research_status` 只能是：

- `complete`：所有问题为 `answered`，没有剩余高优先级缺口；
- `partial`：至少一个问题未完整回答，但已有可交付证据；
- `blocked`：授权、工具、访问或核心证据条件使研究无法继续。

`stop_decision.status` 必须与 `research_status` 相同。

停止证明中的覆盖字段使用以下形态：

- `missing_required_source_kinds`、`unchecked_required_checks`、`unchecked_objects`、
  `unchecked_dimensions`：以问题 ID 为 key、缺失项数组为 value，只保留存在缺口的问题；
- `missing_independent_evidence`：仍缺独立证据的问题 ID 数组；
- `unresolved_high_priority_conflicts`：包含 `question_id`、`conflict`、
  `current_evidence`、`next_step` 的对象数组；
- `coverage_complete`：上述派生缺口和高优先级冲突都为空时才为 `true`；
- `premature_stop_checks`：完整列出 `tool_result_limit_used`、
  `preset_source_count_used`、`time_limit_used`、`fixed_round_count_used`。

前三类覆盖缺口由 validator 根据问题要求、来源和研究轮次重新计算，声明值必须与计算结果
完全一致。`complete` 时全部缺口为空，且所有提前停止项都必须为 `false`。

`partial` 时，每个未完整回答的问题必须增加：

```json
{
  "status": "partially_answered",
  "current_evidence": "当前已经确认的证据和边界",
  "next_step": "下一步应获取或核验什么"
}
```

并在 `remaining_high_priority_gaps` 中逐项记录：

```json
{
  "question_id": "Q2",
  "gap_type": "missing_independent_evidence",
  "missing_items": ["independent"],
  "gap": "仍缺少什么",
  "current_evidence": "目前能确认到哪里",
  "next_step": "如何关闭缺口"
}
```

`gap_type` 只能是 `missing_source_kind`、`missing_independent_evidence`、
`unchecked_required_check`、`unchecked_object`、`unchecked_dimension`、
`unresolved_conflict` 或 `other`。`partial` 中每个由 validator 推导出的覆盖缺口都必须在
`remaining_high_priority_gaps` 中逐项登记；其它无法通过公开研究闭合的问题使用 `other`。
每个状态不是 `answered` 的问题也必须至少有一个 gap。`partial` 至少要有主体研究轮；
访问、授权或资源限制导致未完成缺口／饱和检查时，把对应必要检查登记为 gap，而不是伪造
已经执行的轮次。

`blocked` 时还必须记录 `blocking_conditions` 和 `unblock_requirements`。阻塞发生在开始
研究之前时，`sources`、`key_claims` 和 `research_rounds` 可以为空，但仍应交付范围、
已知边界和解除条件。

研究状态和复核状态是两个独立轴。最终交付标签由 validator 派生：

| 研究状态 | 复核结果 | 交付标签 |
|---|---|---|
| `complete` | 无复核文件 | `complete_draft` |
| `complete` | `pass` | `reviewed_pass` |
| `complete` | `fail` | `reviewed_fail` |
| `partial` | 无复核或 `fail` | `partial` |
| `blocked` | 无复核或 `fail` | `blocked` |

`partial` 和 `blocked` 是诚实、可验证的交付状态，不是 validator 错误。只有结构不满足相应
状态合同，或不完整研究被标为复核通过时，validator 才返回错误。

## `independent_review.json`

独立 reviewer 至少保存：

```json
{
  "reviewed_at": "2026-07-26T20:00:00+08:00",
  "independence_basis": "isolated_agent",
  "verdict": "pass",
  "counts": {
    "blocker": 0,
    "major": 0,
    "minor": 0
  },
  "question_coverage": [
    {
      "question_id": "Q1",
      "status": "complete",
      "notes": "是否实质回答及其边界"
    }
  ],
  "critical_claim_checks": [
    {
      "claim_id": "K1",
      "status": "verified",
      "notes": "核验结果"
    }
  ],
  "sampled_fact_checks": [],
  "no_sampleable_facts_reason": "没有可与关键 claim 分离的普通事实时填写；否则省略此字段",
  "depth_assessment": "adequate",
  "coverage_requirements_adequate": true,
  "premature_stop": false,
  "missing_source_roles": [],
  "omitted_objects": [],
  "omitted_dimensions": [],
  "saturation_check_credible": true,
  "findings": [],
  "candidate_files_modified": false,
  "candidate_file_sha256": {
    "request_snapshot.md": "复核时文件的 SHA-256",
    "final_report.md": "复核时文件的 SHA-256",
    "research_record.json": "复核时文件的 SHA-256"
  }
}
```

`findings` 中每项至少包含 `severity` 和 `description`；`severity` 只能是 `blocker`、
`major` 或 `minor`。`counts` 必须与 findings 的实际数量一致。`pass` 要求：

- `blocker == 0` 且 `major == 0`；
- 所有问题的复核状态为 `complete`；
- 所有关键 claim 的复核状态为 `verified`；
- `depth_assessment` 为 `adequate`；
- 覆盖要求合理，没有提前停止或未披露的来源角色、对象和维度缺口；
- 对抗性饱和检查可信；
- 候选文件哈希与最终校验时完全一致。

`independence_basis` 只能是 `isolated_agent` 或 `independent_human`；`reviewed_at` 使用
`YYYY-MM-DD` 或带时区的 ISO 8601 时间。`sampled_fact_checks` 即使为空也必须保留为数组，
避免把“未记录抽检结果”和“确实没有可抽检事实”混为一谈。为空时必须填写
`no_sampleable_facts_reason`；非空时每项记录 `fact`、`status` 和 `notes`。问题覆盖与关键
claim 检查的 `notes` 也必须说明实际核验内容，不能只写状态枚举。

## 独立性与候选文件完整性

Reviewer 必须满足：

- 未参与候选报告的研究、起草或修改；
- 使用独立的新鲜上下文，不读取生成者的隐藏推理、聊天历史或草稿过程；
- 只接收 `request_snapshot.md`、候选报告、研究记录和核验来源；
- 只评价并生成 `independent_review.json`，不修改候选文件。

“独立上下文”不等于看不到任务材料；reviewer 必须完整读取原始请求和全部候选产物。它只
是不继承生成者的思路、结论偏好和未公开过程。

支持隔离子 agent 的宿主可以启动一个未继承生成对话的新 reviewer，只向它提供上述文件。
例如 Claude Code 可使用独立 subagent，Codex 可使用独立 agent；具体工具名由宿主决定。
宿主没有隔离 reviewer 时，可以交给独立人工复核，或如实交付 `complete_draft`。

第一次运行 validator 时，`validation_receipt.json` 会记录三个候选文件的 SHA-256。
Reviewer 把这些哈希复制到复核文件。加入 `independent_review.json` 后再次运行 validator；
只有当前候选文件与复核时哈希一致，才能得到 `reviewed_pass`。布尔字段
`candidate_files_modified: false` 只是声明，哈希比对才是机器证据。

## 完整报告判定

完整不等于篇幅长。validator 的 100 个实质字符下限只用于发现空文件或明显损坏文件；
它还会根据问题数量给出非阻塞的简短报告 warning，但不会用固定字数替代质量判断。
Reviewer 从原始请求建立问题清单，并逐项判断：

- `answered`：给出明确结论、必要证据和边界；
- `partially_answered`：只有背景或部分维度；
- `unanswered`：没有实质答案；
- `unsupported`：有结论但关键证据不成立。

任一核心问题为 `unanswered` 或 `unsupported` 是 blocker；多个重要问题只部分回答，或
建议无法行动，是 major。

用户明确要求的成本、时延、部署、采用、风险或其它比较轴必须逐项判断。只有方法框架、
待测指标清单或“需要进一步评估”而没有当前数据、明确未知边界或测量方案时，仍属于
`partially_answered`。

关键结论包括：执行摘要中的核心判断、所有精确数字和日期、对象身份与当前状态、比较
胜负、风险判断、成本价格、政策／法律结论和行动建议。关键结论全部核验；普通背景事实
按覆盖不同章节和不同来源的方式抽检。

来源总数只作为诊断信息。Reviewer 重点判断是否存在：

- 同一来源重复包装；
- 来源与对象或 claim 错配；
- 只有厂商自述而无独立验证；
- 明显更新材料或重要对象遗漏；
- 达到某个数字后提前停止；
- 把未知写成不存在；
- 把搜索过程或 ledger 当作报告正文。
