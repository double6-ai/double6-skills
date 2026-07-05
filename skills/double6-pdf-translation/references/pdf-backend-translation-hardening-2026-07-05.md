# PDF 后端翻译质量加固记录（2026-07-05）

本文记录本次针对 PDFMathTranslate/BabelDOC 后端大段英文残留、提示词泄漏和正文/参考文献角色误判的优化，便于原始 skill 或其它分支复刻。

## 背景问题

一次双栏论文 PDF 翻译结果中，译文 PDF 出现多页普通英文正文残留，并且参考文献页混入“以下是根据您的要求翻译……”等提示词复述。中间产物显示后端存在 same-as-input fallback、block alignment 缺失、`references_entry`/`body_prose` 误判，以及最终可见残留 gate 未覆盖非首页正文。

## 已落地改动

### 1. 可见英文残留硬门槛

文件：`scripts/visible_residue_audit.py`

- 新增基于 `poppler_text_bbox_audit.json` 的全页文本层扫描，不再只依赖首页 OCR。
- 检测普通正文页中多行英文残留，生成 `translated_but_source_visible` blocking finding。
- 检测提示词泄漏，例如“以下是根据您的要求”“不要输出解释”“仅输出翻译”等，生成 `prompt_leak` blocking finding。
- 审计结果新增 `ordinary_body_delivery_blocking_count`，便于 delivery gate 汇总。

文件：`scripts/delivery_gate_runtime.py`

- `critical_page_visible_residue` gate 从“只阻断首页 critical page”调整为“任意 `delivery_blocking` 可见残留都阻断”。
- gate 提示改为主 PDF 普通正文不能残留可见英文或提示词。

### 2. 有限质量重试与反思上下文

文件：`scripts/translation_compat_proxy.py`

- 新增 `PAPER_TRANSLATION_QUALITY_RETRY_ATTEMPTS` 控制质量重试次数，默认 `1`，可在 probe 或运行时调高。
- 重试不再原样重复请求，而是带入：
  - 上一轮失败原因；
  - 上一轮坏输出摘要；
  - 源文与输出的英文词数量级；
  - 明确要求不要重复上一轮输出。
- 将代理内普通翻译请求改为 `system + user` 消息结构：翻译规则放入 system，待翻译文本单独放入 user。
- 如果重试耗尽后仍出现提示词复述，丢弃该模型输出并回退为源文本，让后续 gate 阻断，而不是把提示词写入 PDF。

### 3. 正文/参考文献角色纠偏

文件：`scripts/layout_role_policy.py`

- 在 `references_mode` 下新增普通正文片段识别，避免“包含 et al. 和年份的正文句子”被误判为 `references_entry`。
- 收窄 `looks_like_reference_entry()`：只有开头像作者列表或作者年份条目的文本才判为参考文献条目。
- 真正的参考文献条目仍保持 `references_entry`，不会被普通正文规则覆盖。

### 4. 真实 API 小批量 probe

文件：`scripts/translation_api_probe.py`

- 新增 `--failure-dir`，可从失败输出目录自动读取：
  - `backend_retry_failures.json`
  - `translation_proxy_stats.json`
  - `visible_residue_audit.json`
  - `visible_residue_pre_repair_audit.json`
- 新增 `strict_reflection` prompt variant，用于测试“上一轮坏输出 + 失败原因”的反思提示。
- 新增 `direct-system` call path，用于比较“全部放 user message”和“system 放规则、user 放源文”的 API 输入格式。
- 修正失败样本的 expected behavior：普通正文即便来自 `layout_role_passthrough`，也按 `translate` 评测，避免误把正文透传当成功。
- probe 的 `proxy/json-batch` 路径可接收 `--quality-retry-attempts`。

## 实测结论

对真实失败片段做小批量 DeepSeek A/B 后得到：

- `body_prose` 上，`paragraph` 风格 prompt 最稳定。
- `direct-system + paragraph` 在样本中普通正文 10/10 通过。
- `json-batch current` 在修正角色分类后，普通正文 10/10 通过。
- `current` 和 `strict_reflection` 对短 citation/list fragment 仍可能保留英文。
- 剩余失败主要是短引用列表、占位符残片、期刊名等非正文片段，应通过角色/保护规则降权或 passthrough，而不是强行正文翻译。

## 建议迁移步骤

1. 先合入 `visible_residue_audit.py` 与 `delivery_gate_runtime.py` 的 gate 加固，确保坏 PDF 不会被当作合格交付。
2. 合入 `layout_role_policy.py` 的正文/参考文献纠偏，降低正文被 `references_entry` 透传的概率。
3. 合入 `translation_compat_proxy.py` 的有限质量重试和 `system + user` 消息结构。
4. 使用 `translation_api_probe.py --failure-dir <失败输出目录>` 对真实失败片段做小批量 A/B。
5. 若 A/B 显示 `paragraph` prompt 更稳，将普通正文角色的 prompt 收敛为 paragraph 风格；短 citation/list fragment 单独做保护或 passthrough。

## 推荐验证命令

```bash
python3 -m py_compile \
  skills/double6-pdf-translation/scripts/visible_residue_audit.py \
  skills/double6-pdf-translation/scripts/delivery_gate_runtime.py \
  skills/double6-pdf-translation/scripts/layout_role_policy.py \
  skills/double6-pdf-translation/scripts/translation_compat_proxy.py \
  skills/double6-pdf-translation/scripts/translation_api_probe.py
```

```bash
python3 skills/double6-pdf-translation/scripts/translation_api_probe.py \
  --failure-dir <失败输出目录> \
  --output-dir /tmp/pdf_translation_probe \
  --no-synthetic \
  --max-cases-per-kind 12 \
  --call-paths direct-system,proxy,json-batch \
  --prompt-variants current,strict_reflection,paragraph \
  --temperatures 0.1 \
  --quality-retry-attempts 2
```

不要将本地测试目录、评测输出、PDF、截图、日志或 API key 上传到公开仓库。
