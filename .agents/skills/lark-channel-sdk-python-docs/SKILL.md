---
name: lark-channel-sdk-python-docs
description: Complete guide and reference for the Feishu/Lark Channel Python SDK (lark-channel-sdk), covering WebSocket/webhook transports, message normalization, CardKit streaming, meeting agents (join & follow), multi-bot collaboration, security modes, and two-layer dedup architecture.
metadata:
  author: Ecat
  version: "1.1.0"
---

# Feishu / Lark Channel Python SDK Documentation

This skill provides comprehensive documentation, architecture guides, API references, and code samples for the **Feishu / Lark Channel Python SDK** (`lark-channel-sdk`).

`lark-channel-sdk` is the dedicated standalone Python SDK for developing bots, agents, and meeting assistants on Feishu and Lark. It supersedes the legacy `lark_oapi.channel` module with improved modularity, CardKit streaming, live meeting capabilities, security modes, and high-performance message pipelines.

---

## 📦 Package Information

- **PyPI Package**: `lark-channel-sdk`
- **Import Root**: `lark_channel`
- **Main Class**: `FeishuChannel`
- **Current Version**: `v1.1.0`
- **Companion Package**: Can coexist with `lark-oapi` (use `lark-channel-sdk` for bot/channel workflows and `lark-oapi` for general OpenAPI calls if needed).

```bash
pip install lark-channel-sdk
# Optional framework extras for webhook mode:
pip install "lark-channel-sdk[aiohttp]"
pip install "lark-channel-sdk[fastapi]"
pip install "lark-channel-sdk[flask]"
```

---

## 📚 Documentation Index

| Topic | Document | Description |
|---|---|---|
| **Quickstart** | [docs/quickstart.md](docs/quickstart.md) | Setup, credentials, minimal echo bot, and send/stream basics |
| **API Reference** | [docs/reference.md](docs/reference.md) | Full API reference for `FeishuChannel`, configs, models, methods, and error codes |
| **CardKit Streaming** | [docs/cardkit-streaming.md](docs/cardkit-streaming.md) | High-level `stream()` helper vs low-level CardKit sequence APIs (`update_card_element_content`) |
| **Meeting Channel** | [docs/meeting-channel.md](docs/meeting-channel.md) | Live in-meeting agents: `join_meeting` (as bot) vs `follow_my_meeting` (as user) |
| **Webhook Adapter** | [docs/webhook-server.md](docs/webhook-server.md) | HTTP webhook integration using aiohttp, FastAPI, or synchronous frameworks |
| **Security Configuration** | [docs/security.md](docs/security.md) | Security modes (`compat`, `audit`, `strict`), signatures, WebSocket limits, and safe rendering |
| **Dedup Architecture** | [docs/dedup-architecture.md](docs/dedup-architecture.md) | Two-layer deduplication: Pipeline `DedupStore` vs Safety `ICache` / `SeenCache` |
| **Markdown Conversion** | [docs/markdown.md](docs/markdown.md) | Markdown-to-post conversion, native vs structured modes, and media captions |
| **Migration Guide** | [docs/migration-from-lark-oapi.md](docs/migration-from-lark-oapi.md) | Checklist and steps for migrating from `lark_oapi.channel` to `lark-channel-sdk` |
| **Release Notes v1.1.0** | [docs/release-notes/v1.1.0.md](docs/release-notes/v1.1.0.md) | `content_v2` support, native markdown rendering by default |
| **Release Notes v1.0.0** | [docs/release-notes/v1.0.0.md](docs/release-notes/v1.0.0.md) | Initial standalone release highlights and features |

---

## 💻 Code Samples

| Sample File | Description | Key Features Demonstrated |
|---|---|---|
| [samples/channel/echo_bot.py](samples/channel/echo_bot.py) | Minimal WebSocket echo bot | `FeishuChannel`, `channel.on("message")`, `channel.send()`, `channel.connect()` |
| [samples/channel/meeting_join_bot.py](samples/channel/meeting_join_bot.py) | Bot joins a live meeting as participant | `channel.join_meeting()`, `meetingInvited`, `self_echo` handling, live transcription, meeting chat |
| [samples/channel/meeting_follow_agenda.py](samples/channel/meeting_follow_agenda.py) | Follow meeting as user | `channel.follow_my_meeting()`, `FileTokenStore`, REST-only session without `connect()` |

---

## 🚀 Core Concepts & Usage Patterns

### 1. Minimal WebSocket Bot

```python
import asyncio
import os
from lark_channel import FeishuChannel

channel = FeishuChannel(
    app_id=os.environ["LARK_APP_ID"],
    app_secret=os.environ["LARK_APP_SECRET"],
    # domain="https://open.larksuite.com"  # Explicitly set for Lark tenants
)


async def on_message(msg):
    await channel.send(
        msg.chat_id,
        {"text": f"echo: {msg.content_text}"},
    )


channel.on("message", on_message)
asyncio.run(channel.connect())
```

