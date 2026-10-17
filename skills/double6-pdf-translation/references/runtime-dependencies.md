# 运行依赖、来源与许可

## 安装

支持 macOS/Linux 和 Python 3.12。主工作流使用 POSIX 文件锁及进程资源控制；Windows 需使用 Linux 环境，不宣称原生支持。

```bash
bash scripts/setup_venv.sh /absolute/new/venv
```

安装器只接受新环境路径，使用 `uv` 和现有 Python 3.12，在新 venv 安装 `requirements-runtime.lock` 与 `requirements-build.lock` 的哈希锁定依赖，再以无依赖、无构建隔离方式安装本地维护的 PDFMathTranslate-next。用户自行准备 Python 和 uv；脚本不下载解释器、不复用或修改 WorkBuddy 等共享环境。

## 分层

| 内容 | 用途 |
| --- | --- |
| Python、psutil、PyYAML、Pillow、jsonschema | 工作流、资源限制、配置与审校输入 |
| PyMuPDF、fontTools、freetype-py、NumPy、reportlab、pypdf | 真实 PDF 读写、字形/布局/保护区和双语核验；reportlab/pypdf 也服务辅助渲染与诊断，不能因辅助工具缺失宣称所有主翻译路径失败 |
| PDFMathTranslate-next 2.8.2 与 BabelDOC 0.5.24 维护副本 | 电子 PDF 排版、保护和翻译后端，包含本地修复，不能替换成无修改上游包后继承既有质量结论 |
| RapidOCR 1.4.4 | 已有后端及可选 OCR；模型/字体下载与来源单独声明 |
| XeLaTeX 与所需 TeX 包 | 仅可信 LaTeX 路线，调用方显式准备 |
| Poppler | 可选独立文字框诊断 |
| MinerU 4.0.4、其模型及服务 | 可选扫描实验，不在默认环境安装；无此能力时可使用明确提供的已有 OCR，不宣称 OCR 已完成 |
| 模型服务、API key、字体、源论文 | 调用方明确提供与冻结，不随 skill 分发 |

默认依赖已移除 Gradio/gradio-pdf/gradio-i18n、FastAPI/Uvicorn/SSE，以及 Ollama、Xinference、DeepL、Azure 翻译和腾讯翻译 SDK。当前公共入口使用 OpenAI-compatible 服务；需要其它上游适配时应另行配置和验证。上游 GUI 源码仅为完整来源保留，CLI 发行候选拒绝 GUI 执行。

## 来源和许可证

- 先前 `paper-translation 2.0.0-trial.2` 第一方代码采用 AGPL-3.0-only。当前开发副本和本次整理保留该许可脉络及完整 [AGPL 原文](../LICENSE)，本次维护保持既有许可，变更及上游边界见 [MODIFICATIONS.md](../MODIFICATIONS.md)。旧 SHA 接受记录不重写为当前包接受，公开发布动作仍需另行授权。
- `vendor/pdfmathtranslate_next` 来自 PDFMathTranslate-next 2.8.2，保留其 AGPL-3.0 LICENSE 和版权；包含源项目的模型接口、排版、保护及缓存修复。本次另精简 pyproject 默认依赖并阻断 GUI。
- `vendor/babeldoc` 来自 BabelDOC 0.5.24，保留 AGPL v3 LICENSE；包含源项目的布局、字形及链接等修复，安全回移见 `SECURITY_BACKPORT.json`。
- `vendor/babeldoc/babeldoc/pdfminer` 保留自身 MIT LICENSE；Adobe CMap 数据继续适用同目录 README 的再分发条件。
- 未复制许可未闭合的 `vendor/pdf2zh_skill`，也未复制未被运行代码使用的 arxiv-paper-translator 规则副本。
- Python distribution 通过安装获取并适用各自许可证；site-packages、模型、字体、论文和 TeX 不随包分发。当前权利清单和校验回执保留在本项目本地报告中。

## 许可核对与使用边界

公开包保留第一方 AGPL-3.0-only、两项后端原许可证、内嵌 pdfminer 的 MIT 声明与 Adobe CMap 的再分发声明。维护版与所标上游版本的源码差异、维护日期见根目录 [MODIFICATIONS.md](../MODIFICATIONS.md)。旧 `pdf2zh_skill` 缺少可核验的许可凭据，未纳入分发。

本次核对覆盖锁定运行环境的 98 项分发包。它们由安装器按哈希下载，不将 wheel、已安装环境或模型权重放进 Skill 包。MIT、BSD、Apache、ISC、PSF 等许可仍属于各自原作者；不能因为安装后在同一环境中运行，就把其许可证文字替换为本项目许可证。

需要单独保留理解的条目包括：PyMuPDF 与 BabelDOC 使用 AGPL；Levenshtein 0.27.3 标注 GPL-2.0-or-later，可按后续版本选项选择 GPLv3，与 AGPLv3 组合时遵守各自条件；certifi、orjson 与 tqdm 涉及 MPL 或复合许可。GNU 对 GPLv3/AGPLv3 组合及“或更新版本”的说明见[许可兼容说明](https://www.gnu.org/licenses/license-compatibility.en.html)。下载和再分发这些依赖时，仍须保留各自声明和适用的源码义务。

论文、模型、字体和 TeX 由运行者自行提供或安装，各自权利独立核对。回放使用的系统中文字体和已有模型仅在本机读取，未随 Skill 再分发。

本地无鉴权兼容服务由后端 SDK 要求一个非空字段时，命令适配器使用明确的 `local-no-auth` 占位值；它不是凭据。远程后端缺少密钥会明确停止。实际上游 HTTP 请求在未配置密钥时不发送 `Bearer None`。

安装脚本在哈希锁定安装后实际导入主路径原生模块，最多等待 180 秒；该步骤不载入翻译模型、不发送翻译请求。安装完成后的论文任务仍按各自冻结合同计算资源与时限。
