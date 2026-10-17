# PDF 链接与依赖交付检查

`remote_destination_audit.py PLAN.json --output REPORT.json --package` 是 `remote-destination-audit@1` 的共同入口。计划冻结源、成品、注释配对和至多8份依赖的实际SHA。统一补齐同目录的简单文件名依赖；已有文件SHA不符、路径越界、symlink或祖先symlink、歧义及不支持的动作则停止。PDF本身不改写。

源命名目标从当前原生名称树或旧Dests解析；树深度16、对象256、单对象1MiB。显式源页引用必须匹配当前实际页对象；远程页按零起点解析。直接GoToR的原生XYZ与源目标比较，核对当前伴随文件身份、目标页及点在实际页面内。PDF规范规定XYZ的zoom=0与null均保持当前缩放，这一语义规则统一适用；其它坐标或目标差异仍失败。依据：[Adobe PDF Reference 1.5，表8.2](https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/pdfreference1.5_v6.pdf)。源可点击宿主、译文点击宿主、颜色/下划线及阅读器UI分别接受；目标解析不能替代它们。

`external_link_check.py INVENTORY.json --start N --output NEW_REPORT.json` 对保存后的PDF实际URI清单重新核对身份，并每批最多5个唯一地址、一个curl、连接4秒、每地址10秒、最多5次重定向、正文上限256KiB、无自动重试。保留状态、最终地址、标题、正文样本SHA、耗时和失败回执；不保留原始正文或响应header，不发送邮件或登录。

四种外链结果：`reachable`为成功HTTP响应，`unavailable`只用于404/410，`unverified`用于访问限制、挑战页、服务器/网络/重定向未知，`not_applicable`用于有效mailto。收到2xx及部分正文可以证明HTTP可达，传输截断仍明确记录；可达不证明完整下载、论文内容或产品规格未变化。原始批次、初始保守分类和新的语义汇总分别保留，不覆盖历史回执。

这两个入口无页码、URI名称、文字串或坐标豁免，遇逐case修正停在失败/未知。它们产出单项证据；九门独立验收、qa_pipeline综合复算、用户接受和strict晋升继续各自登记。输入JSON上限16MiB。PDF任务同锁、并发1、单页缓存、2GiB及120秒；网络IO每批65秒内、单curl并持续资源监控。定向负控制见消费项目 `test_remote_destination_audit.py`、`test_external_link_check.py`。
