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

1. 生成五个内置用例（每个都有预期结果，结果与预期不符即判失败）：
   - `en_qbr`：英文季度汇报，正文 7 条要点，加安全余量后约为可用高度的 1.87 倍。**预期：被计划检查拦截**（`blocked_by_check`）。这么长的内容应该改写，而不是缩字。
   - `en_qbr_shrink`：同一模板，正文保留前 5 条。**预期：applied**，正文显式缩小到约 27/24pt。
   - `zh_factory`：中文汇报，正文 5 段，下方有三张卡片。**预期：被计划检查拦截**，正文的可用高度截止到卡片顶边（268pt），需要约 1.74 倍高度，超过 1.6 倍门槛。
   - `zh_factory_shrink`：同一模板，正文保留前 3 段。**预期：applied**。标题缩到约 32pt（一行），正文约 30/26pt，并且停在卡片上方。
   - `en_overfull`：正文内容翻倍。**预期：被计划检查拦截**。
2. 运行 `check_plan` 和 `apply_plan`（vendored PPT Master v6.7.0）。
3. 在 PowerPoint 中打开每个输出文件：
   - Windows（COM）：对设置了「溢出时缩小文字」的文本框，先关闭再打开自动调整，强制 PowerPoint 用自己的引擎重算；然后测量每个文本框的实际文本高度（BoundHeight），导出每页 PNG 和 PDF，并另存一份 PowerPoint 重新保存的 pptx。
   - macOS（AppleScript，尽力而为）：测量文本高度，导出 PDF，另存 pptx。
4. 比对。出现以下任一情况，该文本框判为 **FAIL**：
   - PowerPoint 中溢出超过 2pt（打开时或强制重算后，任一时刻）；
   - PowerPoint 重算后字号发生变化，或重新保存时写入的 fontScale 不等于 1.0（说明 PowerPoint 认为还要再缩，我们的估算偏乐观）；
   - 文字实际范围（BoundTop/BoundHeight）压到同页其他形状上（铺满整页的背景除外）。
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

- 「总判定」应为 `passed`。溢出、压到其他形状、字号/fontScale 不一致这三项都应为 0。
- 每个用例都应「符合」预期；如果是 `error`，报告里附有错误信息和调用栈。
- 脚本退出码：0 表示全部通过，1 表示有失败。

## 为什么不再依赖 normAutofit fontScale（0.4.0-exp.3）

2026-10-15 在 Win11 + PowerPoint 16 上实测：PowerPoint 不会稳定应用文件里保存的 `normAutofit fontScale`。强制重算后保存值回到 100%，结果 3 个文本框溢出（最多溢出 202.8pt）。

现在的做法：
- 缩字直接写进每个 run 的 `sz`，`normAutofit` 不再带 fontScale，只作为 PowerPoint 自己的兜底；
- 缩字有下限：比例不低于 0.7，标题不小于 20pt，正文不小于 12pt；
- 多段文字在原字号下超过可用高度的 1.6 倍（相当于要缩到约 0.8 以下），或者到了下限仍放不下，计划检查一律报 ERROR；
- 度量引擎按 PowerPoint 实测重新校准：单倍行距取 1.2 倍字号，spcBef 不计第一段，按层级读取字号（例如 32/28pt）和缩进；另加保守余量（高度 ×1.06，换行宽度 ×0.97）。按这个模型，11 个实测文本框的估算高度与 PowerPoint 的 BoundHeight 误差都在 0.1pt 以内；
- 文本框下方有其他形状（卡片、指标框）时，可用高度截止到该形状的顶边。

实测数据和样例文件放在 `scripts/tests/fixtures/powerpoint_win11/`，回归测试是 `test_powerpoint_calibration.py`。
