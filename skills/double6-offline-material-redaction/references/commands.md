# 指令与计划

`PYTHON`替换为安装返回的Python绝对路径，`scripts/cli.py`相对已安装Skill目录。输入路径、计划路径、输出路径分别引用，尤其注意空格和中文。补选词只存本机计划文件；macOS创建时用0600权限，Windows存入当前账户私有目录，不进入共享盘、Git或聊天。

```text
PYTHON scripts/cli.py inspect --input <原文件>
PYTHON scripts/cli.py redact --input <原文件> --plan <计划.json> --output <新副本>
PYTHON scripts/cli.py verify --input <新副本> --plan <计划.json> [--source <原图>]
PYTHON scripts/cli.py gui
PYTHON scripts/acceptance.py --report <新验收JSON路径>
```

`inspect --show-preview`会向本地标准输出显示Word全文，只在确有需要且不会发送到外部日志时使用。默认inspect、redact、verify输出不包含原文或替换词。

Word计划示例（自编信息）：

```json
{
  "version": 1,
  "kind": "word",
  "reviewed": true,
  "terms": ["示例姓名", "demo@example.invalid"],
  "acknowledge_loss": true,
  "keep": ["整理120条活动反馈"]
}
```

`reviewed`表示已核对实际材料和补选范围；不要仅为让命令运行而填true。`acknowledge_loss`接受图片移除和版式重排，不表示同意转换文件格式。`keep`填写本材料必须保留的短句或数值显示，例如`15%`、`00123`；已填写但缺失时不创建输出。留空会明确记录“未检查”，不会返回这一项通过。图形界面提供同样的关键保留项输入。未知字段会报错，避免拼写错误被忽略。terms中的每项必须能在可见预览中准确找到；未找到时停止，避免错字导致正文漏处理。正文里出现`【已隐去N】`或`〔已处理A〕`也不能把对不上的补选词当成已经处理过，再跑一次同样停止。隐藏载体由重建统一移除，无需把其中原值列为正文替换词。替换标记默认是`【已隐去N】`。若补选词会出现在这个标记里，或正文里已经有同样的标记，改用`〔已处理A〕`；两套都不安全时停止，并写明是标记冲突。错误信息不回显正文里更长的原编号，也不回显另一种写法。数字词只要还出现在输出里，包括作为更长数字的一部分、中间夹了不可见字符，或换成另一种写法，复检都不会报“已经不在”，而是停止。哪种写法被选中都一样：归一化后是同一串数字就拒绝，并提示把各种写法一起补选。短数字两侧的汉字、字母、下划线、斜杠，或连字符两边的数字，同样停止，并提示把整段一起选上。建议词覆盖常见电话写法、邮箱、校验通过的身份证和银行卡，不自动写入补选栏；紧挨订单号的 11 位数字不会被建议成电话。

只清理Word隐藏内容时设 `terms: []`、`clean_only: true`，保留同样的reviewed与acknowledge_loss。此模式不会隐去正文中的姓名或联系方式。

图片计划示例：

```json
{
  "version": 1,
  "kind": "image",
  "reviewed": true,
  "rectangles": [[20, 30, 320, 110], [700, 900, 980, 990]]
}
```

矩形为按EXIF旋转后的显示坐标 `[左, 上, 右, 下]`；先inspect读取显示尺寸，或直接用gui人工框选。最多200框，PNG/WebP框外像素一致；JPEG明确记录重编码容差。图片verify需同时传 `--source` 才能检查框外像素。Word输出必须是.docx；图片默认保持输入扩展名。

命令不会覆盖原件、计划或已有输出，错误时不创建可交付副本。输出目录应是支持安全独占创建文件的本地目录。原值未在输出中检出只覆盖计划指定内容；补选不全仍可能留下敏感信息。

## 文本、表格与演示文稿

`kind`分别用`text`、`markdown`、`csv`、`tsv`、`excel`、`slides`。沿用`version=1`、`reviewed=true`、`terms`和`keep`。CSV/TSV/Excel/PPTX必须`acknowledge_loss=true`，接受格式说明中的重建方式。GB18030输入计划另设`input_encoding: "gb18030"`。输出扩展名见格式说明，XLSM默认导出同格式XLSM，宏内容不保留；只有明确选择才转为XLSX。

## PDF逐页计划

```json
{
  "version": 1, "kind": "pdf", "reviewed": true,
  "pdf_mode": "preserve",
  "reviewed_pages": [1, 2],
  "pages": [{"page": 1, "rectangles": [[20, 20, 120, 70]]}]
}
```

页码从1开始，坐标为`inspect`所报144dpi渲染像素，矩形是左、上、右、下。默认保留可搜索文字与页面。`pdf_mode=rasterize`并`acknowledge_loss=true`才允许整页图像化。`reviewed_pages`必须完整列出每一页；不需要框选的页也要核对。至少一处框选；原生PDF可用`keep`核对保留的可搜索业务文字，图像化模式不接受。保留项在原文里对不上时，错误会写明是保留项没有对上。被删批注只要在外接矩形里留下任何像素变化，或矩形里还有没框选的文字、矢量、图片，就停止。不按类型、颜色或线宽放行。普通高亮、下划线、删除线、波浪线、可见便签、空白色块，以及整块框住的图章或线宽为 0 的色块，都会停止。盖住未选文字的链接或弹出框也会停止。不改像素、也不压住未选对象的隐藏批注可以去掉。报错说明页码和是哪一块，并请先去掉这块批注。PDF的`verify`必须加`--source <原PDF>`。旧PPT须先明确选择转换为PDF，再使用相同的逐页计划，`--source`传原PPT；工具在隔离条件下重建同一渲染来源再比对框外像素。真实材料的框选在本机界面完成，不把原页面发给在线Agent。

`verify --input`接受已经导出的受支持同格式/明确转换副本；旧DOC/XLS/PPT、RTF原件仍拒绝，ODF副本会读取实际容器并核对可见内容。不能先转换原件再当作检查原件；PDF的`--source`仍可提供原PPT，用于渲染比较。


## 显式转换

默认输出路径扩展名须与输入一致。仅改输出文件名不能授权转换：

```text
PYTHON scripts/cli.py redact --input <原件.jpg> --plan <计划.json> --output <新副本.png> --output-format .png
PYTHON scripts/cli.py redact --input <原件.pdf> --plan <已接受图像化损耗的计划.json> --output <新副本.pdf> --pdf-mode rasterize
```

计划也可填写`output_format: ".png"`；`pdf_mode`只有preserve/rasterize两个值，默认preserve。网页的输出格式和PDF处理方式选择对应这些字段。结果报告写实际输入/输出格式和是否转换；创建新文件后不会改写原件、计划或已有副本。

旧DOC/XLS/PPT/RTF预览会调用本机Office转换，CLI的inspect需明确`--allow-conversion`；网页在调用前说明并征得本次转换选择。

## PDF整字对齐与下载名

网页拖框后会先向本机服务请求整字范围，并用黑块显示实际处理区域；请按这个范围确认，尤其注意相邻标点、行和保留数值。CLI默认使用原坐标；需相同对齐时在计划中明确加入`"snap_to_text": true`，导出/复检均按同一规则计算，报告`effective_pages`记录实际坐标。对齐不能绕过保留项和框外检查。

网页每次成功导出均生成`redacted-时间戳-随机标识.原扩展名`，不使用原件的姓名、电话或目录。CLI按用户明确指定的输出路径新建，工具不会擅自改名；请勿在该路径中写敏感原值。
