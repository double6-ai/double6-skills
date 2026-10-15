# PowerPoint 实机一键验证（Windows / macOS）

脚本位于 `scripts/verify/`，用于在装有 Microsoft PowerPoint 的电脑上验证 template-fill 的效果：文本是否真的放得下、PowerPoint 自己的「溢出时缩小文字」重算后是否一致、备注/切换/混合格式是否保留。脚本只写报告目录和独立的 Python 环境，不改动其他文件。

## 前提

- Python 3.11 或更高版本（Windows 可从 python.org 安装，勾选「Add to PATH」；macOS 用 `python3`）。
- 第一次运行需要联网，用来安装锁定的依赖（安装到独立 venv）：
  - Windows：`%LOCALAPPDATA%\double6-template-fill-verify\`
  - macOS：`~/Library/Caches/double6-template-fill-verify/`
- 已安装 Microsoft PowerPoint（Microsoft 365 / 2019 / 2021）。运行期间请关闭其他 PowerPoint 文件。macOS 首次运行时会弹出「允许终端控制 Microsoft PowerPoint」，请点「好」。

## 运行

- **Windows**：在资源管理器中打开 `skills/double6-ppt-cli/scripts/verify/`，双击 `verify_template_fill_windows.cmd`。
- **macOS**：在访达中双击 `verify_template_fill_macos.command`。如果提示无法打开，右键 →「打开」；也可以在终端执行：
  ```bash
  cd skills/double6-ppt-cli/scripts/verify && python3 verify_template_fill.py
  ```

运行大约 1–3 分钟，终端依次显示 `[1/4]`…`[4/4]`。

## 脚本做了什么

1. 生成两个内置用例：
   - `en_qbr`：英文季度汇报。包含多级要点（需要缩字）、混合格式指标、表格、图表、切换效果、重复页和备注。
   - `zh_factory`：中文汇报。包含中文长段落、三张卡片、备注和切换效果。
2. 运行 `check_plan` 和 `apply_plan`（vendored PPT Master v6.7.0）。
3. 在 PowerPoint 中打开每个输出文件：
   - Windows（COM）：对设置了「溢出时缩小文字」的文本框，先关闭再打开自动调整，强制 PowerPoint 用自己的引擎重算；然后测量每个文本框的实际文本高度（BoundHeight），导出每页 PNG 和 PDF，并另存一份 PowerPoint 重新保存的 pptx。
   - macOS（AppleScript，尽力而为）：测量文本高度，导出 PDF，另存 pptx。
4. 比对：
   - 我方估算（fits / autofit / shrunk 及 fontScale）与 PowerPoint 实测溢出量；
   - PowerPoint 重算后写回的 fontScale。
   最后生成报告。

## 结果

桌面上会生成：

- `double6-template-fill-verify-<电脑名>-<时间>/`：
  - `REPORT.md`（中文摘要）
  - `report.json`（完整数据）
  - `filled/`（填充结果）
  - `powerpoint/`（PowerPoint 导出的 PNG/PDF 和重新保存的 pptx）
- 同名 `.zip`：**请把这个 ZIP 文件发回**。

## 判读

- 「PowerPoint 中溢出（>2pt）的文本框」应为 0。
- 「fontScale 最大差」越小越好，≤0.1 视为一致。
- 用例状态应为 `applied`；如果是 `error`，报告里附有错误信息和调用栈。
