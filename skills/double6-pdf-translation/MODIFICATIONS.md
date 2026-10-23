# 来源与维护变更

本目录使用 `paper-translation` 的 `110-unpublished` 执行路线，并已同步第 111 轮当前开工合同，作为独立 Skill 分发草稿，整理日期为 2026-10-17。历史本地分发基线为 `2.0.0-trial.2`，其源码快照提交为 `3eb821454ea2510119b9258a37c9cc8f5978c1bf`；当前源码包含该基线之后的开发与本次整理，不冒称与该提交字节相同。

第一方代码和本次维护沿用 AGPL-3.0-only，完整文本见 [LICENSE](LICENSE)。各上游组件保留原许可证和版权；许可证兼容与源码准备不等同于正式发布授权。

本次主要改动：

- 将翻译编排、质量检查、视觉审计、扫描处理和文档修复规则按职责拆分为静态模块，保留原命令与函数名称，以及扫描渲染对回调替换/恢复的兼容行为。
- 分离安装目录与用户工作目录，补齐必要共享执行代码，要求新翻译显式配置模型与服务地址，冻结重建沿用明确的原合同。
- 移除默认 GUI 和其它服务商 SDK 依赖，保留 OpenAI-compatible 工作流；保留未使用的上游适配源码以便来源核对，但不宣称其依赖已安装。
- 为保护门拒绝的 LaTeX 原始响应补充完整单元审校修订和断点恢复。修订属于显式操作者输入；原模型响应、失败、调用数和最终 PDF 核验继续保留，保护门不放宽。
- 清除环境、缓存、评测/打包产物和固定样例图稿修复脚本；保留既有文档作用域修复规则，并维持它们原有输入范围。

