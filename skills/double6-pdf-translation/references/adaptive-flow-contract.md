# 有界结构流排候选

完整源页、双语读者包、五类质量证据及验收状态统一遵守[质量与交付合同](quality-and-delivery-contract.md)。本文件定义显式计划的实现边界与参数，不能把参数可用视为通用自动准备已完成。

## 入口与身份

主入口显式接收`--adaptive-plan`，先运行既有LaTeX来源发现；有LaTeX或身份歧义时阻断该路线。计划`schema_version=1`，`input_source.path/sha256`必须匹配CLI输入；`sources`逐项绑定实际原文或已冻结中文保护图层，字体绑定SHA。使用新输出目录。标准PDF默认路线沿用原合同。

计划包含：`items`（默认最多100；显式`maximum_items`可声明1–200，仍受页面/框数/内存预算约束）、`frames`（最多20）、`templates`、`sources`、`input_source`、`gap`、`maximum_pages`（最多10）。文字项声明HTML、字体、字号、统一行高、栏宽、期望可见文本、逻辑段落ID和所有source_origins；图形项声明source/index/native_clip及其尺寸。标题可声明独立编号/题名及separator源路径证据和几何间距。

临时Story只做实测，固定scale=1。`layout_policy=whole_paragraph`保留既有整段换框行为，单段超框时报错。用户要求贴近原页位置且允许自然续页时，使用`layout_policy=source_anchored`；语义段落身份统一保存，显示可按完整行跨页。段落首行缩进保留实际来源；悬挂段落用左边距容纳负缩进。源/译行距分别记录，两端对齐按实际字形端点核对。

## 源位置优先的单栏候选

用户要求完整新段落留在原页时，计划声明`preserve_complete_source_page=true`。每项`source_origins.source_page`须齐全且最早源页与anchor一致；同一源页内的完整段落必须全部留在该页，空间不足即停止。只有已核定的跨源页段落允许完整行续排；不能为填补上一页空白而提前放置下一页完整段落。`x_offset_pt`保留摘要等相对frame的来源缩进，须核对实际字形位置。

正文行内已核定的75%字号上下标可显式声明`line_group_policy=body_with_verified_small_scripts`，按实际正文字号与最近基线绑定完整印刷行；比例或位移不符时停止。该选项不替代上下标语义与复制后完整字符核验。

适用范围为已审校的单栏纯文本计划，页面frame须顺序递增。同类正文固定字号/行距，逐项提供`anchor.page/baseline_y`，记录首次显示的`source_page_delta`和`baseline_drift_pt`。`maximum_drift_pt`有界，超过即停止；不能按单段缩字或强行推迟到另一页隐藏偏移。字体按最终中文实际字形观感选择，不能单凭中英pt数值相同或总页数相同判断位置一致。

首页刊头、标题、作者、机构、献词、页脚及空白区都进入完整源页清单。未翻译的身份行须声明native保护角色并逐字形/位置/颜色及保存后像素核验；正文unit清单的100%不能代替完整源页覆盖。固定前置信息按源基线保存。

逐印刷行登记基线、墨迹范围、字符累计offset和连续`line_range`；行间真实空隙用于裁切。默认每个续页片段至少两行；原页边界确有一行且任务要求优先源位置时可显式`minimum_fragment_lines=1`，须核验孤行和阅读效果。跨页源片段可提供`preferred_page_breaks`，在译文对应offset附近选完整行边界，不能仅因中文能放下便提前并到上一页。全段合并后可见字符须与译文一致，不遗漏、不重复。段间因译文缩短产生的空白与段内基线连续分别审查，不能为填空统一放大字体。

CJK字体度量框可能覆盖邻行。碎片复制须按真实墨迹/字符中心去除裁区外字形，去字前后逐项比较被保留字符及origin；裁切框本身不能证明可见完整。允许去掉页面末行后的纯空白高度，实际墨迹仍须在frame内。此策略尚不证明自动多栏、绕图或任意长段能力。

复制PDF区域前，从独立副本删除裁区外文字；URI重定位。保护图层按保存后像素核对，必须区分“与英文源一致”和“与已译冻结图层一致”。成品文字及源页复制须单独验证，不能用可打开代替核验。

## 经核定的多栏及跨页段落候选

