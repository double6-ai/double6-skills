# Licenses and upstreams

- Double6 原创 glue、policy、CLI、schema 和测试：Apache License 2.0，见根 `LICENSE` 与 `NOTICE`。
- `vendor/ppt-master-core/`：PPT Master `v4.8.0`、冻结 commit `53c9c2a5e9f1a49096324fba4f95833649c6a0f4` 的 137 文件精简内核，继续适用 MIT；0.2.0 从 SHA `29dc7d…` 的官方 release asset 补齐了完整 Template Fill Native package。原文件、许可证、BOM 与修改记录必须保留。
- OfficeCLI：`iOfficeAI/OfficeCLI v1.0.144`，Apache-2.0，作为外部固定依赖安装，不 vendoring 二进制。不要误装另一个 `officecli@0.2.x` 同名项目。
- Open XML preset shape data 的 Apache/MIT provenance notice 保留在 vendor 原路径。

`0.2.1-local` 的精简包内容已获授权发布到 `double6-ai/double6-skills`。插件市场上传、OfficeCLI 二进制再分发或其它形式的对外分发仍需另行授权与 package-level 许可证审计。
