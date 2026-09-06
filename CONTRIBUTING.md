# 开发

固定使用 Python 3.12，允许该版本的补丁更新。使用 uv 创建和同步项目 `.venv`：

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src/build_skills
uv run pytest
uv build
```

新增行为通过 CLI 集成测试覆盖。外部进程替身用于验证框架契约；真实模型结果单独验收。新增运行产物写到 `.build-skills/` 或仓库外，不写入源码和 examples。

提交使用 Conventional Commits，例如 `feat: add feedback import` 或 `fix: preserve failed run evidence`。PR 描述写明问题、最终行为和验证结果。只提交相关改动，保持依赖锁文件与 pyproject.toml 一致。

本仓库为私有框架工程。发布包、公开仓库或更改远端规则需要单独决定。

验证时先运行改动直接涉及的测试。交付前在项目 `.venv` 中运行一次完整测试；检查通过后，只有新改动、失败或未解决的问题才需要重跑。不额外创建其他 Python 版本环境。纯文档和配置修改采用对应的轻量检查。
