# LaTeX 完整单元审校与恢复

保护 token 缺失、重复、跨固定边界或模型身份不符时，原入口停止。保留原计划、已完成单元、失败原始响应及回执。不要删除失败文件后重复调用，也不要手改原始响应或把模型未生成的修订写成模型原答。

## 保护失败后的完整单元修订

`latex_unit_review.py --contract /absolute/UNIT_REVIEW.json` 只接受尚无正式单元文件、已有原始模型响应且该响应确实被保护门拒绝的情况。模型身份、源项目、计划、实际请求身份、原始响应 SHA 与完整源单元均须一致。模型身份或响应统计不合格时，此入口不作替代修复。

合同使用 `protocol=latex_failed_complete_unit_review_v1`、`schema_version=1`，字段为：

- `output_directory`：原失败候选目录；`unit_id`：计划中的完整单元。
- `plan_ref`、`failed_raw_ref`、`source_review_ref`、`model_fingerprint_ref`：精确 `{path, sha256}`。
- `source_unit_sha256`、`complete_source_unit_reviewed=true`、具名 `reviewer`。
- `complete_masked_translation`：整份完整单元的审校修订，保留全部原保护 token；不能只交局部替换片段。

`source_review_ref` 指向具名审校记录，至少含 `status=complete_unit_reviewed`、`reviewer`、`unit_source_sha256`、逐字一致的 `complete_source_text` 及 `complete_masked_translation_sha256`。后者按完整修订 UTF-8 文本的 SHA256 计算。记录实际来源、判断依据和仍待执行的 PDF 检查。

工具再次执行原保护校验后，只追加缺失的正式单元候选；原始响应保留。单元明确标记 `operator_reviewed_complete_unit`、`new_model_calls=0`、`human_user_accepted=false`。编译时重新检查修订合同、审校和原始响应，调用计量另列操作者修订单元数。语义、页面和用户接受不因该操作自动通过。

## 继续原失败候选

```bash
python scripts/paper_translation_workflow.py resume-latex \
  --input /absolute/source.pdf --freeze /absolute/ORIGINAL_FREEZE.json \
  --output /absolute/original-partial-candidate --receipts /absolute/new/receipts \
  --previous-result /absolute/WORKFLOW_CANDIDATE.json \
  --previous-result-sha256 EXACT_SHA256 \
  --model EXPLICIT_MODEL --base-url https://configured-provider.example/v1
```

必须沿用原失败时的精确冻结合同、输入、模型、源计划和原成功准备目录。回执目录必须全新。沿父链核验原始准备回执，拒绝变更、循环、不同源、已编译候选和缓存计划漂移。已完成单元按原身份复用；失败原始响应若没有经过完整单元审校修订则停止，不新增该单元的模型请求。缺失的后续单元继续通过原 `translate` 入口生成，最后走原编译与 QA。

真实模型响应中的语义错误不能借“保护失败修复”跳过审校；已完成整件候选的源绑定返修沿用 `revise-latex`。新模型、源项目、执行实现或冻结身份发生变化时，使用新的候选目录与相应重新核验。恢复成功后仍须完整检查最终 PDF、双语、链接、阅读器复制及冷重建。
