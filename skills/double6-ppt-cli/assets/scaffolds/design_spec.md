# Design Spec

状态：草稿。开始绘制 SVG 前填写下列内容，并先读 references/visual-design.md。

- 受众：
- 使用场景：
- 核心结论：
- 页数与叙事顺序：
- 风格：{{VISUAL_STYLE}}（方法与视觉默认值见 {{STYLE_REF}}）
- 调色：以 spec_lock `## colors` 为锚点（主色 {{PRIMARY}}，强调色 {{ACCENT}}），配色行为按 style 的 Color Behavior
- 字体与替代字体：{{FONT_FAMILY}}
- 跨页 motif（一种贯穿全 deck 的元素，如标题上方强调短线 / 封面几何）：
- 图像方向：{{IMAGERY}}（`image-search` / `image-add` 取得带署名的免版税图片；没有合适图片时用标明 placeholder 的生成图）
- 节奏：封面 → 章节页/全幅图 → 内容页（每 2–3 页换一次版式密度，至少 1 页 hero 大数字或全幅图）→ 结尾
- 图标库：{{ICON_LIBRARY}}（`<use data-icon="tabler-outline/<name>" .../>`，compile 自动嵌入）
- 需要原生编辑的对象：
- 图表、表格、公式和图片来源：

## IX. Content Outline

<!-- PPT Master quality gate requires this exact section title and one block per slide.
     Each Slide block: Audience move, Relationships (v6 hard requirement), and Composition
     (page job -> composition -> devices, see references/visual-design.md). Replace NN. -->

### Slide 01
- Audience move: [本页希望听众产生什么理解或情绪变化]
- Relationships: [本页内容单元之间的关系，如 顺序/对比/总分/因果；没有则写 none]
- Composition: [page job → 版式结构 → 设备，如 “单焦点 → 主色场域封面 → 强调短线 + 大标题”]

### Slide NN
- Audience move: [本页希望听众产生什么理解或情绪变化]
- Relationships: [本页内容单元之间的关系；没有则写 none]
- Composition: [page job → 版式结构 → 设备]
