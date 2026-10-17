# Channel Bot CLI Antigravity

[![Python Version](https://img.shields.io/badge/python->=3.14-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Google Antigravity](https://img.shields.io/badge/Powered%20by-Google%20Antigravity-orange.svg)](https://github.com/google/antigravity)
[![Channels](https://img.shields.io/badge/IM%20Channels-Feishu%20%7C%20DingTalk-brightgreen.svg)](#)

通用企业级多渠道（**飞书 Feishu / Lark** & **钉钉 DingTalk**）即时通讯 AI 智能助手、命令行工具与双工长连接服务网关。

基于 **Google Antigravity SDK**、**`lark-channel-sdk`** 与 **`dingtalk-channel-sdk`** 深度构建，支持双工 WebSocket Stream 长连接监听、AI 卡片打字机流式输出、主动消息/多媒体附件投递，以及细粒度会话并发隔离与零磁盘内存多模态流转。

---

## 核心特性

- 🌐 **双平台全特性适配 (Feishu & DingTalk)**：
  - **飞书**：支持 WebSocket 长连接、CardKit 流式打字机卡片、Reaction 思考中表情反馈与多媒体附件直传。
  - **钉钉**：支持 Stream 模式双向长连接、AI 卡片流式打字机、思考/完成状态流转卡片与主动单聊/群聊推送。
- 🔄 **双通道并发监听 (`--channel all`)**：
  - 支持单进程内同时建立飞书与钉钉的双工长连接，共享相同的会话调度器与 Agent 上下文，充当全企业统一的跨平台 AI 机器人网关。
- 🔀 **3 级流式回显与平滑降级机制 (3-Tier Streaming & Fallback)**：
  1. **第一级 (卡片打字机)**：优先使用飞书 CardKit 或钉钉 AI Card 打字机实时动态流式回显思考与生成内容；
  2. **第二级 (标准 Markdown)**：若平台卡片未授权或创建失败，无缝降级为标准 Markdown 富文本消息回复；
  3. **第三级 (纯文本)**：若富文本解析受限，保底降级为纯文本 (Plain Text) 发送，确保对话链路 100% 高可用。
- 🔒 **细粒度会话并发隔离 (`channel:chat_id` Locks)**：
  - 每个会话维护独立的并发互斥锁（`asyncio.Lock`），实现同一群聊/私聊内的并发消息排队串行消费，彻底杜绝上下文污染与回复穿插。
  - 不同群聊与平台之间全异步并发执行，互不阻塞。
- 💾 **零磁盘内存多模态管道 (Zero-Disk In-Memory Media Pipeline)**：
  - 接收到的用户图片、音频、PDF、代码等文件全部拉取至内存缓冲区，通过 `create_media_from_bytes` 统一转化为 Antigravity 原生 Media 对象。全程无任何磁盘临时文件残留，安全且高效。
- 📋 **统一 YAML Frontmatter 消息归一化**：
  - 异构平台的事件消息清洗归一化，自动为 Agent 注入清晰的会话上下文元数据：
    ```yaml
    ---
    channel: feishu | dingtalk
    chat_id: "..."
    sender_id: "..."
    message_id: "..."
    create_time: "..." # ISO 8601 UTC
    chat_type: "p2p" | "group"
    ---
    ```
- 🖥️ **跨平台管道与编码保护 (Windows UTF-8 Safe)**：
  - 完美支持标准输入 (`stdin`) 管道输入，内置强鲁棒性的 UTF-8 / UTF-8-SIG 解码与回退机制，彻底避免 Windows 终端下的代码页乱码问题。

---

## 环境配置

在项目根目录或指定的工作目录下创建 `.env` 文件进行配置：

### 环境变量一览表

| 环境变量名 | 所属模块 / 渠道 | 必填项 | 默认值 | 说明与示例 |
|---|---|---|---|---|
| `DD_CLIENT_ID` | 钉钉 (DingTalk) | 是 (使用钉钉时) | 无 | 钉钉企业内部应用 AppKey (即 Client ID) |
| `DD_CLIENT_SECRET` | 钉钉 (DingTalk) | 是 (使用钉钉时) | 无 | 钉钉企业内部应用 AppSecret (即 Client Secret) |
| `FEISHU_APP_ID` | 飞书 (Feishu) | 是 (使用飞书时) | 无 | 飞书企业自建应用 App ID（向后兼容 `LARK_APP_ID`） |
| `FEISHU_APP_SECRET` | 飞书 (Feishu) | 是 (使用飞书时) | 无 | 飞书企业自建应用 App Secret（向后兼容 `LARK_APP_SECRET`） |
| `FEISHU_DOMAIN` | 飞书 (Feishu) | 否 | `open.feishu.cn` | 开放平台接口域名。国内节点为 `https://open.feishu.cn`；海外版 Lark 请配置为 `https://open.larksuite.com`（向后兼容 `LARK_DOMAIN`） |
| `GEMINI_API_KEY` | Antigravity 智能体 | 是 (使用 Agent 时) | 无 | Google Gemini API 凭证密钥 |
| `AGY_MODEL` | Antigravity 智能体 | 否 | SDK 默认 | Agent 主对话推理模型（如 `gemini-2.5-flash`、`gemini-3.8-flash`） |
| `AGY_IMAGE_MODEL` | Antigravity 智能体 | 否 | SDK 默认 | Agent 绘图生图模型（如 `gemini-3.1-flash-lite-image`、`imagen-3.0-generate-002`） |
| `LOG_LEVEL` | 系统全局 | 否 | `INFO` | 日志输出级别：`DEBUG`, `INFO`, `WARNING`, `ERROR` |

### 完整的 `.env` 配置范例

```env
# ==========================================
# 1. 钉钉凭据 (DingTalk Credentials)
# ==========================================
DD_CLIENT_ID=dingxxxxxxxxxxxx
DD_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ==========================================
# 2. 飞书凭据 (Feishu Credentials)
# ==========================================
FEISHU_APP_ID=cli_xxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# FEISHU_DOMAIN=https://open.feishu.cn

# ==========================================
# 3. Google Antigravity & 模型配置
# ==========================================
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxx
AGY_MODEL=gemini-2.5-flash
AGY_IMAGE_MODEL=gemini-3.1-flash-lite-image

# ==========================================
# 4. 全局日志输出级别
# ==========================================
LOG_LEVEL=INFO
```

### 凭据申请与配置指南

#### 钉钉 (DingTalk) 凭据获取：
1. 登录 [钉钉开发者后台](https://open-dev.dingtalk.com/)，创建或进入已有“企业内部开发应用”；
2. 在“凭证与基础信息”中获取 **AppKey**（对应 `DD_CLIENT_ID`）与 **AppSecret**（对应 `DD_CLIENT_SECRET`）；
3. 进入“应用能力” -> “机器人”，开启机器人配置，消息接收模式选择 **Stream 模式**（无需公网服务器与 Webhook 域名配置）；
4. 进入“权限管理”，开通所需的机器人消息发送、群聊与接口调用权限。

#### 飞书 (Feishu) 凭据获取：
1. 登录 [飞书开放平台](https://open.feishu.cn/)，创建“企业自建应用”；
2. 在“凭证与基础信息”中获取 **App ID**（对应 `FEISHU_APP_ID`）与 **App Secret**（对应 `FEISHU_APP_SECRET`）；
3. 在“添加应用能力”中添加“机器人”能力；
4. 在“事件与回调”中选择“使用长连接接收事件 (WebSocket Stream)”；
5. 添加以下权限项：
   - 接收消息：`im:message`、`im:message.p2p_msg:readonly`、`im:message.group_at_msg:readonly`；
   - 发送消息：`im:message:send_as_bot`；
   - 打字机流式卡片 (可选)：`cardkit:card:write`；
6. 创建版本并发布上线。

---

## 快速开始

> [!NOTE]
> **关于 `uvx` 运行时依赖说明**：
> 由于目前钉钉官方尚未把 `dingtalk-channel-sdk` 发布到 PyPI，使用 `uvx` 免安装运行时需要通过 `--with` 指定其 Git 仓库依赖：
> ```bash
> uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity
> ```
> *注：待钉钉官方正式将 `dingtalk-channel-sdk` 发布至 PyPI 后，即可移除 `--with` 部分，直接使用 `uvx channel-bot-cli-antigravity` 执行。*

推荐直接使用 `uvx` 免安装运行（需安装 [uv](https://github.com/astral-sh/uv)）：

```bash
# 查看帮助文档
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity --help

# 启动双通道并发监听
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen --channel all

# 命令行主动发送一条通知
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --chat-id <目标会话ID> -m "Hello from channel-bot-cli-antigravity!"
```

若在本地克隆代码开发：

```bash
# 安装依赖
uv sync

# 运行长连接服务
uv run channel-bot-cli-antigravity listen

# 执行测试用例
uv run pytest
```

---

## CLI 命令行使用指南

> [!TIP]
> **命令执行说明**：当前所有 `uvx` 示例均使用 `uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity` 执行。待钉钉官方正式将 `dingtalk-channel-sdk` 发布到 PyPI 后，即可简化为 `uvx channel-bot-cli-antigravity`。

### 全局参数（置于子命令之前）

| 参数 | 缩写 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `--work-dir` | `-w` | 否 | 当前路径 | 指定工作目录，自动加载该目录下的 `.env`、`AGENTS.md`、`skills` 与 `mcp_config.json` |
| `--log-level` | 无 | 否 | `INFO` | 设置日志输出级别：`DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

### 1. 长连接服务监听 (`listen` / `serve`)

启动常驻 WebSocket Stream 长连接网关，实时接收消息、下载内存多模态附件并调用 Antigravity Agent 进行多轮思考与流式卡片回复。

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen [选项]
# 或使用等价别名
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity serve [选项]
```

#### 选项说明

- `--channel {dingtalk,feishu,all}`：指定监听通道。
  - `all`：**双通道并发监听模式**。同时启动飞书和钉钉长连接，共享相同的会话管理器与 Agent 生命周期。
  - `dingtalk`：仅监听钉钉通道。
  - `feishu`：仅监听飞书通道。
  - *未指定时*：按环境变量配置自动推断（优先钉钉，若仅有飞书凭据则推断为飞书）。
- `--chat-id`, `-c <CHAT_ID>`：可选过滤参数。指定后仅响应该会话的消息，其他会话消息自动忽略。

#### 实战范例

```bash
# 启动双通道并发常驻监听网关（生产推荐）
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen --channel all

# 单独启动飞书长连接监听
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen --channel feishu

# 单独启动钉钉长连接监听
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen --channel dingtalk

# 仅响应指定群聊或私聊（防止测试期间打扰其他群组）
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen --channel feishu --chat-id oc_a1b2c3d4e5f6

# 指定特定项目工作目录（加载该工作区的 .env、AGENTS.md 行为约束及技能）
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity -w /path/to/my-agent-workspace listen --channel all
```

---

### 2. 命令行主动发送消息 (`send`)

支持向指定的群聊或单聊会话主动推送富文本 Markdown、纯文本、本地多文件附件或通过管道输入构建输出与监控日志。

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --chat-id <目标会话ID> [选项]
```

#### 选项说明

- `--chat-id`, `-c <CHAT_ID>`：**必填**。目标会话 ID：
  - **飞书**：群聊 ID 以 `oc_...` 开头，单聊用户 ID 以 `ou_...` 开头；
  - **钉钉**：群聊会话 ID 以 `cid...` 开头（即 openConversationId），单聊用户 ID 使用员工 `userId`。
- `--channel {dingtalk,feishu}`：目标渠道。未指定时根据环境变量自动推断（钉钉优先）。
- `--message`, `-m <TEXT>`：要发送的文本/Markdown 内容。若指定为 `-`，表示从标准输入读取。
- `--stdin`, `-s`：指示从标准输入读取内容（与 `-m` 互斥）。
- `--file`, `-f <PATHS...>`：待发送的本地文件路径，支持同时指定多个文件（空格分隔）。
- `--type`, `-t {markdown,text}`：消息格式，默认为 `markdown`。

> 💡 **提示**：`--message`、`--stdin` 和 `--file` 必须至少提供一项。

#### 实战范例

##### 场景 A：发送 Markdown 格式消息（默认推荐）

```bash
# 向钉钉群发送构建完成报告
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  --channel dingtalk \
  --chat-id cid_xxxxxxxxxxxx \
  -m "### 🚀 CI/CD 构建已完成
- **项目**: channel-bot-cli-antigravity
- **分支**: main
- **测试通过率**: 100% (284/284)
- **状态**: :white_check_mark: Success"

# 向飞书群发送相同格式通知
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  --channel feishu \
  --chat-id oc_xxxxxxxxxxxx \
  -m "### 📢 系统巡检通知\n所有微服务健康指标正常运行。"
```

##### 场景 B：发送纯文本消息 (`--type text`)

当文本中包含特殊字符（如代码片段、带有 `_` 或 `*` 的日志文本）且不希望被解析为 Markdown 排版时：

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  --chat-id oc_xxxxxxxxxxxx \
  -m "原始配置串: token_abc*123_[prod]" \
  --type text
```

##### 场景 C：管道标准输入推送 (CI/CD、日志与运维脚本)

针对持续集成产物、大段 Markdown 报告或系统输出日志，无需临时保存文件，直接通过标准输入推送：

```bash
# 1. 显式使用 --stdin / -s
cat deploy_report.md | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send -c oc_xxxxxxxxxxxx --stdin

# 2. 将 Git Diff 直接推送到指定钉钉群
git diff HEAD~1 | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --channel dingtalk -c cid_xxxxxxxxxxxx -s

# 3. 使用 -m - 语法
python generate_summary.py | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -m -

# 4. 自动管道识别（未提供 -m 与 -f 时，自动从管道读取）
docker logs web-backend --tail 80 | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send -c oc_xxxxxxxxxxxx

# 5. 交互式多行输入（按 Ctrl+Z 回车 [Windows] 或 Ctrl+D [Linux/macOS] 提交）
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send -c oc_xxxxxxxxxxxx --stdin
```

##### 场景 D：发送本地文件与图片 (`--file` / `-f`)

工具会自动识别扩展名并适配各平台的媒体接口：
- **图片**（`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.gif`）：以原生图片气泡/图片卡片呈现；
- **文件**（`.pdf`, `.zip`, `.xlsx`, `.csv`, `.docx`, `.txt` 等）：以文件消息或附件卡片呈现。

```bash
# 发送单张图片
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send -c oc_xxxxxxxxxxxx -f ./docs/architecture.png

# 同时发送多个文件与图表
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  -c cid_xxxxxxxxxxxx \
  -f ./release.zip ./summary.pdf ./metrics.png \
  -m "附件为本期发布包与指标分析报告，请查阅。"
```

---

### 3. 版本信息查询 (`version`)

```bash
# 查看标准版本信息
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity version
# 输出示例: channel-bot-cli-antigravity 0.1.dev0+d20261017

# 仅输出版本号 (适合脚本解析)
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity version --short
# 输出示例: 0.1.dev0+d20261017
```

---

## 全局工作目录与上下文扩展 (`--work-dir`)

`--work-dir` / `-w` 参数允许你在任何目录下执行命令时，指定特定的 Agent 业务工作空间：

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity --work-dir /path/to/my-agent-workspace listen --channel all
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity -w /path/to/my-agent-workspace send -c oc_xxx -m "同步消息"
```

### 工作目录资源加载规范

当指定了 `--work-dir`（未指定时默认为当前命令运行目录），系统会自动按以下约定联动检索与挂载资源：

1. **`.env`（环境变量隔离）**：优先加载该工作目录下的 `.env` 文件。支持针对不同业务项目维护独立的凭据与模型参数；
2. **`AGENTS.md`（行为指令与系统 Prompt）**：自动读取工作目录根路径下的 `AGENTS.md`，作为 Antigravity Agent 的核心行为准则、专业设定与安全约束；
3. **`skills/` 与 `.agents/skills/`（自定义技能扩展）**：自动探测工作目录下的技能包，为 Agent 动态注册专属工具与可执行功能；
4. **`.agents/mcp_config.json`（Model Context Protocol 服务）**：自动解析加载 MCP 配置，让 Agent 无缝桥接外部系统服务。

### MCP (Model Context Protocol) 扩展配置

在工作目录下放置 `.agents/mcp_config.json`，即可为常驻 Agent 接入强大的外部工具集：
- 支持 `stdio`（本地进程/脚本）与 `http` / `sse`（远程流式服务）两种传输类型；
- 支持在参数与环境变量中使用 `${VAR_NAME}` 语法自动展开系统环境变量。

#### `.agents/mcp_config.json` 配置范例

```json
{
  "mcpServers": {
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "./data"]
    },
    "remote-tools": {
      "serverUrl": "https://mcp.internal.example.com/sse",
      "headers": {
        "Authorization": "Bearer ${INTERNAL_MCP_TOKEN}"
      }
    }
  }
}
```

---

## Agent 技能安装 (Skill)

如果你的主 AI Agent（如 Antigravity CLI、Claude Code 等）支持技能规范，可通过一行命令直接接入：

```bash
npx skills add https://github.com/ecator/channel-bot-cli-antigravity --skill channel-bot-cli-antigravity
```

安装后，Agent 将自动学习如何识别飞书和钉钉的会话 ID，并在需要主动告知用户、发送报表文件或交付成果时，自主调用 CLI 完成双渠道精准推送。

---

## 工程规范与测试

本项目遵循严格的代码规范与高覆盖率自动化测试。

```bash
# 1. 运行自动化测试套件 (包含单测、并发压力与边界测试)
uv run pytest

# 2. 代码静态规范检查
uv run ruff check

# 3. 代码格式化校验
uv run ruff format --check
```

---

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。
