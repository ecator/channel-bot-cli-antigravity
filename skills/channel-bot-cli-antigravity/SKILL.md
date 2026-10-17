---
name: channel-bot-cli-antigravity
description: Comprehensive multi-channel IM bot CLI & service gateway (Feishu & DingTalk) with Antigravity Agent. 指导如何在命令行或脚本中使用 channel-bot-cli-antigravity 向钉钉 (DingTalk) 与飞书 (Feishu) 主动发送文本、Markdown、单/多文件附件及管道输入，以及启动双通道双工长连接监听网关。
metadata:
  author: Martin
---

# Channel Bot CLI Antigravity 技能手册

`channel-bot-cli-antigravity` 是一个基于 Google Antigravity SDK 与企业级即时通讯平台（飞书 Feishu / 钉钉 DingTalk）构建的通用 IM 智能助手与服务网关。本手册为智能体与开发者提供完整的命令行操作、参数规范、工作流集成与实战示例。

---

## 1. 智能体行动指南 (Agent Action Guide)

> [!IMPORTANT]
> **关于 `uvx` 运行时依赖说明**：
> 由于目前钉钉官方尚未把 `dingtalk-channel-sdk` 发布到 PyPI，通过 `uvx` 独立运行时必须携带 `--with` 参数以指定 Git 仓库依赖：
> ```bash
> uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity <subcommand>
> ```
> *注：待钉钉官方正式将 `dingtalk-channel-sdk` 发布至 PyPI 后，即可移除 `--with` 部分，直接使用 `uvx channel-bot-cli-antigravity` 执行。*

当作为自主智能体（Autonomous Agent）使用本技能时，请遵循以下核心原则：

1. **主动发送为主 (`send`)**：
   - 在 99% 的自动化运维、开发报告推送、CI/CD 通知、测试结果反馈及告警场景中，**仅需调用 `send` 命令**。
   - **严禁擅自启动 `listen`**，除非用户明确要求“启动后台监听服务”、“运行机器人网关”或“作为长连接 Daemon 运行”。
2. **确定目标渠道 (`--channel`)**：
   - 钉钉渠道：显式指定 `--channel dingtalk`。
   - 飞书渠道：显式指定 `--channel feishu`。
   - 若用户未指定渠道且会话 ID 无明显特征，CLI 会根据环境变量自动推断（优先检测钉钉凭据 `DD_CLIENT_ID`，其次检测飞书凭据 `FEISHU_APP_ID`；若均未配置默认优先 `dingtalk`）。
3. **获取会话标识 (`--chat-id` / `-c`)**：
   - `chat_id` 为发送消息的必填参数。若用户提示词中未提供，**必须主动引导用户提供目标 `chat_id`**。
   - **飞书 (Feishu)**：
     - 群聊 ID 通常以 `oc_` 开头（如 `oc_a1b2c3d4e5f6...`）。
     - 用户私聊 ID 通常为 `ou_...` 或用户 open_id。
   - **钉钉 (DingTalk)**：
     - 群聊 ID 通常以 `cid` 或 `chat` 开头（如 `cid123456...` 或 `chatxxxxxxxx`，即 openConversationId）。
     - 用户私聊 ID 通常为员工的 `staff_id` 或 `userId`（如 `012345678`）。
   - 允许携带渠道前缀（如 `feishu:oc_xxx` 或 `dingtalk:cid_xxx`），系统内部会自动剥离统一处理。
4. **格式与多模态文件处理**：
   - 默认推荐使用 Markdown 格式（`--type markdown`），支持排版标题、加粗、表格、代码块与链接。
   - 发送程序日志、长文本或构建输出时，优先采用管道标准输入（`--stdin` 或 `-m -`）。
   - 发送本地图片或报告附件时，使用 `--file` / `-f`（支持多文件混合投递）。

---

## 2. 凭据与环境配置

在执行命令所在路径或指定的工作目录（`--work-dir`）下配置 `.env` 文件：

