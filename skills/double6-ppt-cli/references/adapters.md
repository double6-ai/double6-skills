# Adapter boundary

v0.1 只有：

- 通用 PPTX postflight core：对任意已有 PPTX 做只读检查、inspection map、受限副本 patch 和验证。
- PPT Master deep adapter：authoring project → DrawingML 编译 → semantic contract → object map。

`slides_maker`、Gorden、Anthropic 和其它生成器没有接入。未来 adapter 必须提供稳定 source ID、结构意图、对象映射与 source repair hook；不能只把生成器输出机械交给 OfficeCLI 就宣称“融合”。
