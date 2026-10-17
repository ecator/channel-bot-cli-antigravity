---
name: feishu-bot-cli-antigravity
description: 指导如何使用 feishu-bot-cli-antigravity 工具进行飞书消息发送（包含 Markdown、纯文本、管道标准输入、单/多文件附件、图文说明）以及服务监听。
metadata:
  author: Martin
---

# Feishu Bot CLI Antigravity 技能手册

`feishu-bot-cli-antigravity` 是一个基于 Google Antigravity SDK 与飞书开放平台构建的命令行与私人 AI 助手工具。本手册重点介绍如何通过命令行、管道传输以及本地文件向飞书会话**发送消息**。

---

## 1. 核心功能与运行模式

工具提供两大模式：
1. **主动发送模式 (`send`)**：通过命令行、标准输入或脚本主动向指定飞书会话（群聊/私聊）推送文本、Markdown、多附件或图文消息。**大多数情况下只需要使用 `send` 发送消息，不需要主动调用监听。**
2. **监听服务模式 (`listen`)**：启动长连接网关（WebSocket），实时接收飞书消息与多模态附件，驱动常驻 Antigravity Agent 思考并通过 CardKit 流式打字机卡片回复（常驻后台私人助手，常规消息推送无需调用）。

---

## 2. 获取目标会话 ID (`chat_id`)
- **大多数情况下由用户告知**；如果用户没有提供，请**主动引导用户提供目标 `chat_id`**。
- 群聊 `chat_id` 通常以 `oc_` 开头（例如 `oc_a1b2c3d4e5f6...`）。
- 可以在飞书群设置中查看，或运行 `listen` 模式并在群里发送任意一条消息，在控制台日志中查看捕获的 `chat_id`。

---

## 3. 命令行发送消息 (`send`) 详述

命令行发送命令统一使用 `send` 子命令。

```bash
# 推荐使用 uvx 直接执行
uvx feishu-bot-cli-antigravity send --chat-id <oc_xxx> [选项]

# 若需要指定工作目录以加载该目录下的 .env 环境变量等配置（--work-dir 为全局参数，置于子命令前）：
uvx feishu-bot-cli-antigravity --work-dir /path/to/workspace send --chat-id <oc_xxx> [选项]
# 或使用简写 -w
uvx feishu-bot-cli-antigravity -w /path/to/workspace send --chat-id <oc_xxx> [选项]
```

### 参数一览表

#### 全局参数（置于子命令前）

| 参数 | 缩写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--work-dir` | `-w` | 否 | 当前路径 | 工作目录路径（优先加载该目录下的 `.env` 环境变量文件；在 `listen` 模式下还会加载工作区技能、mcp 与 AGENTS.md） |
| `--log-level` | 无 | 否 | 环境变量 | 日志输出级别：`DEBUG`, `INFO`, `WARNING`, `ERROR`（默认: `INFO`） |

#### `send` 子命令参数

| 参数 | 缩写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--chat-id` | `-c` | **是** | 无 | 目标飞书会话 ID (`oc_...`) |
| `--message` | `-m` | 否 | `None` | 要发送的文本/Markdown 内容。若指定为 `-`，表示从 stdin 读取 |
| `--stdin` | `-s` | 否 | `False` | 显式指示从标准输入读取消息内容（与 `-m` 互斥） |
| `--file` | `-f` | 否 | `None` | 要发送的本地文件路径（支持同时传入多个路径，空格分隔） |
| `--type` | `-t` | 否 | `markdown` | 消息格式类型：`markdown`（默认）或 `text` |

> [!NOTE]
> `--message`、`--stdin` 和 `--file` 必须至少提供一项。

---

### 场景 1：发送 Markdown 格式消息（默认推荐）

飞书支持富文本 Markdown 渲染（标题、加粗、斜体、列表、超链接、引用、行内代码与代码块等）：

```bash
# 发送多行 Markdown 消息
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -m "### 🚀 构建通知
- **项目**: feishu-bot-cli-antigravity
- **状态**: 成功
- **详情**: [查看构建报告](https://github.com/ecator/feishu-bot-cli-antigravity)"
```

### 场景 2：发送纯文本消息 (`--type text`)

当不希望内容中的特殊符号（如 `_`, `*`, `[ ]`）被解析为 Markdown 时，可指定 `--type text`：

```bash
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -m "Raw string: *no markdown* [test]" --type text
```

### 场景 3：管道传输与大文本输入 (CI/CD、日志与报告推送)

针对大段 Markdown 报告、系统日志、Git Diff 或构建输出，通过标准输入（stdin）管道传输最为便捷可靠。

#### 方式 A：使用 `--stdin` / `-s` 标志
```bash
# 读取文件并通过管道推送
cat deploy_report.md | uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx --stdin

# 将命令执行输出直接推送到飞书
git diff HEAD~1 | uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -s
```

#### 方式 B：使用 `-m -` 语法
```bash
python generate_summary.py | uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -m -
```