`layout_policy=verified_multiframe`使用`semantic_paragraph_flow.py`。每个item是一份完整译文及一次Story试排；`verified_fragments`保存完整源段的所有片段（id、logical_paragraph_id、source_page、bbox、source_text、source_baseline和boundary_evidence）。译文不能含`{break0}`等源框强制分隔符。相邻源页缺失、重复片段或读取顺序倒置时停止。`expected_text`是完整可见译文，须与实际字形一致。

`frame_indices`绑定有序框；每框提供`page`（输出页）、`source_page`、`column`、`bbox`、`first_baseline`和`source_fragment_id`。框只占该段已核定的可用空间，完整新段、图表、页脚及其它保护对象限制其下边界。首框绑定真实段首，源页及基线保持；续框按剩余实际行数取完整行，可以为空。全部文字在前框放得下时，旧续框留空并清除其中源片段，不保留重复文字，也不把后续完整新段提前填入。各框统一栏宽、字号和行距，scale=1，溢出停止。只有全段末行按自然宽度结束；续栏/页前的非末行沿用全段对齐。宿主正文基线绑定核定上下标，逐字形、连续line_range、无遗漏/重复、移动后链接及保护像素均须复验。裁片重写的origin容差为0.002pt，Unicode/GID/字体/RGB、字号及行序仍独立检查。

同页同栏被保护图形分开的上下子框可沿用真实column；首基线须递增、框纵向不重叠、左右边界须在0.002pt内一致。完整段只试排一次，连续行跨过保护间隔，框与源片段仍逐项绑定。此显式框支持不授予自动绕图结构识别。

该入口只支持显式审校计划，不能自动推断任意PDF的跨栏/页关系。Nature八段开发案覆盖四组跨栏和四组跨页；物理1/4/6页为既有全译样页，3/5/7页只补齐对应段落，其余英语有native context/protected角色，不能写成六页全文翻译。任意自动准备、绕图、不同栏宽及未声明资产组合仍须单独验证。质量接受绑定新PDF和具名范围。

科学表达式可用`scientific_atoms.py`显式标记完整数值、复合单位、指数以及中文金额量级/年月；调用方须声明冻结的Lat/LatBold字体。Story的CJK字体在nowrap环境下可能把数字映成不一致字形，不能只检查HTML。表达式后允许HTML软断点U+200B，仍由整段实测决定换行；实际PDF的控制无可见墨迹，按已声明布局空白规范比较完整译文，字体/数字/科学符号仍逐字形核验。每个完整表达式的主体字形须属于同一宿主印刷行，上下标绑定该行；不得只绑定指数而任由数值、复合单位或每年项被拆开。nowrap造成大空隙时，保留两端对齐的间距门，不通过放宽阈值或缩字掩盖。

裸数字和Latin文字同样使用声明字体，并检查实际Unicode；科学复合单位须按最长完整表达式绑定，短年份不能抢占更长年月。新增上下标沿用源字号比例及位移，不能叠加HTML默认上下移。`plan_line_flow.maximum_script_offset_em`默认0.5，有独立源字形证据时可声明0.1–0.8以内的位移上限；超出声明范围停止，并保留证据，不以参数扩大代替源样式核验。全页流排另做全文覆盖门；八段样本的机制验证不代表邻页普通正文已译。

## 连续章节候选

### 固定行内绑定

文字项可以同时声明 `balanced_line_flow:true` 和 `inline_attachment_policy:"numeric-and-figure-v1"`，经主入口 `--adaptive-plan` 进入正式候选流程。该选项在 Story 实际字形上识别完整图表编号、括号文献编号及数字型小字号片段，绑定前方最多四个连续汉字或相邻 Latin 片段，然后由同一个断行器选择合法断点。字体、字号、颜色和 CID 不变；最大扩张 0.3em、压缩 0.05em，末行自然收尾。四字绑定是启发式，不授完整语义宿主识别。

策略参数冻结于 `scripts/inline_attachment.py`，不提供逐输入覆盖。未知策略或未启用完整段落断行时报错。缺宿主、整项超框、完整文字绑定失败或未重绑定链接时停止该输入。实际样段重建必须验证该输入嵌入的字体文件 SHA；重新绘制导致原 Unicode/GID/样式改变时保留失败，不为该段补丁。schema 与样例见 `schemas/inline-attachment-options.schema.json`、`examples/inline-attachment-options.example.json`；审校提示见 `prompts/inline-attachment-review.md`。

该规则的安装不迁移旧标准 SHA 或既有验收。实际 PDF 前后效果、容量、字体和链接分别核验；样段通过不能写成整件通过。

