# 双语版式核验档案

日期：2026-09-08  
状态：随 `double6-pdf-translation` 1.0.7 生效。这不是后端方向保证书，只记录已核验组合和交付合同。

## 交付合同

- 显式布局 `en-left-zh-right` / `zh-left-en-right` 必须打开双语 PDF，按页统计左半页/右半页的 CJK 与拉丁字母。
- `layout_verification` 成功值只能是 `geometry`。`backend_contract` 不能标 `ok`。
- `observed_layout` 必须与请求布局一致，否则重建或失败，不得把反的文件标成成功。
- `--dual-translate-first` 只是传给后端的提示，不能代替几何核验。

## 已核验后端

| 包 | 版本 | 未加 `--dual-translate-first` 的实测方向 | 源码注释声称的方向 |
| --- | --- | --- | --- |
| `pdf2zh_next` | 2.9.0 | 中文左、英文右 | 原文左、译文右 |
| `babeldoc` | 0.6.2 | 同上（本格 2026-09-07 探针） | `create_side_by_side_dual_pdf` 注释写默认原文在左 |

两者冲突时以打开文件后的栏位为准。未在本表中的后端版本必须重新做几何夹具，不能沿用注释。
