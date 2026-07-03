# Provider Base URL Candidates

本表用于根据 `LOCAL_TRANSLATION_PROVIDER` / `--provider`，或在用户只配置一个厂商专属 API key 时推断 `LOCAL_TRANSLATION_BASE_URL`。推断优先级：

1. `--base-url` / `LOCAL_TRANSLATION_BASE_URL` 显式值。
2. `--provider` / `LOCAL_TRANSLATION_PROVIDER` 对应的候选 URL。
3. 刚好检测到一个厂商专属 API key 时，对应的候选 URL。

如果同时存在多个厂商 key 且没有显式 provider，不自动猜。`LOCAL_TRANSLATION_API_KEY` 是泛用 key，不参与厂商推断；若使用泛用 key，请同时设置 `LOCAL_TRANSLATION_PROVIDER` 或 `--provider`。

| Provider | API key env | Candidate base URL | Notes |
| --- | --- | --- | --- |
| DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` | OpenAI-compatible endpoint. |
| OpenAI | `OPENAI_API_KEY` | `https://api.openai.com/v1` | OpenAI official endpoint. |
| Alibaba Cloud Model Studio / DashScope | `DASHSCOPE_API_KEY` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | Generic compatible-mode endpoint. Workspace-specific Model Studio endpoints should be passed explicitly. |
| Moonshot / Kimi | `MOONSHOT_API_KEY`, `KIMI_API_KEY` | `https://api.moonshot.cn/v1` | OpenAI SDK compatible endpoint. |
| SiliconFlow | `SILICONFLOW_API_KEY` | `https://api.siliconflow.cn/v1` | OpenAI-compatible chat completions endpoint. |
| Zhipu / Z.ai | `ZHIPUAI_API_KEY`, `ZHIPU_API_KEY`, `BIGMODEL_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` | OpenAI-style chat completions endpoint. |
| OpenRouter | `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1` | OpenAI SDK compatible model router. |
| Volcengine Ark | `ARK_API_KEY`, `VOLCENGINE_API_KEY` | `https://ark.cn-beijing.volces.com/api/v3` | Common Ark OpenAI-compatible endpoint. Override for non-Beijing regions if needed. |

官方文档复核日期：2026-07-03。DeepSeek、DashScope、Moonshot/Kimi、SiliconFlow、Zhipu/Z.ai、OpenRouter 已按公开文档复核；Volcengine Ark 保留为常见区域候选，实际 endpoint 仍应以火山方舟控制台为准。厂商 endpoint 可能调整；如果 preflight endpoint 检查失败，优先使用厂商控制台或官方文档中的最新 URL 覆盖候选值。

## Local Skill Survey

本地调研过的相关 skill 显示了几种不同模式：

- `translate-pdf`、`pdf-translate`：依赖 agent 自身完成翻译，不管理外部 LLM endpoint。
- `arxiv-paper-translator`：通过 agent/subagent 翻译 LaTeX 内容，也不配置外部 OpenAI-compatible endpoint。
- `azure-ai-translation-document-py`、`azure-ai-translation-ts`：Azure 文档翻译服务使用固定 Azure endpoint + key，属于单厂商固定 endpoint 模式。
- `pdf2zh-skill`：要求 `PDF2ZH_TRANSLATION_API_KEY`、`PDF2ZH_TRANSLATION_BASE_URL`、`PDF2ZH_TRANSLATION_MODEL` 三元组明确配置。

本 skill 采用折中策略：保留模型名显式配置；`base_url` 可以显式传入，也可以由明确 provider 或单一厂商 key 从候选表推断。
