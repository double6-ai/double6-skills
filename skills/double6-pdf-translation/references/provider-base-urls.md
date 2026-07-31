# Provider Base URL Candidates

本表只用于根据本次命令显式给出的 `--provider` 推断 base URL；`--base-url` 优先。运行时不会扫描宿主环境中的 API key、provider 或 endpoint。

| Provider | `--provider` | Candidate base URL | Notes |
| --- | --- | --- | --- |
| DeepSeek | `deepseek` | `https://api.deepseek.com` | OpenAI-compatible endpoint. |
| OpenAI | `openai` | `https://api.openai.com/v1` | OpenAI official endpoint. |
| Alibaba Cloud Model Studio / DashScope | `qwen` / `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | Generic compatible-mode endpoint. |
| Moonshot / Kimi | `kimi` / `moonshot` | `https://api.moonshot.cn/v1` | OpenAI SDK compatible endpoint. |
| SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1` | OpenAI-compatible chat completions endpoint. |
| Zhipu / Z.ai | `glm` / `zhipu` | `https://open.bigmodel.cn/api/paas/v4` | OpenAI-style chat completions endpoint. |
| OpenRouter | `openrouter` | `https://openrouter.ai/api/v1` | OpenAI SDK compatible model router. |
| Volcengine Ark | `ark` | `https://ark.cn-beijing.volces.com/api/v3` | Common Ark endpoint; override non-Beijing regions explicitly. |

官方文档复核日期：2026-07-03。DeepSeek、DashScope、Moonshot/Kimi、SiliconFlow、Zhipu/Z.ai、OpenRouter 已按公开文档复核；Volcengine Ark 保留为常见区域候选，实际 endpoint 仍应以火山方舟控制台为准。厂商 endpoint 可能调整；如果 preflight endpoint 检查失败，优先使用厂商控制台或官方文档中的最新 URL 覆盖候选值。

## Local Skill Survey

本地调研过的相关 skill 显示了几种不同模式：

- `translate-pdf`、`pdf-translate`：依赖 agent 自身完成翻译，不管理外部 LLM endpoint。
- `arxiv-paper-translator`：通过 agent/subagent 翻译 LaTeX 内容，也不配置外部 OpenAI-compatible endpoint。
- `azure-ai-translation-document-py`、`azure-ai-translation-ts`：Azure 文档翻译服务使用固定 Azure endpoint + key，属于单厂商固定 endpoint 模式。
- `pdf2zh-skill`：要求 `PDF2ZH_TRANSLATION_API_KEY`、`PDF2ZH_TRANSLATION_BASE_URL`、`PDF2ZH_TRANSLATION_MODEL` 三元组明确配置。

本 skill 要求模型与凭据显式传入；`base_url` 可以显式传入，也可以由明确的 `--provider` 从候选表推断。
