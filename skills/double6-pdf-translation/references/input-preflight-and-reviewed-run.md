# 109 输入预检与审后重放（未发布）

当前默认选择以 [configs/default-routes.json](../configs/default-routes.json) 为唯一机器配置，开工合同在 [SKILL.md](../SKILL.md)，已同步源项目第 111 轮。路线动作仍是 110 收束的五条，下文实现和参数合同继续适用。旧的整篇强翻译命令不再作为开工入口；当前副本按本目录运行说明安装。

从已安装skill目录用独立环境Python。当前开发入口复用原 `paper_translation_workflow.py` 的锁与有界执行（资源上限按平台默认，可显式调整，见[运行说明](release-quickstart.md#资源上限)），以及原 `prepare-scan` / `trial-render`；单配置总作业上限120秒，逐步骤重新取共享锁，不在持锁时递归启动另一条重链。渲染失败仍为失败，输出不签语义、视觉、人验或strict。

## 新输入先核事实

```bash
python scripts/paper_translation_workflow.py inspect-input \
  --input /absolute/source.pdf --output /new/INPUT_PREFLIGHT.json --receipts /new/receipts
```

默认最多2物理页；读取真实MediaBox/CropBox/旋转、render mode/opacity的字形数、图像并集覆盖及单图最大bbox覆盖，不修改PDF。type3或零opacity算隐藏字形；其它字形只是可见render mode候选，图像遮挡、OCR正确性和完整语义仍UNKNOWN。源图是否为完整作品、打印或手写不能由编号、图像覆盖率、文字量或文件名自动判定。此facts命令可以成功返回`needs_source_review`，须读report的status/blockers/todos，不能把进程退出0当资格通过。

准备新扫描路线时增加 `--fresh --source-review /bound/source-review.json --model <actual-load-key-or-loaded-ID>`。源review按`schemas/scan-input-source-review.schema.json`，须绑定精确源及源图审阅证据；printed_with_protected_signature仍需完整角色保护。未确认完整作品或手写/未知会阻断fresh。fresh的单图最大bbox覆盖须≥85%，与现有prepare_scan门一致；两张半页图并集100%不扩展该能力。旧隐藏OCR会报告并阻断该有限纯图扫描入口；源是否保留、另走原生链或显式适配由具名决定，不自动去隐藏层、改页框或重封装。

库存仅在显式给定 `--catalog-url` 时读取LM Studio兼容 `/api/v1/models`，分开列`key`（load key）、`variants/selected_variant`和`loaded_instances`。例如库存key可能为`qwen/qwen3.8-27b`，`qwen/qwen3.8-27b@8bit`是variant，不能当load key。缺失/错误配置阻断fresh；不静默改为库存模型。库存key可用不代表模型已加载或权重指纹已冻结；实际新MT提交仍须绑定当时loaded ID、权重/参数和服务。预检不加载模型、生成或下载。

## 已审同源只填一个配置

```json
{"schema_version":1,"mode":"reprepare","preparation_ref":{"path":"/absolute/OLD/TRIAL_CONTRACT.json","sha256":"<exact SHA256>"},"max_pages":1}
```

```bash
python scripts/paper_translation_workflow.py run-reviewed-scan \
  --config /absolute/run.json --output /new/run --receipts /new/receipts
```

配置schema为`reviewed-scan-run.schema.json`。源从旧合同读取，进入重作业前核合同、source、原OCR、完整组、roles、target、完整语义review、font、materialization/source-plan和renderer代码父链SHA。配置错误或父变更在渲染前拒绝。`reprepare`内部复用现有`--reuse-preparation`，再渲染mono/dual；不补译、不重签接受。冻结重放的库存为`not_required`、网络probe0，即使模型服务离线也可使用原审后目标。

纯同冻结合同重建优先直接使用既有`trial-render --input … --contract … --output … --receipts …`；不必为了这个动作多跑预检和prepare。配置`mode=rebuild`只在需要同一入口集中回执时选择。源/OCR分组仍从既有`prepare-scan --source-plan SEED --draft-source-plan`开始，草案所有确认空；完整源/角色/几何/当前译文审后准备仍沿原入口，不自动识别或授予语义通过。

