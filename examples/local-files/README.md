# 本地文件示例

本例演示框架的准备、确认、执行和交付流程。它调用仓库内的确定性进程替身，不调用模型，也不证明生成的 Skill 具备泛化能力。示例材料与替身均为手工维护的工程测试数据。

从仓库根目录执行：

```bash
uv sync --locked
uv run build-skills doctor --config examples/local-files/config.toml --json
uv run build-skills loop --config examples/local-files/config.toml --json
```

首次 loop 以退出码 3 停止。读取输出中的 `brief_path`，审阅任务范围、标准和场景。需要修改时直接编辑该文件，然后用 status 获取最新 `brief_digest`。

把输出中的运行标识和摘要代入以下命令：

```bash
uv run build-skills approve --config examples/local-files/config.toml --run RUN_ID --accept BRIEF_DIGEST --json
uv run build-skills loop --config examples/local-files/config.toml --run RUN_ID --json
```

成功结果中的 `delivery` 指向交付目录。所有运行文件写入被 Git 忽略的 `.build-skills/example/`。再次调用相同 loop 会验证并读取已有交付，不重新执行模型调用。

需要观察各阶段时，在确认后依次调用 build、execute、evaluate、verify、deliver，均使用同一配置与运行标识。未达标时可以调用 improve，再执行和评估；完整循环会自动处理开发阶段的改进。
