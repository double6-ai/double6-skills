# 安装与故障处理

完整安装`double6-offline-material-redaction`目录。公开包包含源码、指引和依赖哈希清单，需要Python3.12；不包含预编译EXE、App或Python运行时。Python可从[官方网站](https://www.python.org/downloads/)取得，按系统正常方式安装，不关闭安全检查。

从Skill目录新建独立环境：

```bash
# macOS Apple芯片
python3.12 scripts/bootstrap.py --venv /absolute/new/redaction-venv
```

```powershell
# Windows x64
py -3.12 scripts/bootstrap.py --venv C:\absolute\new\redaction-venv
```

首次安装从PyPI下载已登记哈希的wheel；不执行源码构建。安装完成返回Python路径，下文称`PYTHON`。已准备依赖的离线电脑可以额外指定`--wheelhouse <本机wheel目录>`；此时不访问软件源。哈希校验检测依赖文件是否匹配清单，不能证明发布者身份或材料安全。

需要离线安装时，先在与目标电脑系统、架构相同且已安装Python3.12的联网电脑上，从Skill目录准备wheel目录，再把整个Skill及wheel目录一起复制过去：

```text
# PYTHON312 在Mac为python3.12，在Windows为py -3.12。
PYTHON312 -m pip download --require-hashes --only-binary=:all: --index-url https://pypi.org/simple -r requirements-runtime.lock --dest <新wheel目录>
PYTHON312 scripts/bootstrap.py --venv <新环境绝对路径> --wheelhouse <已复制的wheel目录>
```

Windows与Mac的原生wheel不能混用；离线电脑也须先正常安装对应Python3.12。准备下载会联网，指定wheelhouse的安装不访问软件源。

安装脚本运行pip check、doctor和selftest，成功后才记录安装完成。同版完整环境可重复核对；已有其它文件或未完成环境时改用新目录，不覆盖、不自动删除用户文件。

```text
PYTHON scripts/cli.py doctor
PYTHON scripts/cli.py selftest
PYTHON scripts/cli.py gui
```

`doctor`报告系统、Python、Web资源及兼容依赖路径；检测到LibreOffice路径不等于已验证转换。`selftest`只用自编材料测试主要适配器、实际PDF原生库、隐藏清理、内容保留和禁止覆盖，不启动旧格式转换器，也不保证任意材料可用。

服务启动后默认打开本机浏览器。独立自动化测试可用`gui --no-browser --session-file <新JSON路径>`取得本次地址；该文件不含材料。正常退出使用“结束工具并清空会话”，再次运行gui会创建新地址。

| 实际结果 | 处理 |
| --- | --- |
| Python版本或架构不支持 | 安装Python3.12并核对Windows x64/macOS Apple芯片；不要运行另一平台文件 |
| 无网络、无匹配wheel、哈希不符 | 保留具体错误，暂不处理材料；检查网络或正规离线wheel来源，不跳过哈希和TLS检查 |
| 目标目录已有其它内容 | 改用新目录，不覆盖或清空 |
| doctor正常但selftest失败 | 保存不含原文的错误，停止处理真实材料 |
| 旧格式缺依赖或隔离未配置 | 按[兼容导入](compatibility.md)完成准备；现代格式不要求Office |
| 工具拒绝复杂材料 | 按[格式边界](formats.md)核对，不静默换在线工具或强行转换 |

退出码0表示命令成功，2表示输入/计划/本地文件问题，3表示导出复检失败，4表示环境检查失败。成功仍需阅读JSON范围，未检查项不代表通过。

材料处理不需要网络；软件首次准备可能联网。普通格式在进程内处理，旧二进制/RTF转换使用私有临时文件，正常结束清理，异常退出可能残留。关闭标签页不结束工具，清空会话不删除已经下载的副本。