```env
# ==========================================
# 钉钉凭据 (DingTalk Credentials)
# ==========================================
DD_CLIENT_ID=dingxxxxxxxxxxxxxx
DD_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ==========================================
# 飞书凭据 (Feishu Credentials)
# ==========================================
FEISHU_APP_ID=cli_xxxxxxxxxxxxxx
FEISHU_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
# 兼容历史变量名: LARK_APP_ID / LARK_APP_SECRET
# 可选: 企业自建飞书域名 (默认官方开放平台)
# FEISHU_DOMAIN=https://open.feishu.cn

# ==========================================
# Antigravity Agent 与大模型配置 (可选)
# ==========================================
GEMINI_API_KEY=AIzaxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AGY_MODEL=gemini-3.8-flash
AGY_IMAGE_MODEL=gemini-3.1-flash-lite-image
LOG_LEVEL=INFO
```

---

## 3. CLI 命令完整参数规范

### 3.1 全局参数（置于子命令前）

全局参数控制运行环境与日志级别，在 `send` 与 `listen` 模式下均有效：

| 参数 | 缩写 | 必填 | 默认值 | 详细说明 |
|---|---|---|---|---|
| `--work-dir` | `-w` | 否 | 当前终端工作目录 | 指定工作目录路径。系统优先加载该目录下的 `.env`；在 `listen` 模式下还会动态挂载该目录下的 `AGENTS.md` 规则、`.agents/skills` 技能包以及 `.agents/mcp_config.json` |
| `--log-level` | 无 | 否 | `INFO` | 设置控制台日志输出级别：`DEBUG`, `INFO`, `WARNING`, `ERROR`（优先于环境变量 `LOG_LEVEL`） |

示例：
```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity --work-dir /path/to/project --log-level DEBUG send ...
```

---

### 3.2 `send` 子命令：主动发送消息与文件

主动向指定渠道的会话推送文本、Markdown、多文件附件或标准输入流。

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --chat-id <ID> [选项]
```

#### 参数一览表

| 参数 | 缩写 | 必填 | 默认值 | 详细说明 |
|---|---|---|---|---|
| `--chat-id` | `-c` | **是** | 无 | 目标会话 ID。飞书群聊 (`oc_...`) / 飞书用户 (`ou_...`)；钉钉群聊 (`cid...`) / 钉钉用户 (`userId`) |
| `--channel` | 无 | 否 | 自动推断 | 目标 IM 平台：`dingtalk`（钉钉）或 `feishu`（飞书）。未指定时按已配置的环境变量自动推断（优先钉钉） |
| `--message` | `-m` | 否 | `None` | 要发送的消息文本或 Markdown。若指定为 `-`，表示从标准输入 (stdin) 读取 |
| `--stdin` | `-s` | 否 | `False` | 显式指示从标准输入读取消息内容（与 `--message` 互斥） |
| `--file` | `-f` | 否 | `None` | 要发送的本地文件路径，支持同时传入多个路径（空格分隔） |
| `--type` | `-t` | 否 | `markdown` | 消息格式类型：`markdown`（默认推荐）或 `text`（纯文本） |

> [!IMPORTANT]
> **参数校验约束**：`--message`、`--stdin` 和 `--file` 必须至少提供一项，否则命令将拒绝执行并返回错误提示。

---

### 3.3 `listen` (别名 `serve`) 子命令：双工长连接网关

启动 WebSocket / Stream 长连接，常驻监听群聊与私聊消息，并驱动 Google Antigravity Agent 自动执行思考与流式卡片回复。

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen [选项]
```

#### 参数一览表

| 参数 | 缩写 | 必填 | 默认值 | 详细说明 |
|---|---|---|---|---|
| `--channel` | 无 | 否 | 自动推断 | 监听渠道：`dingtalk`（仅钉钉）、`feishu`（仅飞书）或 `all`（**同时监听飞书与钉钉双通道**）。未指定时按凭据自动推断 |
| `--chat-id` | `-c` | 否 | `None` | 可选的会话过滤白名单。若指定，则机器人仅响应该会话的消息，静默过滤其他群或私聊 |

> [!NOTE]
> - 当 `--channel all` 时，程序使用 `asyncio.gather` 并发拉起飞书与钉钉两个长连接网关，共享统一的 `AgentSessionManager` 会话管理器。
> - 无需配置公网 IP 或 Webhook 回调地址，内网开发机或本地服务器即可直接双工通信。

---

### 3.4 `version` 子命令：查看版本信息

```bash
# 查看完整版本信息 (如: channel-bot-cli-antigravity 0.2.0)
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity version

# 仅输出版本号
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity version --short
# 或简写
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity version -s
```

---

## 4. 实战运行示例 (Runnable Examples)