维护版 PDFMathTranslate-next 以 [v2.8.2](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next/tree/v2.8.2) 为来源，BabelDOC 以 [v0.5.24](https://github.com/funstory-ai/BabelDOC/tree/v0.5.24) 为来源；它们包含原项目已有的模型接口、排版、字体/字形、链接、角色保护和缓存等修改。本次不是原样复制上游发布包。BabelDOC 的安全回移另见其 `SECURITY_BACKPORT.json`。

上游许可证原文随相应目录提供。内嵌 pdfminer 保留 MIT 原文；Adobe CMap 数据保留其 README.txt 中的版权和再分发条件。当前一方 LICENSE 使用 GNU 官方 AGPL v3 全文；上游各自 LICENSE 中的应用示例与版权文字原样保留。

源论文、译稿、字体、TeX、模型权重与验证证据不包含在公开运行包中。每份文档的完整语义、实际单语/双语页面、样式链接、阅读复制和冷重建仍须执行；本次维护没有授予任意输入的自动严格交付能力。

## 2.0.0-rc.8 维护改动（2026-10-22）

- 新增 `scripts/ocr_route.py`：扫描页检测、格线/列间隙表格检测、OSD 旋转、Tesseract 调用（有界、超时即杀）、逐行置信与多遍核对、重建 PDF（PyMuPDF 内置 `china-s` 字体）、OCR 清单与阈值记录、`cap_ocr_quality`、`ocr_engine_status`。
- 修改 `scripts/paper_translation_workflow.py`：`candidate --route scanned_ocr`（`run_scanned_ocr_candidate`），OCR 子任务经 `run_bounded`，`_execute-digital` 新增 `--ocr-manifest`/`--ocr-manifest-sha256` 绑定，`doctor` 报告 `ocr_engine_status`，冻结校验增加 OCR 合同字段。
- 修改 vendored BabelDOC `format/pdf/document_il/backend/pdf_creater.py`：辅助子进程使用 `multiprocessing.get_context("spawn").Process`；文件头维护日期更新为 2026-10-22。
- 文档：新增 `references/ocr-route.md`（设计、支持/拒绝矩阵、错误码）；`references/runtime-dependencies.md` 增加 Tesseract 与语言数据的版本与许可证声明；`references/release-quickstart.md`、`SKILL.md` 增加路线说明。
- CI：`.github/workflows/tests.yml` 的 Linux PDF 作业安装 `tesseract-ocr`、`tesseract-ocr-eng`、`tesseract-ocr-chi-sim`、`tesseract-ocr-osd` 并列出版本。
- 新增 `tests/test_ocr_route.py`（单元与真实引擎测试）、`tests/test_ocr_route_processes.py`（真实进程计量/回收正反例）。
- 版本号：`SKILL.md`、`configs/default-routes.json`、`scripts/scanned_raster/constants.py`、仓库 `README.md` 更新为 2.0.0-rc.8。
- RSS 任务上限 5 GiB（PR #20 第 2 轮）：`scripts/resource_limits.py` 新增 `RSS_TASK_LIMIT_BYTES`、`RSS_CONTRACT`，macOS 平台默认改用它（`LEGACY_CONTRACT` 不变）；`configs/default-routes.json` 的 `runtime.task_rss_bytes` 与 `platform_defaults.macOS`；`scripts/paper_translation_workflow.py` 帮助文字；SKILL.md、`references/release-quickstart.md`、`references/ocr-route.md`；测试 `tests/test_rc3_preflight_limits.py`（macOS 默认断言改为 5 GiB，新增 5 GiB 合同、越限、旧合同、主机授权测试）、`tests/test_ocr_route_processes.py`（正例与超时例用 `RSS_TASK_LIMIT_BYTES` 并按冻结合同的 50% 主机授权运行；内存越限例不变）。
- 扫描页上下标/叠排分式几何门（PR #20 review 1）：`scripts/ocr_route.py` 新增 `line_script_evidence`、`fraction_bar_evidence`、`_mark_zone` 与相应阈值常量，行记录携带 `word_texts`，`analyse_scanned_page` 在所有既有门之后、覆盖原图之前检查，命中时报 `ocr_formula_unsupported`（`evidence=image_geometry`）；新增 `tests/ocr_math_pages.py`（真实引擎边界页生成器）、`tests/test_ocr_formula_preservation.py`（reviewer 测试，仅路径改动）、`tests/test_ocr_math_script_boundaries.py`；`references/ocr-route.md` 增补设计、边界与局限；`references/release-quickstart.md`、`references/runtime-dependencies.md` 去掉文末空行。
- 汉字旁上下标 / 粘连上下标 / 带圈序号（PR #20 review 2）：`scripts/ocr_route.py` 新增 `_han_part`、`_runs`、`_latin_low_touching`、`_touching_pieces`、`_enclosed_numerals` 与 `HAN_*`、`CJK_MARK_*`、`CJK_RAISED_MARK_MAX_WIDTH`、`TOUCH_*`、`CJK_TOUCH_*`、`ENCLOSED_*` 常量，改写 `line_script_evidence` 的汉字行判定与记号归属，`_mark_zone` 只排除夹在拉丁字母数字之间的逗号，几何门 finding 增加 `enclosed_numerals`；`tests/ocr_math_pages.py` 增加 review 2 样张（reviewer probe 同一排版）与 `reviewer2_root()`；新增 `tests/test_cjk_math_protection.py`（reviewer 测试，仅路径改动）、`tests/test_ocr_cjk_script_boundaries.py`；`references/ocr-route.md` 增补设计、边界与剩余限制。

## 2.0.0-rc.7 维护改动（2026-10-22）

- 修改 `scripts/pdf_input_preflight.py`、`scripts/paper_translation_workflow.py`、`scripts/pdf_translation_cli.py`、`scripts/pdf_translation_commands.py`、`scripts/pdf_translation_render.py`、`scripts/pdf_translation_runtime.py`、`scripts/run_pdf_translation_context.py`、`scripts/qa_pipeline.py`、`scripts/render_residue_check.py`：`--target-language {zh,en}`、目标语言感知预检、中译英后端参数/提示词/术语过滤、渲染中文残留与保留字形压叠检查。
- 修改 vendored BabelDOC：
  - `utils/layout_helper.py`：`_is_cjk_no_space_pair`，汉字（含部首、全角标点）间小间隙与跨行不补空格（两处：`get_char_unicode_string`、`_add_space_dummy_chars_to_list`）；
  - `midend/il_translator.py`：`passes_min_text_length`；中文源 → 非 CJK 目标时跳过不含汉字的段落；
  - `midend/il_translator_llm_only.py`：最短长度判定改用 `passes_min_text_length`；
  - `midend/table_figure_text.py`：中文源 → 非 CJK 目标时放行含汉字的紧凑标签；
  - `midend/typesetting.py`：`english_word_break_extent`；拉丁目标语言单行段落右扩、可读下限处右/下扩（`_is_single_source_line`、`_latin_target_expanded_box`），扩框受矢量路径、Form XObject 与表格区域限制（`_latin_expansion_obstacles`、`_latin_vector_right_limit`、`_latin_vector_bottom_limit`）；
  - `midend/il_translator.py`、`midend/il_translator_llm_only.py`：`classify_same_as_input_result` 增加 `lang_in`，中文源时含汉字的原样返回判未翻译。
  - 上述文件头维护日期更新为 2026-10-22。
- 评审第 1 轮修正：`scripts/qwen_pdf2zh_cli_translator.py`（`--target-language`、目标语言感知的修补/重试/术语）、`scripts/policy_utils.py`（`DEFAULT_SYSTEM_PROMPT_EN` 移入、`normalize_target_language`、`policy_item_matches_target`）、`scripts/pdf_input_preflight.py`（`inline_object_math`、`zh2en_inline_object_math_unsupported`、`target_language_route_unsupported`）、`scripts/paper_translation_workflow.py`（`check_target_language_route`）、`scripts/pdf_translation_render.py`（中译英拒绝 HY-MT 兼容代理/原生传输）、`scripts/render_residue_check.py`（短页整句残留、整份文件评估、压叠与矢量字形丢失判 high）、`scripts/qa_pipeline.py`（独立规则码）。
- 评审第 2 轮修正：`scripts/pdf_input_preflight.py`（行内结构对象阈值 1、`with_objects` 定位明细、整页 Form 处理）、`scripts/render_residue_check.py`（`page_inline_object_damage` 逐对象核对丢失/压叠，压叠阈值 1 个字符）、`scripts/qa_pipeline.py`（`inline_object_damage_high`）。
- 评审第 3 轮修正：`scripts/pdf_input_preflight.py`（`inline_object_math` 逐个 Form 归类为正文 Form/行内 Form，只清空行内 Form 求差集；新增 `_form_tree`、`_has_cjk_row` 与 `body_forms`/`inline_forms` 计数）。
- 评审第 4 轮修正：`scripts/pdf_input_preflight.py`（带中文行的 Form 按宿主行结构判据再分类：新增 `_char_lines`、`_hosted_in_cjk_line`、`HOST_*` 阈值与 `hosted_cjk_forms` 计数）。
- 评审第 5 轮修正：`scripts/pdf_input_preflight.py`（按 Form 自身内容分类 container/object/body/mixed，正文准入与数学证据 `_math_like_glyphs`/`_fraction_rules`，宿主正文行 `_host_lines`/`_in_flow`，needs_review 拒绝与 `reasons`、`needs_review_forms`/`standalone_mixed_forms`/`container_forms`/`form_rules` 计数；去掉第 4 轮的 `_hosted_in_cjk_line` 与 `HOST_*` 尺寸上限）、`scripts/render_residue_check.py`（`form_rule` 分数线逐个核对）；第 3、4 轮测试按新语义调整（见 CHANGELOG）。
- 评审第 6 轮修正：`scripts/pdf_input_preflight.py`（页面等价 Form 类 `page_equivalent`；文字层数学字形 `text_layer_math` 列表与计数；`_char_records` 增加绘制顺序 `seq`，新增 `_same_line`、`_in_chinese_text_run`，`_math_like_glyphs` 增加 `admit_text_runs`）、`scripts/render_residue_check.py`（新增成品门 `page_text_layer_math_loss`/`text_layer_math_loss_pages`）；第 3、4 轮正例按 905dbf3 原样恢复，其中第 4 轮图注/旁注一页据端到端证据改为拒绝断言（输入不变）。
- 评审第 7 轮修正：`scripts/render_residue_check.py`（`page_text_layer_math_loss` 改为逐实例匹配：新增 `_target_tokens`、`_standalone_letter`、`_target_math_instances`、`_eligible`，规则名 `per_instance_v1`）、`scripts/pdf_input_preflight.py`（`text_layer_math` 条目增加字体/字号/标志）、`scripts/bounded_execution.py`（`_unowned_codex_scan` 逐进程隔离错误；`snapshot` 记录 `unowned_scan`、`owned_monitor_errors`；`violation` 新增 `owned_process_monitor_unavailable`；`launched_members` 按 `psutil.pids()` 枚举并抛 `OwnedDiscoveryError`；`run_bounded` 监控异常 `resource_monitor_unavailable` 结构化停止）、`scripts/paper_translation_workflow.py`（停止时 `error_code`=`stop_reason`；未预期错误输出结构化 JSON 并写 `WORKFLOW_INTERNAL_ERROR.json`）。新增 `tests/test_pr19_review7_text_layer_counter.py`、`tests/test_pr19_review7_monitor_permissions.py`（评审原样，只改路径）、`tests/test_pr19_review7_fixes.py`、`tests/fixtures/pr19_review7/italic_x_backend_mono_chars.json`（真实后端成品的逐字符几何，不含 PDF）。
- 评审第 8 轮修正：`scripts/bounded_execution.py`（`OwnedDiscoveryError` 携带启动身份与已确认成员；新增 `read_launch_identity`、`reclaim_owned_tree`、`_identity_state`、`_signal_pid`、`_signal_group`、`_group_empty`；`run_bounded` 保留可信身份、用核验过的后备回收替代 `stop_children`、结束时独立核实并输出 `cleanup`/`launch_identity`，无法确认时 `status=cleanup_unconfirmed`）、`scripts/paper_translation_workflow.py`（`error_code=owned_tree_cleanup_unconfirmed`）。新增 `tests/test_pr19_review8_discovery_cleanup.py`（评审原样，只改路径）、`tests/test_pr19_review8_owned_cleanup.py`。
- 评审第 9 轮修正：`scripts/bounded_execution.py` 新增 `_raw_pids`、`_enumerate_all_pids`、`_owner_markers`、`_recovery_scan`。`reclaim_owned_tree` 增加 `nonce` 参数，在枚举失败后做恢复扫描并核实整树，新增 `tree_scope`、`recovered_members`，删除 `not_covered`。`run_bounded` 把恢复到的成员并入已确认成员，并汇总各轮扫描。新增 `tests/test_pr19_review9_cleanup_boundaries.py`（评审原样，只改路径）、`tests/test_pr19_review9_whole_tree.py`；调整 `tests/test_pr19_review8_owned_cleanup.py::test_root_exited_descendant_in_group_reclaimed`，改为只断言安全结果。
- 评审第 10 轮修正：`scripts/bounded_execution.py::_recovery_scan`：已知成员先核实当前身份才作祖先起点（`ancestor_roots`、`rejected_ancestors`），每一跳重新核实父进程身份；指向被拒号码的无证据进程及其后代记为 `ownership_unknown`；复用号码按普通候选判定；最终核实扫描带已知身份。新增 `tests/test_pr19_review10_reused_ancestor.py`（评审原样，只改路径）、`tests/test_pr19_review10_ancestry_identity.py`。
- 新增 `tests/test_zh2en_translation.py`、`tests/fixtures/zh2en/`、`tests/test_pr19_review_boundaries.py`、`tests/test_pr19_review2_sparse_math.py`、`tests/test_pr19_review3_wrapped_form.py`、`tests/test_pr19_review4_chinese_formula_form.py`、`tests/test_pr19_review5_mixed_form.py`、`tests/test_pr19_review6_text_runs.py`。
- 版本号：`SKILL.md`、`configs/default-routes.json`、`scripts/scanned_raster/constants.py` 更新为 2.0.0-rc.7。

## 2.0.0-rc.6 维护改动（2026-10-22）

- 修改 vendored BabelDOC `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/styles_and_formulas.py`：公式分组在栏内视觉折行处断开；`merge_overlapping_formulas` 不跨折行合并、不合并中间夹正文的不相邻公式；按逗号拆分公式时保留下标/上标逗号；零高度/零宽度线段（分式线）按 0.5pt 线宽参与公式包含判定。文件头维护日期更新为 2026-10-18。
- 新增 `tests/test_inline_math_wrap.py` 与 `tests/fixtures/inline_math/`（真实 arXiv CC BY 4.0 论文的单段字符几何 JSON，不含 PDF）。
- 版本号：`SKILL.md`、`configs/default-routes.json`、`scripts/scanned_raster/constants.py` 更新为 2.0.0-rc.6（原 rc.4，合并到 rc.5 之上后改号）。

## 2.0.0-rc.5 维护改动（2026-10-18）

- 新增 vendored BabelDOC `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/table_figure_text.py`：填充节点内多行合并、紧凑标签翻译范围判定、单行源基线记录。
- 修改 `midend/paragraph_finder.py`：调用上述三步；非首页独立年份标为 `year_label` 而非 `cover_year`。
- 修改 `il_version_1.py`：`PdfParagraph` 新增可选属性 `source_baseline`（`sourceBaseline`）。
- 修改 `midend/typesetting.py`：有 `source_baseline` 时译文首行落在原文基线（只上移、最多半行，上边界同步放宽）。
- 修改 `midend/il_translator.py`、`midend/il_translator_llm_only.py`：`year_label` 不再被改标为封面年份；最短长度判定改用 `bypasses_min_text_length`。
- 修改 `utils/paragraph_helper.py`：`NUMERIC_PATTERN` 接受千分位分组；新增 `bypasses_min_text_length`；补维护文件头。
- 评审第 1 轮（2026-10-22）：`table_figure_text.py` 新增 `assign_baseline_ceilings`、同类标签判定与 `context_released` 标记，`ORG_SUFFIX` 收窄为法律实体后缀；`il_version_1.py` 新增可选属性 `source_ceiling`（`sourceCeiling`）、`context_released`（`contextReleased`）；`typesetting.py` 在预处理与逐页渲染前计算上移上限并按它夹住上移量；`il_translator.py` 对 `context_released` 段落的原样返回保留原文（`preserved`）；`scripts/pdf_translation_tracking.py` 不把该状态计为未翻译失败。上述文件头日期更新为 2026-10-22。
- 以上 vendored 文件头维护日期更新为 2026-10-18。
- 新增 `tests/test_table_figure_text.py` 与 `tests/fixtures/table_figure_text/`（真实文档裁剪后的逐字符几何 JSON，不含 PDF）。
- 版本号：`SKILL.md`、`configs/default-routes.json`、`scripts/scanned_raster/constants.py` 更新为 2.0.0-rc.5。

## 2.0.0-rc.3 维护改动（2026-10-17）

- 新增 `scripts/pdf_input_preflight.py`、`scripts/resource_limits.py`、`scripts/render_residue_check.py`（AGPL-3.0-only 一方代码）。
- 修改 `scripts/paper_translation_workflow.py`、`scripts/bounded_execution.py`、`scripts/scan_input_preflight.py`、`scripts/qa_pipeline.py`、`scripts/scanned_raster/constants.py` 及 `schemas/scan-input-preflight.schema.json`：结构化预检与错误码、可配置资源上限与 PSS 计量、真实错误消息收据、源语言检测、渲染英文残留检查、`candidate` 质量失败退出码 3（附失败原因）、版本号统一。
- 评审修复：`scripts/resource_limits.py`（冻结合同权威、覆盖冲突错误码、建议合同）、`scripts/render_residue_check.py`（参考文献/代码/URL/引用剔除）、`scripts/paper_translation_workflow.py`（任意路线质量结论与退出码 3、有界输入预检、冻结预算执行）、`scripts/pdf_input_preflight.py`（页数超限短路、子进程入口）、`scripts/bounded_execution.py`（峰值含基线与收尾样本）；新增 `tests/test_rc3_review_fixes.py`。
- 评审修复第二轮：`scripts/render_residue_check.py` 改为几何阅读顺序定位参考文献区域、逐条校验条目、字母附录结束区域、无标题严格条目连续段剔除、译文侧剔除上限；新增 `tests/test_rc3_review_round2.py`。
- 评审修复第三轮：`scripts/render_residue_check.py` 新增正文否决、无标题参考文献强结构证据（strong/weak 分类、左边距、文末位置、全文比例上限、译文侧跟随源文）与 `excluded.headingless_runs` 审计输出；新增 `tests/test_rc3_review_round3.py`，第二轮无标题用例的正文加长到与上限相称。
- 评审修复第四轮：`scripts/render_residue_check.py` weak 条目默认计数、仅凭编号连续或续接证据剔除，标题区域与无标题段共用逐条规则并输出逐条审计；修正以年份开头续行被拆成新条目的分组问题；新增 `tests/test_rc3_review_round4.py`。
- 未修改 vendored PDFMathTranslate-next / BabelDOC 源码。

## 与所标上游版本有差异的实现文件

以下文件包含继承的维护或本轮兼容性修改，均已增加维护日期声明，原版权与许可继续保留：

- `vendor/babeldoc/babeldoc/assets/assets.py`
- `vendor/babeldoc/babeldoc/docvision/doclayout.py`
- `vendor/babeldoc/babeldoc/format/pdf/converter.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/backend/link_anchors.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/backend/pdf_creater.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/frontend/il_creater.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/il_version_1.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/diagram_nodes.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/il_translator.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/overflow_source_fallback.py`（Double6 新增模块）
- `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/paragraph_finder.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/styles_and_formulas.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/midend/typesetting.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/utils/fontmap.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/utils/formular_helper.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/utils/layout_helper.py`
- `vendor/babeldoc/babeldoc/format/pdf/document_il/xml_converter.py`
- `vendor/babeldoc/babeldoc/format/pdf/high_level.py`
- `vendor/babeldoc/babeldoc/pdfminer/_cmap_manifest_data.py`
- `vendor/babeldoc/babeldoc/pdfminer/cmap_secure_loader.py`
- `vendor/babeldoc/babeldoc/pdfminer/cmapdb.py`
- `vendor/babeldoc/babeldoc/pdfminer/image.py`
- `vendor/babeldoc/babeldoc/pdfminer/layout.py`
- `vendor/pdfmathtranslate_next/pdf2zh_next/config/model.py`
- `vendor/pdfmathtranslate_next/pdf2zh_next/gui.py`
- `vendor/pdfmathtranslate_next/pdf2zh_next/high_level.py`
- `vendor/pdfmathtranslate_next/pdf2zh_next/main.py`
- `vendor/pdfmathtranslate_next/pdf2zh_next/translator/utils.py`
- `vendor/pdfmathtranslate_next/pyproject.toml`

本轮真实回放还修复了两项运行阻断：将 `source_text_matrix` / `source_local_bbox` 的空值按既有 XML 保存规则统一为缺省表示，实际非空矩阵继续参与身份校验。保留 3 GiB、120 秒与单并发限制。命令适配器同时区分本地无鉴权 SDK 占位字段与实际上游凭据。


2026-10-17 追加闭环：电子PDF源账本及文件SHA使用流式哈希，规范序列化字节序列不变；每次请求仍重核磁盘身份与内存账本的原始冻结摘要，防止调用方修改内容或重签摘要。只有冻结缓存作业且存在外层nonce进程树监督时，PDFMathTranslate-next复用当前后端进程，避免重复载入；其它调用保持原子进程路径。最终支持结论以完整三页实际成品、资源与质量回执为准。

2026-10-17 来源纠正：第 111 轮修改 4 份文档，新增历史说明，原迁入清单其余 811 个文件逐项 SHA 相同。公开入口采用最新短合同并保留独立安装、显式模型配置和恢复要求；旧长说明与源项目历史本地路径保存在本地报告中，不加入公开运行包。三页内存和最终 LaTeX 核验仍待完成，旧候选的发布准备结论不适用于当前成员。

2026-10-17 继续完成 111 基线下的资源与实际成品核验：

- 保留实际源内容的独立重编译，仅重绑定搬迁后的源码来源描述，历史和当前源码均逐次校验；翻译后用当前调用的段落身份核成员，只对不可变科学源段重核原字形，普通中文目标不再送入源字形解析器。
- 仅在有界冻结缓存作业下关闭 CPU ONNX 的内存预留与模式缓冲；模型图、权重、计算参数和既有单线程设置不变。翻译阶段后释放可按原 SHA 重算的解析对象，源引用和校验要求不变。
- 复用已有 `owned_font_unicode`：依据实际排版字符为新加入字体绑定精确 Unicode，并保留其声明，避免后续 cmap 兼容清理丢弃无墨迹空格。原 PDF 字体、科学字形、页面内容流和链接不为此改写。
- 两个已审完整逻辑组共享原生宿主时保留组间显式换行，复用后端现有换行排版；同组片段继续连贯。此逻辑不包含论文专用坐标或模型原始响应改写。
- 实际回放与技术审查不授予任意输入的自动严格验收，也不自动等同于软件发布或用户接受。

- 安装验收：除入口帮助外，以独立进程实际导入 PyMuPDF、ONNX/ONNX Runtime、OpenCV、scikit-learn 及 DocLayout 主路径原生扩展；单线程、180 秒安装核验上限，失败时不宣告环境已准备。未改变论文任务 3 GiB／120 秒预算。

## 2.0.0-rc.9 维护改动（2026-10-23）

- 新增 `scripts/chunked_translation.py`：冻结分块合同 `CHUNKING_CONTRACT`、安全页边界信号与划分、块源 PDF、原文导航（目录/页码标签/内部链接）、整份文档术语上下文、按页序合并与逐页核对、合并综合质量（不好于最差的一块）、跨块术语一致性检查；`plan`/`merge` 子命令只在有界任务内运行。
- 新增 `scripts/chunked_workflow.py`：`chunked-candidate` 编排（块级 FREEZE 派生、每块普通 `candidate`、资源停止二分、瞬时失败重试 1 次、失败关闭、原子运行状态、`--resume` 的遗留进程树回收与逐 sha 复用、后端字体子集化临时件登记后删除）。
- 修改 `scripts/paper_translation_workflow.py`：新增 `chunked-candidate` 动作与 `PER_CHUNK_ROUTING`；`validate_freeze` 增加仅关键字参数 `chunked`（默认 False 时行为不变）；`bounded_input_preflight` 增加 `max_pages`（默认仍为 5）；`candidate_command` 在给出整份术语上下文时追加 `--document-term-context(-sha256)`；`_execute-digital` 核对块 FREEZE 的 `document_term_context_ref`；`check_target_language_route` 允许 `chunked-candidate --route per_chunk`。
- 修改 `scripts/pdf_translation_cli.py`（`--document-term-context`、`--document-term-context-sha256`）、`scripts/pdf_translation_render.py`（`load_document_term_context`，sha 不符即拒绝）、`scripts/pdf_translation_commands.py`（`build_backend_system_prompt` 可选 `document_context`：文档级条目在前、块内新条目在后；不传时输出不变）。
- 第 2 轮（真实长文档运行发现，同一 PR）：`chunked_workflow.py` 把后端内部超时（块 `render_manifest.json` 的 `errors` 含 `timeout`）按资源停止 `backend_timeout` 二分；新增尝试后核查（按启动 nonce 扫描存活进程，回收并复查，无法核实即 `chunk_cleanup_unconfirmed` 并停止调度后续块；`owned_tree_cleanup_unconfirmed` 同样停止调度）；块级上下文 `CHUNK_TERM_CONTEXT.json`。`scripts/render_residue_check.py` 新增 `reference_region_open_pages` 与 `check_render_residue(..., region_open_at_start=False)`、`split_counted_text(..., region_open_at_start=False)`；`scripts/qa_pipeline.py` 的 `attach_pipeline_quality` / `render_residue_gate` 增加同名可选参数；`scripts/pdf_translation_runtime.py` 从已按 sha 核对的块上下文读取该状态。默认值下单份翻译的行为与报告逐字不变。
- 文档：新增 `references/chunked-translation.md`；`SKILL.md`、`references/release-quickstart.md`（错误码 `chunk_failed`、`chunk_page_exceeds_task_budget`、`chunk_merge_failed`、块错误码 `chunk_cleanup_unconfirmed`）。
- 新增 `tests/test_chunked_translation.py`。
- 版本号：`SKILL.md`、`configs/default-routes.json`、`scripts/scanned_raster/constants.py`、仓库 `README.md` 更新为 2.0.0-rc.9。
- rc.9 第 3 次代码提交：`scripts/bounded_execution.py::reclaim_owned_tree`（`adopt` 对带本次启动 nonce、记录身份读作 `pid_reused` 的进程以观测 create_time 刷新身份并回收，组长同理恢复整组信号；报告新增 `identity_refreshed`、`process_group.identity_refreshed_by_nonce`）。新增 `tests/test_chunk_clock_step_reclaim.py`。
- rc.9 第 4 次代码提交：`scripts/chunked_workflow.py::run` 在启动有界 `chunk-plan` 前创建运行目录（`wf.ROOT`，有界任务的 cwd）；CI 的全新 `PAPER_TRANSLATION_WORKSPACE` 尚不存在时此前整份退出 1。新增成对测试 `test_chunked_run_creates_a_missing_workspace_root` / `test_chunked_run_fails_closed_when_workspace_root_is_a_file`。
- rc.9 第 5 次代码提交（PR #21 review-1）：`scripts/chunked_workflow.py`（`owner_nonce_scan` 只作记录；`_verify_receipt` 逐回执预检 + `reclaim_owned_tree(discovery_failed=True)`；`reclaim_stale`/`post_attempt_guard` 输出 `unverified`/`reason_codes`，协议 `launch_receipt_recovery_scan_v2`）、`scripts/chunked_translation.py`（分块合同 `post_attempt_guard` 协议名）、`scripts/bounded_execution.py`（`_query_failure_counts`；`launched_members` 的 `unknown` 收集；`run_bounded` 遇归属未知时回收转恢复扫描并记 `ownership_unknown_during_run`；`_recovery_scan` 的 ppid 查询失败、墙钟回拨 nonce、僵尸/其它用户过滤）。新增 `tests/test_pr21_review1_guard_query_failures.py`。
- rc.9 第 6 次代码提交（PR #21 review-2）：新增 `scripts/launch_clock.py`；`scripts/bounded_launch.py`（回执 `start_evidence`）；`scripts/bounded_execution.py`（`root_start_evidence`、`older_unreadable_verdict`、`OLDER_NONCE_UNREADABLE`；`_recovery_scan`/`launched_members` 较早且读不到 nonce 的进程按单调证据排除否则归属未知；`reclaim_owned_tree` 固定现场证据；未知项带 `code`）；`scripts/chunked_workflow.py`（`_verify_receipt` 的 `root_identity_clock_shifted` 与预检未知保留；`detail_codes`）。新增 `tests/test_pr21_review2_clock_rollback_unknown.py`；`tests/test_pr21_review1_guard_query_failures.py` 移除断言旧丢弃行为的 `older-unreadable` 参数。
- rc.9 后续修复（realmodel-r1 真实模型评测的两个首要问题，2026-10-23）：
  - 溢出降级：新增 vendored BabelDOC `midend/overflow_source_fallback.py`（准入 `admission`、按页/按文档上限 `cap_violations`）；
    `il_version_1.py` 的 `PdfParagraph` 新增不序列化字段 `overflow_source_backup`；`midend/il_translator.py` 新增
    `_backup_source_for_overflow_fallback`（只对目录/表格/图内标签角色与 `fallback_line` 备份源组合）；`midend/typesetting.py`
    在既有缩字/折行/扩框全部失败、段落被记为 `hard_readable_floor_overflow` 后调用 `_apply_overflow_source_fallback`
    （原字形原位置直通，`writeback_status=overflow_source_fallback`），`_enforce_overflow_fallback_cap` 超限整批撤销，
    `typesetting_writeback_report.json` 新增 `source_fallbacks` / `source_fallback_count` / `source_fallback_cap` 与
    `status=needs_review`，失败行新增 `source_fallback_rejected`。`scripts/qa_pipeline.py` 新增 `audit_overflow_source_fallbacks`
    （pending `overflow_source_fallback`，综合质量最多 unverified）；`scripts/chunked_translation.py::aggregate_quality` 汇总
    `overflow_source_fallback_count`、`reference_exclusion`；`scripts/paper_translation_workflow.py::quality_verdict` 输出两项计数。
  - 参考文献剔除：`scripts/render_residue_check.py` 在 References 标题区内（无标题路径不变）新增 `title_verb_waiver`、
    `author_year_sequence`、按含文字行计行数、出处缩写行尾续接，以及回执汇总 `reference_exclusion_summary`；阈值不变。
  - 新增 `tests/test_overflow_source_fallback.py`、`tests/test_reference_residue_exclusion.py`。
- PR #23 review-1 修复（2026-10-23）：
  - `scripts/render_residue_check.py`：新增 `entry_fields`（纯作者名单/题名/其余字段的结构证明）；`title_verb_waiver` 只豁免已证明题名字段内的动词。
  - vendored BabelDOC `midend/overflow_source_fallback.py`：`cap_violations` 输出原始分母 `paragraphs_per_page`、`segment_count`；
    新增 `document_cap_scope()`（环境变量 `DOUBLE6_OVERFLOW_FALLBACK_DOCUMENT_CAP=chunk_merge`）与回执不完整码。
    `midend/typesetting.py::_enforce_overflow_fallback_cap`：分块作用域下只执行按页上限，整份违规记入 `deferred_violations`。
  - `scripts/pdf_translation_render.py`：仅当已按 SHA-256 绑定的块上下文带 `chunk` 字段时设置该变量，否则清除。
  - `scripts/qa_pipeline.py`：回执审计带出上限、原始分母、作用域与逐条降级记录；`attach_pipeline_quality(chunk_mode=)`，
    非分块出现推迟作用域即 `overflow_source_fallback_cap_scope_mismatch`；`scripts/pdf_translation_runtime.py` 传入 `chunk_mode`。
  - `scripts/chunked_translation.py`：新增 `document_fallback_cap`（逐块核对回执完整性，按原始页码统一计算整份/按页上限），
    `aggregate_quality` 超限或不完整记 blocker；`scripts/chunked_workflow.py` 合并后遇这两种码整份阻断（exit 2，不交付）。
  - 新增 `tests/test_pr23_review1_reference_narrative.py`、`tests/test_pr23_review1_document_fallback_cap.py`（复审原测试，仅改路径）、
    `tests/fixtures/pr23_review1/`、`tests/test_pr23_review1_reference_fields.py`、`tests/test_pr23_review1_fallback_document_cap.py`；
    `tests/test_overflow_source_fallback.py` 的分块汇总用例改为提供完整回执（另加无回执失败关闭用例与分块作用域用例）。
