# 宿主集成手册（Windows / 受限宿主）

本手册面向在 WorkBuddy、TRAE 等宿主中驱动 Double6 工作台制作器的调用方，沉淀 Windows 实测踩坑经验。流程语义与边界以 `SKILL.md` 为准；本文只覆盖操作层面的"怎么做、别怎么做"。

## 1. CLI 操作

### 最小命令序列

```bash
python scripts/double6.py start --run <run_dir> --request "<用户原话>" --route-file route.json
python scripts/double6.py respond --run <run_dir> --event-file event.json
python scripts/double6.py propose --run <run_dir> --product-file product.json
python scripts/double6.py build --run <run_dir>
python scripts/double6.py evaluate --run <run_dir> --preflight   # 环境预检，不改状态
python scripts/double6.py evaluate --run <run_dir>
```

- `start` 必须同时带 `--request`（或 `--request-file`）和 `--route-file`；缺路由文件时只返回场景目录，不会创建 run。
- 长文本或含特殊字符的原话优先用 `--request-file` 传文件，避免 shell 转义损耗。

### evidence_spans：逐字摘自原话

`route.json` 中的 `evidence_spans` 必须是用户原话里**逐字存在**的片段，校验器做逐字包含比对（`span in 原文`）。概括、改写、同义替换、编造的片段都会以 ContractError 拒绝。拿不准就多抄少改：直接从原话中截取连续子串。

### SHA 获取路径（拿错就 ContractError）

| 事件 | 绑定的 SHA | 从哪里读 |
| --- | --- | --- |
| `approve_product` | 理解稿 SHA | 当前 run 的 `product.json` → `presentation.content_sha256` |
| `approve_visual` / `reject_visual` | 候选 SHA | 当前 `build` 返回结果中的 `candidate_sha256` |

两条铁律：确认前**现读现用**，从当前 run 的文件里取，不复用缓存或上一轮的值；确认后任何产品内容变化都会使旧 SHA 失效，`build` 会强制重新提案与确认。

### 成败判据：只看 exit code

stderr 中的 `SAFE_DELETE_FAIL_CLOSED` 是 Windows 沙箱无回收站导致的噪音，不代表失败。只要 exit code 正常即为成功——不要据此重试、判失败或中断流程。旧 run 若有残留 journal/staging，用 `cleanup --run` 恢复。

### ContractError 自查表

| 报错场景 | 优先检查 |
| --- | --- |
| `start` 报路由相关错误 | `primary_domain` 是否在场景目录内；`evidence_spans` 是否逐字摘自原话；辅助领域是否超过两个或与主场景重复 |
| `approve_product` 被拒 | SHA 是否取自当前 `product.json` 的 `presentation.content_sha256`；产品文件确认后是否被改动过 |
| `approve_visual` / `reject_visual` 被拒 | SHA 是否取自**最近一次** `build` 的 `candidate_sha256`；是否重复或乱序提交事件 |
| `build` 失败要求重新提案 | 确认后标题、模块、内容、边界等是否发生变化——需重新走 propose → 展示 → approve_product |

## 2. 浏览器验收守则（宿主自写验收脚本时）

- **优先用系统 Chrome**：通过 `DOUBLE6_CHROMIUM_EXECUTABLE` 或 Playwright 的 `executable_path` 指向已安装的 Chrome.exe，不要先 `playwright install` 下载二进制。Windows 下 CLI 预检会自动尝试常见 Chrome 安装路径，先跑 `evaluate --preflight` 看指引。
- **禁用 `networkidle`**：SPA 页面长连接/轮询会让它 30 秒超时。统一用 `domcontentloaded` + 显式等待（等待具体选择器或状态出现）。
- **验证数据链路，不模拟完整答题**：答题 UI 自动化（自绘键盘、输入框焦点）太易碎。可靠做法是在页面内用 `page.evaluate` 直接执行与 `persist` 相同的写入逻辑，然后刷新页面、断言数据已落盘并正确回渲染。存储故障验收仍须按 `SKILL.md` 要求先填全部必填字段再逐字段比对。

## 3. 本机服务器扩展守则（local deploy）

用户主动提出"本机部署"（磁盘持久化、局域网访问）时直接执行，不要求额外的授权前置；它与"公开发布（云托管）"是两个方向，都超出单文件交付本身。实施时记住：

- **双写改造范围很小**：交付的 `index.html` 存储高度集中——单一 `STORAGE_KEY`、仅 3 处 localStorage 调用点。localStorage → 本地服务器的双写只需在这 3 处动手，不要去散落处补。
- **"换一批"必须用时间戳种子**：用日期做种子时同一天点几次结果都一样，用户会以为坏了。用 `Date.now()` 级别的时间戳或递增计数。
- **每日推荐要过滤恢复指针**：`edu-resume-*` 之类的恢复指针项不是内容，混入每日推荐会露出内部 ID（也会触发内部标识符泄漏检查）。
- **磁盘写入用原子写**：先写临时文件再 rename，防止中断时写坏数据文件。
- **查本机 IP 用 `ipconfig`**：`Get-NetIPAddress` 在部分环境无输出；注意排除 WSL、代理、蓝牙等虚拟网卡。
- **非 ASCII 路径删除用 PowerShell**：`rm` 在中文路径下可能失败，用 `Remove-Item -LiteralPath`。
- **定时任务双保险**：服务器内置定时器 + 宿主自动化（如 Windows 计划任务）各挂一份，任一失效另一份仍能兜底。
