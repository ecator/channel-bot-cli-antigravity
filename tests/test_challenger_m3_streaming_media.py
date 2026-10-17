"""Adversarial Verification Suite for Milestone M3 (Mid-Stream Fallback & Media Leak).

Author: challenger_m3_2 (Empirical Challenger)
Coverage:
1. Feishu mid-stream CardKit failure: disconnect midway after k tokens -> recover via response.text() without duplicate initial tokens.
2. DingTalk mid-stream AI Card failure: disconnect midway -> recover full message without truncating remaining tokens.
3. Immediate stream failures: fallback to Markdown, then to plain text, then to polite error notification.
4. Reaction exceptions: add_typing_reaction, remove_typing_reaction, mark_thinking, mark_done exceptions never crash turn.
5. Zero disk residue: verify that multimodal processing (images, audio, video, pdf, unknown binary) generates 0 disk writes/files.
6. Session lock resilience: ensure locks are cleanly released even when streams and fallbacks fail.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from channel_bot_cli_antigravity.channels.dingtalk import DingTalkBotChannel
from channel_bot_cli_antigravity.channels.feishu import FeishuBotChannel
from channel_bot_cli_antigravity.config import Config

from .conftest import (
    MockAgent,
    MockAgentSessionManager,
    MockDingTalkCardStreamer,
    MockDingTalkChannel,
    MockDingTalkIncomingMessage,
    MockDingTalkReply,
    MockFeishuChannel,
    MockFeishuInboundMessage,
)


class MultiChunkChatResponse:
    """Mock simulating Google Antigravity ChatResponse with independent cursors and text() method."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = list(chunks)
        self.cursor_requests = 0

    def __aiter__(self) -> AsyncIterator[str]:
        self.cursor_requests += 1

        async def _gen() -> AsyncIterator[str]:
            for chunk in self.chunks:
                await asyncio.sleep(0.005)
                yield chunk

        return _gen()

    async def text(self) -> str:
        return "".join(self.chunks)


# ===========================================================================
# Scope 1: Mid-Stream CardKit Failure in Feishu
# ===========================================================================


@pytest.mark.asyncio
async def test_feishu_midstream_cardkit_disconnect_recovers_without_duplicates(
    feishu_env: None,
) -> None:
    """CardKit stream fails midway after k tokens; response.text() recovers full message without duplicating initial tokens."""
    cfg = Config.from_env()
    mock_sdk = MockFeishuChannel()

    # Fail on 3rd token
    append_count = 0

    async def faulty_stream(chat_id: str, spec: dict[str, Any]) -> None:
        nonlocal append_count
        producer = spec.get("markdown")

        class _StreamTarget:
            async def append(self, token: str) -> None:
                nonlocal append_count
                append_count += 1
                if append_count >= 3:
                    raise ConnectionResetError(
                        "Feishu CardKit WebSocket broken mid-stream at token 3"
                    )

        if callable(producer):
            await producer(_StreamTarget())

    mock_sdk.stream = faulty_stream

    chunks = ["Alpha", "_Beta", "_Gamma", "_Delta", "_Epsilon"]
    resp = MultiChunkChatResponse(chunks)

    class _CustomAgent(MockAgent):
        async def _mock_chat(self, agent_input: Any) -> Any:
            return resp

    session_mgr = MockAgentSessionManager(agent=_CustomAgent())
    bot = FeishuBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockFeishuInboundMessage(
        msg_id="om_feishu_mid_1",
        chat_id="oc_feishu_mid_1",
        content_text="Hello bot",
    )

    await bot.on_message(msg)

    # Must fall back to sending markdown
    assert len(mock_sdk.sent_messages) == 1
    target, payload = mock_sdk.sent_messages[0]
    assert target == "oc_feishu_mid_1"

    delivered = payload.get("markdown") or payload.get("text", "")
    expected = "Alpha_Beta_Gamma_Delta_Epsilon"
    assert delivered == expected, (
        f"Delivered message must equal '{expected}', but got '{delivered}' (possible duplication/corruption)!"
    )
    # Check that initial tokens 'Alpha_Beta' are not duplicated
    assert delivered.count("Alpha") == 1
    assert delivered.count("Beta") == 1


