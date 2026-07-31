# Known Pitfalls (踩坑汇总)

本 skill 在 Windows + WorkBuddy 托管 Python 环境中完成了真实运行验证。以下 19 个问题用于帮助新机器和新 agent 避免重复踩坑。

每项按“现象 → 根因 → 修复 → 影响位置”组织。

## 目录

- [P1–P4：安装与虚拟环境](#p1--pip-install-pdf2zh-installs-the-wrong-backend)
- [P5–P8：Windows 环境与模型配置](#p5--setx--registry-env-persistence-is-blocked)
- [P9–P11：质量门和首次运行](#p9--a-partial-delivery-gate-is-expected-for-trimmedsample-inputs)
- [P12–P13：Windows 文本解码和 CJK 文本层](#p12--bundled-portablegit-pdftotext-emits-gbk-bytes--texttrue-crash--false-zero-cjk)
- [P14：双语 PDF 布局与同步](#p14--bilingual-pdf-layout-and-content-sync)
- [P15：扫描版 PDF](#p15--scanned--image-only-pdfs-silently-degrade-detect-before-running)
- [P16–P17：venv 静默失败 & MSYS 路径（本次安装实测新增）](#p16--python--m-venv-在托管-python-上是静默-no-op)
- [P18：双语 PDF 左右版式反向（backend_native 捷径踩 babeldoc 默认方向）](#p18--双语-pdf-左右版式反向backend_native-捷径踩-babeldoc-默认方向)
- [P19：Git-Bash `/d/...` 输入/输出路径未规范化 → Windows Python 解析成盘符重复路径](#p19--git-bash-d输入--output-dir-路径未规范化--windows-python-解析成盘符重复路径)

---

## P1 — `pip install pdf2zh` installs the WRONG backend

- **Symptom**: The backend appears "installed" and preflight may even pass, but the real run dies with:
  `pdf2zh: error: unrecognized arguments: --output ... --openai-model ...`
- **Root cause**: PyPI has an unrelated/older project literally named `pdf2zh` (≈1.7.9). Its CLI only accepts `--service` / `--lang-out` / `--thread` and does **not** understand the `--output` / `--openai-*` flags this skill passes. This skill actually needs the **`pdf2zh_next`** package (≈2.9.0), which provides both the `pdf2zh_next.main` module (used by `scripts/pdf2zh_backend.py`) **and** a `pdf2zh` CLI that carries the matching `--output` / `--openai-model` flags.
- **Fix**: `pip install pdf2zh_next`（可同时安装 `pymupdf reportlab` 以启用完整 QA 和双语重建）。不要安装 `pdf2zh`。
- **Bites at**: install time, only surfaces at the first real translation run.

## P2 — managed-Python safety policy can block `pip install`

- **Symptom**: `pip install` either (a) aborts partway with a bulk-delete confirmation error, or (b) hangs for minutes doing nothing; afterwards the venv's `pdf2zh.exe` launcher is **missing** even though `import pdf2zh_next` works → real run fails with `系统找不到指定的文件` / `file not found`.
- **Root cause**: The WorkBuddy managed Python injects a `sitecustomize.py` (loaded when `CODEBUDDY_SESSION_ID` / `CLAUDE_SESSION_ID` is set and `PYTHONPATH` points at the shim dir). It patches `os.remove` / `shutil` with a **bulk-delete guard**. This environment has no Recycle Bin, so the guard either trips (>50 deletes → abort before the `.exe` launcher is written) or routes every delete through a non-existent trash → hang.
- **Fix**: 不要由 skill 关闭宿主安全策略。改用用户控制的标准 Python 与专用新 venv，或请宿主管理员提供批准的安装路径；失败时保留原环境并停止。
- **Bites at**: every `pip install` / `python -m venv` in the managed-Python env.

## P3 — never `rm -rf` an existing venv

- **Symptom**: `rm -rf <venv>` hangs indefinitely (non-interactive bulk-delete confirmation never resolves).
- **Root cause**: The bash safe-delete wrapper (the `rm` itself) stalls on bulk-delete confirmation when there is no interactive prompt.
- **Fix**: do **not** delete the old venv. To rebuild, create a *fresh* path instead (e.g. `default`, or `$VENV.installing.<ts>` then `mv` into place). See `scripts/setup_venv.sh` for the rename-into-place pattern.
- **Bites at**: any attempt to "start clean" by removing a venv.

## P4 — killing `pip` leaves invalid `~` dists that silently stall the next install

- **Symptom**: A later `pip install` shows no output and never finishes (appears hung on dependency resolution).
- **Root cause**: Interrupting `pip` (e.g. on a timeout) leaves partial `~radio` / `~ymupdf` directories in `site-packages`. pip sees those invalid dists and stalls.
- **Fix**: before retrying, remove the leftover `~*` entries in the target `site-packages`; wheels are already cached, so a clean retry is fast. Best: don't kill pip — `block`-wait for it. `scripts/setup_venv.sh` cleans `~*` after install as a safety net.
- **Bites at**: after any aborted/killed install.

## P5 — `setx` / registry env persistence is blocked

- **Symptom**: `setx VAR value` and `reg add ...` fail (security policy forbids persisting user env vars).
- **Root cause**: The sandbox blocks writing to the user environment / registry.
- **Fix**: export the API key、model、`base_url` and backend path in the current session, then invoke `run_translate.sh`. The shared launcher only reads environment variables and must never contain a plaintext key.
- **Bites at**: any "make the config survive sessions" attempt via `setx`.

## P6 — MSYS path mangling in the bash launcher

- **Symptom**: A path like `D:/WorkBuddySpace/...` gets rewritten to `D:/d/WorkBuddySpace/...` inside `$(cd ... && pwd)`, breaking the skill dir resolution.
- **Root cause**: Git Bash auto-converts some MSYS paths unpredictably.
- **Fix**: on Git Bash use `pwd -W` to return a native Windows path; on macOS/Linux fall back to `pwd -P`. `run_translate.sh` performs this selection automatically and does not hardcode a user path.
- **Bites at**: launcher path resolution under Git Bash.

## P7 — model name is never validated (can 404 only at real API call)

- **Symptom**: preflight reports endpoint `ok` (HTTP 200), but the real translation returns 404 / auth errors for the model.
- **Root cause**: 不同厂商和兼容端点支持的模型名不同；只检查端点连通性不能证明模型存在。
- **Fix**: 模型必须通过 `--model` 或 `LOCAL_TRANSLATION_MODEL` 明确提供。配置后用 `scripts/setup_venv.sh --verify-model` 或最小 Chat Completions 请求验证模型名。
- **Bites at**: first real API call, after a green preflight.

## P8 — `preflight` passing ≠ the real run succeeding

- **Symptom**: a standalone `python scripts/preflight_runtime.py --strict` returns `ok: true`, but `run_pdf_translation.py` then fails.
- **Root cause**: Two gaps — (a) wrong `pdf2zh` package (P1) passes the module check yet breaks at runtime; (b) the safe-delete shim (P2) can remove launchers *after* a green preflight, so the backend binary is gone by run time.
- **Fix**: after fixing the backend, re-run preflight **through the same launcher/env used for the real run** (e.g. `bash run_translate.sh <pdf> --preflight-only`), not a separate ad-hoc invocation.
- **Bites at**: the moment you trust an isolated preflight.

## P9 — a `partial` delivery gate is EXPECTED for trimmed/sample inputs

- **Symptom**: quality report shows `decision: partial` with `coverage` / `sample-boundary` warnings and a 17-item terminology "待确认" list.
- **Root cause**: when the input is a 2-page **trim** excerpt, the missing pages are the sample's own boundaries (not translation gaps), and the glossary is simply not pre-filled — those are `low`-severity suggestions, not errors.
- **Fix**: do not treat `partial` as a failure for sample inputs. To clear the coverage warning, re-run on the **full** PDF; to clear the glossary hints, pre-fill `references/glossary-template.tsv`. Core translation is still valid (check `english_residue_count` and `accuracy`).
- **Bites at**: interpreting the delivery gate on non-full inputs.

## P10 — 不要忽略文本子进程的 `UnicodeDecodeError`

- **现象**：日志中出现后台 reader thread 的 `UnicodeDecodeError`，随后帮助参数探测、CJK 计数或文本审计得到空结果。
- **根因**：Windows 工具可能按系统代码页输出，直接使用 `text=True` 会在 Python 默认编码与实际输出不一致时解码失败。
- **修复**：所有需要读取 stdout/stderr 的工具调用统一使用 `_subprocess_safe.run_text()`；若仍出现此异常，应视为遗漏的调用点并修复，不再把它当作可忽略噪声。
- **影响位置**：后端帮助探测、Poppler、Tesseract、LaTeX 与最终文本层审计。

---

## P11 — first preflight run after a fresh venv may time out the backend check

- **Symptom**: the very first `preflight_runtime.py` run right after (re)creating the venv reports `pdf2zh_backend` → `fail` with `returncode 124` (`timed_out: True`), even though `pdf2zh.exe --help` works instantly when called directly.
- **Root cause**: the freshly installed `pdf2zh.exe` console launcher does a one-time warmup on first invocation (archive/dep extraction or asset cache), which can exceed the preflight's `command_timeout` that first time only.
- **Fix**: simply **re-run** the preflight (ideally through the launcher, e.g. `bash run_translate.sh <pdf> --preflight-only`). The second run is cached and passes. Not a real backend fault.
- **Bites at**: the first preflight immediately after `setup_venv.sh` / a venv rebuild.

---

## P12 — bundled PortableGit `pdftotext` emits GBK bytes → `text=True` crash / false-zero CJK

- **Symptom**: any run that calls `pdftotext` (the binary resolved from `.../mingw64/bin/pdftotext.EXE` inside WorkBuddy's bundled PortableGit) either (a) **crashes** with `AttributeError: 'NoneType' object has no attribute 'strip'` during source discovery / QA, or (b) **silently** reports `cjk_char_count = 0` ("译文 PDF 缺少中文可复制文本") even though the PDF clearly contains correct Chinese.
- **Root cause**: that mingw `pdftotext` writes its output in the **system code page (GBK on this host)** instead of UTF-8. With `subprocess.run(..., text=True)`, Python's reader thread fails to decode the bytes as UTF-8 (observed bad byte `0xb7` = GBK middle-dot `·`), the decode throws inside the background thread, and `CompletedProcess.stdout` ends up **`None`**. The next line's `result.stdout.strip()` then raises the AttributeError and aborts the whole run. (When the same binary is used for *validation* text extraction, the decode failure yields an empty/garbled string → CJK count 0.)
- **Fix (crash)**: 所有捕获文本的外部命令统一使用 `scripts/_subprocess_safe.py::run_text()`，按 `UTF-8 → 系统首选编码 → GB18030 → Latin-1` 解码，并保证 `.stdout` / `.stderr` 始终是字符串。
- **Second-order fix (P13)**: `extract_pdf_text()` 优先选择真正包含 CJK 字符的抽取结果，避免 Poppler 的固定加权覆盖 PyMuPDF 的正确中文文本层。
- **Bites at**: every PDF run — source discovery (`extract_pdf_frontmatter_text`), LaTeX-source prep (`try_pdftotext`), poppler bbox QA (`extract_bbox_lines`), preflight (`pdftotext -v`), and the final `text_layer` delivery gate. This is the #1 reason a fresh environment "runs but produces blocking/empty output" for Chinese PDFs.

## P13 — `text_layer` delivery gate false-positives on pdf2zh-next Chinese renders

- **Symptom**: `delivery_gate_status = partial` with `worst_gate = "blocking"` and the message "译文 PDF 缺少中文可复制文本 / 未检测到 CJK 字符", **even though the translated PDF visibly contains correct Chinese**.
- **Root cause**: the gate's `cjk_char_count` is computed from `extract_pdf_text()`, which (before P12's second-order fix) voted `pdftotext` to win. On certain pdf2zh-next outputs, Poppler's `pdftotext` reads the text layer as English/empty while **PyMuPDF reads the Chinese correctly** — so the gate wrongly concluded "no Chinese text layer". (Quick verify: `doc[i].get_text("text")` via PyMuPDF returns the Chinese; `pdftotext` returns English/garbage.)
- **Fix**: see the P12 second-order fix — `extract_pdf_text()` now prefers any CJK-containing extractor. After the fix, `validation.cjk_char_count` is correct (e.g. 1360 for the AI Index report, 1920 for LaTeXTrans) and the `text_layer` gate passes; the remaining `partial/blocking` gates are genuine content issues (terminology / protected-span / visible-residue), not the text-layer false alarm.
- **Bites at**: delivery-gate review of any pdf2zh-next render where the Chinese is drawn via a text layer Poppler can't decode.

---

## P14 — bilingual PDF layout and content sync

- **Symptom**: 双语 PDF 的左右顺序不符合当前标准，或中文单语件经过目录/元数据/残留修复后，双语件仍包含修复前页面。
- **Root cause**: 后端原生双语件生成早于本 skill 的确定性后处理；直接复用时无法自动带入最终中文单语件的修复。
- **Fix**: 默认标准改为“中文左、英文右”。未发生中文后处理时直接复用后端双语件；发生后处理时用 PyMuPDF 和最终中文单语件重建。PyMuPDF 缺失时保留后端件，但 manifest 标记 `partial`、`content_sync=backend_snapshot`。旧的 `pypdf-vector` 参数只作为映射到 PyMuPDF `vector` 的兼容别名。
- **Bites at**: 所有启用双语输出且中文单语件被后处理的运行。
- **Quick verify**: 检查 `bilingual_pdf_manifest.json` 的 `layout`、`source`、`content_sync` 和 `layout_verification`。

---

## P15 — scanned / image-only PDFs silently degrade (detect BEFORE running)

- **Symptom**: a scanned or image-only PDF is passed in; translation either fails outright (no extractable text → backend reports empty source) or produces a poor result (OCR-less renders keep English, or the QA `text_layer`/coverage gates go `blocking`). The user only discovers it after a long run.
- **Root cause**: this skill targets **non-scanned** PDFs. Scanned pages carry images but no text layer, so the backend and the PyMuPDF/Poppler extractors find little or no text to translate. The backend also historically ran with `--skip-scanned-detection`, so it would not even warn.
- **Fix / prevention**: (1) `SKILL.md` now opens with a WARNING: "本 skill 只针对非扫描版 PDF；对于扫描版可能翻译失败或效果较差，请谨慎使用。" (2) `run_translate.sh` runs a **pre-translation scanned check** (PyMuPDF): it counts image-only pages and computes text density; if ≥50% of pages are image-only **or** density < 50 chars/page, it prints that same Chinese warning to the user **before** invoking the backend. Warning only — it does not hard-block, because mixed PDFs may still translate fine. (3) the scanned check lives in the launcher so the user sees it early, while `preflight_runtime.py` stays focused on deps/endpoint.
- **Bites at**: any run whose input is a scanned paper, a fax, or slides exported as images.
- **Quick verify**: feed a known scanned file → launcher prints the `⚠️ WARNING: 输入 PDF 疑似扫描版 / 图像版 …` line and then continues.

---

## P16 — `python -m venv` is a silent no-op on WorkBuddy managed Python

- **现象**：在本机托管 Python（3.13.12）上执行 `python -m venv <path>`，命令 **退出码为 0，但目标目录为空**（连 `pyvenv.cfg`、`Scripts/python.exe` 都没有）。后续 `Scripts/python.exe` 找不到，安装脚本随即失败。
- **根因**：托管 Python 的 `venv/__main__.py`（CLI 入口）被包装过，会吞掉真实异常；直接调用 `venv.EnvBuilder(with_pip=True).create(path)` 则正常工作。
- **修复**：
  1. **优先复用已存在的 venv**：如果目标 venv（如 `default`）里已经有可用的 `python.exe`，直接往里 `pip install`，**不要重建**。这既能绕过该 bug，又能避免覆盖托管 Python `default` venv 里其它共享包（gradio/pandas/pydantic 等）。
  2. **确需新建时，用 builder 而非 CLI**：`"$MP" -c "import venv,sys; venv.EnvBuilder(with_pip=True, clear=True).create(sys.argv[1])" "$TMPV"`。
  3. `scripts/setup_venv.sh` 已按上述逻辑改写（先判断复用、再 builder 创建、绝不 `rm -rf` 旧 venv，见 P3）。
- **影响位置**：任何依赖 `python -m venv` 初始化环境的安装步骤；`setup_venv.sh` 的旧实现首行就踩了这个坑（最终报 `pdf2zh.exe` 找不到 / preflight `pdf2zh_backend` 127）。

## P17 — Git-Bash MSYS 路径（`/c/...`）无法被 Windows subprocess 解析 → WinError 2

- **现象**：在 Git Bash 下把 `PAPER_TRANSLATION_PDF2ZH_BINARY` 设成 `/c/Users/.../pdf2zh.exe`（或直接用 `run_translate.sh` 由 `$HOME` 拼出的 `/c/...` 路径），preflight / 实际运行调用后端时报 `FileNotFoundError: [WinError 2] 系统找不到指定的文件`。但 `import pdf2zh_next` 正常，因为模块后端走的是 `runpy`，不经过这个路径。
- **根因**：Windows 的 `subprocess` 用 Windows 路径规则解析可执行文件，Git-Bash 风格的 MSYS 路径（`/c/Users/...`）不是合法 Windows 路径，解析失败。注意 `bash` 自己执行 `/c/.../python.exe` 能跑（Git Bash 在 **exec 时** 做了转换），但 **Python 内部的 `subprocess` 不会再被转换**。
- **修复**：
  1. **所有要传给 Windows 子进程的可执行路径，必须转成原生 `C:\...`**。Git Bash 下用 `cygpath -w` 转换最稳：`PDF2ZH_BIN="$(cygpath -w "$PDF2ZH_BIN")"`。
  2. `run_translate.sh` 现在在导出 `PAPER_TRANSLATION_PDF2ZH_BINARY` 前，会判断 `MSYSTEM`（MINGW/MSYS/CYGWIN）并用 `cygpath -w` 把默认 / 用户覆盖的二进制路径规范化为原生 Windows 路径；后端存在性检查也会先尝试 `cygpath` 转换，避免误报“找不到”。
  3. 手动指定时请用 `C:\Users\<username>\.workbuddy\binaries\python\envs\default\Scripts\pdf2zh.exe` 这种原生路径，不要用 `/c/...`。
- **影响位置**：后端二进制解析（`pdf2zh_backend.py` 的 binary 模式、preflight 的 `pdf2zh_backend` 检查、任何显式传 `--pdf2zh-binary /c/...` 的地方）。模块后端（`pdf2zh_next.main` via runpy）不受影响，因此该坑主要表现为“偶发找不到后端”，容易被忽略。

---

## P18 — 双语 PDF 左右版式反向：`backend_native` 捷径踩中 BabelDOC 默认方向

- **现象**：skill 默认双语版式是“中文在左、英文在右”（`--bilingual-layout zh-left-en-right`），但部分走 `backend_native` 捷径的文件会产出“英文在左、中文在右”的双语 PDF。
- **根因**：BabelDOC 的 `--dual` 默认把原文放左侧、译文放右侧。`build_standard_bilingual_output` 在单语 PDF 未发生后处理时会直接采用后端 dual PDF，却把 manifest 标记为 `zh_left_en_right`，造成标签与实际内容不一致；其它经 PyMuPDF 重建的路径则会遵循显式布局。
- **修复**：`build_pdf2zh_command` 在布局为 `zh-left-en-right` 且后端帮助文本确认支持时，为 `--dual` 补充 `--dual-translate-first`。`en-left-zh-right` 和 `backend-default` 保持后端默认方向。
- **验证**：Windows 实测重跑后，左半页为中文、右半页为英文；同时新增命令构建回归测试，覆盖三种布局及后端不支持该参数时的降级。
- **影响位置**：`build_pdf2zh_command` 与采用后端原生 dual PDF 的 `backend_native` 分支。

---

## P19 — Git-Bash `/d/...` 输入/输出路径未规范化 → Windows Python 解析成盘符重复路径

- **现象**：在 Git Bash 下把输入 PDF 或 `--output-dir` 写成 MSYS 风格路径（如 `/d/WorkBuddySpace/.../x.pdf`、`--output-dir /d/WorkBuddySpace/.../out`），产物可能写入错误的 `D:\d\WorkBuddySpace\...`，后续读取 JSON 清单时报 `FileNotFoundError`。
- **根因**：只要把 MSYS 风格路径直接交给 Windows Python，输入 PDF、输出目录和其它路径参数都可能被当作当前盘根下的相对路径。旧启动器只规范化后端二进制，没有处理用户参数。
- **修复**：`run_translate.sh` 在执行 Python 前遍历参数，用 `normalize_path()` 将输入 PDF、`--output-dir`、`--pdf2zh-binary`、`--source-override`/`--latex-source`、`--latex-source-root`、`--latex-baseline-pdf` 和 `--engine-home` 转为原生 Windows 路径，同时兼容 `--flag value` 与 `--flag=value`。macOS/Linux 下保持原样。
- **验证**：使用 `--preflight-only` 和 MSYS 风格输入/输出路径实测通过；新增离线回归测试验证多种路径参数的改写结果。
- **影响位置**：Git Bash / MSYS 下经 `run_translate.sh` 传入 Windows Python 的全部路径类参数。

---

## Quick reference

| ID | One-line | Where fixed in this skill |
| --- | --- | --- |
| P1 | wrong PyPI `pdf2zh` package | `setup_venv.sh`, `runtime-dependencies.md`, `workflow.md` WARNING |
| P2 | managed safety policy blocks pip | use an approved standard Python and dedicated venv |
| P3 | don't `rm -rf` venv | `setup_venv.sh` rename-into-place |
| P4 | `~` leftover dists stall next install | inspect and clean the dedicated venv manually |
| P5 | `setx` blocked → use per-session env | `run_translate.sh` reads env without storing secrets |
| P6 | MSYS path mangling | `pwd -W` in launchers |
| P7 | model name unverified | 显式 `--model` + `setup_venv.sh --verify-model` |
| P8 | preflight ≠ real run | re-run preflight via the launcher |
| P9 | `partial` expected for samples | interpretation note (this doc) |
| P10 | 文本子进程解码异常不可忽略 | `_subprocess_safe.run_text()` |
| P11 | first-run preflight backend check may time out (exe warmup) | re-run preflight (this doc) |
| P12 | PortableGit `pdftotext` emits GBK → `text=True` crash / 0 CJK | `scripts/_subprocess_safe.py::run_text` + `extract_pdf_text` CJK-prefer vote |
| P13 | `text_layer` gate false-positives on pdf2zh-next Chinese renders | same P12 second-order fix (prefer CJK extractor) |
| P14 | bilingual layout or repaired-content mismatch | backend-native default + PyMuPDF post-repair rebuild |
| P15 | scanned / image-only PDF silently degrades | `SKILL.md` WARNING + `run_translate.sh` pre-run scanned check (warn before backend) |
| P16 | `python -m venv` silent no-op on managed Python | `setup_venv.sh` reuses existing venv / uses `venv.EnvBuilder` (not the CLI) |
| P17 | Git-Bash `/c/...` path → WinError 2 in Windows subprocess | `run_translate.sh` normalizes backend binary path via `cygpath -w` to native `C:\...` |
| P18 | 双语 PDF 左右版式反向（backend_native 踩 BabelDOC 默认方向） | `build_pdf2zh_command` 在 zh-left-en-right 下补 `--dual-translate-first` |
| P19 | Git-Bash `/d/...` 输入/输出路径 → 盘符重复 `D:\d\...` | `run_translate.sh` 重写所有路径参数为 `cygpath -w` 原生路径 |
