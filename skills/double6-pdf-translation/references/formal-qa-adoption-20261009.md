# 正式QA组件采用记录（2.0.0未发布）

2026-10-09，用户恢复四步路线后，稳定渲染已接入12个调用文件的25处调用及helper。每次按原生接口参数重置MuPDF store；默认annots=true，dpi行为与原生接口一致。重置缺失、失败、失效页、原生渲染失败均停止，背景采样和roster写入失败直接报错。背景采样成功后才修改目标。

共享脚本新增form_text_guard、source_script_binding、source_story_script_writer、source_script_audit及source_script_report_gate，schema为schemas/source-script-audit.schema.json。完整标签中的连接符、逗号和逐个成员均进入基线/字号比较。审查报告按冻结实际输入重算，未知不算检出；源范围和来源角色由调用方独立冻结。

source_script_audit的采用包含709→775绑定核心升级，除路径迁移外还采用外部源/目标/绑定/范围/计划身份核对及源关系重算。775核心是实际采用源；891历史plan中的path_relocation_only不足以描述这项升级，本记录补正，旧plan不改。小于等于0.2pt的银行返修接口仅适用已核定横排和字号的有限范围，不推广为所有科学符号的容差。

Story返回完成时，filled仍可能超出栏框。insert_source_htmlbox在任何目标写入前检查实际filled范围；真实扫描段落反例修复前误放行，修复后拒绝。完整语义段先一次测量，再由semantic_paragraph_flow按完整印刷行进入经核定栏框；不得按源片段拆译或把整段超框当成成功。

全页预览和局部裁图均为必检。源暗像素上的透明掩码可能在低倍率留下采样边缘，须按完整源印刷行、保护边界和实际成品核验。两处局部去字成功不证明整页无重叠、字号统一或其余文字完整。

采用前7项、采用后103项现有功能控制与183项组件控制均有回执。真实溢出2项及相关流排26项通过属于接口验证。独立892提出的八个测试绝对路径与过时说明已修正；科学90单元的完整区域仍未核，不把普通诊断微差算成错误或通过。完整45+13页回归、陌生样本、独立视觉及用户接受继续分别登记。

接口安装、合同控制和限定组件资格不能授予整稿接受、严格交付或晋升。hardening-qa-contract.md的b416历史标准、旧资格与失败回执保持原身份；本记录描述正式采用和新增防漏检检查。2.0.0仍未发布。


### 2026-10-09：完整脚本样式生产接入

`qa_pipeline.evaluate_quality_packet`额外要求独立源审校冻结的`script_styles_scope_ref`，实际源/目标逐页重读，所有引用成员（含连接符）重新计算并通过schema门。没有范围、少成员、身份或冻结改变保持未核验；实际样式冲突判失败。无脚本的范围须具名理由且现场源字形没有相反信号；扫描空清单不能判不适用。容差逐项冻结，仅适用于明确政策，不扩展到普通科学字形微差。组件通过仍须原有九项质量门、独立视觉和用户接受。源枚举及正文绑定改为每批1页，链接沿用全局闭合审计。


## 非空范围的完整源成员核对

996实际13页审校发现，旧504样式清单漏了旋转单位指数，还错误排除了10^0和1/n。正式`qa_script_styles`现在要求非空`items`绑定`source_members_ref`。该独立清单必须绑定源PDF、标准、审校员及全部页；`method=source_first`、`source_scope_status=pass`，并声明`source_scope_item_ids`、`required_members`（[页号,原生字符索引]）、`excluded_source_items`及`complete_groups`（id、members）。未知或无理由排除不能通过。空清单、成员重复、源标记未进入执行范围、成员同时被拥有且排除、负指数或复合分数被拆成不同样式项均阻止通过。非空输入schema同步要求该引用。

集合检查不生成源范围，也不授予字体、视觉或整件接受。源范围须来自独立完整源页枚举；机械集合齐全不能证明源识别正确。缺少独立清单保持unverified，具体遗漏在清单有效时为fail。固有上下标、语义改写、旋转文字和自然折行仍按各自适配边界处理。当前508组修复仍是候选，未获得整件或用户接受；2.0.0未发布。


## 五类样式的正式检查

非空源范围可通过`typed_routes_ref`绑定五类已核定路线：普通原生关系、具名字体排印适配、固有上下标字体轮廓/墨迹、语义呈现和复合分数。所有项必须来自同一独立完整源范围，执行清单与独立接受清单逐项相等；源成员清单通过`independent_source_scope_ref`绑定独立枚举，排除及完整标签成员不能由生产端裁小。

`qa_typed_script_styles`现场读取源/译实际物理页，源/译各仅缓存当前一页，PDF句柄立即关闭。跨页续片段使用其已经接受的实际目标页；不把它重新认成新段。当前字形数组须与独立原生快照完全相同，变化时拒绝继承。普通关系按局部文字方向和每个目标字形的实际宿主重算，归一基线及字号比例容差固定0.001。字体排印差只继承对应不可变实例的具名接受，未扩大普通容差；固有上下标须有完整字体轮廓、字符身份及阅读接受，不能把字体标称字号当作墨迹大小。语义呈现不拥有共享参考字形；复合1/n须保留完整父式及已接受的矢量横线，不能套用单基线规则。

`typed_routes_ref`引用对象包含source/target/standard/reviewer_id/pages、runtime_refs、acceptance_ref、source_scope_ref、ordinary_policy_ref、typography_ref及typography_overlay_ref、intrinsic_ref、semantic_ref、composite_ref、fraction_ref。各证据引用绑定绝对路径和SHA；缺项、身份改变或未接受类型保持unverified。所有组件报告quality_pass=false，整件九门、独立及用户接受另行执行。

实际加载身份守门：除冻结文件SHA外，另核对调用函数的实际来源路径，拒绝同名模块替换；运行依赖同时冻结qa_source_contract、native_line_spacing和source_script_binding。独立1024发现的同名导入反例保留，修复不改变源/译PDF或普通容差。