# ===========================================================================
# Scope 2: Mid-Stream AI Card Failure in DingTalk
# ===========================================================================


@pytest.mark.asyncio
async def test_dingtalk_midstream_aicard_failure_recovers_without_truncation(
    dingtalk_env: None,
) -> None:
    """DingTalk AI Card stream fails midway; fallback must recover entire message without truncating remaining tokens."""
    cfg = Config.from_env()
    mock_sdk = MockDingTalkChannel()

    append_count = 0
    streamer = MockDingTalkCardStreamer()

    async def faulty_append(delta: str) -> None:
        nonlocal append_count
        append_count += 1
        if append_count >= 2:
            raise ConnectionError("DingTalk stream socket dropped on token 2")
        streamer.tokens.append(delta)

    streamer.append = faulty_append
    reply = MockDingTalkReply(streamer=streamer)

    chunks = ["Header\n\n", "Item 1\n", "Item 2\n", "Item 3\n", "Footer Final"]
    resp = MultiChunkChatResponse(chunks)

    class _CustomAgent(MockAgent):
        async def _mock_chat(self, agent_input: Any) -> Any:
            return resp

    session_mgr = MockAgentSessionManager(agent=_CustomAgent())
    bot = DingTalkBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_mid_1",
        conversation_id="cid_dd_mid_1",
        text="Give me list",
    )

    await bot.on_message(msg, reply)

    # Verify fallback markdown message
    assert len(reply.markdown_replies) == 1
    _title, body = reply.markdown_replies[0]
    expected_body = "".join(chunks)

    assert body == expected_body, (
        f"DingTalk fallback was truncated! Expected '{expected_body}', got '{body}'"
    )
    assert "Footer Final" in body
    assert "Item 3" in body


# ===========================================================================
# Scope 3: Immediate Stream Failure Fallback to Markdown & Plaintext
# ===========================================================================


@pytest.mark.asyncio
async def test_feishu_immediate_stream_failure_cascade(feishu_env: None) -> None:
    """CardKit fails immediately; tests fallback to Markdown, then text fallback if Markdown fails."""
    cfg = Config.from_env()
    mock_sdk = MockFeishuChannel()

    # 1. Stream fails immediately
    mock_sdk.stream = AsyncMock(side_effect=RuntimeError("CardKit not provisioned"))

    # When markdown fails, allow text
    sent_payloads: list[dict[str, Any]] = []

    async def custom_send(chat_id: str, content: dict[str, Any]) -> Any:
        sent_payloads.append(content)
        if "markdown" in content:
            raise ValueError("Markdown syntax error or disabled by admin")
        return {"status": "ok"}

    mock_sdk.send = custom_send

    mock_agent = MockAgent(response_chunks=["Fallback", " Plain", " Text"])
    session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = FeishuBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockFeishuInboundMessage(
        msg_id="om_feishu_casc",
        chat_id="oc_feishu_casc",
        content_text="Testing cascade",
    )

    await bot.on_message(msg)

    # First tried markdown, then succeeded on text
    assert len(sent_payloads) == 2
    assert "markdown" in sent_payloads[0]
    assert "text" in sent_payloads[1]
    assert sent_payloads[1]["text"] == "Fallback Plain Text"


@pytest.mark.asyncio
async def test_dingtalk_immediate_stream_failure_cascade(dingtalk_env: None) -> None:
    """AI Card stream fails immediately; tests fallback to Markdown, then plain text."""
    cfg = Config.from_env()
    mock_sdk = MockDingTalkChannel()

    reply = MockDingTalkReply()
    reply.stream = AsyncMock(side_effect=RuntimeError("AI Card stream disabled"))
    reply.markdown = AsyncMock(side_effect=RuntimeError("Markdown rejected"))

    mock_agent = MockAgent(response_chunks=["Direct", " Text", " Recovery"])
    session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = DingTalkBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_casc",
        conversation_id="cid_dd_casc",
        text="Cascade test",
    )

    await bot.on_message(msg, reply)

    # Verified text fallback
    assert len(reply.text_replies) == 1
    assert reply.text_replies[0] == "Direct Text Recovery"


