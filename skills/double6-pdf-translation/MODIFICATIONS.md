# 来源与维护变更

## 公开版 3.1.0（2026-10-31）

- 审计盲区自动化：新增第一方模块 `scripts/ink_metrics.py`（写回墨迹覆盖率测量：整页灰度栅格化、bbox 切片暗像素比例、逐行测量与分类；零墨迹 ≤0.5% 绝对判据 + 同页中位数相对基准）与 `scripts/audit_blindspots.py`（行尾截断守恒检查 + 写回墨迹抽查；段落终结性 + 悬空功能词 + 源段数字守恒双确认，无源段证据时报警线从 3 分提至 4 分压图题误报；孤立符号行不做 low-ink 相对判定）。`translation_continuation.py` 每页结果组装处最小挂接：issue code 上浮翻译审校记录并写 `receipts/audit/BLINDSPOT_AUDIT.json`，不改路由分发、重试与交付判定，审计器自身故障只记 `blindspot_audit_unavailable`。
- 日文横排 ja→zh（电子路线）：`pdf_input_preflight.detect_language` 增补假名/谚文区块（ja：假名 ≥10 且占汉字+假名 ≥10%；ko：谚文 ≥20 且占绝对主体；无假名/谚文时与旧版逐字一致）；`run_pdf_translation_context` 新增 `DEFAULT_SYSTEM_PROMPT_JA2ZH` 与 `PAPER_TRANSLATION_SOURCE_LANGUAGE` 显式声明、`resolve_system_prompt` 三级方向分支；`pdf_translation_render.resolve_input_source_language`（声明 > 输入前 3 页检测）贯穿提示词、`--lang-in`（`pdf_translation_commands`，纯英译中命令行不变）与 render_manifest 的 `source_language(_basis)`；`render_residue_check` 新增 `check_japanese_residue` 假名残留门（缺省行为不变），`qa_pipeline`/`pdf_translation_runtime` 透传；`configs/model-profiles.json` 两档案补 `translation_directions` 能力标注。**不引入字体管理框架**：电子写回字体链与 3.0.0 相同。
- 编排优化（T10-B，电子路线）：B1 单页任务页级 dual 提升为任务级双语件（`PAPER_TRANSLATION_DISABLE_DUAL_REUSE` 可关，row 记 `bilingual_reuse`）；B4 babeldoc `pdf_creater` 字体子集默认共享内存、溢出/失败/超时自动回退落盘（产物字节等价实证；`BABELDOC_SUBSET_DISK` 诊断路径保留）；B5 页级预检事实入 FREEZE、candidate 身份核对通过跳过预检子进程（首页保留抽样复核，拒绝码逐字保持；`PAPER_TRANSLATION_DISABLE_PREFLIGHT_REUSE` 可关）；B6 纯电子页多信号合取高置信门 + 页型历史 ≥3 次真实盲区审计全过 → 跳过重核与盲区审计（workspace 级 append-only 历史，跳过显式留痕；`PAPER_TRANSLATION_DISABLE_LIGHT_REVIEW` 可关）。B2 后端预热经实测无净收益，未采纳。
- 双语方向修正：`build_bilingual_pdf` 支持方向对补 (ja,zh)/(ko,zh)、语言标签补日文/韩文；`translation_continuation._resolved_document_source_language`（页 render_manifest 多数 > 声明环境变量 > 输入检测 > 旧默认）驱动终局双语件方向并写 `bilingual_direction_source` 证据，ja/ko 源页签/文件名不再错标英文，既有 en/zh 流程行为不变。
- 新增测试：`test_audit_blindspots.py` 8 例、`test_multilang_preflight.py` 9 例、`test_multilang_render.py` 4 例、`test_bilingual_direction_multilang.py` 5 例（源语言证据链按 render_manifest 口径）。
- 以上均为第一方维护代码（AGPL-3.0-only）；除 `vendor/babeldoc` 的 `pdf_creater.py`（B4 字体子集共享内存，维护性修改随 vendor 目录说明保留）外未改动其它上游 vendor 文件。

## 公开版 3.0.0（2026-10-30）

- 本公开包自 3.0.0 起仅含电子版翻译路线；扫描 OCR 路线及其维护历史不在本包中。
- 相对上游 BabelDOC / PDFMathTranslate-next 的维护性修改随各 vendor 目录内说明与提交历史保留。
