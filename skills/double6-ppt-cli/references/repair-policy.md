# Repair policy v0.2

## 自动允许

- `set_property`：精确文字、导航、结构化数字关系支持的单位/表达，以及小范围明确数值的 `x/y/width/height/size/color/fill/font`。
- `remove_leaf`：已证明为模板示例的文字、公式或顶层/组内叶子形状。
- 每个操作必须绑定当前 PPTX SHA、finding ID、稳定 OfficeCLI 叶子路径、DrawingML ID/type、期望文字/媒体/几何指纹、来源模板对象 ID 和修复理由。
- `package-clean` 可移除 presentation XML 未引用的 slide relationship、live slide XML 未引用的 slide-jump relationship，以及因此没有保留入边的非逻辑 slide part/自身 rel/content-type override；必须证明逻辑页顺序、live slide XML 和 master/layout/theme/notes 未变且内部关系闭包完整。

## 自动禁止

- master/layout/group 或共享关系删除。
- 未逐个确认的图片删除/替换，即使媒体 hash 能证明来自模板。
- 仅因包含“公式、分子、分母、乘除”等词而删除业务语义文本；必须有精确模板对象身份、文字 hash 或样例媒体 SHA 证明。
- 模糊文本地址、无可信映射对象、大范围重排、审美重做或波及未点名页。
- postflight 中仅凭颜色推断并批量修改导航选中态；检测器可报告静态高亮，但必须先由内容映射或用户确认每页所属章节。template-fill 已确认的章节起始页映射可作为章节归属证据，但仍必须证明原模板恰有一套唯一选中样式和一套重复未选中样式。
- 没有结构化 `numeric_claims` 的数字关系“猜修”。
- 把语义图片、media、master、layout、theme、notes 或仍有保留入边的非逻辑 slide 当作“孤儿”清理。

`patch-plan` 只收录确定性 finding；图片需逐个 `--confirm-finding`。`patch` 始终复制当前文件再修改，保存 OfficeCLI 操作回执、前后 SHA、package diff 和 scope invariants。修改后旧 inspect、PowerPoint、视觉复核和豁免全部失效，必须重跑。

布局空白、语义图片、署名许可证、大面积容量问题只定位并请求确认。模板署名先核许可证：要么保留对象，要么在得到合法删除依据后删除并在 delivery 中保留所需 attribution。

模板填充中的已确认图片替换不是模糊视觉操作：必须先导入本地资产并冻结 SHA，再由计划把一个输出页、一个来源 picture 对象和一个资产唯一绑定。执行时只为该 slide 新增媒体 part 并重定向该对象的 image relationship；若地址不唯一、对象/媒体 fingerprint 已变、资产 SHA 已变或 disposition 不一致，均 fail closed。