### 场景 1：向钉钉群发送运维告警与部署报告

针对钉钉企业内部群，通过 Markdown 发送高亮告警或发布总结：

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  --channel dingtalk \
  --chat-id cid_a1b2c3d4e5f6g7h8 \
  --message "### 🚨 线上服务告警通知
- **服务名称**: payment-gateway
- **告警级别**: CRITICAL
- **发生时间**: 2026-10-17 15:30:00
- **错误详情**: P99 响应延迟超过 2500ms
> 请运维值班人员尽快排查容器资源占用与数据库连接池。"
```

---

### 场景 2：向飞书用户发送交互式富文本与指标报告

飞书端原生支持富文本渲染（粗体、链接、代码高亮、无序列表）：

```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  --channel feishu \
  --chat-id oc_89f02a3b1c4d5e6f \
  --message "### 📊 自动化测试执行周报
| 测试模块 | 用例总数 | 通过数 | 失败数 | 覆盖率 |
| :--- | :--- | :--- | :--- | :--- |
| **API Gateway** | 128 | 128 | 0 | 98.4% |
| **Channel Core** | 86 | 86 | 0 | 95.1% |
| **Agent Pipeline** | 54 | 54 | 0 | 92.8% |

✅ **结论**: 全部 268 项测试均已通过，符合发布准入标准。[查看完整构建报告](https://ci.internal.example.com/job/42)"
```

---

### 场景 3：管道传输大段文本（CI/CD、日志与测试输出推送）

针对大段 Markdown 报告、系统错误日志、Git Diff 或自动化测试输出，使用管道（stdin）传输最为便捷高效，内置跨平台 UTF-8 / UTF-8-BOM 自动纠错解码：

#### 方式 A：使用 `--stdin` / `-s` 标志
```bash
# 1. 运行 pytest 测试并将控制台输出直接推送到钉钉群
uv run pytest --tb=short | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --channel dingtalk -c cid_ops_group --stdin

# 2. 将 Git 最新变更推送至飞书群
git diff HEAD~1 | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --channel feishu -c oc_dev_group -s
```

#### 方式 B：使用 `-m -` 语法
```bash
cat ./test-results/summary.md | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --channel feishu -c oc_dev_group -m -
```

#### 方式 C：自动管道检测 (Auto Stdin Detection)
当未提供 `-m` 且未提供 `-f` 时，只要检测到标准输入为重定向管道，CLI 会自动消费标准输入：
```bash
docker logs --tail 100 app-service | uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send --channel dingtalk -c cid_sre_group
```

---

### 场景 4：多文件附件与图片伴随文字说明投递

工具会自动区分文件后缀：
- **图片扩展名**（`.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.gif`）：通过渠道图片协议发送原生图片。
- **通用文件**（`.pdf`, `.zip`, `.xlsx`, `.log`, `.docx` 等）：上传后以原生文件卡片或带下载链接的 Markdown 呈现。

#### 单图 + 配文说明 (图文消息)
在飞书渠道中，单张图片配合 `-m` 与 `-t text` 会被自动合并为带说明的原生图文卡片：
```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  --channel feishu \
  --chat-id oc_89f02a3b1c4d5e6f \
  --file ./benchmark_chart.png \
  --message "Q3 性能压测吞吐量指标图表已生成，请参阅。" \
  --type text
```

#### 多文件混合批量推送
```bash
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity send \
  --channel dingtalk \
  --chat-id cid_releases \
  --file ./release-v1.0.0.tar.gz ./checksums.sha256 ./release-notes.pdf \
  --message "新版本已构建打包完毕，包含校验码与发布说明。"
```

---

### 场景 5：常驻运行双通道智能机器人网关 (`listen --channel all`)

作为常驻后台服务启动，同时接入飞书与钉钉长连接网关，为两个平台的用户提供基于 Antigravity Agent 的智能对话服务：

```bash
# 启动双通道双工长连接网关，指定工作目录以挂载项目提示词、技能与 MCP
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity -w /path/to/workspace listen --channel all
```

若仅需单独监听某一平台：
```bash
# 仅启动钉钉长连接监听
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen --channel dingtalk

# 仅启动飞书长连接监听，并仅响应指定群聊
uvx --with "dingtalk-channel-sdk@git+https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python.git" channel-bot-cli-antigravity listen --channel feishu --chat-id oc_vip_customer_group
```

---

## 5. 核心架构特性与工作机制

了解底层实现有助于在复杂编排任务中准确评估工具行为：

1. **细粒度会话并发锁 (`Session Concurrency Lock`)**：
   - 按照 `f"{channel}:{chat_id}"` 维护独立的 `asyncio.Lock`。
   - 确保同一会话内的并发消息严格串行处理，彻底杜绝多轮对话上下文冲突与响应交错。
2. **消息归一化与元数据前置注入 (`Normalization & Frontmatter`)**：
   - 入站消息会自动被清洗并提取关键上下文，转化为标准 YAML Frontmatter 前置注入 Agent：
     ```yaml
     ---
     channel: dingtalk # 或 feishu
     chat_id: "cid_12345"
     sender_id: "user_789"
     message_id: "msg_abc"
     create_time: "2026-10-17T15:30:00Z"
     chat_type: "group" # 或 "p2p"
     ---
     ```
3. **零磁盘多模态媒体流转 (`Zero-Disk Media Pipeline`)**：
   - 用户发送的图片、代码文件、音频或 PDF 附件由 SDK 直接在内存中拉取为字节流，并利用 `create_media_from_bytes` 工具转为 Antigravity Media 原生对象，全程无临时文件残留。
4. **打字机流式卡片与三级平滑降级 (`Streaming & 3-Tier Fallback`)**：
   - **Tier 1 (打字机卡片)**：优先通过飞书 CardKit 流式卡片或钉钉 AI 卡片逐字打字机回显。
   - **Tier 2 (静态 Markdown)**：若平台卡片权限未开通或流式中断，自动抓取全量回复降级补发为标准 Markdown。
   - **Tier 3 (纯文本 Text)**：若 Markdown 语法解析受限，无缝降级为纯文本，确保消息 100% 可达。
5. **用户思考状态反馈 (`Typing Indicators`)**：
   - 飞书：自动为提问消息打上 `typing` 表情 Reaction，回复完成后自动移除。
   - 钉钉：触发卡片思考中骨架态，回复完毕打上完成标记。

---

## 6. 常见问题与故障排查 (Troubleshooting)

### Q1: 报错 `配置错误: 请在环境变量或 .env 中配置 DD_CLIENT_ID 与 DD_CLIENT_SECRET...`
- **原因**：目标渠道为钉钉（或自动推断命中钉钉），但未检测到相关环境变量。
- **解决**：检查当前目录或 `--work-dir` 下的 `.env` 文件，确认已填写 `DD_CLIENT_ID` 与 `DD_CLIENT_SECRET`。若想发送至飞书，显式指定 `--channel feishu`。

### Q2: 报错 `从标准输入读取到的内容为空。`
- **原因**：通过管道或 `--stdin` 模式执行时，上游命令未产生任何标准输出，且未指定 `--file`。
- **解决**：确认上游命令是否有输出，例如检查 `cat` 的文件是否为空，或命令是否输出了 stderr 而非 stdout（如需要，可在上游重定向 `2>&1`）。

### Q3: 报错 `主动发送消息必须提供 --message、--stdin 或 --file 至少一项参数。`
- **原因**：调用 `send` 时未传入任何待发送的消息文本、管道指示或附件文件。
- **解决**：补充 `-m "内容"`、`-s` 或 `-f <路径>` 参数。

### Q4: 报错 `未找到待发送的文件: xxx`
- **原因**：`--file` 指定的文件路径不存在或当前用户无读取权限。
- **解决**：检查相对路径基准或传入绝对路径；确认文件是否存在。

### Q5: 飞书或钉钉端未收到消息但命令返回 `[SUCCESS]`
- **排查步骤**：
  1. **检查机器人是否已进群**：企业机器人必须已被邀请为群成员，否则群消息无法投递。
  2. **核对 `chat_id`**：确认 `chat_id` 是否精确匹配目标会话。钉钉群为 `cid...`，飞书群为 `oc_...`。
  3. **检查机器人权限**：飞书需开通 `im:message:send_as_bot`，钉钉需具备机器人发送消息权限。

### Q6: Windows 控制台管道中文出现乱码
- **说明**：工具内部已集成强制 UTF-8 与 UTF-8-BOM 解码。若在旧版 Windows CMD 窗口中直接交互输入，建议先执行 `chcp 65001` 切换终端代码页为 UTF-8。
