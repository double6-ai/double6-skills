# 安装、验收与离线启动

支持Windows x64、Apple芯片macOS，Python3.10–3.14。安装完整Skill目录。优先复用已有兼容解释器；新装从[Python官网](https://www.python.org/downloads/)取得仍受维护的较新兼容版本，按正常方式安装。Python3.10兼容用于已有环境，其[官方维护期限](https://devguide.python.org/versions/)与工具功能兼容分别判断。

## 安装

从Skill目录执行：

```bash
# macOS自动选择已有兼容版本
sh scripts/setup-macos.sh --venv /absolute/new/redaction-venv
# 或明确使用已有解释器
python3.10 scripts/bootstrap.py --venv /absolute/new/redaction-venv
```

```powershell
# Windows已有py启动器或python命令
powershell -NoProfile -File scripts/setup-windows.ps1 -Venv C:\absolute\new\redaction-venv
# 或明确使用已有解释器
py -3.10 scripts/bootstrap.py --venv C:\absolute\new\redaction-venv
```

系统策略拦截脚本时，使用已获准Python直接执行bootstrap，不更改机器/用户执行策略。目录已有其它内容、旧版/不同Python环境或未完成安装时改用新目录，保留现场。

安装会创建独立venv，用`--require-hashes --only-binary=:all:`从PyPI取得固定版本wheel，不自动源码编译。完成pip check、环境诊断、适配器自检和合成正反例验收后，才创建安装完成回执与本次启动入口。解释器的小版本和架构写入回执；不同版本不共用同一venv。

## 自动验收与交付

基础安装自动执行23个正例、26个反例，包括同格式图片/Word/表格/PPT/ODF、PDF文字保留、显式转换，以及禁止覆盖、保留项缺失、越界框选、伪装扩展名、旧格式未经授权转换、PDF加密/不可见文字/遮盖后仍可恢复文字等拒绝场景。反例必须按预期拒绝，意外崩溃不能算通过。

输出`acceptance.json`列出每例结果、实际系统/架构/Python版本及未测试范围。旧Office兼容引擎的执行、真实材料补选完整性和可见桌面操作不列为基础验收通过。

成功后Agent交付本次`checks/<本次编号>/launchers/`中的双击文件、`离线使用说明.md`和完整离线命令。重复核对生成新的报告/入口目录，不覆盖用户改过的文件。

## 离线准备与使用

在与目标电脑系统/架构相同的联网电脑、对应Python版本下，从Skill目录准备依赖：

```text
PYTHON -m pip download --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r requirements-runtime.lock --dest <新wheel目录>
PYTHON scripts/bootstrap.py --venv <新环境绝对路径> --wheelhouse <wheel目录>
```

将完整Skill、wheel和正常Python安装带到离线电脑。不同小版本的原生wheel可能不同，不要把一台电脑的wheel当作覆盖全部平台/版本。`--wheelhouse`使用`--no-index`安装，不访问软件源；仍执行全部验收。

以后断网双击安装返回的启动文件，或运行返回的完整命令。Python和Skill源码目录需保留原位置；移动后重新安装到新环境，勿手改旧回执冒充验证。HTML由本机Python服务提供，直接双击scripts/web/index.html不会处理文档。

## 故障

无Python或版本/架构不支持时停止并引导正常安装；无匹配wheel、TLS/哈希失败时保留错误，不跳过校验。验收失败保留目录，未生成完成回执和启动入口。doctor检测到LibreOffice路径不等于转换已测试，另按兼容指引验证。正常退出请用页面“结束工具并清空会话”，已下载副本和系统缓存由用户管理。