HTML颜色会取整到8位。当需要保留成品原生浮点RGB时，文字项可提供 `actual_style_ref.path/sha256`。该JSON包含冻结 `pdf.path/sha256`、页码及完整实际 `glyphs`；跨页完整段落的glyphs包含各实际片段。最大16MiB、10000字形。逐个非空白字符的Unicode/GID、字体名、字号和透明度必须与Story一致，才在原生Identity-H文字流恢复RGB。原生浮点写回的RGB容差为0.000001，报告实际最大误差；这不同于HTML的1/255取整。字形清单含origin时，小字号片段保留其相对源正文最近基线的位移。来源SHA变化、身份不符、非RGB或非有限颜色均停止。恢复颜色不授权改字形、缩字或重新定义该case宿主。

```bash
python scripts/run_native_chapter.py source.pdf \
  --start-heading '1. Introduction' --end-heading '2. Results' \
  --model <已核验本地单实例标识> --font <冻结正文字体> \
  --bold-font <冻结粗体> --glossary <术语TSV> --output-dir <新目录>
```

识别范围最多5源页，PDF大小128MiB、搜索最多40页。当前自动准备器支持单栏、以实际首行缩进区分段落的原生连续章节。内部未知标题、多栏、图片/绘图或边界缺失均报错，不漏掉后继续。正文空格从全部source spans恢复；仅移除印刷行末且下行小写的连字断行，并保存操作。化学式/作者引用/引用编号可逆保护，上下标由真实源span字号和基线推断，不猜格式。

每段请求顺序执行；原响应与失败保留，保护协议错误最多一次约束重试。引用及容器边界必须保序，科学名称调序只允许身份计数不变，并标记为待语义复核。全段译文即使所有保护标记齐全也必须做另一模型及控制端语义审校，不能将标记通过称为翻译通过。

