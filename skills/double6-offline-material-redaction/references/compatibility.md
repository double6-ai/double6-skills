# 旧 Office、RTF 与 OpenDocument

ODT/ODS/ODP直接读取XML、按支持的可见内容重建，无需安装Office。DOC/XLS/PPT及RTF先用本机LibreOffice转换成ODF，随后走同一重建；转换文件不能直接作为脱敏结果。

这四种输入需要额外依赖，主工具使用安装脚本创建的Python环境。不要把“材料处理可离线”写成“旧格式不需安装任何软件”。

## macOS Apple芯片

使用[LibreOffice官方安装包](https://www.libreoffice.org/download/download-libreoffice/)，按系统正常方式安装到`/Applications/LibreOffice.app`。遇系统拦截先报告，不移除隔离属性或关闭安全检查。其它位置通过当前进程的`REDACTION_LIBREOFFICE`明确指定完整`soffice`路径。

工具为每次转换创建私有profile，禁用文档宏、OLE/DDE等活动内容及链接更新，使用系统沙盒阻断外连、允许本机回环IPC。源文件仅写入私有临时目录，完成或正常失败后删除；进程崩溃可能留下系统临时文件，按本轮临时目录定位，不能笼统清理用户临时目录。

## Windows x64

从上述官方下载页取得Windows x64 MSI，核对官方SHA256及有效签名。采用应用专用目录，不给用户现有Office加防火墙规则、不更改文件关联。

管理员PowerShell可对MSI做管理提取（`/a`，不注册为默认Office）。`TARGETDIR`使用一个新目录，例如`$env:LOCALAPPDATA\Double6\LibreOffice`；Windows Installer的提取完成后，应存在`program\soffice.exe`及`program\soffice.bin`。不要覆盖已有不同版本目录。

```powershell
$msi = 'C:\absolute\LibreOffice_Win_x86-64.msi'
$dest = Join-Path $env:LOCALAPPDATA 'Double6\LibreOffice'
# 先核对目录不存在、签名及官方校验值，再执行；日志保存到本次安装目录外。
Start-Process msiexec.exe -ArgumentList @('/a',('"'+$msi+'"'),'/qn',('TARGETDIR="'+$dest+'"')) -Wait
# 确认实际提取出的两个程序存在，再配置这份专用引擎。
& 'C:\absolute\double6-offline-material-redaction\scripts\configure-compat-windows.ps1' -Converter (Join-Path $dest 'program\soffice.exe')
```

配置脚本只为这份引擎建立两条出站阻断规则，并设置用户级`REDACTION_LIBREOFFICE`。防火墙任一配置文件未启用时停止；不自动打开全局防火墙或提升权限。处理前工具再次检查两条程序规则，未满足则拒绝旧二进制/RTF导入。此隔离只限制网络，不是恶意文件的完整操作系统沙盒；仅处理有权使用、来源可信的材料。

重新开终端后执行`PYTHON scripts/cli.py doctor`（仅检测路径与启动器身份，不启动Office），再用合成旧格式做`inspect`及一次导出/复检。卸载这份专用引擎时，可明确删除`Double6-Redaction-Compat-Launcher`与`Double6-Redaction-Compat-Engine`两条规则并清除该用户变量；不删除别的规则或Office。

## 业务内容核对

输入DOC/RTF/ODT输出DOCX；XLS/ODS输出XLSX；ODP输出PPTX。旧PPT为避免转换丢失图片/表格，保留页面外观后逐页人工框选，输出纯图像PDF。文字不可再编辑或搜索。对应计划使用`word`、`excel`、`slides`；旧PPT使用`pdf`及逐页矩形计划，`verify`针对实际现代格式副本。检查完整预览中的关键句、数值、时间、表头及表内关系，再补选。转换可能影响公式计算结果；格式化数值按源显示缓存保留为普通文字，普通数值尽量保持数值；这不保留原计算能力。条件显示、缺少显示缓存或可见性不确定时停止。金额、日期等关键内容请逐项对照原件，使用`keep`记录保留项。

ODF隐藏文字、隐藏表/行/列、隐藏幻灯片、批注、备注及修订历史不带入。正文以外的属性、原容器、嵌入文件和原链接目标不复制；文中直接写出的URL仍是正文，需人工补选。条件隐藏、复杂条件内容样式、多母版或首页/奇偶页眉、嵌套表格、加密ODF、宏或嵌入对象的ODF、无缓存公式及无法保留整页内容等会停止。图片/图表/布局及交互无法保留；关键业务依赖这些对象时改用PDF/图片人工框选路线，不能接受丢失后仍声称材料可用。
