# 本地材料脱敏

准备把简历、作业、合同节选或表格交给在线AI之前，先在自己电脑上生成脱敏副本。用户补选敏感文字或区域，工具清理支持的隐藏内容，导出后核对业务信息是否保留。原文件不覆盖。

本Skill免费开源，提供源码和本地浏览器界面；不需要模型或API key。首次安装下载Python依赖，处理材料不调用在线服务。支持Windows11 x64与Apple芯片Mac、Python3.12。

## 安装与启动

先按仓库说明安装整个Skill目录。进入该目录：

```bash
# macOS
python3.12 scripts/bootstrap.py --venv /absolute/new/redaction-venv
/absolute/new/redaction-venv/bin/python scripts/cli.py gui
```

```powershell
# Windows
py -3.12 scripts/bootstrap.py --venv C:\absolute\new\redaction-venv
& 'C:\absolute\new\redaction-venv\Scripts\python.exe' scripts/cli.py gui
```

也可以告诉具备本地执行能力的Agent：

> 请用 $double6-offline-material-redaction 准备本机脱敏工具，检查安装和自检结果，然后打开界面让我补选。不要把真实材料内容发送到聊天。

安装会检查依赖、运行环境与合成材料自检。目录已有其它内容、依赖哈希不符或自检失败会停止；详细处理见[安装说明](references/install.md)。

## 能处理什么

图片、DOCX、文本/Markdown、CSV/TSV、PDF、XLSX/XLSM、PPTX及ODT/ODS/ODP有对应路线。DOC/XLS/PPT/RTF需要另外安装LibreOffice。输入和输出格式、版式变化及拒绝条件见[格式说明](references/formats.md)。

图片/PDF需要人工选全敏感区域，PDF需逐页查看。Word/PPTX的图片、图表及原设计无法完整保留，复杂表格显示也可能被拒绝。请填写关键保留内容，打开实际副本核对；自动复检不能保证找全敏感信息。

图形界面用“结束工具并清空会话”退出；关闭标签页不会结束工具。已下载副本和系统缓存不属于会话清理范围。

入口：[SKILL.md](SKILL.md) · [命令计划](references/commands.md) · [兼容依赖](references/compatibility.md) · [验证范围](references/validation.md) · [依赖许可](references/runtime-dependencies.md)