本地资源限制：task 4GiB、provider 40GiB、Codex单进程20GiB、swap增量256MiB；10秒采样、单并发。已租用模型由调用方finally释放，实际加载身份及上下文须与请求分开记录。API兼容/推理模式失败保留，不能读取思考片段当作最终审校答案。LM Studio原生接口的reasoning选项及最终message字段见[官方接口](https://lmstudio.ai/docs/developer/rest/chat)。

## 验收

源文完整范围、可见译文、字体/间距/颜色/URI、公式/图形保护像素、段落映射与原页一致性分别验。候选仍须full-page sweep、区域核验、独立视觉spot check、人工接受及cutover/promotion receipt；任何一个缺失都不能写strict。章节翻译范围与完整原页范围分别标明。

### 同页图注的完整跨度

已核定同一逻辑图注的并排两列源片段，默认保留源左右双栏。`caption_column_flow.caption_columns`登记两列起点、同页基线、相同栏宽、栏间带及下方分隔线；`plan_caption_columns`对完整译文只调用一次试排，按完整宿主行选择最接近平分且两栏均可容纳的连续断点。上下标随行，段落仅在完整末行自然收尾；裁片空白边缘可收紧，全部字形度量范围、实际墨迹及逆平移后原点须复验。`verify_caption_columns`独立核对两个有序目标列、连续line_range、scale=1、左右界及下沿。容量不足保持阻断，不逐图缩字。只有用户明确要求通栏时，才采用`caption_structure_geometry.caption_band`及`verify_caption_span`；原生整宽及真实单栏继续保留。跨度门独立于字形碰撞门：没有碰撞不能证明源列结构已保留。未知跨页、非并排或多义边界仍须结构适配。

同类行距调整须联合核验真实印刷行、其它段落和固定资产边界。记录统一参数、最拥挤段落的上限、源页起点及有限段首偏移；完整新段不得为了填空提前到前页。CSS变化后复用银行页须同时核对字号、行距和宽度，不能仅因HTML及译文未变继承旧排版。


### 完全相同流去重

结构排版器保存使用`garbage=4`合并完全相同的PDF流，避免每个段落重复嵌入完整CJK字体。它不做字体子集，也不改GID/Unicode；保存后继续核对全部原生字形。当前两页真实样本的字体程序SHA、字形全部字段、完整直接链接动作/NM/矩形及144dpi冷像素一致，文件455902611→28098007字节。该等价核验只支持流去重，不授予排版、语义或完整交付接受。


### 完整单位与源URI动作

所有文本单位在Story准备后登记完整文字，声明`expected_text`时先核对准备文字；复制到所有目标栏/页后的实际原生字形文字必须完整等于该单位文字，再写出文件。不能以复制后已缺字的字形分区自洽代替完整性核验。保存后仍冷读全原生字形字段。单位核验不代替源页完整范围、语义、模板背景角色和整体九门质检。

CSS数值输出有限十进制，避免科学计数缩进被解析成大幅负缩进导致首字被裁去。实际案例的完整源缩进保留到六位小数，误差小于0.000001pt。

显式`source_uri_action_policy: unique_source_uri_full_actions_and_names`从已冻结`input_source`恢复完整直接URI动作及NM；允许源NM为空时同一唯一源URI对应多个文字点击框。源URI重复、具名源注释拆分、目标URI无源或源URI遗漏均拒绝，需另行明确映射。该有限政策仅支持最多10页、2000个URI注释的唯一源URI输入，不适用于GoToR等其它动作。插入注释后释放旧页引用并刷新页缓存，保存后冷读核对全动作和名称。


## 完整段落与链接通用回写（候选）

`paragraph_link_rebind.py` 提供 `paragraph-link-rebind@1` 独立正式候选入口：保留完整源PDF对象图，用实际Unicode/GID/字体/字号/RGB及原位置唯一绑定完整段落；输入新层必须是无注释的单页真实字体PDF。段首正文基线和源页保留。固定0.012pt中心探针删除原字形，删除后完整核对保护字形；发生邻字删除或不唯一则停止。

链接矩形以源实际字形中心绑定连续标签成员，按新实际字形重新计算原有四边留量。只改原注释 `/Rect`，保存后核对所有其它原生对象字段和引用、注释顺序与总数。混合所有权、无明确宿主、跨行需拆注释、异常留量或点击框包含无关字形均停止；不增加逐页或逐链接例外。原对象图保留使间接动作与原生远程XYZ坐标无需重写；这不证明外部目标文件/URL存在或可打开。

命令：`python scripts/paragraph_link_rebind.py PLAN.json --output-dir NEW_DIR`。必须在项目受限runner同锁下执行，单页缓存、2GiB、120秒，先smoke后扩大。schema、样例及审阅提示分别见 `schemas/paragraph-link-rebind.schema.json`、`examples/paragraph-link-rebind.example.json`、`prompts/paragraph-link-rebind-review.md`。PDF存在和回写核验不能代替完整语义、整页视觉、独立审阅、人工接受和切主证据；2.0.0仍为未发布候选。


原生URI宿主余量的共同入口为 `native_uri_host_rebind.py PLAN.json --output-dir NEW_DIR`，schema为`native-uri-host-rebind@1`。按源和目标实际相同URI/原生动作分组，完整标签字形中心绑定；源点击留量从实际标签框与源注释框推导，最大3pt，统一投影译文标签。首尾相接、同基线、同动作的冗余框可合为一个，连接误差限0.03pt；多行、空隙、重叠、不同动作、无关字形或非文字资产改变则停止。非文字URI只允许原框和动作保持。输入限5页，保存重开核对宿主、所有实际字形/样式/位置及动作；原生两页实测25框收敛为8个URI框，字体、引用颜色及整页图像由独立审阅另核。此规则没有URI名称或坐标例外。见 `schemas/native-uri-host-rebind.schema.json`、`examples/native-uri-host-rebind.example.json`；仍为候选，不代签用户接受或发布。

保存后的完整PDF还须按 [链接与依赖交付合同](link-delivery-check-contract.md) 实查原生目的地、冻结伴随文件与全部唯一外链。成功HTTP、缺失资源、访问/网络未知和mailto分别记录；URL逐项替换及坐标豁免不进入通用流程。


## 统一URI留白投影（候选）

`uri_padding_projection.py`按完整字面标签、同组统一源留白投影既有目标分框，仅原位修改Rect。源留白差≤0.5pt、各边≤3pt，实际误差>0.5pt才修复；新框成员须完整且不含邻文。多行/碎片保留原分框，原生动作和非选中框保持。非文字、源留白不统一、标签歧义或投影缺成员停止本组，无URI/页码/词串例外。保存复核0.001pt，规则/schema/样例/审阅提示/负控制见 `references/uri-padding-projection-contract.md`（scripts目录入口为 `../references/uri-padding-projection-contract.md`）。主论文13页16组/20框实证通过不代签新SHA全篇/下划线/阅读器/用户接受，2.0.0继续未发布。
