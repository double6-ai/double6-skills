# 脚本入口

主入口为 `paper_translation_workflow.py`；从已安装skill目录使用新环境Python运行。输入、输出、回执、冻结与审校合同使用绝对路径。完整参数由 `python scripts/paper_translation_workflow.py <action> --help` 提供。

`runtime_paths.py` 分离安装目录和用户运行目录；`daily_skill_research/` 仅保留有界执行、失败回执和输出路径所需的四个共享模块，不需要安装原研究项目。

`scanned_raster/`、`cutover/`、PDF修复和QA组件沿用源项目；结果必须由主工作流及完整审校判定。可选实验工具不自动成为默认支持范围，详见 [SKILL](../SKILL.md) 和 [运行说明](../references/release-quickstart.md)。
