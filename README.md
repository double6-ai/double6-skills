# Double6 Skills

**想学会用 AI，从一件具体的事开始。**

[Double6 · 普通人的 AI 入门网站](https://double6.cn) 提供中文 AI 入门知识、工具介绍和实际任务教程。刚开始接触 AI，可以从基础内容学起；已经有想做的事，可以按场景寻找方法。

本仓库由 Double6 AI 维护，源于我们建设 Double6 网站时遇到的实际需求。在调研和实测中，我们发现现有开源 skills 在部分任务上仍有功能缺口或改进空间，于是围绕这些问题开发和完善了一系列解决方案。当前包括 PDF 翻译、深度研究、个人工作台、PPT 制作和离线材料脱敏等可独立安装的 skills。

## Skills

| Skill | 适合做什么 | 运行要求 | 公开状态 |
|---|---|---|---|
| [`double6-pdf-translation`](skills/double6-pdf-translation/) | 将英文 PDF/可信 LaTeX 或有限清晰单栏扫描译为简体中文，保留完整审校并生成单语与双语 PDF | macOS/Linux、Python 3.12、随包维护后端和显式配置的模型服务 | [2.0.0-rc.2](https://github.com/double6-ai/double6-skills/releases/tag/double6-pdf-translation-v2.0.0-rc.2)，111 开工合同 |
| [`double6-deep-research`](skills/double6-deep-research/) | 研究开放性问题、比较多个对象、形成有证据的决策建议，并交付可核验的完整报告 | 宿主 agent 已提供并允许使用搜索、网页或材料读取能力；Python 3.10+ 仅用于可选的交付校验 | 可公开使用 |
| [`double6-workbench-builder`](skills/double6-workbench-builder/) | 把反复要做的真实事情（学习台、备考台、任务面板、内容/社媒运营台、阅读与研究追踪、记录与复盘等）构建为离线优先、严格单文件的本地个人工作台，个人数据只留在当前设备 | Python 3.10+（仅标准库）；浏览器验收可选 Playwright + Chromium | 可公开使用（实验性） |
| [`double6-ppt-cli`](skills/double6-ppt-cli/) | 生成、套用模板、读取、检查和闭环修复原生可编辑 PPTX，覆盖 Markdown/结构化材料创作、模板对象级填充，以及已有 PPTX 的质检与受限修复 | Python 3、OfficeCLI 1.x（bootstrap 固定安装 pin `1.0.157`，运行时接受 ≥ 1.0.144 的 1.x）；**portable 档不需要 macOS**；native 档需要 macOS + Microsoft PowerPoint + `osascript` | 可公开使用；完整 native 闭环建议本机 PowerPoint，portable 档交付为 `pass_with_warnings` |
| [`double6-offline-material-redaction`](skills/double6-offline-material-redaction/) | 上传 AI 前，在本机补选敏感内容、清理支持的隐藏内容并生成脱敏副本，保留业务文字与数字 | Windows x64 或 Apple 芯片 macOS、Python 3.10–3.14；旧格式显式转换另需 LibreOffice | 免费开源源码；安装和验证范围见该Skill说明 |

这些 skill 都不会随仓库分发模型、API key、搜索服务、OfficeCLI 二进制或未声明的第三方组件。请根据任务选择安装，不必复制整个仓库。

## 安装

先克隆仓库：

```bash
git clone https://github.com/double6-ai/double6-skills.git
cd double6-skills
```

将需要的目录复制到你的 agent skills 目录：

```bash
mkdir -p <agent-skills-dir>
cp -R skills/double6-pdf-translation <agent-skills-dir>/
cp -R skills/double6-deep-research <agent-skills-dir>/
cp -R skills/double6-workbench-builder <agent-skills-dir>/
cp -R skills/double6-ppt-cli <agent-skills-dir>/
cp -R skills/double6-offline-material-redaction <agent-skills-dir>/
```

也可以从公开目录安装：

```bash
# skills.sh（GitHub 源）
npx skills add double6-ai/double6-skills --skill double6-pdf-translation
npx skills add double6-ai/double6-skills --skill double6-deep-research
npx skills add double6-ai/double6-skills --skill double6-workbench-builder
npx skills add double6-ai/double6-skills --skill double6-ppt-cli
npx skills add double6-ai/double6-skills --skill double6-offline-material-redaction

# ClawHub
clawhub install double6-pdf-translation
clawhub install double6-deep-research
clawhub install double6-workbench-builder
clawhub install double6-ppt-cli
```

`<agent-skills-dir>` 的具体位置由所使用的 agent 决定。只要宿主能够读取 `SKILL.md`，并具备对应 skill 所需的网页读取或本地 shell 能力，就可以按名称调用。

部分宿主只在会话启动时发现 skills。如果复制后按名称调用仍提示 unknown skill，请新建
会话或重启宿主，再检查安装目录是否正确；这不是 skill 运行失败。

## 使用

### PDF 翻译

```text
请使用 $double6-pdf-translation 将这个 PDF 翻译成准确、可读的简体中文，并尽量保持原始版式。
```

当前目录保留 `paper-translation` 的 `110-unpublished` 路线，已同步第 111 轮当前开工合同；来源按第 111 轮合同纠正，软件候选与每份成品的接受状态分别登记。每份文档需要完整语义、页面、字形样式、链接、真实阅读复制及冷重建核验；陌生输入不自动准入。

在已安装 skill 目录创建独立环境：

```bash
bash scripts/setup_venv.sh /absolute/new/venv
/absolute/new/venv/bin/python scripts/paper_translation_workflow.py --help
```

适用 macOS/Linux、Python 3.12。电子 PDF 与可信 LaTeX 主入口限完整 1–5 页；扫描预检默认最多 2 页，随后须具名确认完整源组和角色。新翻译必须明确模型、服务与凭据；冻结重建可离线运行。模型、字体、TeX、论文和缓存不随包分发。维护后端源码保留其 AGPL v3 与内嵌组件许可。

当前 main 上的候选版本为 `2.0.0-rc.9`（未发布，变更见 [CHANGELOG](skills/double6-pdf-translation/CHANGELOG.md)）。上一版 `2.0.0-rc.2` 已按精确冻结包[公开发布](https://github.com/double6-ai/double6-skills/releases/tag/double6-pdf-translation-v2.0.0-rc.2)，下载包 SHA256 为 `cf3cb6a3e0780459f1c9b0625e376f373edfbf9e0e8a37cc5c1a4043a79eace6`。它保留候选版本标识和包内冻结时的状态元数据；每份 PDF 的技术核验、用户接受和严格交付仍分别登记。

入口及配置见 [SKILL.md](skills/double6-pdf-translation/SKILL.md)、[运行说明](skills/double6-pdf-translation/references/release-quickstart.md) 和 [运行依赖及许可](skills/double6-pdf-translation/references/runtime-dependencies.md)。

### 多来源深度研究

```text
请使用 $double6-deep-research 调研这个问题，明确给出证据、冲突、覆盖缺口、结论和限制。
```

这个 skill 提供研究方法、逐问题覆盖与饱和停止规范和交付校验器，不按固定来源数判定深度，也不自带搜索引擎或网页抓取服务。宿主没有获准的检索能力，或关键来源无法核验时，它会将结果标记为 `partial` 或 `blocked`，而不是把推断包装成事实。当前 validator 版本为 `2.3.0`，`research_record.json` 使用 schema v2。

详细说明见 [`skills/double6-deep-research/SKILL.md`](skills/double6-deep-research/SKILL.md)。

### 个人工作台制作器

```text
请使用 $double6-workbench-builder 把我反复要做的这件事做成一个可离线使用的本地工作台。
```

这个 skill 用 `start` → `respond` → `propose` → `build` → `evaluate` 五个命令完成六步流程（选场景、澄清、理解稿确认、构建候选、候选确认、验收），把澄清后的需求构建成一个可离线打开的单个 `index.html`：内置可直接操作的起始内容、localStorage 本地保存、导入导出备份和移动端适配。联网、多人协作、账号、支付和公开发布不属于单文件交付范围，只标记为人工交接或暂不支持。

适用边界：

- 交付物只写入本产品唯一的 localStorage 命名空间；儿童、学生、财务、医疗等敏感场景默认使用合成或脱敏数据。
- 构建器只依赖 Python 标准库；完整的浏览器验收需要自行安装 Playwright 与 Chromium，环境缺失时只会标记为 `evaluation_blocked`，不会假装通过。
- 发布到云托管或本机部署由独立的宿主流程执行，本 skill 不自行上线任何页面。

入口说明见 [`skills/double6-workbench-builder/SKILL.md`](skills/double6-workbench-builder/SKILL.md)，完整流程与验收边界见 [`runtime-contract.md`](skills/double6-workbench-builder/references/runtime-contract.md)。

### 可编辑 PPTX 闭环

```text
请使用 $double6-ppt-cli 基于这份材料生成可编辑 PPTX，并完成 inspect / repair / 验证闭环。
```

这个 skill 默认闭环是 `模板分析/原生创作 → 生成副本 → inspect → 确定性修复 → 验证 → 可选视觉复核 → finalize`。它支持原生生成、模板填充和已有 PPTX 质检修复三种模式；原文件永不覆盖，自动修复只允许确定性叶子操作。

适用边界：

- 本机有 Microsoft PowerPoint 与 `osascript` 时走 native 验证；没有或系统拒绝辅助访问时，`verify --verify-tier auto` 自动降级 portable 档（OfficeCLI 校验/改字探针 + 可选 LibreOffice 渲染），交付状态为 `pass_with_warnings`。**非 macOS / 无 PowerPoint 可直接使用 portable 档。**
- OfficeCLI 由 `bootstrap` 固定安装 pin `1.0.157`（最低兼容 1.0.144）；运行时也接受更新的 1.x，非 pin 版本由 doctor 报 `warn` 并可继续使用，major ≠ 1 或低于最低兼容版本才 fail。`--verify-tier native` 可强制要求 PowerPoint。
- `init --mode generate --design consulting|investor-pitch|product-launch|operating-review|academic|training|neutral` 会创建 spec/design 与语义身份草稿；`recipe deck --plan plan.json` 用 18 个版式配方直接出页，包括满版照片封面、超大数字、引语、开放式时间轴、标注式原生图表、高亮原生表格等；`image-search` / `image-add` 获取 royalty-free 图片并记录署名；PowerPoint 始终是可选 native 验证能力，显式 portable 会完整跳过它。
- 不负责 PDF/DOCX 内容解析、图片式 PPT、HTML slides、TTS 或视频。
- 视觉检查默认要求；用户明确跳过时结果只能是 `pass_with_warnings`，不会伪装成完整视觉通过。
- vendored `ppt-master-core` 来自 PPT Master v6.7.0（实验分支 exp/pm6-generate，仅 generate；template-fill 暂未迁移），适用其 MIT 许可证；OfficeCLI 作为外部固定依赖由用户自行安装。

入口说明见 [`skills/double6-ppt-cli/SKILL.md`](skills/double6-ppt-cli/SKILL.md)，交付门禁与上游许可证见 [`delivery-gates.md`](skills/double6-ppt-cli/references/delivery-gates.md) 与 [`licenses-and-upstreams.md`](skills/double6-ppt-cli/references/licenses-and-upstreams.md)；PowerPoint 可选双档与完整测试报告见 [`test-report-and-verification-tiers.md`](skills/double6-ppt-cli/references/test-report-and-verification-tiers.md)。

### 本地材料脱敏

```text
请使用 $double6-offline-material-redaction 准备本机脱敏工具，检查安装和自检结果，然后打开界面让我补选。不要把真实材料发到聊天。
```

适用Windows x64和Apple芯片macOS、Python3.10–3.14。首次安装按哈希清单下载依赖，处理图片、Word、文本、PDF、表格和PPT时不调用在线服务。默认生成同格式新副本，转换须明确指定；PDF不默认整页图像化。图片/PDF需要人工选全区域；Word/PPTX重建不保留全部图片和版式，复杂表格显示可能被拒绝。请声明业务保留项，打开实际副本核对，自动检查不能保证找全敏感信息。

本Skill原创源码采用MIT许可；原生PDF依赖PyMuPDF/MuPDF，适用AGPL-3.0，MIT不覆盖该依赖。本Skill只通过GitHub源码与Skills CLI提供，尚未另行上架ClawHub。公开包不包含EXE/App、Python或Office；旧DOC/XLS/PPT/RTF另需用户安装LibreOffice。入口与安装见[SKILL.md](skills/double6-offline-material-redaction/SKILL.md)、[README](skills/double6-offline-material-redaction/README.md)，依赖许可见[说明](skills/double6-offline-material-redaction/references/runtime-dependencies.md)。

## 安全与隐私

- 不要把 API key、`.env`、私有文档、研究快照或运行产物提交到仓库。
- 安装 skill 前建议先阅读其 `SKILL.md`、脚本和依赖说明；PDF 翻译 skill 会执行本地进程、写入指定输出目录并访问用户配置的网络服务；PPT skill 会读写本地 run 副本，并在 native 档驱动本机 PowerPoint 做验证。
- 深度研究结果可能包含网页摘录或用户提供的材料。公开研究 bundle 前，请自行检查版权、个人信息和保密要求。
- 仓库不包含本地治理工具、验收报告、缓存、测试运行产物或 OfficeCLI 二进制。PDF 翻译候选包含有许可声明的维护后端源码。

## 仓库结构

```text
skills/
├── double6-pdf-translation/
│   ├── SKILL.md / README.md / LICENSE
│   ├── configs/ / schemas/ / examples/ / prompts/
│   ├── references/
│   ├── scripts/
│   ├── vendor/             # PDFMathTranslate-next / BabelDOC维护源码
│   └── requirements-*.lock
├── double6-deep-research/
│   ├── SKILL.md
│   ├── references/
│   ├── scripts/
│   ├── tests/
│   └── CHANGELOG.md
├── double6-workbench-builder/
│   ├── SKILL.md
│   ├── manifest.json
│   ├── agents/
│   ├── evals/
│   ├── references/
│   ├── scripts/
│   ├── security/
│   ├── tests/
│   └── CHANGELOG.md
├── double6-ppt-cli/
│   ├── SKILL.md
│   ├── assets/
│   ├── references/
│   ├── scripts/            # 含 scripts/tests/
│   ├── vendor/             # ppt-master-core（MIT）
│   ├── licenses/
│   ├── LICENSE / NOTICE / THIRD_PARTY_NOTICES.md
│   ├── MODIFICATIONS.md / UPSTREAM_LOCK.json
│   ├── requirements-core.lock
│   └── CHANGELOG.md
└── double6-offline-material-redaction/
    ├── SKILL.md / README.md / LICENSE
    ├── scripts/            # 本地处理、界面、安装与测试源码
    ├── references/
    ├── requirements-runtime.lock
    └── CHANGELOG.md
```

## 反馈与更新

欢迎通过 GitHub Issues 报告可复现的问题或提出改进建议。提交问题时请去除 API key、私有文件内容和其它敏感信息。

如果这些 skills 对你有帮助，欢迎 Star 关注后续更新。

## 许可

除 `skills/double6-ppt-cli` 和 `skills/double6-pdf-translation` 外，本仓库源码使用 [MIT License](LICENSE) 发布。`skills/double6-ppt-cli` 是例外：其中 Double6 原创的 glue、policy、CLI、schema 与测试按该 skill 根目录的 Apache License 2.0 发布，`vendor/ppt-master-core` 继续适用 PPT Master 的 MIT 许可证，详见该目录的 [`LICENSE`](skills/double6-ppt-cli/LICENSE)、[`NOTICE`](skills/double6-ppt-cli/NOTICE) 与 [`THIRD_PARTY_NOTICES.md`](skills/double6-ppt-cli/THIRD_PARTY_NOTICES.md)。PDF 翻译候选保留 AGPL v3 许可原文与上游声明，当前开发成员仍待精确许可范围及发布接受，见其 [依赖与许可说明](skills/double6-pdf-translation/references/runtime-dependencies.md)。子目录中的 LICENSE 文件优先于根目录 LICENSE。通过安装获取的 Python 包、外部模型服务、OfficeCLI 和系统工具适用各自的许可证与服务条款；随包维护源码按对应目录声明保留许可。

发布到 ClawHub 的 skill 版本按该平台规则另行使用 MIT-0：允许使用、修改和再分发（包括商业使用），且不要求署名。该 MIT-0 说明不适用于当前 PDF 翻译候选及 `double6-ppt-cli`：PDF 翻译候选保留 AGPL v3 许可脉络。PPT 的 Apache-2.0 原创部分与 vendored MIT 组件仍须按各自许可证保留版权声明与 NOTICE。GitHub 与 skills.sh 上的仓库源码适用上述根目录及子目录许可证。
