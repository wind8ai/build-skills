# build-skills

将杂乱信息或低质量 Skill 整理、提炼并改进为优质 Skill 的 Python CLI 框架。

用户提供材料与目标，框架通过配置运行准备、确认、构建、执行、评估和优化步骤。它使用同一套 Skill 在多个模型和场景下执行任务，并通过保留场景验证后交付。

## 开始使用

需要 Python 3.12+、uv 和 macOS 或 Linux。

```bash
uv sync --locked
uv run build-skills --help
uv run build-skills doctor --config examples/local-files/config.toml --json
uv run build-skills loop --config examples/local-files/config.toml --json
```

首次 loop 在确认点停止，返回运行标识、待审阅文档和摘要。按照 [本地示例](examples/local-files/README.md) 审阅并确认，再继续运行。

示例使用确定性进程替身，不调用真实模型。Codex 和 Qoder 适配器已实现，真实模型与 Skill 质量验收待首套用户配置。

## 文档

- [CLI 与配置](docs/cli.md)
- [产品意图](docs/intent.md)
- [框架设计](docs/design.md)
- [实施计划](plans/001-framework.md)
- [开发约定](CONTRIBUTING.md)
