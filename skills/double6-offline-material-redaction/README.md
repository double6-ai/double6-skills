# 本地材料脱敏

在上传AI材料前，用本机工具生成脱敏副本。用户补选敏感文字或区域，工具清理支持的隐藏内容，再核对必须保留的业务内容。原件、计划和已有结果都不覆盖。

支持Windows x64、Apple芯片macOS，兼容Python3.10–3.14。新装推荐Python3.14；3.10仅兼容已有环境，3.15未验证。优先复用已有兼容Python；首次安装按哈希清单下载依赖，材料处理可以离线完成。原格式无法安全导出时停止，转换须明确选择。

## 让Agent准备工具

> 请使用 $double6-offline-material-redaction 安装并检查本机环境，自动跑正例与反例，全部通过后给我双击启动文件和本机离线指令。真实材料和补选原文不要发到聊天。

安装整个Skill目录，进入目录后运行：

```bash
# macOS：复用已有兼容Python，也可直接用对应Python执行bootstrap.py
sh scripts/setup-macos.sh --venv /absolute/new/redaction-venv
```

```powershell
# Windows：在本次进程内正常执行已审阅脚本，不改系统执行策略
powershell -NoProfile -File scripts/setup-windows.ps1 -Venv C:\absolute\new\redaction-venv
```

缺少Python时先按[安装说明](references/install.md)从正规来源安装。脚本不替换系统Python。安装依赖、自检或正反例失败时不会生成“可用”状态。

## 以后离线使用

安装成功返回验收报告、`Start-Redaction.command`或`Start-Redaction.cmd`及本机使用说明。双击启动文件，工具会打开系统浏览器中的本地HTML页面。选择文件、补选、填写业务保留项、导出并复检，最后打开实际副本核对。也可以复制安装返回的完整离线命令运行。

界面与处理服务都在本机，不需要在线Agent、模型或API。HTML页面由本机Python服务提供，不能只双击源码中的index.html。退出请点击“结束工具并清空会话”；关闭标签页不结束服务，已下载副本仍保留。

## 格式和许可

图片保持PNG/JPEG/WebP原编码；Word、文本、表格、PPT及ODF按支持范围生成同格式新副本。PDF默认原生删除选定内容，保留框外文字与页面；整页图像化必须明确选择。旧DOC/XLS/PPT/RTF暂不能安全原格式导出，需要用户明确选择转换路线，另需LibreOffice。

同格式不代表版式无损：Word/PPT/ODF仍会重建支持的文字与表格，图片和复杂设计可能丢失；JPEG会重编码。缺少必要业务内容、存在不支持的隐藏结构或复检失败时停止。详情见[格式说明](references/formats.md)。

原创源码MIT；PDF原生引擎PyMuPDF/MuPDF适用AGPL-3.0，MIT声明不覆盖该依赖。分发组合运行环境或对外提供服务时须遵守对应许可，详见[依赖说明](references/runtime-dependencies.md)。

入口：[SKILL.md](SKILL.md) · [安装与离线使用](references/install.md) · [命令](references/commands.md) · [验证范围](references/validation.md)
