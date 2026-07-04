# metadata 修复与可见残留候选优化记录

本文记录本地 `double6-pdf-translation` 对 PDF 后处理链路的一组防退化优化，便于原始 skill 或上游实现同步同样修复。

## 背景

SKILLRL 样例运行中出现两类问题：

- 首页正文中的普通短语 `serve as references` 被误判为参考文献标题，导致 `metadata_label_repair_runtime.py` 把首页下半部分原文区域克隆回中文译文 PDF。
- `visible_residue_repair.py` 生成的 rejected 候选 PDF 留在输出根目录，容易被误认为是正式交付。

## 已实施策略

- 参考文献区域只接受独立行标题 `References` / `参考文献`，不再使用任意单词 `references` 触发。
- `source_region_clone` 在执行前增加安全检查：
  - `references_region` 不允许作用于第 1 页；
  - `references_region` 必须包含真实参考文献证据；
  - 第 1 页正文区、`Introduction`、`Abstract`、`Preprint` 等普通正文区域禁止克隆。
- `metadata_label_repair_manifest.json` 增加交付选择信号：
  - `unsafe_clone_skipped_count`
  - `selected_as_delivery`
  - `delivery_status`
- 主流程只在 `metadata_label_repair_manifest.selected_as_delivery == true` 时采用 `metadata-label-repaired` PDF。
- 最终交付清理会把 metadata repair 与 visible residue repair 的 `output_pdf` 都纳入清理候选；未被选作交付的候选 PDF 不应留在输出根目录。
- partial/blocking 运行仍保留标准两份 PDF 作为诊断产物，但 CLI summary 会输出 `delivery_gate_status`、`worst_gate` 和 `delivery_contract`，提醒不要当作最终合格交付。

## 移植要点

同步到原始 skill 时，至少需要更新以下位置：

- `scripts/metadata_label_repair_runtime.py`
  - 增加独立参考文献标题判断。
  - 增加 source-region clone 安全检查。
  - 增加 metadata repaired PDF 的 `selected_as_delivery` 语义。
- `scripts/run_pdf_translation.py`
  - 改为只按 `selected_as_delivery` 采用 metadata repaired PDF。
  - 将 rejected/unsafe repair PDF 加入最终 cleanup candidates。
  - partial summary 中暴露交付降级契约。

## 验收建议

- 首页正文包含 `serve as references` 时，不应生成第 1 页 `references_region` clone。
- 独立 `References` 标题页仍应生成真实参考文献 clone。
- 第 1 页正文区域 clone 被跳过时，manifest 应标记 `unsafe_clone_skipped`，且不应选作交付。
- rejected visible-residue candidate PDF 不应残留在输出根目录。
- 对 SKILLRL 源 PDF 重新生成 repair plan 时，`references_region` clone 应只出现在真实参考文献页，不应出现在第 1 页。
