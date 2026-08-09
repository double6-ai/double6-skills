---
name: double6-workbench-builder
version: 0.41.0
description: 把普通用户反复要做的真实事情构建成离线优先、严格单文件、个人数据留在当前设备的本地工作台。用户提到个人工作台、学习台、备考台、任务面板、记录与复盘工具，或想把重复流程做成可保存恢复的页面时应使用；联网、多人协作、账号、支付和发布属于独立外部流程。
metadata:
  openclaw:
    homepage: https://github.com/double6-ai/double6-skills/tree/main/skills/double6-workbench-builder
    emoji: "🧰"
    requires:
      anyBins:
        - python3
        - python
        - py
---

# Double6 工作台制作器

把澄清后的真实重复工作做成一个可离线打开的 `index.html`。触发后先读
`references/runtime-contract.md`；它是完整运行合同，本文只保留路由和执行入口。

## 核心流程

1. 从 CLI 返回的 16 个领域中选择主场景和最多两个辅助场景；`evidence_spans` 必须逐字摘自用户原话。
2. 用 `start` 建立 run；只询问会改变对象、核心动作、数据边界或验收结果的问题，最多三个，并给出推荐答案。
3. 用 `propose` 展示包含 4–15 个核心模块、内置 starter 和可选模块的完整理解稿；用户确认必须绑定当前理解稿 SHA。
4. 确认后用 `build` 只生成一个推荐候选，再运行 `evaluate --preflight`。环境未就绪时先修复环境。
5. 让用户查看候选；视觉确认或拒绝必须绑定当前候选 SHA。需要改 renderer/CSS 时进入 `renderer_revision_required`，不得空跑重建。
6. 用 `evaluate` 完成静态与浏览器验收；只有完整通过才交付。`--skip-browser` 只是预检，不能形成交付。

在 skill 根目录运行 CLI：

```bash
python scripts/double6.py start --run <run_dir> --request "<用户原话>" --route-file route.json
python scripts/double6.py respond --run <run_dir> --event-file event.json
python scripts/double6.py propose --run <run_dir> --product-file product.json
python scripts/double6.py build --run <run_dir>
python scripts/double6.py evaluate --run <run_dir> --preflight
python scripts/double6.py evaluate --run <run_dir>
```

## 必守边界

- 交付严格为单个离线 HTML；个人数据仅留在当前设备，并提供导入、导出和恢复。
- 儿童、学生、客户、财务、医疗和健康场景默认只用合成或脱敏数据；不得保存 token、密码、Cookie 或会话密钥。
- 联网数据、多人协作、账号、消息、支付、下单和公开发布只能标为人工交接或暂不支持，页面不得自行执行。
- 每个核心模块必须同时有可立即操作的内置内容和真实交互表面，不能用空表、占位卡或纯说明冒充能力。
- 内部 ID、schema 字段和治理术语不得进入用户可见文案；外部导入内容必须限量、转义、可撤销。
- 视觉确认、产品确认和候选验收都必须使用当前 run 现读的 SHA，不能复用旧值或伪造确认。

## 按需读取

- 所有构建：`references/runtime-contract.md`。
- 儿童学习：`references/education-rules.md`；内容来源不确定时再读 `references/education-content-research-policy.md`。
- Windows、受限宿主、浏览器预检或本机部署：`references/host-integration-playbook.md`。
- 产品字段：`references/product.schema.json`；领域、starter、视觉与风险规则使用 `references/` 中对应 JSON 合同。

公开命令与 schema 版本以 `manifest.json` 为准；维护者的安装后发布检查见 `evals/release_sandbox_cases.json`。打包、覆盖安装、共享晋升和外部发布必须由宿主在用户授权后执行。
