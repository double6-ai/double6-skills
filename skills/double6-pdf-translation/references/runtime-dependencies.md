# 运行依赖、来源与许可

## 安装

支持 macOS/Linux 和 Python 3.12。主工作流使用 POSIX 文件锁及进程资源控制；Windows 需使用 Linux 环境，不宣称原生支持。

```bash
bash scripts/setup_venv.sh /absolute/new/venv
```

安装器只接受新环境路径，使用 `uv` 和现有 Python 3.12，在新 venv 安装 `requirements-runtime.lock` 与 `requirements-rapidocr.lock`（后者只装 RapidOCR 本体，不跟随它声明的带界面 OpenCV），再安装 `requirements-build.lock` 以便构建本地维护的 PDFMathTranslate-next。构建完成后卸掉打包工具。用户自行准备 Python 和 uv；脚本不下载解释器、不复用或修改 WorkBuddy 等共享环境。PyPI 上的 babeldoc 包不安装，运行使用 `vendor/babeldoc`。

## 分层

| 内容 | 用途 |
| --- | --- |
| Python、psutil、PyYAML、Pillow、jsonschema | 工作流、资源限制、配置与审校输入 |
| PyMuPDF、fontTools、freetype-py、NumPy、reportlab、pypdf | 真实 PDF 读写、字形/布局/保护区和双语核验；reportlab/pypdf 也服务辅助渲染与诊断，不能因辅助工具缺失宣称所有主翻译路径失败 |
| PDFMathTranslate-next 2.8.2 与 BabelDOC 0.5.24 维护副本 | 电子 PDF 排版、保护和翻译后端，包含本地修复，不能替换成无修改上游包后继承既有质量结论 |
| RapidOCR 1.4.4 | 已有后端及可选 OCR；模型/字体下载与来源单独声明 |
| XeLaTeX 与所需 TeX 包 | 仅可信 LaTeX 路线，调用方显式准备 |
| Poppler | 可选独立文字框诊断 |
| Tesseract OCR 5.x（CLI）与 tessdata_fast `chi_sim`/`eng`/`osd` | 仅 `candidate --route scanned_ocr`；系统包安装，不随 skill 分发；缺失只阻断该路线，不算主路线失败 |
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

本次核对覆盖运行锁 76 条，另加不跟随声明依赖的 RapidOCR。它们由安装器按哈希下载，不将 wheel、已安装环境或模型权重放进 Skill 包。MIT、BSD、Apache、ISC、PSF 等许可仍属于各自原作者；不能因为安装后在同一环境中运行，就把其许可证文字替换为本项目许可证。带界面的 OpenCV、Hugging Face 下载库、`lxml`、`uharfbuzz`、`ruff`、xsdata 的命令行附加项和 `scikit-image` 不在运行环境里。图像处理只用 `opencv-python-headless`。配置读写用 `tomlkit`。扫描件判断默认跳过；真要跑那一步时才导入 `scikit-image`，需要的话另行安装。PyPI 上的 babeldoc 发行包不安装。

