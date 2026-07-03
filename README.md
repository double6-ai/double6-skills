# Double6 Skills

Double6 AI 维护的本地可执行 agent skills 仓库。

## 项目内容

- `double6-pdf-translation`：面向英文 PDF 和学术论文的高保真中文翻译 skill。它依赖外部 PDF 后端保留版式，保护术语与结构化片段，生成文本/视觉 QA 证据，并为需要局部重渲染的页面保留修复产物。

## 安装

将 `double6-pdf-translation` 安装到你的 agent skills 目录：

```bash
mkdir -p <agent-skills-dir>
cp -R skills/double6-pdf-translation <agent-skills-dir>/
```

安装后可按名称调用。Codex、Claude Code 或其它支持本地 shell 执行的 agent 可使用各自的 skill 目录或适配器配置：

```text
Use $double6-pdf-translation to translate this PDF into accurate, readable Simplified Chinese.
```

## 许可

本仓库使用 MIT License 发布。运行时依赖不随仓库分发，详见 `skills/double6-pdf-translation/references/runtime-dependencies.md`。
