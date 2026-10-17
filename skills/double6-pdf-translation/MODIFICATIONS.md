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

## 2.0.0-rc.3 维护改动（2026-10-17）

- 新增 `scripts/pdf_input_preflight.py`、`scripts/resource_limits.py`、`scripts/render_residue_check.py`（AGPL-3.0-only 一方代码）。
- 修改 `scripts/paper_translation_workflow.py`、`scripts/bounded_execution.py`、`scripts/scan_input_preflight.py`、`scripts/qa_pipeline.py`、`scripts/scanned_raster/constants.py` 及 `schemas/scan-input-preflight.schema.json`：结构化预检与错误码、可配置资源上限与 PSS 计量、真实错误消息收据、源语言检测、渲染英文残留检查、版本号统一。
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
