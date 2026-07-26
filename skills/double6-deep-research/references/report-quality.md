# 最小研究记录与报告审阅

## 目录

- [`research_record.json`](#research_recordjson)
- [`independent_review.json`](#independent_reviewjson)
- [完整报告判定](#完整报告判定)

## `research_record.json`

只保存报告完成与审阅所需的信息：

```json
{
  "schema_version": 1,
  "status": "complete",
  "questions": [
    {
      "question_id": "Q1",
      "question": "用户要求回答的问题",
      "status": "answered",
      "answer_section": "## 报告中的逐字标题"
    }
  ],
  "sources": [
    {
      "source_id": "S01",
      "title": "来源标题",
      "publisher": "发布者",
      "url": "https://example.com/body-page",
      "published_at": "时效性来源填写 YYYY-MM-DD；稳定来源可省略",
      "accessed_at": "YYYY-MM-DD",
      "access_status": "full_text",
      "content_origin": "host_opened_page",
      "snapshot_path": "snapshots/S01.md",
      "snapshot_sha256": "仅在实际保存正文时填写"
    }
  ],
  "key_claims": [
    {
      "claim_id": "K1",
      "claim": "逐字存在于 final_report.md 的关键结论",
      "source_ids": ["S01"],
      "evidence_locator": "支持该结论的章节、表格、页码或段落"
    }
  ],
  "research_rounds": [
    {
      "round_id": "R1",
      "round_type": "main_research",
      "focus": "主体研究",
      "new_useful_sources": 12,
      "material_findings": ["本轮改变报告结论的发现"]
    },
    {
      "round_id": "R2",
      "round_type": "gap_check",
      "focus": "遗漏、更新和反证",
      "new_useful_sources": 3,
      "material_findings": ["补齐的缺口或确认的稳定结论"]
    }
  ],
  "stop_decision": {
    "status": "complete",
    "remaining_high_priority_gaps": [],
    "adequacy_rationale": "逐项说明问题、对象、来源角色和反证为何已经充分。",
    "why_more_search_unlikely_to_change_conclusions": "说明最后的缺口检查结果。"
  }
}
```

`snapshot_path` 是可选字段。没有保存正文时不要伪造；reviewer 直接打开 URL 核验关键
claim。保存快照时只能保存宿主实际取得的正文或文档，不能把研究摘要写入快照。

报告正文使用 `[S01]` 形式引用 `research_record.json` 中的来源。关键 claim 的原句和其
source IDs 必须出现在同一正文段落或表格行。`metadata_only` 和 `unavailable` 来源不能
支撑关键 claim。涉及当前状态、价格、政策、版本或排名时，优先记录原文发布日期，并在
报告中明确 `as of` 时间点。

## `independent_review.json`

独立 reviewer 至少保存：

```json
{
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
  "findings": [],
  "candidate_files_modified": false
}
```

Reviewer 不得修改候选文件。没有保存这份复核产物时，即使聊天中曾口头评价，也只能把
报告标为 `complete_draft`，不能标为 `reviewed_pass`。

## 完整报告判定

完整不等于篇幅长。Reviewer 从原始请求建立问题清单，并逐项判断：

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