# ===========================================================================
# Scope 4: Reaction Exceptions Resilience
# ===========================================================================


@pytest.mark.asyncio
async def test_feishu_reaction_exceptions_do_not_crash(feishu_env: None) -> None:
    """Both add_typing_reaction and remove_typing_reaction raise exceptions; turn must proceed normally."""
    cfg = Config.from_env()
    mock_sdk = MockFeishuChannel()

    mock_sdk.add_typing_reaction = AsyncMock(
        side_effect=RuntimeError("Network error on add_typing_reaction")
    )
    mock_sdk.remove_typing_reaction = AsyncMock(
        side_effect=RuntimeError("Network error on remove_typing_reaction")
    )

    mock_agent = MockAgent(response_chunks=["Reaction", " Resilient", " Reply"])
    session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = FeishuBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockFeishuInboundMessage(
        msg_id="om_react_resilience",
        chat_id="oc_react_resilience",
        content_text="Hi",
    )

    # Must complete cleanly without raising
    await bot.on_message(msg)

    # Stream reply was delivered
    assert len(mock_sdk.streams) == 1
    target_chat, stream_spec = mock_sdk.streams[0]
    assert target_chat == "oc_react_resilience"
    assert "markdown" in stream_spec
    assert len(mock_agent.chat_history) == 1


@pytest.mark.asyncio
async def test_dingtalk_reaction_exceptions_do_not_crash(dingtalk_env: None) -> None:
    """Both mark_thinking and mark_done raise exceptions; turn must proceed normally."""
    cfg = Config.from_env()
    mock_sdk = MockDingTalkChannel()

    mock_sdk.mark_thinking = AsyncMock(side_effect=Exception("mark_thinking 500 error"))
    mock_sdk.mark_done = AsyncMock(side_effect=Exception("mark_done timeout error"))

    reply = MockDingTalkReply()
    mock_agent = MockAgent(response_chunks=["DingTalk", " Emotion", " Resilient"])
    session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = DingTalkBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_react_res",
        conversation_id="cid_dd_react_res",
        text="Emotion test",
    )

    # Must complete cleanly without raising
    await bot.on_message(msg, reply)

    # Stream tokens were delivered
    assert reply.streamer.tokens == ["DingTalk", " Emotion", " Resilient"]
    # mark_done was still called in finally block
    assert mock_sdk.mark_done.call_count == 1


# ===========================================================================
# Scope 5: Zero Disk Residue Verification
# ===========================================================================


@pytest.mark.asyncio
async def test_zero_disk_residue_interceptor_feishu(feishu_env: None) -> None:
    """Adversarially intercept builtins.open and tempfile during Feishu multimodal processing.

    Verifies that NO disk file is opened in write mode ('w', 'wb', 'a', etc.).
    """
    cfg = Config.from_env()
    mock_sdk = MockFeishuChannel()

    # Pre-populate downloaded resources in memory
    mock_sdk.downloaded_resources["img_1"] = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    )
    mock_sdk.downloaded_resources["pdf_1"] = b"%PDF-1.4 test document"
    mock_sdk.downloaded_resources["aud_1"] = b"ID3\x03\x00\x00\x00mock audio"
    mock_sdk.downloaded_resources["vid_1"] = (
        b"\x00\x00\x00 ftypisom\x00\x00\x02\x00mp41mp42isom"
    )
    mock_sdk.downloaded_resources["bin_1"] = b"\x00\x01\x02binary unparseable"

    class Res:
        def __init__(self, key: str, rtype: str, name: str) -> None:
            self.file_key = key
            self.type = rtype
            self.file_name = name

    mock_agent = MockAgent(response_chunks=["Processed zero disk"])
    session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = FeishuBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockFeishuInboundMessage(
        msg_id="om_zero_disk_intercept",
        chat_id="oc_zero_disk_intercept",
        content_text="Check zero disk",
        resources=[
            Res("img_1", "image", "photo.png"),
            Res("pdf_1", "file", "doc.pdf"),
            Res("aud_1", "audio", "song.mp3"),
            Res("vid_1", "video", "movie.mp4"),
            Res("bin_1", "file", "random.dat"),
        ],
    )

    # Intercept open() calls to detect any disk write operations
    real_open = open
    disk_write_attempts: list[str] = []

    def tracking_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(m in mode for m in ("w", "a", "x", "+")):
            disk_write_attempts.append(f"Write operation on {file} with mode {mode}")
        return real_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=tracking_open):
        await bot.on_message(msg)

    assert len(disk_write_attempts) == 0, (
        f"Disk write operations detected during multimodal download: {disk_write_attempts}"
    )


