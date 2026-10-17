# 原生完整行的有界行距写回

`scripts/native_line_spacing.py PLAN --page N --output-dir NEW`只处理已有可见译文的冻结完整印刷行，不调用模型。并发1，每次1页；先1页smoke，再处理计划中最多5页。调用方须用`bounded_execution.run_bounded`限制timeout、内存和进程数。默认任务RSS不超过4GiB；字形写回可能较慢，不用无上限超时。

计划身份为`schema_version="native-line-spacing@1"`，输入是完整JSON文件，单文件上限16MiB：

| 字段 | 合同 |
| --- | --- |
| baseline | 已有中文PDF的绝对路径及SHA，≤128MiB |
| source_scope_evidence | 源段落及原页归属审校文件的路径及SHA，≤16MiB；不能用旧抽取位置替代当前具名裁决 |
| fonts | 源PostScript font名称到完整TrueType/OpenType字体路径、SHA及source_font_xrefs；1–8份，每份≤64MiB，总计≤128MiB，源PDF所声明xref的实际字体字节也须匹配 |
| ratio | 声明范围内所有语义类型使用同一倍率，1–1.2；不同源规格保留其证据 |
| same_original_page_required | 必须为true，输出页1明确映射到输入物理页N |
| maximum_baseline_drift_pt | >0且≤60，段首必须0，后续行超过声明上限即阻断 |
| pages | 1–5个不同页号；每页≤400行、≤10000个字形，含空格 |
| pages[].rows | old_baseline、paragraph_id、line_index、delta_y、bbox、characters；从完整印刷行冻结 |
| characters | 精确unicode整数/GID/font/size/RGB/type/origin/bbox，方向及opacity继承源；不支持旋转、描边/隐藏/半透明文字、U+FFFD和代理标量 |
| rows[].verified_scripts | 字形完整身份、host_baseline、relative_y、reason及SHA绑定source_evidence；只有实际正文主基线一致、小号字形与唯一最近宿主行匹配时接受，歧义阻断 |
| paragraph_fragments | id、role、source_page_set、start_row/end_row（半开）、old_step_pt/new_step_pt；恰好覆盖全部行；源页集合包含当前页，逻辑段ID及连续行号一致 |
| underlines | 逐条source_drawing_sha256、row_index、role=source_verified_underline、reason、SHA绑定source_evidence；只支持唯一宿主行的水平stroke line |
| uri_links | 逐条source_link_sha256、row_index、reason、SHA绑定source_evidence；只支持唯一宿主行的URI，保留整份页面全部URI |
| restorable_protected_spaces | 每页具名保护空格完整身份白名单，最多1000个；须有protection_role=verified_residual_source_space、protection_reason及SHA绑定source_evidence。只补偿窄去字删除的已冻结残留空格，Unicode/GID/字体/字号/RGB/方向/opacity/原点均保持，delta=0，按源multiplicity仅恢复缺少次数；不得包含实际主基线/正文字号的行内空格 |

`object_sha(drawing_record(d))`生成源线条身份；`object_sha(link_identity(l))`生成链接身份，排除复制时变化的xref。相交drawing不会自动授予下划线身份。跨多行、内部跳转、任意图形、模糊范围及非链接注释均阻断，转交文档级结构适配。未知或重复线条/链接、遗漏声明、声明找不到均阻断。白色填充作为既有保护背景保存，不由相交推断移动。

当前入口限已审校的单栏完整印刷行。同一实际主基线上的所有可见非空白源字形，以及该基线/实际主字号的全部源空格均须按真实数量纳入该行。空格不能从行成员移出后改列为原位保护；源中不同规格的旧空格须有具名残留证据才可进入白名单。行框等于实际字符框的并集，正文主字号的全部字形须与old_baseline一致。交换成员、假基线、漏字或拆行因此阻断。小号字形的几何宿主与具名源语义分别核对，不据数字文本盲目归类上标。

每个片段首行delta=0，其余delta由行号、源步长与统一倍率计算。目标逐字形须与实际基线吻合，逻辑框也不可扩大。成品保持字形、精确Unicode（包括空格）、GID、字体、字号、RGB、X及核定的上标相对基线；GID别名对应不同Unicode时阻断。重复空格只在数量与真实源字形恰好一致时保留。只为本次新拥有字体绑定实际使用CID，源字体不可改。保护空格的恢复不授权补写任何其它损失；其它保护字形损失继续阻断。

每次保存后重新打开PDF，核对全部目标及非目标字形、全部drawing、全部链接与144dpi目标遮罩外像素。文字碰撞、出页或进入图片即阻断；文字与复杂图形的可见关系仍须独立视觉检查。遮罩由源真实字形框及核定移量生成，仅扩1pt用于抗锯齿/线宽，不由任意宽区域授权。

输出路径在resolve和mkdir前使用共享guard，拒绝父穿越、符号链接祖先、选项式组件和重复项目根。输出为`candidate-page.pdf`、`elements.json`（before/expected/after字形/drawing/link）和`verification.json`。验证失败保留failure及unverified文件，不给有效candidate指针。`mechanical_candidate_verified`不代表语义、视觉或接受；候选仍遵守[质量与交付合同](quality-and-delivery-contract.md)五类证据、具名接受及cutover。原页段落、实际成品源页映射与英文→中文既有偏移分别审校。

本工具只共享经过审校的原生完整行写回。自动段落/角色准备、多栏绕图计划、表格/脚注结构及新的翻译质量继续由各自路线和真实陌生样本验证，不因本工具通过而宣称通用支持。

## 复制、移动和重建链接的原始动作

复制页面前冻结完整直接`/A`动作与`/NM`身份，保存后重开核对全部动作及点击矩形。公开`get_links()["to"]`可能把不同GoToR XYZ坐标都呈现为零，不能证明跳转保持。URI删除重建后按动作与预期矩形形成完整唯一映射，歧义或遗漏阻断；注释顺序不作为宿主证据。

共享`scripts/raw_link_actions.py`只接受每页最多2000条、单动作不超过64KiB的直接URI/GoToR动作，遇内部引用、间接依赖、链式或附加动作先阻断再复制。原生行距入口仍限URI；GoToR的文档映射、相对文件可访问性和交互跳转由文档级验收处理。完整动作保持和机械测试通过不授予语义、视觉或交付接受。
