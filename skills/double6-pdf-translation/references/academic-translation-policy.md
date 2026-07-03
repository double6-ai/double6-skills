# 学术论文翻译规则

## 标题与摘要

- 标题先判断领域和双关，再翻译。不要逐词硬译。
- 缩写、系统名、数据集名、模型名默认保留原文；首次出现时可加中文解释。
- `LLM` / `LLMs` 在大模型论文中表示 large language model(s)，优先译为“大型语言模型”或保留为 `LLMs（大型语言模型）`，不能译成“法学硕士”。
- `Literature Review` 在学术论文语境中通常是“文献综述”，不是“文学评论”。
- `Human-Centered AI` 在 AI Index / HAI 语境中优先译为“以人为本人工智能”，不要直译成“人类中心人工智能”。
- `Hong Kong Polytechnic University` 是“香港理工大学”，不要误译为“香港大学”。
- `AI sovereignty` 优先译为“人工智能主权”；报告目录中的 `Research and Development` 优先译为“研究与开发”，正文中可按语境使用“研发”。
- 如果标题包含自造词，例如 `LitLLMs`，默认保留原文，并在译注或首次出现处解释。

## 术语

- 翻译前先建立 `glossary.tsv`，至少覆盖标题、摘要、关键词和高频专有名词。
- 术语表优先级高于模型临场翻译。
- 同一术语在全文中保持一致；除非作者明确区分多个含义，不能一会儿译成 A、一会儿译成 B。
- 对领域术语不确定时，保留英文并加括号解释，比误译更好。
- 用户人工修订术语后，应更新术语表并生成受影响 block 的局部重译计划，不要只在最终译文里手工替换一次。

## 结构与格式

- 保留章节层级、图表编号、公式编号、引用编号、算法编号、脚注、URL、代码块和数据集名称。
- 公式和符号默认不翻译，只翻译公式周围的解释文字。
- 表格可翻译表头和说明，数值、单位和引用标记保持原样。
- 参考文献列表默认不翻译作者、标题和来源，除非用户明确要求。
- `protected_spans.json` 中列出的元素必须原样保留；如确需改写，必须在质量报告或译注中说明原因。
- 分块翻译时，每个 block 都要保留可回查锚点，不得合并到无法追踪原文位置的长段落里。

## 风格

- 默认风格是学术、准确、可读，避免过度口语化，也避免生硬机翻。
- 长句可以拆分，但不能改变逻辑关系、否定范围、实验结论或限制条件。
- 对 `may`、`might`、`suggest`、`indicate` 等保守措辞保持保守，不要强化成确定结论。
- 对 `associated with`、`correlated with`、`association` 等相关性表达保持为“相关/有关联”，不能翻成“导致/造成/引起”。
- 对 `cannot conclude`、`limited evidence`、`insufficient evidence`、`no evidence` 等证据限制必须保留，不能弱化或删除。
- 对作者的局限性、威胁有效性、未来工作等段落保持克制，不替作者补结论。

## 译注

- 译注只用于消除歧义、解释自造词或说明保留原文原因。
- 译注应简短，避免把译文变成扩写综述。

## MQM 质检

- 质检时按 `accuracy / entity_accuracy / terminology / coverage / omission / addition / style / structure / protected_span / source_quality / rendering` 标注问题类型。
- 对高/中风险问题必须尽量给出 `block_id`、页码、源文证据、译文证据和建议修订；如果是整篇级问题，使用 `document/global` 标记。
- 对 `may`、`might`、`suggest`、`indicate` 等保守措辞被强化的情况，归入 `accuracy`。
- 对公式、引用、DOI、URL、代码、LaTeX 命令丢失或被翻译的情况，归入 `protected_span`。
- 对机构、作者、项目、出版物等专名实体误译，归入 `entity_accuracy`。
- 对页面覆盖缺口、截取样本边界或章节连续性风险，归入 `coverage`。
- 对 PDF 抽取导致的页眉页脚、断词、元数据混排、双栏错序、长英文 token 和异常 heading，归入 `source_quality`，不要混同为模型翻译失败。
- 对译文 PDF/HTML 的兼容汉字、中文缺字、目录错位、脚注漂移和底层原文残留，归入 `rendering`。