需要单独保留理解的条目包括：PyMuPDF 与 BabelDOC 使用 AGPL；Levenshtein 0.27.3 标注 GPL-2.0-or-later，可按后续版本选项选择 GPLv3，与 AGPLv3 组合时遵守各自条件；certifi、orjson 与 tqdm 涉及 MPL 或复合许可。GNU 对 GPLv3/AGPLv3 组合及“或更新版本”的说明见[许可兼容说明](https://www.gnu.org/licenses/license-compatibility.en.html)。下载和再分发这些依赖时，仍须保留各自声明和适用的源码义务。

论文、模型、字体和 TeX 由运行者自行提供或安装，各自权利独立核对。回放使用的系统中文字体和已有模型仅在本机读取，未随 Skill 再分发。

## 翻译服务凭据

运行时只读环境变量 `LOCAL_TRANSLATION_API_KEY`；`doctor`、`candidate` 及各路线都只读它（不再读取 `OPENAI_API_KEY`），`doctor` 结果的 `credential` 字段只报告来源与是否存在，不记录值。默认模型档案是智谱 coding plan（`configs/model-profiles.json`，模型 `glm-5.3-flash`，端点 `https://open.bigmodel.cn/api/coding/paas/v4`）。这个档案在 `LOCAL_TRANSLATION_API_KEY` 为空、且环境里已有 `GLM_API_KEY` 时，先把后者抄进前者，再走同一条通道；值不进命令行。不要把 coding plan 密钥配到 `https://open.bigmodel.cn/api/paas/v4`，那个地址会返回 429（错误码 1113）。`run_pdf_translation.py --api-key` 仅为兼容保留，用它时值会出现在该进程自身的命令行里，不建议使用。

- 回环地址（`localhost`、`127.0.0.1`、`::1`）未提供时使用明确的 `local-no-auth` 占位值；它不是凭据。远端地址（包括其它 `127.x` 地址）未提供即报 `remote_backend_requires_explicit_api_key`，在启动任何子进程或代理之前停止。实际上游 HTTP 请求在未配置密钥时不发送 `Bearer None`。
- 凭据不进入任何子进程的命令行，按各后端原生的非命令行通道传入：电子 PDF 后端（PDFMathTranslate-next）读取其配置环境变量 `PDF2ZH_OPENAI_API_KEY`；`qwen-cli` 适配器继承 `LOCAL_TRANSLATION_API_KEY`；可信 LaTeX 路线（`independent_latex`）在本进程内发起请求。启动后端前先清除继承的 `PDF2ZH_OPENAI_API_KEY`、`LOCAL_TRANSLATION_API_KEY`、`OPENAI_API_KEY` 与 `PDF2ZH_DEBUG`（后者会让后端把含凭据的完整配置写进调试日志），再只放入该后端需要的一个变量。
- 旧 LaTeX 直连后端 `pdf2zh_skill` 未随本仓库分发，其非命令行凭据通道无法在本仓库核实：后端缺失时返回结构化错误 `latex_direct_backend_unavailable`，不启动子进程；已安装且需要凭据时，本进程只在 `127.0.0.1` 起一个转发器，保留用户显式的上游地址、模型与凭据，子进程命令行只含一次性访问令牌（子进程结束即随转发器关闭失效）；转发器无法启动时报 `latex_direct_credential_forwarder_unavailable`。不静默改用本机服务或其它模型。
- 翻译缓存按端点、模型、目标语言与提示词隔离，不以凭据为缓存身份；凭据不写入缓存库。经本机兼容代理时，缓存身份还包含代理声明的真实上游身份（规范化上游地址、上游模型、传输方式，见 `scripts/upstream_identity.py`），同一本机代理端口换了上游不会复用另一服务的译文；运行中响应声明的上游与缓存身份不一致即失败关闭。本机其它（非本项目）中间层不声明身份，无法据此区分其背后的上游，此时缓存身份只有它的本机地址。
- 边界：环境变量对同一用户的其它进程可见（如 Linux `/proc/<pid>/environ`），不构成保密隔离边界；本改动只保证凭据不出现在子进程命令行、日志、回执、清单、异常与缓存中，不宣称完全隔离。

安装脚本在哈希锁定安装后实际导入主路径原生模块，最多等待 180 秒；该步骤不载入翻译模型、不发送翻译请求。安装完成后的论文任务仍按各自冻结合同计算资源与时限。

## OCR 路线第三方声明（rc.8，`--route scanned_ocr`）

以下组件由运行者通过系统包管理器安装，不随 Skill 再分发；本 Skill 只以子进程方式调用 `tesseract` 命令行，不链接其库。

| 组件 | 核对版本（Debian trixie 包） | 许可证 | 来源 |
| --- | --- | --- | --- |
| Tesseract OCR 引擎（`tesseract-ocr`、`libtesseract5`） | 5.5.0-1+b1（`tesseract 5.5.0`） | Apache-2.0（个别构建脚本 MIT） | https://github.com/tesseract-ocr/tesseract |
| Leptonica 图像库（`libleptonica6`，Tesseract 的依赖） | 1.84.1-4 | Leptonica 许可（BSD 2 条款式） | https://github.com/DanBloomberg/leptonica |
| 语言数据 `chi_sim.traineddata`（`tesseract-ocr-chi-sim`） | 1:4.1.0-2，2,469,156 字节 | Apache-2.0（上游 tessdata_fast） | https://github.com/tesseract-ocr/tessdata_fast |
| 语言数据 `eng.traineddata`（`tesseract-ocr-eng`） | 1:4.1.0-2，4,113,088 字节 | Apache-2.0（上游 tessdata_fast） | 同上 |
| 方向与文字检测 `osd.traineddata`（`tesseract-ocr-osd`） | 1:4.1.0-2，10,562,727 字节 | Apache-2.0（上游 tessdata_fast） | 同上 |
| 重建源中文字体：PyMuPDF 内置 `china-s`（Droid Sans Fallback） | 随 PyMuPDF 1.25.2（锁定依赖） | Apache-2.0（字体）；PyMuPDF 本身 AGPL-3.0 | PyMuPDF / Android Open Source Project |

`OCR_MANIFEST.json` 记录实际运行的引擎版本横幅、`tessdata` 目录及每个语言数据文件的大小与 sha256，便于复核。没有使用任何付费 API、云 OCR 或密钥。其它发行版的 Tesseract 5.x 可用，但识别结果和置信度会随版本与语言数据变化；本版只在上表版本上测量过。
