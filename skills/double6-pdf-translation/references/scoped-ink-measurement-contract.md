# 指定字体范围的墨迹测量

`EmbeddedGlyphInk(document, page, required_fonts={...})` 可用于已冻结的局部字符范围。`required_fonts`须由实际字符及其宿主的字体集合产生，以真实trace/PostScript身份绑定全部嵌入字体候选；不得写页码、词串或特定字体豁免。

默认不传该参数，继续检查页面全部字体，未嵌入资源仍阻断。局部模式明确记录`excluded_resources`；范围外未嵌入资源不阻断本次局部测量，也不能获得墨迹、碰撞或整页接受。请求内未嵌入字体、未解析字体、字体身份歧义和范围外后续字符调用仍报错。局部测量不替代所有邻字碰撞检查；碰撞任务应声明所有参与比较的字形字体，或继续使用默认整页范围。

真实下标须同时测量字符含义、下标与宿主墨迹高度、相对基线及完整公式的可见性。轮廓成功不意味着源/译排版相等；Unicode固有下标与普通数字降低基线时，不能只比较名义字号。测量结果仍需要实际PDF审阅及独立接受才能进入正式typed样式验收。此增量只补证据，不改变现有容差、综合QA状态或2.0.0未发布边界。

原生两页0030的4组实测：源/目标共8个下标轮廓及8个相邻宿主轮廓可提取；所需字体身份唯一。默认整页接口仍在Times-Roman阻断。源文数字下标墨迹底部低于宿主基线约1.86–2.09pt，当前译文约−0.13至−0.41pt；字母x约2.09pt与0.96pt。字符含义一致，位置及实际字形比例存在差异，不能标为样式已等价。

回归见项目`tests/test_glyph_ink_geometry.py`；实测及局限见`projects/paper-translation/04_iterations/iteration_038_qa_hardening/team_handoff_1154/coordinator/science_crossfile_20261011/SCIENCE_MEASUREMENTS.json`。
