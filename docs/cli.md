# CLI 使用

## 安装

要求 Python 3.12 或更新版本、uv、macOS 或 Linux。进程组清理和运行锁使用 POSIX 接口，暂不支持 Windows。

```bash
uv sync --locked
uv run build-skills --help
```

uv 在仓库内使用 `.venv`。命令入口也可通过 `.venv/bin/build-skills` 调用。构建安装 wheel 后，可在仓库外运行；阶段默认模板随包安装。

## 配置

参考 [本地文件配置](../examples/local-files/config.toml) 和 [模板](../examples/local-files/template.toml)。任务配置通过 `template` 引用一个 TOML 模板，可覆盖同名顶层配置组，不递归合并子字段。例如覆盖 execution 时需要重新提供整个 execution 组。

任务配置保存 name、goal、materials、workspace；模板通常保存 providers、roles、execution、limits、quality 和可选 prompts。材料支持 UTF-8 文本文件和 Skill 目录。单文件最多 1 MB，总材料最多 5 MB，不跟随符号链接。

材料与 workspace 相对路径基于任务配置所在目录。provider 的 command 是参数数组；其中 `{config_dir}`、`{template_dir}` 分别展开为任务配置和模板所在目录。程序由框架直接启动，不经过 shell。需要脚本时使用这些显式路径，不能依赖 Agent 的当前目录定位脚本。

每个 provider 包含 kind、command、model 和 permission。kind 为 codex、qoder 或 command。真实适配器必须指定 model，可用 reasoning_effort 配置推理强度，例如 Codex 的 high。command 用于可控外部程序或自定义接入，stdin 接收 stage、prompt、context 和 schema 的 JSON。

构建和改进阶段将完整文件写到当前目录的 `skill/`。准备和评估阶段写 `response.json`，内容按提供的 JSON Schema 在本地校验。执行阶段保留最终文本、文件变化和日志。最终聊天消息只需简短说明完成情况，无需再返回一份完整 Skill JSON；Codex 不再使用服务端 `--output-schema`。只有进程成功退出且文件校验通过，阶段才成功，失败过程留下的文件保留作证据。

execution.git_repository 为 true 时，每个任务目录初始化独立 Git 仓库，防止 Agent 的 Git 命令向上落到框架仓库。默认为 false。

permission 为 restricted 或 full，默认 restricted。full 显式映射到 CLI 完整权限设置。所有 Agent 在独立工作目录启动，但完整权限可以访问目录外资源，目录本身不是系统沙箱。command 程序的权限由程序及其运行环境控制。

roles 必须包含 prepare、build、evaluate、improve；execution.models 引用 provider 名称。真实模型由用户模板配置，框架不预设。实际模型接入与输出格式需要首次真实运行验收，尤其是 Qoder 的 print 输出。

prompts 可按阶段覆盖内联 Jinja 模板。材料通过 data 传入，不能直接拼到 Jinja 模板源码中。构建阶段的 data 包含原始材料快照，避免整理摘要丢失细节。可用变量为 data、schema、goal 和 task。默认模板由包提供；execute 模板用于用户任务，不包含评估标准或其他模型结果。保留场景仅在 verify 阶段提供给执行者，完整权限环境不具备强制的信息隔离。

## 单步与循环

所有阶段使用 `--config`；操作已有运行时使用 `--run`。`--json` 使 stdout 成为一个 JSON 结果，便于脚本调用。

| 命令 | 用途 |
| --- | --- |
| doctor | 校验配置、路径和程序存在性，不验证账号或模型额度 |
| prepare | 整理材料和反馈，提出范围、标准与开发及保留场景 |
| status | 读取状态、待审阅文件及其当前摘要 |
| approve --accept DIGEST | 确认指定版本的范围和标准；questions 必须已解决 |
| build | 创建首个候选 Skill |
| execute | 按模型、开发场景和重复次数执行 |
| evaluate | 直接检查加匿名模型判断，逐条保存证据 |
| improve | 根据开发失败改进 Skill，消耗新一轮预算 |
| verify | 执行保留场景并判断最终结果 |
| deliver | 导出经过验证的准确版本与报告 |
| feedback --file PATH | 保存实际使用问题，供同工作区下一次 prepare 读取 |
| loop | 从头运行或继续已有运行，遇到确认、未达标或失败时退出 |

开发与保留场景都在 brief.json 中供用户审阅；优化阶段的模型输入不包含保留场景。场景包含 id、task、files 和 checks；checks 支持文件存在、精确文本 equals 和子串 contains。格式受包内模型定义约束，prepare 会向模型提供对应 JSON Schema。

brief 可以在 approve 前编辑。启动构建后修改 brief、配置或原始材料，需要新建运行。新的保留场景应与先前已用于评估的场景不同；框架不自动保证用户提供的不同文本具有统计独立性。

## 失败与恢复

| 退出码 | 含义 |
| --- | --- |
| 0 | 本命令成功；只有 delivered 状态表示 Skill 已交付 |
| 2 | 参数、配置、文件或文档校验失败 |
| 3 | 等待用户确认 |
| 4 | 未达标或预算耗尽 |
| 5 | 外部 Agent 调用失败或运行冲突 |
| 130 | 用户中断 |

limits.max_rounds 限定优化循环的轮数。prepare、build、improve、execute、evaluate 分别配置 timeout_seconds、max_calls 和 total_seconds，数值 0 表示不限制。构建与改进默认不限制；执行默认单次十五分钟，准备和评估默认单次十分钟。

```toml
[limits.build]
timeout_seconds = 0
max_calls = 0
total_seconds = 0

[limits.execute]
timeout_seconds = 900
max_calls = 0
total_seconds = 0

[limits.evaluate]
timeout_seconds = 600
```

execute 的限制按每个执行模型独立累计，跨场景和轮次使用；一个模型不会消耗其他模型的额度。其他阶段各自累计。构建耗时不扣减执行或评估预算。数值校验和模板渲染在扣额度前完成。status 的 usage 显示各阶段或模型的使用量；进行中的有限调用包含预留时间，结束后按实际时间结算。

模板只限制本框架的进程调用，不能覆盖供应商自身额度或内部重试策略。框架不计费，也不能用 CLI 调用次数推算供应商内部请求数或金额。

执行失败或超时后，框架记录失败并继续其他模型，矩阵完成后返回非零退出码。evaluate 仍能评估已完成部分，缺失任务强制判定未完成；一次调用匿名批量评估，标签由框架分配并核验。loop 会保存部分评估后停止，不将基础设施故障自动转成 Skill 优化任务。

再次 execute 默认读取已有结果，不重复调用。使用 `execute --retry-failed` 只重试失败任务；verify 同样支持该选项，已完成但质量未通过的任务不会重跑。重试消耗该模型剩余额度，成功后重新评估更新的矩阵。所有旧文档版本保存在 history/。进程中断前未完成的任务会在新目录重试；外部副作用不保证恰好一次。原始 stdout、stderr 与结构化结果保留在工作区，默认只在本地保存。

保留场景验证未达标时，当前运行停止。继续改进需要新运行和新的保留场景。交付目录只包含 Skill 文件及验证报告，不包含整个运行目录。

Skill 的附属资源需通过 Markdown 链接从 SKILL.md 可达。框架拒绝路径别名、大小写冲突和未引用资源，防止打包时覆盖或夹带无关文件。


旧实验的全局 limits 配置和 JSON stdout 接入协议已移除。旧运行记录保留用于查看；使用新模板启动新运行，不将旧状态迁移成成功状态。
