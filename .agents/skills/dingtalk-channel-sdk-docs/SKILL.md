---
name: dingtalk-channel-sdk-docs
description: 钉钉 Channel SDK 接入指南与多语言使用手册（Go / Python / Node.js / Java），提供 Stream 长连接、AI 卡片流式打字机、消息与媒体收发、主动通知、卡片交互、安全准入配置及 runnable 示例。
---

# 钉钉 Channel SDK 接入指南

钉钉 Channel SDK 是专为**大模型 Agent、企业机器人、自动化助手**打造的会话接入层 SDK。它与具体的模型 Runtime（LangChain、LlamaIndex 等）完全解耦，底层自动接管 WebSocket Stream 长连接、心跳重连、消息双层去重、AI 卡片流式输出（打字机）、Markdown 渲染修复、媒体上传与主动通知。

开发者只需要关注一件事：**「用户说了什么，机器人回什么」**。

---

## 目录

- [1. 接入效果与核心能力](#1-接入效果与核心能力)
- [2. 前置准备（一次性）](#2-前置准备一次性)
- [3. 多语言 SDK 安装](#3-多语言-sdk-安装)
- [4. 快速开始（四语言快速上手）](#4-快速开始四语言快速上手)
- [5. 核心使用场景与范式](#5-核心使用场景与范式)
  - [5.1 AI 卡片流式回复（打字机）](#51-ai-卡片流式回复打字机)
  - [5.2 真实大模型（LLM）流式对接范式](#52-真实大模型llm流式对接范式)
  - [5.3 消息表情状态章（🤔思考中 / 🥳完成）](#53-消息表情状态章思考中--完成)
  - [5.4 基础回复（文本 / Markdown / 图片 / 媒体）](#54-基础回复文本--markdown--图片--媒体)
  - [5.5 主动发送消息（单聊 / 群聊 @ / 文件通知）](#55-主动发送消息单聊--群聊---文件通知)
  - [5.6 卡片按钮交互回调（OnCardAction）](#56-卡片按钮交互回调oncardaction)
  - [5.7 安全准入控制与防刷（SafetyPipeline）](#57-安全准入控制与防刷safetypipeline)
  - [5.8 A2UI 动态交互卡片（DWS 接入）](#58-a2ui-动态交互卡片dws-接入)
- [6. 四语言 API 速查对照](#6-四语言-api-速查对照)
- [7. 配套使用示例索引（example/）](#7-配套使用示例索引example)
- [8. 真机一键联调验证（LiveCheck）](#8-真机一键联调验证livecheck)

---

## 1. 接入效果与核心能力

| 能力 | 终端用户可见效果 | SDK 内部实现机制 |
|---|---|---|
| **秒级卡片响应** | 提问后瞬间出现「输入中...」卡片骨架 | `reply.stream()` 立即创建并投递卡片，不阻塞等待模型首个 Token |
| **平滑流式打字机** | 回答逐字/逐词平滑浮现，无闪烁跳行 | 内置 800ms 智能节流 + 尾帧补刷 (Trailing Flush) + 去除未结束换行 |
| **Markdown 定格** | 生成完毕后 loading 消失，定格为高亮 Markdown | 自动发送终帧并收口，适配钉钉代码高亮、表格对齐与换行语法 |
| **消息防重与高可用** | 网络重试或多实例时绝不重复回复 | 协议层 `messageId` + 业务层 `msgId` 双层去重（TTL 5min） |
| **自动断线自愈** | 服务端发布、切换或网络断开无感知 | 指数退避重连（1s~30s 带抖动）+ 120s 心跳保活与 5s Pong 超时判死 |
| **失败静默降级** | 卡片模板无权限或 QPS 限流时用户无感 | 自动退避 2s 重试；卡片投递失败自动降级为 Webhook 纯文本，不报错崩溃 |

---

## 2. 前置准备（一次性）

1. 打开 [钉钉开发者后台](https://open-dev.dingtalk.com)，进入或创建**企业内部应用**。
2. 在应用能力中添加**机器人**能力，填写基本信息并发布。
3. 获取凭据：在「凭证与基础信息」中记录 **ClientID（AppKey）** 和 **ClientSecret（AppSecret）**。
4. **无需公网 IP、无需域名、无需配置 Webhook 回调 URL**（采用 Stream 模式，本地开发或内网服务器即可直接双向通讯）。

---

## 3. 多语言 SDK 安装

| 语言 | 仓库地址 | 安装命令 |
|---|---|---|
| **Python** | [dingtalk-channel-sdk-python](https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-python) | `pip install dingtalk-channel-sdk` |
| **Node.js** | [dingtalk-channel-sdk-nodejs](https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-nodejs) | `npm install dingtalk-channel-sdk` |
| **Go** | [dingtalk-channel-sdk-go](https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-go) | `go get github.com/DingTalk-Real-AI/dingtalk-channel-sdk-go` |
| **Java** | [dingtalk-channel-sdk-java](https://github.com/DingTalk-Real-AI/dingtalk-channel-sdk-java) | Maven: `com.dingtalk:dingtalk-channel-sdk` |

---

## 4. 快速开始（四语言快速上手）

以下四门语言实现完全相同的逻辑：**初始化 → 监听消息 → AI 卡片打字机回复 → 监听卡片按钮点击 → 启动长连接**。

### Python
```python
import asyncio
import os
from dingtalk_channel_sdk import DingTalkChannel

ch = DingTalkChannel(
    client_id=os.environ["DD_CLIENT_ID"],
    client_secret=os.environ["DD_CLIENT_SECRET"],
)

@ch.on_message
async def handle_message(msg, reply):
    if not msg.text:
        return  # 富媒体在 msg.content / msg.msg_type 中
    
    # 1. 秒级弹出 "输入中" 卡片
    s = await reply.stream()
    
    # 2. 模拟/真实 LLM 流式输出
    answer = f"**收到你的提问**：{msg.text}\n\n- 发送人：{msg.sender_nick}"
    for token in answer:
        await s.append(token)
        await asyncio.sleep(0.015)
        
    # 3. 定格为最终 Markdown
    await s.finish(answer)

@ch.on_card_action
async def handle_card(action, reply):
    await reply.text(f"收到按钮操作: {action.data_content}")

if __name__ == "__main__":
    asyncio.run(ch.start())  # 阻塞运行，断线自愈
```

### Node.js
```javascript
import { DingTalkChannel } from 'dingtalk-channel-sdk';

const ch = new DingTalkChannel({
  clientId: process.env.DD_CLIENT_ID,
  clientSecret: process.env.DD_CLIENT_SECRET,
});

ch.on('message', async (msg, reply) => {
  if (!msg.text) return;

  const s = await reply.stream(); // 立即出卡
  const answer = `**收到**：${msg.text}\n\n- 发送人：${msg.senderNick}`;
  
  for (const char of answer) {
    await s.append(char);
    await new Promise((r) => setTimeout(r, 15));
  }
  await s.finish(answer); // 定格 Markdown
});

ch.on('cardAction', async (action, reply) => {
  await reply.text(`收到按钮点击: ${JSON.stringify(action.dataContent)}`);
});

const controller = new AbortController();
process.on('SIGINT', () => controller.abort());
await ch.start(controller.signal);
```

### Go
```go
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"time"

	channel "github.com/DingTalk-Real-AI/dingtalk-channel-sdk-go"
)

func main() {
	ch := channel.New(channel.Config{
		ClientID:     os.Getenv("DD_CLIENT_ID"),
		ClientSecret: os.Getenv("DD_CLIENT_SECRET"),
	})

	ch.OnMessage(func(ctx context.Context, msg *channel.IncomingMessage, reply channel.Reply) error {
		if msg.Text == "" {
			return nil
		}
		s, err := reply.Stream(ctx) // ① 立即出"输入中"卡片
		if err != nil {
			return reply.Text(ctx, "系统繁忙，稍后重试")
		}

		answer := fmt.Sprintf("**收到**：%s\n\n- 发送人: %s", msg.Text, msg.SenderNick)
		for _, r := range answer { // ② 流式追加
			_ = s.Append(string(r))
			time.Sleep(15 * time.Millisecond)
		}
		return s.Finish(answer) // ③ 终帧定格 Markdown
	})

	ch.OnCardAction(func(ctx context.Context, action *channel.CardAction, reply channel.Reply) error {
		return reply.Text(ctx, "收到点击: "+string(action.DataContent))
	})

	log.Fatal(ch.Start(context.Background())) // 阻塞运行，断线自愈
}
```

### Java
```java
package com.example;

import com.dingtalk.channel.CardStreamer;
import com.dingtalk.channel.Config;
import com.dingtalk.channel.DingTalkChannel;

public class App {
    public static void main(String[] args) throws Exception {
        DingTalkChannel ch = DingTalkChannel.create(Config.builder(
                System.getenv("DD_CLIENT_ID"), 
                System.getenv("DD_CLIENT_SECRET")
        ).build());

        ch.onMessage((msg, reply) -> {
            if (msg.text.isEmpty()) return;

            CardStreamer s = reply.stream(); // 立即出卡
            String answer = "**收到**：" + msg.text + "\n\n- 来自: " + msg.senderNick;
            
            for (char c : answer.toCharArray()) {
                s.append(String.valueOf(c));
                Thread.sleep(15);
            }
            s.finish(answer); // 定格 Markdown
        });

        ch.onCardAction((action, reply) -> {
            reply.text("收到点击: " + action.dataContent);
        });

        Runtime.getRuntime().addShutdownHook(new Thread(ch::close));
        ch.start(); // 阻塞运行
    }
}
```

---

## 5. 核心使用场景与范式

### 5.1 AI 卡片流式回复（打字机）
流式打字机通过 `s = reply.stream()` 初始化，核心方法如下：
- `s.append(delta)`：向卡片追加文本增量。SDK 会在 800ms 内智能合批，并在结束时通过 Trailing Flush 自动补刷最后一批内容。
- `s.finish(fullMarkdown)`：定格卡片，关闭 loading 转圈，并以完整 Markdown 渲染。
- `s.fail("错误提示")`：将卡片置为失败态并呈现提示。
- `s.abort()`：用户取消生成或外部打断时关闭流。
- `s.card_delivered` / `s.CardDelivered()`：检查卡片是否在端上投递成功（若因权限未开通，SDK 会自动降级为普通文本回复）。

### 5.2 真实大模型（LLM）流式对接范式

接入 OpenAI 兼容接口（如 DeepSeek、通义千问、Ollama、vLLM）的标准写法：

```python
from openai import AsyncOpenAI

openai_client = AsyncOpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com"),
)

@ch.on_message
async def handle_agent(msg, reply):
    if not msg.text:
        return

    # 1. 弹出卡片
    s = await reply.stream()
    
    # 2. 调用大模型并流式消费
    response = await openai_client.chat.completions.create(
        model=os.environ.get("AGENT_MODEL", "deepseek-chat"),
        messages=[{"role": "user", "content": msg.text}],
        stream=True,
    )

    full_chunks = []
    async for chunk in response:
        delta = chunk.choices[0].delta.content or ""
        if delta:
            full_chunks.append(delta)
            await s.append(delta)

    # 3. 终帧收口
    await s.finish("".join(full_chunks))
```

> **Go 开发者提示**：在 `example/go/agent/main.go` 中内置了支持 DeepSeek（OpenAI 兼容协议）与 Anthropic 协议的完整 Agent 示例，支持多轮上下文会话缓存与自动降级。

### 5.3 消息表情状态章（🤔思考中 / 🥳完成）

在用户提问的消息气泡上直接打上 Text Emotion 反应（不依赖卡片，用于表示「正在思考」与「已完成」）：

```go
// Go 示例
ch.OnMessage(func(ctx context.Context, msg *channel.IncomingMessage, reply channel.Reply) error {
    // 收到消息后立即贴上 "🤔思考中"
    _ = ch.MarkThinking(ctx, msg.ConversationID, msg.MsgID)
    defer ch.MarkDone(ctx, msg.ConversationID, msg.MsgID) // 退出时置为 "🥳完成"

    s, _ := reply.Stream(ctx)
    // ... 执行业务与流式回复 ...
    return s.Finish(answer)
})
```

### 5.4 基础回复（文本 / Markdown / 图片 / 媒体）

在 `on_message` 的 `reply` 句柄中，支持丰富的标准消息形式：

```python
# 1. 发送纯文本
await reply.text("你好，这是文本回复")

# 2. 发送标准 Markdown
await reply.markdown("标题", "# 一级标题\n- 列表项\n```python\nprint(1)\n```")

# 3. 发送公网图片
await reply.image("https://example.com/photo.png")

# 4. 上传媒体文件（图片/音频/视频/普通文件）并获取 mediaId
media = await reply.upload_media("image", "avatar.png", img_bytes, "image/png")
# 上传后的 mediaId 可通过独立媒体消息可靠发送，或提取 media["downloadUrl"]

# 5. 下载用户发送在会话中的附件/图片
file_url = await reply.download_url(resource.download_code, msg.msg_id)
```

### 5.5 主动发送消息（单聊 / 群聊 @ / 文件通知）

不依赖入站触发，由系统定时任务、报警监控主动向钉钉推送：

```python
from dingtalk_channel_sdk import SendTarget

# 1. 主动向员工发送单聊文本（需传入员工 staffId）
await ch.send_text(SendTarget(user_id="staff123"), "【系统提醒】你的审批已通过")

# 2. 主动向群聊发送 Markdown 并在群里 @ 特定人员
await ch.send_markdown(
    SendTarget(
        conversation_id="cid_xxx",           # 群的 openConversationId
        at_user_ids=["staff123", "staff456"],# 需要 @ 的员工列表
    ),
    "发布成功通知",
    "@staff123 新版本发布已完成，请核对环境。"
)

# 3. 主动群发 @所有人
await ch.send_markdown(
    SendTarget(conversation_id="cid_xxx", is_at_all=True),
    "全员周会提醒",
    "@所有人 下午 3:00 周会准时开始。"
)

# 4. 发送独立文件（图片/文档可靠送达）
await ch.send_file(SendTarget(user_id="staff123"), "report.pdf", raw_media_id)
```

### 5.6 卡片按钮交互回调（OnCardAction）

当卡片中包含操作按钮时，用户点击会回调到注册的 `on_card_action` 处理器：

```python
@ch.on_card_action
async def on_card(action, reply):
    # action 关键字段：
    # - action.user_id: 点击者的员工 ID
    # - action.out_track_id: 被点击卡片的唯一 ID
    # - action.data_content: 按钮绑定的业务参数 (字典/JSON)
    
    print(f"用户 {action.user_id} 触发了按钮: {action.data_content}")
    await reply.text("已收到并处理你的操作请求！")
```

### 5.7 安全准入控制与防刷（SafetyPipeline）

面向多人生产群聊，SDK 内置开箱即用的安全过滤管线：
- **过期消息丢弃**：过滤掉超过 30 分钟的历史消息（防宕机重启刷屏）。
- **群聊 @机器人 过滤**：只有被 `@` 时才响应，默认忽略 `@所有人`。
- **单聊/群聊名单限制**：支持设置黑白名单。
- **连续图片自动合并批处理（MediaBatch）**：连续上传的多张图自动合批为一次处理。

```python
from dingtalk_channel_sdk import Config, PolicyConfig, MediaBatchConfig

cfg = Config(
    client_id=os.environ["DD_CLIENT_ID"],
    client_secret=os.environ["DD_CLIENT_SECRET"],
    # 策略门控
    policy=PolicyConfig(
        require_mention=True,        # 群聊必须 @机器人
        respond_to_mention_all=False,# 不响应 @所有人
        dm_mode="open",              # 单聊模式：open | allowlist | blocklist | disabled
        admins=["admin_staff_id"],   # 管理员名单（豁免所有限制）
        group_allowlist=["cid_auth"],# 仅在指定的群响应
    ),
    # 连续图片自动合并：800ms 内连续发送的多张图片合并为 1 条消息
    media_batch=MediaBatchConfig(enabled=True, delay_s=0.8, max_items=9),
)

ch = DingTalkChannel(config=cfg)

# 监听被拦截的无效/未授权事件
@ch.on_reject
def handle_reject(event):
    print(f"消息拦截: {event.message_id}, 原因: {event.reason}")
```

### 5.8 A2UI 动态交互卡片（DWS 接入）

A2UI 是钉钉新一代 AI 原生卡片标准。SDK 支持通过本机的 [DingTalk Workspace CLI (dws)](https://github.com/DingTalk-Real-AI/dingtalk-workspace-cli) 发送与增量更新 A2UI 界面：

```python
import json
from pathlib import Path
from dingtalk_channel_sdk import Config, DingTalkChannel, DwsA2UIClient

ch = DingTalkChannel(config=Config(
    client_id=os.environ["DD_CLIENT_ID"],
    client_secret=os.environ["DD_CLIENT_SECRET"],
    a2ui_client=DwsA2UIClient(profile=os.environ["DWS_PROFILE"]),
))

# 1. 投递 A2UI 卡片 (需要用户的 openDingTalkId 或群 openConversationId)
card_data = json.loads(Path("example/python/a2ui-card.json").read_text(encoding="utf-8"))
result = await ch.send_a2ui_card({"open_dingtalk_id": "dt_id..."}, card_data)

# 2. 根据服务端 bizId 进行增量更新并置为 FINISH
update_data = json.loads(Path("example/python/a2ui-update.json").read_text(encoding="utf-8"))
await ch.update_a2ui_card(result.biz_id, update_data, "FINISH")
```

---

## 6. 四语言 API 速查对照

| 能力模块 | Python | Node.js | Go | Java |
|---|---|---|---|---|
| **创建实例** | `DingTalkChannel(...)` | `new DingTalkChannel(cfg)` | `channel.New(cfg)` | `DingTalkChannel.create(cfg)` |
| **监听消息** | `@ch.on_message` | `ch.on('message', fn)` | `ch.OnMessage(fn)` | `ch.onMessage(fn)` |
| **卡片动作** | `@ch.on_card_action` | `ch.on('cardAction', fn)` | `ch.OnCardAction(fn)` | `ch.onCardAction(fn)` |
| **启动连接** | `await ch.start()` | `await ch.start(signal)` | `ch.Start(ctx)` | `ch.start()` |
| **优雅关闭** | `ch.close()` | `controller.abort()` | `cancel()` / `bot.Close()` | `ch.close()` |
| **流式卡片** | `await reply.stream()` | `await reply.stream()` | `reply.Stream(ctx)` | `reply.stream()` |
| **追加内容** | `await s.append(tok)` | `await s.append(tok)` | `s.Append(tok)` | `s.append(tok)` |
| **卡片收口** | `await s.finish(md)` | `await s.finish(md)` | `s.Finish(md)` | `s.finish(md)` |
| **回复文本** | `await reply.text(...)` | `await reply.text(...)` | `reply.Text(ctx, ...)` | `reply.text(...)` |
| **回复 Markdown**| `await reply.markdown(...)`| `await reply.markdown(...)`| `reply.Markdown(ctx, ...)`| `reply.markdown(...)`|
| **上传媒体** | `await reply.upload_media(...)`| `await reply.uploadMedia(...)`| `reply.UploadMedia(ctx, ...)`| `reply.uploadMedia(...)`|
| **主动单聊** | `await ch.send_text(...)`| `await ch.sendText(...)` | `ch.SendText(ctx, ...)`| `ch.sendText(...)` |
| **主动群聊@**| `await ch.send_markdown(...)`| `await ch.sendMarkdown(...)`| `ch.SendMarkdown(ctx, ...)`| `ch.sendMarkdown(...)`|
| **A2UI 卡片**| `await ch.send_a2ui_card(...)`| `await ch.sendA2UICard(...)`| `client.SendCard(...)` | `client.sendCard(...)` |

---

## 7. 配套使用示例索引（example/）

SDK 仓库在 `example/` 目录下为四门语言提供了完整可运行的代码：

```
example/
├── python/
│   ├── echo.py             # ① 流式打字机卡片极简验证
│   ├── fullflow.py         # ② 全流程：收消息 + 文本回复 + 流式卡片 + 媒体上传 + 主动发消息
│   ├── livecheck.py        # ③ 线上联调逐步检测脚本（PASS/FAIL）
│   ├── a2ui.py             # ④ A2UI 卡片投递与更新示例
│   ├── a2ui-card.json      #    A2UI 初始卡片 JSON 结构
│   └── a2ui-update.json    #    A2UI 增量更新 JSON 结构
├── nodejs/
│   ├── echo.mjs            # ① 流式打字机卡片示例
│   ├── fullflow.mjs        # ② 全流程验证示例
│   ├── livecheck.mjs       # ③ 线上联调测试
│   ├── a2ui.mjs            # ④ A2UI 发送与增量更新
│   ├── a2ui-card.json
│   └── a2ui-update.json
├── java/
│   ├── EchoBot.java        # ① 流式打字机机器人
│   ├── FullFlow.java       # ② 全流程闭环测试
│   ├── LiveCheck.java      # ③ 联调检测脚本
│   ├── A2UI.java           # ④ A2UI 示例
│   ├── a2ui-card.json
│   └── a2ui-update.json
└── go/
    ├── echo/main.go        # ① 流式打字机卡片极简验证
    ├── agent/main.go       # ② 接入 DeepSeek/Anthropic 大模型的真实 Agent 示例
    ├── fullflow/main.go    # ③ 全流程：被动回复 + 卡片流式 + 媒体上传 + 主动发消息
    ├── livecheck/main.go   # ④ 线上联调检测脚本
    ├── a2ui/main.go        # ⑤ A2UI 发送与更新示例
    ├── a2ui-card.json
    └── a2ui-update.json
```

---

## 8. 真机一键联调验证（LiveCheck）

配置环境变量并在终端运行对应语言的 `livecheck`，给机器人发一句话，控制台会逐步输出 PASS/FAIL 结果，验证全链路联通：

### Go
```bash
DD_CLIENT_ID=ding... DD_CLIENT_SECRET=... go run ./example/go/livecheck
```

### Python
```bash
DD_CLIENT_ID=ding... DD_CLIENT_SECRET=... python example/python/livecheck.py
```

### Node.js
```bash
DD_CLIENT_ID=ding... DD_CLIENT_SECRET=... node example/nodejs/livecheck.mjs
```

### Java
```bash
DD_CLIENT_ID=ding... DD_CLIENT_SECRET=... mvn -q compile exec:java -Dexec.mainClass=com.dingtalk.channel.example.LiveCheck
```

**验证步骤**：
1. `config loaded`：凭据加载
2. `stream message received`：长连接建立并成功收取第一条用户消息
3. `text reply via sessionWebhook`：验证临时 Token 文本回复链路
4. `AI card created & delivered (E1)`：验证卡片创建与投递
5. `AI card streaming lifecycle (E2/E3)`：打字机流式输出与终帧 Markdown 定格收口
6. （可选通过 `DD_UPLOAD_FILE=/path/to/img.png`）验证 OAPI 媒体上传链路
