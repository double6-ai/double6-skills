# 依赖与许可

Double6原创代码按本Skill目录的[MIT许可](../LICENSE)发布。这里不分发Python运行时、Office、第三方wheel、模型或API key；安装脚本下载依赖，材料处理阶段不调用在线服务。

`requirements-runtime.lock`锁定版本及Windows x64/macOS Apple芯片Python3.12所需wheel的SHA256。只允许二进制wheel，不自动退回源码编译，不跳过TLS或哈希检查。依赖适用各自随wheel附带的许可：

| 依赖 | 本版版本 | 用途与主要许可 |
| --- | --- | --- |
| Pillow | 12.3.0 | 图片读取/遮盖；MIT-CMU及其图像库子许可 |
| python-docx | 1.2.0 | Word重建；MIT |
| lxml | 6.1.3 | 文档XML；BSD及随附XML库许可 |
| typing_extensions | 4.16.0 | 类型兼容；PSF类许可 |
| openpyxl | 3.1.5 | Excel读取/重建；MIT |
| et_xmlfile | 2.0.0 | Excel XML写入；MIT |
| python-pptx | 1.0.2 | PPTX读取/重建；MIT |
| XlsxWriter | 3.3.0 | PPTX的表格依赖；BSD-2-Clause |
| pypdf | 6.21.2 | PDF结构；BSD-3-Clause |
| pypdfium2 | 5.14.0 | 本机PDF渲染；Apache-2.0/BSD及随附PDFium子许可 |

Python本身及其本机依赖由用户从正规Python分发取得，适用对应分发条款。LibreOffice只在DOC/XLS/PPT/RTF路径使用，由用户独立安装，适用其MPL/LGPL等许可；本Skill未修改或打包Office。每次兼容转换创建私有配置并禁用活动内容，Windows另外要求专用引擎的出站隔离规则；这不构成恶意文件的完整沙盒。

源码发布不需要申请本工具的Apple Developer ID或Windows代码签名证书。以后若另外提供预编译安装包，需要重新核对其签名、系统信任和二进制再分发许可，不能自动继承本源码包的发布结论。
