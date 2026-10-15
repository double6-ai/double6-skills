# 更新记录

## 0.42.0 - 2026-10-15

修复
- 内容运营首页漏掉第 5 个默认模块“数据复盘”，导致默认方案过不了自带验收；所有 renderer 现在都会自动补全遗漏的已确认模块入口。
- 去掉内置内容里的 `synthetic_demo` 机器标记；静态验收新增 snake_case 标记扫描，并覆盖由脚本渲染的内置内容。
- 侧栏短标签不再硬截断（如“实验与工”），“数据复盘”不再与数据入口同名；验收新增导航重名检查。
- “今天”、周起点、连续天数统一按设备本地时区计算（修复东八区周键偏移一天、0–8 点记录算到前一天）。
- “使用这个模板”把模板正文填入第一个文本/长文本字段，不再误填日期或下拉框。
- `--request-file` 等输入文件兼容 UTF-8 BOM 与 UTF-16（PowerShell 5 默认输出），其他编码给出明确报错。
- Playwright 浏览器发现补齐 `PLAYWRIGHT_BROWSERS_PATH`、macOS 缓存目录与 chrome-linux64 / chrome-mac-arm64 / chrome-win64 新目录。
- CLI 启动时检查 Python ≥ 3.10。
- 补记：CLI 强制以 UTF-8 输出 stdout/stderr，修复 Windows cp1252 控制台打印中文时崩溃（3646e2b，此前未发版）。

内容与视觉
- 内容运营内置内容改为面向一人多平台自媒体：素材卡、选题打分卡、一鱼多吃拆四平台、脚本骨架、发布前自检、一周发布节奏、互动率/涨粉转化率计算与周复盘三问。
- 研究知识更名为“研究阅读”，新增“阅读清单”模块（三遍阅读法、读书卡、阅读进度）与证据卡、引用格式速查、写作大纲等内置内容。
- 新增 `research_reading_desk` 场景与 `research_reading_dashboard` renderer（阅读书架 + 研究工作流 + 三遍阅读法），内容运营首页重做为“内容流水线 + 一周节奏 + 常用平台”。
- 非学习场景不再出现“老师布置的内容、错题”“可反复练习”“点一点就能听”等教育话术。
- 统一 CJK 无衬线字体栈，收紧首屏 hero 与“今天要处理”高度，去掉重复的进度文案；模块 emoji 改为按语义分配且不重复。
- 候选 `<head>` 内置 Content-Security-Policy，从机制上阻断外联。

文档、测试与发布
- SKILL.md 触发描述改为中英双语并覆盖内容运营、阅读/研究追踪等说法；写明 Python 3.10+。
- 宿主手册补充事件/产品文件最小示例与 `presented_content_sha256` / `presented_candidate_sha256` 字段名；ContractError 报错写明期望字段；`product.schema.json` 与校验逻辑对齐；`surface` 可省略由 CLI 从快照补全。
- 新增 `tests/test_end_to_end.py`：16 个领域及全部细分档案的六步端到端与静态验收；Playwright 可用时追加浏览器验收。CI 新增 ubuntu 浏览器验收 job，并升级 actions 版本。
- manifest 的 `release_validation` 指向随仓库测试；`.clawhubignore` 改为随包分发 `agents/` 与 `security/`（安装后检查依赖 `agents/interface.yaml`）。

## 0.41.0 - 2026-08-09

- 将完整运行合同下沉到按需读取的 reference，缩小初始上下文并保持原有能力边界。
- 补齐 OpenAI、Claude 与通用本地执行 agent 的接口元数据。
- 增加文件写入、离线浏览器验收的权限与网络策略，并让浏览器依赖延迟加载。
- 增加安装沙箱真实运行 smoke，验证公开包能读取路由目录并运行 CLI。
- 增加 ClawHub 包边界，排除本地报告、治理材料和运行产物。

## 0.40.0 - 2026-08-07

- 首次转为公开共享状态。