#### 方式 C：自动管道检测
当未提供 `-m` 且未提供 `-f` 时，只要检测到标准输入为管道重定向，CLI 会自动读取 stdin：
```bash
docker logs app-backend --tail 50 | uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx
```

#### 方式 D：终端交互式多行输入
在终端直接执行，随时粘贴长篇文本：
```bash
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx --stdin
```
> [!TIP]
> 结束输入：Windows 终端请按 `Ctrl+Z` 然后回车；Linux / macOS 终端请按 `Ctrl+D`。
> 工具已内置强制 UTF-8 / UTF-8-BOM 解码与回退机制，在 Windows (CP936/GBK) 终端下可杜绝乱码问题。

---

### 场景 4：发送本地文件与图片 (`--file` / `-f`)

工具会自动检测文件扩展名：
- **图片文件**（`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.gif`）：通过飞书图片接口以原生图片气泡发送。
- **普通文件**（`.pdf`, `.zip`, `.xlsx`, `.csv`, `.docx`, `.txt` 等）：以文件卡片附件形式发送。

#### 发送单个文件/图片
```bash
# 发送单一附件
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -f ./release-v0.2.0.zip

# 发送图片
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -f ./architecture.png
```

#### 同时发送多个文件
```bash
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -f ./summary.pdf ./metrics.xlsx ./error.log
```

---

### 场景 5：图文组合与附件伴随说明

`feishu-bot-cli-antigravity` 支持将文本消息与文件同时发送：

#### 单张图片 + 说明文本（自动整合为带标题图文）
当仅发送一张图片且附带 `-m` 时，工具支持将其整合为带有 Caption 的图文消息。由于默认消息格式为 `markdown`，在此场景下需要显式指定 `-t text`（或 `--type text`），飞书端即可呈现为精美的带字配图：
```bash
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx \
  -f ./metrics_chart.png \
  -m "Q3 业务监控大盘：请各模块负责人关注 P99 延迟指标。" \
  -t text
```

#### 多个文件 + 说明文本
当指定多个文件或普通文件并附带说明时，工具会依次上传所有文件，随后紧接着发送说明文本：
```bash
uvx feishu-bot-cli-antigravity send -c oc_xxxxxxxxxxxx \
  -f ./report.pdf ./data.csv \
  -m "本日巡检报告与原始数据已生成，请审阅。"
```

---

## 4. 监听模式下的消息回复机制 (`listen`)

> [!NOTE]
> **绝大多数情况下只需要使用 `send` 发送消息，不需要主动调用监听。**
> `listen` 模式主要用于作为常驻后台服务运行，接收群聊或私聊消息并调用 AI 进行智能交互回复。若仅需向飞书推送告警、通知或文件，直接使用 `send` 即可。

了解监听模式下的消息生成与回复有助于配合双向通信：

```bash
# 启动常驻监听，接收消息并自动回复
uvx feishu-bot-cli-antigravity listen

# 仅限定监听指定会话（防止打扰其他群）
uvx feishu-bot-cli-antigravity listen -c oc_xxxxxxxxxxxx

# 显式指定工作目录（局参数置于子命令前，自动挂载该目录下的 .env、skills、mcp 与 AGENTS.md）
uvx feishu-bot-cli-antigravity -w /path/to/workspace listen
# 或使用完整参数
uvx feishu-bot-cli-antigravity --work-dir /path/to/workspace listen
```

- **思考中反馈**：机器人接收到用户提问时，会自动为用户消息打上思考中的表情 Reaction。
- **CardKit 打字机流式回复**：Agent 生成的回复将通过 CardKit 流式卡片以打字机形式动态追加（需开通 `cardkit:card:write` 权限）。
- **智能降级机制**：若无 CardKit 权限，系统自动无缝降级为标准 Markdown 消息回复；若 Markdown 发送受限则降级为纯文本回复。
- **内存多模态附件理解**：用户在飞书中发送的图片、代码文件、PDF 等附件会被直接下载至内存并交由 Antigravity SDK 解析。

---

## 5. 常见问题排查 (Troubleshooting)

1. **报错 `从标准输入读取到的内容为空`**：
   - 检查管道上游命令是否有输出；如果仅发送文件，无需传递 `-m` 或 `--stdin`。
2. **报错 `未找到待发送的文件: xxx`**：
   - 请核对相对路径或绝对路径是否正确，注意文件权限。
3. **报错 `主动发送消息必须提供 --message、--stdin 或 --file 至少一项参数`**：
   - 命令行未指定任何需要发送的消息或文件，请补充 `-m "内容"` 或 `-f "路径"`。
4. **飞书端未收到消息但命令返回成功**：
   - 确认机器人已被邀请进目标群聊中（在群设置中将机器人添加为群成员）。
   - 确认 `chat_id` 是否匹配。
5. **Windows 控制台输出或管道中文乱码**：
   - 工具内置了 UTF-8 与 UTF-8-BOM 优先解码处理；若遇到终端显示问题，可临时切换代码页：`chcp 65001`。
