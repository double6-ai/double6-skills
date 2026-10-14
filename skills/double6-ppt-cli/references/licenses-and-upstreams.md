# Licenses and upstreams

- Double6 原创 glue、policy、CLI、schema 和测试：Apache License 2.0，见根 `LICENSE` 与 `NOTICE`。
- `vendor/ppt-master-core/`：PPT Master `v4.8.0`、冻结 commit `53c9c2a5e9f1a49096324fba4f95833649c6a0f4` 的 137 文件精简内核，继续适用 MIT；0.2.0 从 SHA `29dc7d…` 的官方 release asset 补齐了完整 Template Fill Native package。原文件、许可证、BOM 与修改记录必须保留。
- OfficeCLI：`iOfficeAI/OfficeCLI v1.0.157`（0.3.0 起；此前为 v1.0.144，两版 LICENSE/NOTICE 字节一致），Apache-2.0，作为外部固定依赖安装，不 vendoring 二进制。不要误装另一个 `officecli@0.2.x` 同名项目。
- Open XML preset shape data 的 Apache/MIT provenance notice 保留在 vendor 原路径。

`0.2.1-local` 的精简包内容已获授权发布到 `double6-ai/double6-skills`。插件市场上传、OfficeCLI 二进制再分发或其它形式的对外分发仍需另行授权与 package-level 许可证审计。

## 上游检查记录（2026-10-15，0.3.0）

- OfficeCLI：升级 pin 至 `v1.0.157`（commit `b65272a`，2026-10-12）；1.0.145–1.0.157 changelog 仅修复（pptx placeholder 继承、隐藏形状、母版 z 序、query `>` 组合符等）。LICENSE/NOTICE 与 1.0.144 字节一致。运行时最低兼容仍为 1.0.144。
- PPT Master：最新 `v6.7.0`（2026-10-08），**未升级**。v5.0.0 起删除 Template Fill Native 与 native_enhance，改为 roundtrip 路线，需单独迁移 template-fill。上游重写历史后 `v4.8.0` 标签指向 `5da13a0`，内容与锁定的 `53c9c2a` 逐文件一致。