### 2. Webhook Integration (FastAPI / aiohttp)

The SDK does not bundle an HTTP server; application owns the server and routes:

```python
from fastapi import FastAPI, Request, Response
from lark_channel import FeishuChannel

channel = FeishuChannel(
    app_id="cli_xxx",
    app_secret="***",
    encrypt_key="...",
    verification_token="...",
    transport="webhook",
)


@app.post("/feishu/webhook")
async def webhook(request: Request):
    status, body_bytes = await channel.handle_webhook_request(
        headers=dict(request.headers),
        body=await request.body(),
    )
    return Response(
        status_code=status, content=body_bytes, media_type="application/json"
    )
```

### 3. Outbound Messages & Replies

```python
# Plain text
await channel.send(chat_id, {"text": "Hello"})

# Markdown (rendered as native Feishu md by default in v1.1.0)
await channel.send(chat_id, {"markdown": "**Important** update!"})

# Smart reply (preserves thread vs flat context automatically)
await channel.reply(msg, {"text": "Got it!"})

# Manual reply options
await channel.send(
    chat_id,
    {"markdown": "replying to message"},
    {"reply_to": msg.message_id, "reply_in_thread": True},
)

# Media with caption (supported for image & video)
await channel.send(
    chat_id,
    {"image": {"source": "./chart.png"}, "caption": "Daily Analytics"},
)
```

### 4. Streaming Output (CardKit)

High-level markdown stream:

```python
async def producer(stream):
    for token in ["Analyzing ", "codebase... ", "Done!"]:
        await stream.append(token)


await channel.stream(
    msg.chat_id,
    {"markdown": producer},
    {"reply_to": msg.message_id},
)
```

For custom element updates, use low-level CardKit methods with monotonic `sequence`:
- `create_card_instance(spec)`
- `send_card_by_reference(to, card_id)`
- `update_card_element_content(card_id, element_id, content, sequence)`
- `finish_streaming_card(card_id, sequence)`

### 5. In-Meeting Agents (VC Channel)

| Method | Identity | Connection | Permissions Required |
|---|---|---|---|
| `channel.join_meeting(meeting_no)` | Visible Bot Participant | WebSocket (`await channel.connect()`) | `vc:meeting.bot.join:write`, `vc:meeting.message:write` |
| `channel.follow_my_meeting(user_open_id=...)` | Invisible (User Token) | REST Only (no `connect()` needed) | `vc:meeting.meetingevent:read` |

> ⚠️ **Critical Load-Bearing Rule for Meeting Chat:**  
> In meeting sessions, the bot's own spoken messages loop back as incoming chat events. Always check:
> ```python
> if event.self_echo:
>     return
> ```
> Failing to check `self_echo` will cause infinite recursive reply loops at network speed.

### 6. Multi-Bot Collaboration (Bot-at-Bot)

- **Identify sender**: `msg.sender_is_bot`, `msg.sender_type`, and `channel.get_bot_identity()`.
- **Detect bare poke**: `msg.mentioned_bot and not msg.body_text.strip()`.
- **Roster & Mentions**: `channel.get_chat_members()`, `channel.get_chat_bots()`, or pass `resolve_mentions_in_text=True`.
- **Ping-Pong Loop Protection**:
  ```python
  from lark_channel import BotLoopGuardConfig, PolicyConfig

  policy = PolicyConfig(
      bot_loop_guard=BotLoopGuardConfig(
          enabled=True,
          window_ms=60_000,
          max_bot_mentions=5,
          on_trip="reject",  # or "drop"
      )
  )
  ```
- **Required Permission**: `im:message.group_at_msg.include_bot:readonly` in Feishu developer console to receive events when other bots `@` your bot.

### 7. Security Modes

```python
from lark_channel import FeishuChannel, SecurityConfig

channel = FeishuChannel(
    app_id="cli_xxx",
    app_secret="***",
    security=SecurityConfig(
        mode="audit",  # "compat" (default) -> "audit" -> "strict"
        max_ws_fragment_parts=128,
        max_ws_fragment_bytes=8 * 1024 * 1024,
    ),
)
```

- **`compat`**: Backward-compatible with existing bots.
- **`audit`**: Validates security policies and emits audit log events without blocking traffic.
- **`strict`**: Enforces webhook signature validation before decrypt, blocks remote insecure `ws://`, and masks error details.

---

## 🛠️ Helper Methods Reference

- `await channel.update_card(message_id, card)`: Replace full card content.
- `await channel.edit_message(message_id, message)`: Edit text/post messages.
- `await channel.recall_message(message_id)`: Recall sent message.
- `await channel.add_reaction(message_id, emoji_type)`: Add emoji reaction.
- `await channel.add_typing_reaction(message_id)`: Add "Typing" indicator reaction.
- `await channel.download_resource(file_key, resource_type)`: Download media bytes.
- `await channel.get_chat_info(chat_id)`: Query chat metadata.
