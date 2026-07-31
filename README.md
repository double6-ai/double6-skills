# Double6 Skills

Double6 AI 维护的开源 agent skills。仓库目前包含两个可以独立安装的 skill：一个负责多来源深度研究，一个负责保留版式的 PDF 中文翻译。

## Skills

| Skill | 适合做什么 | 运行要求 | 公开状态 |
|---|---|---|---|
| [`double6-deep-research`](skills/double6-deep-research/) | 研究开放性问题、比较多个对象、形成有证据的决策建议，并交付可核验的完整报告 | 宿主 agent 已提供并允许使用搜索、网页或材料读取能力；Python 3.10+ 仅用于可选的交付校验 | 可公开使用 |
| [`double6-pdf-translation`](skills/double6-pdf-translation/) | 将非扫描版英文 PDF 翻译为简体中文，尽量保留原始版式，并生成中文单语与中英双语 PDF | Python 3.11、`pdf2zh_next`、用户自行配置的 OpenAI-compatible 模型服务；PyMuPDF 和 reportlab 推荐安装 | 可公开使用，但需要先配置运行环境 |

两个 skill 都不会随仓库分发模型、API key、搜索服务或第三方 PDF 后端。请根据任务选择安装，不必复制整个仓库。

## 安装

先克隆仓库：

```bash
git clone https://github.com/double6-ai/double6-skills.git
cd double6-skills
```

将需要的目录复制到你的 agent skills 目录：

```bash
mkdir -p <agent-skills-dir>
cp -R skills/double6-deep-research <agent-skills-dir>/
cp -R skills/double6-pdf-translation <agent-skills-dir>/
```

`<agent-skills-dir>` 的具体位置由所使用的 agent 决定。只要宿主能够读取 `SKILL.md`，并具备对应 skill 所需的网页读取或本地 shell 能力，就可以按名称调用。

部分宿主只在会话启动时发现 skills。如果复制后按名称调用仍提示 unknown skill，请新建
会话或重启宿主，再检查安装目录是否正确；这不是 skill 运行失败。

## 使用

### 多来源深度研究

```text
请使用 $double6-deep-research 调研这个问题，明确给出证据、冲突、覆盖缺口、结论和限制。
```

这个 skill 提供研究方法、逐问题覆盖与饱和停止规范和交付校验器，不按固定来源数判定深度，也不自带搜索引擎或网页抓取服务。宿主没有获准的检索能力，或关键来源无法核验时，它会将结果标记为 `partial` 或 `blocked`，而不是把推断包装成事实。当前 validator 交付合同版本为 `2.0.0`。

详细说明见 [`skills/double6-deep-research/SKILL.md`](skills/double6-deep-research/SKILL.md)。

### PDF 翻译

```text
请使用 $double6-pdf-translation 将这个 PDF 翻译成准确、可读的简体中文，并尽量保持原始版式。
```

首次使用前，在已安装的 skill 目录中准备运行环境：

```bash
bash scripts/setup_venv.sh
bash run_translate.sh <input-file.pdf> --output-dir <output-dir> \
  --provider deepseek --model <model-name> --api-key-file <key-file>
```

启动器会先执行运行时检查，再进入正式翻译。也可以使用其它 OpenAI-compatible 服务；provider、base URL、模型与 API key 仅从本次命令行参数读取。缺少必要配置时不会开始正式翻译。

适用边界：

- 面向包含可提取文本层的英文 PDF；扫描版、图像版或严重损坏的 PDF 应先做 OCR。
- 默认可能把待翻译文本发送到用户配置的模型服务；处理敏感文档前，请确认服务商的数据与隐私政策。
- 默认不会访问 arXiv；只有用户明确同意并传入 `--allow-arxiv-source-autodownload` 时才下载论文源码；子进程使用环境白名单，且不再执行文档专用硬编码改写。
- PDF 后端和辅助工具由用户自行安装，并分别受其自身许可证约束。

完整依赖、配置和故障处理见：

- [`skills/double6-pdf-translation/SKILL.md`](skills/double6-pdf-translation/SKILL.md)
- [`runtime-dependencies.md`](skills/double6-pdf-translation/references/runtime-dependencies.md)
- [`known-pitfalls.md`](skills/double6-pdf-translation/references/known-pitfalls.md)

## 安全与隐私

- 不要把 API key、`.env`、私有文档、研究快照或运行产物提交到仓库。
- 安装 skill 前建议先阅读其 `SKILL.md`、脚本和依赖说明；PDF 翻译 skill 会执行本地进程、写入指定输出目录并访问用户配置的网络服务。
- 深度研究结果可能包含网页摘录或用户提供的材料。公开研究 bundle 前，请自行检查版权、个人信息和保密要求。
- 仓库不包含本地治理工具、验收报告、缓存、测试运行产物或第三方后端源码。

## 仓库结构

```text
skills/
├── double6-deep-research/
│   ├── SKILL.md
│   ├── references/
│   ├── scripts/
│   └── tests/
└── double6-pdf-translation/
    ├── SKILL.md
    ├── references/
    └── scripts/
```

## 反馈与更新

欢迎通过 GitHub Issues 报告可复现的问题或提出改进建议。提交问题时请去除 API key、私有文件内容和其它敏感信息。

如果这些 skills 对你有帮助，欢迎 Star 关注后续更新。

## 许可

本仓库源码使用 [MIT License](LICENSE) 发布。外部模型服务、Python 包、PDF 工具和其它第三方组件不随本仓库分发，并适用各自的许可证与服务条款。

发布到 ClawHub 的 skill 版本按该平台规则另行使用 MIT-0：允许使用、修改和再分发（包括商业使用），且不要求署名。GitHub 与 skills.sh 上的仓库源码仍适用根目录的 MIT License。
