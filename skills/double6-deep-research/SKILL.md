---
name: double6-deep-research
version: 2.0.2
description: 在用户授权范围内使用宿主搜索、网页和本地材料完成多来源研究；在指定目录写入报告、记录、SHA-256 候选哈希与验证回执，并运行 Python validator。用于深入调研、对象比较、证据化决策和复杂事实核验。
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

交付可核验的报告；validator 通过不等于质量合格。

## 1. 冻结任务合同

把请求拆为问题清单，冻结对象、时间、地域、排除项、输出形态、比较维度和决策用途，并
区分当前与历史材料。仅在关键歧义会改变报告时提问，否则采用保守假设并说明；
语言和格式跟随用户请求。

用户明确要求的成本、时延、部署、采用和风险等维度须分别成为可检查的问题。

## 2. 制定自适应研究计划

为每个问题冻结来源类型、独立证据、时效／反证／遗漏检查、对象和维度。优先一手来源；
比较、建议、风险和采用结论不能只依赖利益相关方自述。来源是否充分取决于问题、对象、
反例和证据角色是否覆盖，以及继续搜索是否仍会改变主要结论，不能用预设数量、工具返回
上限、耗时或固定轮次代替充分性判断。

## 3. 研究并持续补最高缺口

只使用宿主已经提供且用户允许的搜索、网页、浏览器或材料读取能力。不要配置 provider、
读取 credential、启动自建 runtime，或执行与研究交付无关的外部操作。

权限边界：先确认用户允许访问的网页和本地材料；本地读取仅限这些材料与交付目录，写入
仅限该目录中的报告、审阅和验证文件。validator 只读该目录、计算候选 SHA-256 并写入
`validation_receipt.json`，不联网、不读凭据，也不写其它路径。

按以下职责循环研究：

1. 按问题而不是按网站收集材料；
2. 打开正文，区分全文、实质章节、元数据和不可访问状态；
3. 记录来源标题、发布者、URL、访问日和支持范围；时效性来源同时记录发布日期；
4. 对日期、价格、百分比、排名和建议所依赖的事实保存精确证据；
5. 完成主体覆盖后，按覆盖合同检查缺少的来源角色、对象、维度、更新材料和反证；
6. 再用不同策略执行对抗性饱和检查，主动寻找会改变、收窄或推翻主要结论的证据；
7. 最后一轮仍改变主要结论时继续研究，直到新的饱和检查不再产生实质变化，或如实交付
   `partial`／`blocked`。

导航页、登录页、脚本壳、错误页和搜索摘要不得标记为 `full_text` 或充当正文证据。应改找
官方正文、PDF 或仓库原始文档；替代来源只能支持其实际覆盖的较窄结论。快照必须来自宿主
实际取得的页面或文档，并记录 SHA-256，不能用研究者摘要冒充原文。

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

交付目录只需：

```text
request_snapshot.md
final_report.md
research_record.json
snapshots/                 # 仅在实际保存正文时需要
validation_receipt.json    # 运行最小 validator 后生成
independent_review.json     # 完成独立审阅后生成
```

`research_record.json` 使用 schema v2，最小字段见
[report-quality.md](references/report-quality.md)。只登记问题、来源、关键 claim、研究轮次
和停止理由，不保存完整查询或候选全集。必须分别记录 `research_status`、
`research_as_of`、逐问题覆盖要求、来源材料类型和利益关系、各轮检查策略与结论影响；
不要用一个模糊的 `status` 同时表达研究完成度与独立复核结果。

## 5. 停止与完成

只有问题、来源角色、独立证据、检查、对象和维度全部覆盖，没有高优先级缺口，且最后一次
对抗性饱和检查不再改变主要结论时，才可标记 `complete`。尚有可继续补齐的缺口时交付
`partial`；授权、工具、访问或核心证据阻断时交付 `blocked`。两者都必须列出缺口、当前证据
和解除或下一步条件，不能伪装成完整报告。

运行最小底线检查：

```bash
# macOS / Linux
python3 <skill-dir>/scripts/validate_research_bundle.py <bundle-dir>

# Windows PowerShell / CMD
py -3 "<skill-dir>\scripts\validate_research_bundle.py" "<bundle-dir>"
```

脚本需要 Python 3.10+ 且只使用标准库；Windows 没有 `py` 时使用可用的 `python`。它检查
状态合同、逐问题覆盖、饱和停止、引用、候选哈希和复核记录，但不联网判断来源真实性或
研究质量。路径须使用宿主原生绝对路径或 bundle 内相对路径，`snapshot_path` 不得越界。

## 6. 独立审阅

完整报告必须由未参与生成、未继承生成对话的 reviewer 阅读原始请求、候选产物和核验来源；
reviewer 只评价，不修补。先运行 validator 取得候选哈希，保存
`independent_review.json` 后再验证。未隔离复核时只能交付 `complete_draft`；只有 `0 blocker /
0 major`、问题与关键 claim 全部核验、深度和饱和检查可信且哈希未变化时才是
`reviewed_pass`。格式与完整复核清单见 [report-quality.md](references/report-quality.md)。

隐私、授权和失败关闭边界见
[privacy-and-fail-closed.md](references/privacy-and-fail-closed.md)。
