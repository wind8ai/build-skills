# Web example

在仓库根目录运行：

```bash
uv sync --locked --extra web
uv run build-skills web --config examples/web/config.toml
```

打开 http://127.0.0.1:8765 。需要其他端口时添加 `--port 8766`。

1. 上传本目录的 `materials/copy-text.md`，展开核对提取文字。
2. 点击“下一步”，填写目标，选择各阶段使用的 provider、执行模型、Loop 最大轮次、重复次数和最低分数。
3. 生成审阅草案。草案包含范围、标准、来源、开发场景与保留场景；可编辑 JSON。若有 questions，先在范围、标准或场景中落实答案，再清空 questions。
4. 勾选已审阅，点击“确认并开始构建”。等待开发测评与保留场景验证完成。
5. 复制本地交付地址，或下载 Skill ZIP 和测评 JSON。刷新页面或从“本地任务”选择任务可查看已有结果。

此例使用两个确定性进程替身，固定执行文本复制场景，不调用真实 LLM。修改目标不会让替身获得新能力；示例通过仅证明流程与交付契约工作正常。

## 真实模型

将已有的 Codex/Qoder 配置放入 `.build-skills/` 下，用 `--config` 指向它。配置须满足现有 CLI 的校验规则，包括可读取的初始 materials。Web 新任务会以本次上传材料替换 materials，并创建独立 workspace。可参考 [CLI 配置说明](../../docs/cli.md)。

网页显示本地配置中的 provider，允许填写模型名称和思考等级，并分配准备、构建、评估、改进职责。可选择多个执行模型。不内置容易过期的模型目录；有效模型名称和思考等级由对应 CLI 校验。命令、权限、阶段调用预算、超时和提示模板沿用本地配置。网页不接收任意命令或凭据。

启动前完成相应 CLI 登录。真实运行会按照 provider 配置向模型服务发送提取文字、任务内容及运行证据；“本地”指 Web、文件存储和进程运行位置，不表示模型推理离线。

## 文件支持

| 类型 | 处理方式与限制 |
| --- | --- |
| TXT、Markdown、CSV、JSON、YAML、RST | UTF-8 文本读取 |
| PDF | 提取每页文字；加密文件需先解密，无文字页面需先 OCR |
| Word `.docx` | 按正文顺序读取段落与表格；图片、批注及页眉页脚不作为正文导入 |
| Word `.doc` | macOS 使用系统 textutil；其他系统请先转存 `.docx` |
| JPG、PNG | Tesseract OCR，只识别文字，不理解图表或视觉布局 |

最多 20 个文件，单文件 10 MB，总计 50 MB；提取文字单文件不超过 1 MB、合计不超过 5 MB。上传后应核对提取内容，确认没有影响任务的遗漏。

图片需要在本机安装 Tesseract。中文图片还需要 `chi_sim` 语言包；已安装时自动使用 `chi_sim+eng`，否则使用英文 OCR。macOS 可运行 `brew install tesseract tesseract-lang`；Linux 使用发行版的 Tesseract 及简体中文语言包。扫描 PDF 请先完成 OCR，或将页面转成 JPG/PNG 上传。

## 本地保存与提交边界

所有上传原件、提取文本、配置快照、调用证据、草案、测评报告与 ZIP 写入 `.build-skills/web/`，该目录已被 Git 忽略。任务路径以网页显示为准，形如：

```text
.build-skills/web/materials/<material-id>/
.build-skills/web/jobs/<job-id>/config.toml
.build-skills/web/jobs/<job-id>/runs/<job-id>/delivery/
.build-skills/web/jobs/<job-id>/delivery.zip
```

应提交 Web 源码、依赖锁文件、测试、公开合成 example 和说明。不提交真实输入、内部资料、模型凭据、本地配置、运行证据、下载包、缓存和服务日志。不要将真实材料放入 examples；清理本地数据前先停止服务并确认不再需要对应任务。

只监听 `127.0.0.1`，供本机单用户使用。浏览器关闭不影响运行，停止服务会中断管理线程；若重启后提示此前模型进程仍在运行，应先检查该运行的 CLI 证据，不能盲目重复执行。失败后可查看测评 JSON；需要只重试失败执行或恢复构建调用时，使用网页显示的运行标识和配置路径，按现有 CLI 的 `--retry-failed` / `--recover-call` 操作，再刷新网页。“继续执行”复用 CLI loop，不修改预算或跳过验证。