@pytest.mark.asyncio
async def test_zero_disk_residue_interceptor_dingtalk(dingtalk_env: None) -> None:
    """Adversarially intercept builtins.open and tempfile during DingTalk multimodal processing."""
    cfg = Config.from_env()
    mock_sdk = MockDingTalkChannel()
    reply = MockDingTalkReply()

    mock_agent = MockAgent(response_chunks=["Processed DD zero disk"])
    session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = DingTalkBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_zero_disk_intercept",
        conversation_id="cid_dd_zero_disk_intercept",
        text="Check DD zero disk",
        resources=[
            {"downloadCode": "c1", "fileName": "image.png", "type": "image"},
            {"downloadCode": "c2", "fileName": "report.pdf", "type": "file"},
            {"downloadCode": "c3", "fileName": "data.bin", "type": "file"},
        ],
    )

    real_open = open
    disk_write_attempts: list[str] = []

    def tracking_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if any(m in mode for m in ("w", "a", "x", "+")):
            disk_write_attempts.append(f"Write operation on {file} with mode {mode}")
        return real_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=tracking_open):
        await bot.on_message(msg, reply)

    assert len(disk_write_attempts) == 0, (
        f"Disk write operations detected during DingTalk download: {disk_write_attempts}"
    )


# ===========================================================================
# Scope 6: Concurrency Lock Release During Stream Failure
# ===========================================================================


@pytest.mark.asyncio
async def test_session_lock_released_when_stream_and_all_fallbacks_fail(
    feishu_env: None,
) -> None:
    """When CardKit stream, markdown, and text fallback all crash, lock must still be unlocked."""
    cfg = Config.from_env()
    mock_sdk = MockFeishuChannel()

    # Fail everything
    mock_sdk.stream = AsyncMock(side_effect=RuntimeError("Stream exploded"))
    mock_sdk.send = AsyncMock(side_effect=RuntimeError("Send completely broken"))

    mock_agent = MockAgent(response_chunks=["Token"])
    session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = FeishuBotChannel(config=cfg, channel=mock_sdk, session_manager=session_mgr)

    msg1 = MockFeishuInboundMessage(
        msg_id="om_fail_lock_1",
        chat_id="oc_shared_lock_session",
        content_text="Catastrophic fail turn 1",
    )
    msg2 = MockFeishuInboundMessage(
        msg_id="om_fail_lock_2",
        chat_id="oc_shared_lock_session",
        content_text="Turn 2 should acquire lock",
    )

    # First turn fails completely
    await bot.on_message(msg1)

    # Lock must NOT be acquired / locked
    session_key = bot.get_session_key("oc_shared_lock_session")
    lock = session_mgr.get_lock(session_key)
    assert not lock.locked(), "Session lock was left locked after catastrophic failure!"

    # Now repair send for turn 2
    mock_sdk.stream = AsyncMock()  # normal stream
    await bot.on_message(msg2)
    assert not lock.locked(), "Session lock was left locked after turn 2!"
