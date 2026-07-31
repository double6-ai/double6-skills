# double6-pdf-translation 变更记录

## 1.0.1

- arXiv 源码下载改为显式 opt-in，默认不访问 arXiv。
- Docker LaTeX 编译改为显式 opt-in，默认只检查本机编译器。
- 明确模型 endpoint 授权、输入文件只读、输出目录派生写入和外部代码路径信任边界。

## 1.0.0

- 首次面向 skills.sh 与 ClawHub 发布。
- 支持将非扫描版英文 PDF 翻译为简体中文，并生成中文单语与中英双语 PDF。
- 要求用户显式配置模型、API endpoint 和 credential，不携带默认模型或密钥。
- 增加 ClawHub 版本、主页、运行时与环境变量元数据。
