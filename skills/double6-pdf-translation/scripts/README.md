# double6-pdf-translation 脚本分层

本目录只保留高保真 PDF 翻译所需的可复用入口、质量证据层和修复工具；评测 runner、一次性 round 汇总、旧诊断刷新脚本和缓存文件不放在这里。

## 主入口

- `preflight_runtime.py`：新机器/新 agent 安装后的运行时自检入口，检查 PDF backend、模型 endpoint 和可选审计依赖。
- `run_pdf_translation.py`：单篇 PDF/LaTeX-first 强路径入口，负责调用后端、生成 PDF、manifest、QA 与 gate。
- `prepare_paper_source.py`、`extract_terms.py`、`translate_with_qwen.py`、`check_translation.py`：文本/Markdown/降级路径的基础链路。
- `pdf2zh_backend.py`：启动外部安装的 `pdf2zh_next` Python module 的薄 wrapper；默认路径仍优先使用 `PATH` 中的 `pdf2zh` CLI。

## 共享策略

- `policy_utils.py`：术语、实体、protected span、禁用译法和 canonical check 的共享层。
- `layout_role_policy.py`：PDF 后端进入翻译前的 layout role 分类与 passthrough 策略。
- `model_client.py`、`translation_compat_proxy.py`、`qwen_pdf2zh_cli_translator.py`：商业 OpenAI-compatible API、本地/自托管模型与 PDF 后端适配；`translation_compat_proxy.py` 是内部请求适配层，不代表用户必须本地部署模型；正式运行前必须配置 model 和 API key，显式 provider 或单一厂商专属 key 可按 `references/provider-base-urls.md` 推断 endpoint。
- `translation_api_probe.py`：DeepSeek/OpenAI-compatible 翻译诊断工具，可用 `backend_retry_failures.json`、`translation_proxy_stats.json` 或 JSONL fixture 回放 PDF 碎片，比较 prompt、温度、DeepSeek thinking mode 和调用路径对同文/英文残留/保护 span 的影响；支持 `--concurrency` 并发真实 API probe；只写 probe 输出，不修改正式翻译 manifest。

## PDF 证据层

- `build_babeldoc_il_layout_map.py`、`build_block_bridge.py`、`build_pymupdf_layout_audit.py`、`build_poppler_text_bbox_audit.py`、`build_layout_structure_gate.py`：PDFMathTranslate-next/BabelDOC 结构证据、PyMuPDF/Poppler 旁路 bbox 审计与 strict gate。
- `visible_residue_audit.py`：聚合 PyMuPDF/Poppler/visual/OCR findings，并用 `translation_proxy_ledger.json` 做 fuzzy 关联，定位“已有中文输出但主 PDF 仍可见英文”的 writeback/paint 残留。
- `visible_residue_repair.py`：为首页普通正文残留生成保守局部修复候选；只有 post-repair OCR/text gate 通过时才允许进入交付。
- `visual_layout.py`、`build_pdf_rerender_plan.py`、`build_structured_writeback_manifest.py`、`build_structured_visual_candidates.py`：视觉审计、候选页和 rerender 计划。视觉候选必须经人工接受后才能进入交付。
- `build_bilingual_pdf.py`、`render_readable_pdf.py`：标准双语 PDF 和可读降级 PDF 渲染。

## 维护与独立工具

- `apply_glossary_edits.py`、`repair_protected_spans.py`、`repair_quality_issues.py`：人工术语修订、protected span 修复和 QA 文本修复工具。

## 删除准则

- 可以删除：一次性 round 汇总脚本、临时截图生成脚本、运行缓存、`__pycache__`、`.pytest_cache`、没有被 README/manifest/test 引用的本地诊断导出。
- 暂不删除：被 `run_pdf_translation.py` 或项目测试动态加载的脚本，即使 `rg` 静态引用很少。
- 视觉候选相关脚本必须保留候选边界：它们只能生成 review evidence 或人工验收候选，不能绕过 backend/writeback 和 strict delivery gate。
