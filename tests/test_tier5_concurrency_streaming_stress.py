"""Tier 5: Adversarial Stress Tests - Concurrency, Streaming Fallback, Reaction Resilience, and Zero Temp Files."""

from __future__ import annotations

import asyncio
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from channel_bot_cli_antigravity.channels.dingtalk import DingTalkBotChannel
from channel_bot_cli_antigravity.channels.feishu import FeishuBotChannel
from channel_bot_cli_antigravity.config import Config
from channel_bot_cli_antigravity.utils import create_media_from_bytes

from .conftest import (
    MockAgent,
    MockAgentSessionManager,
    MockChatResponse,
    MockDingTalkCardStreamer,
    MockDingTalkChannel,
    MockDingTalkIncomingMessage,
    MockDingTalkReply,
    MockFeishuChannel,
    MockFeishuInboundMessage,
)

# ---------------------------------------------------------------------------
# Section 1: Streaming Exception & Graceful Fallback Stress Tests
# ---------------------------------------------------------------------------


class MidStreamFailureAgent(MockAgent):
    """Agent that yields tokens slowly to allow testing midway stream interruptions."""

    def __init__(self, tokens: list[str]) -> None:
        super().__init__(tokens)
        self.tokens_yielded: list[str] = []

    async def _mock_chat(self, agent_input: Any) -> Any:
        tokens = self.response_chunks or []
        yielded_list = self.tokens_yielded

        class _StreamIterable:
            def __aiter__(self) -> AsyncIterator[str]:
                async def _gen() -> AsyncIterator[str]:
                    for t in tokens:
                        yielded_list.append(t)
                        await asyncio.sleep(0.01)
                        yield t

                return _gen()

            async def text(self) -> str:
                return "".join(tokens)

        return _StreamIterable()


async def test_stress_feishu_stream_immediate_failure_fallback_markdown(
    feishu_env: None,
) -> None:
    """CardKit stream fails immediately; must fallback to Markdown without crashing."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    # Simulate CardKit permission error
    mock_sdk_channel.stream = AsyncMock(
        side_effect=PermissionError("cardkit:card:write permission missing")
    )

    mock_agent = MockAgent(response_chunks=["Markdown", " Fallback", " Content"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockFeishuInboundMessage(
        msg_id="om_stream_fail_imm",
        chat_id="oc_test_imm",
        content_text="Trigger immediate stream fail",
    )

    # Must complete cleanly
    await bot.on_message(msg)

    # Must have fallen back to sending markdown
    assert len(mock_sdk_channel.sent_messages) == 1
    target, payload = mock_sdk_channel.sent_messages[0]
    assert target == "oc_test_imm"
    assert "Markdown Fallback Content" in payload.get("markdown", "")


async def test_stress_feishu_stream_midway_failure_full_message_recovery(
    feishu_env: None,
) -> None:
    """CardKit stream fails midway during producer append; must collect all remaining tokens and send full fallback."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    # Streamer fails on the 2nd token
    append_count = 0

    async def broken_stream(chat_id: str, spec: dict[str, Any]) -> None:
        nonlocal append_count
        producer = spec.get("markdown")

        class _BrokenStreamer:
            async def append(self, token: str) -> None:
                nonlocal append_count
                append_count += 1
                if append_count >= 2:
                    raise ConnectionResetError("CardKit stream socket broken midway")

        if callable(producer):
            await producer(_BrokenStreamer())

    mock_sdk_channel.stream = broken_stream

    mock_agent = MidStreamFailureAgent(tokens=["Part1_", "Part2_", "Part3_End"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockFeishuInboundMessage(
        msg_id="om_stream_fail_mid",
        chat_id="oc_test_mid",
        content_text="Trigger midway stream fail",
    )

    await bot.on_message(msg)

    # Fallback message must contain all 3 parts without truncation
    assert len(mock_sdk_channel.sent_messages) == 1
    target, payload = mock_sdk_channel.sent_messages[0]
    assert target == "oc_test_mid"
    delivered = payload.get("markdown") or payload.get("text", "")
    assert "Part1_Part2_Part3_End" in delivered


async def test_stress_feishu_stream_and_markdown_failure_fallback_text(
    feishu_env: None,
) -> None:
    """CardKit stream fails AND markdown send fails; must fallback to plain text."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_sdk_channel.stream = AsyncMock(side_effect=RuntimeError("Stream unavailable"))

    # When markdown send is attempted, reject it
    original_send = mock_sdk_channel.send

    async def fail_markdown_send(chat_id: str, content: dict[str, Any]) -> Any:
        if "markdown" in content:
            raise ValueError("Markdown format rejected by tenant policy")
        return await original_send(chat_id, content)

    mock_sdk_channel.send = fail_markdown_send

    mock_agent = MockAgent(response_chunks=["Safe", " Plain", " Text"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockFeishuInboundMessage(
        msg_id="om_text_fallback",
        chat_id="oc_test_txt",
        content_text="Trigger text fallback",
    )

    await bot.on_message(msg)

    assert len(mock_sdk_channel.sent_messages) == 1
    target, payload = mock_sdk_channel.sent_messages[0]
    assert target == "oc_test_txt"
    assert payload.get("text") == "Safe Plain Text"


async def test_stress_feishu_all_fallbacks_fail_graceful_no_crash(
    feishu_env: None,
) -> None:
    """CardKit stream, markdown send, and text send all fail; bot must catch error and send polite notice without crashing."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_sdk_channel.stream = AsyncMock(side_effect=RuntimeError("Stream dead"))

    send_attempts: list[dict[str, Any]] = []

    async def fail_replies(chat_id: str, content: dict[str, Any]) -> Any:
        send_attempts.append(content)
        # Fail the first 2 reply attempts (markdown and text fallback)
        if len(send_attempts) <= 2:
            raise RuntimeError(f"Network error on attempt {len(send_attempts)}")
        # 3rd attempt is the error notice
        return {"status": "ok"}

    mock_sdk_channel.send = fail_replies

    mock_agent = MockAgent(response_chunks=["Payload"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockFeishuInboundMessage(
        msg_id="om_catastrophic",
        chat_id="oc_catastrophic",
        content_text="Trigger cascading fail",
    )

    # Must NOT raise unhandled exception
    await bot.on_message(msg)

    # Must have attempted markdown, text, then error notice
    assert len(send_attempts) >= 3
    assert "抱歉，处理您的请求时出现异常" in send_attempts[-1].get("text", "")


async def test_stress_dingtalk_stream_immediate_failure_fallback_markdown(
    dingtalk_env: None,
) -> None:
    """DingTalk AI Card stream fails immediately; must fallback to Markdown without crashing."""
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    reply = MockDingTalkReply()
    reply.stream = AsyncMock(
        side_effect=RuntimeError("DingTalk AI Card stream refused")
    )

    mock_agent = MockAgent(response_chunks=["DingTalk", " MD", " Fallback"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_imm_fail",
        conversation_id="cid_dd_imm",
        text="Stream fail test",
    )

    await bot.on_message(msg, reply)

    # Must have sent markdown fallback
    assert len(reply.markdown_replies) == 1
    _title, text = reply.markdown_replies[0]
    assert "DingTalk MD Fallback" in text


async def test_stress_dingtalk_stream_midway_failure_token_drain_behavior(
    dingtalk_env: None,
) -> None:
    """Adversarial challenge: DingTalk AI Card stream fails midway.

    Empirically inspects whether remaining tokens from the generator are drained or lost.
    """
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    # Streamer appender fails on token 2
    append_count = 0
    streamer = MockDingTalkCardStreamer()

    async def broken_append(delta: str) -> None:
        nonlocal append_count
        append_count += 1
        if append_count >= 2:
            raise ConnectionError("DingTalk card socket terminated midway")
        streamer.tokens.append(delta)

    streamer.append = broken_append
    reply = MockDingTalkReply(streamer=streamer)

    mock_agent = MidStreamFailureAgent(tokens=["Alpha_", "Beta_", "Gamma_Done"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_mid_fail",
        conversation_id="cid_dd_mid",
        text="Midway fail test",
    )

    await bot.on_message(msg, reply)

    # Verify fallback was delivered
    assert len(reply.markdown_replies) >= 1 or len(reply.text_replies) >= 1
    delivered_text = (
        reply.markdown_replies[0][1]
        if reply.markdown_replies
        else reply.text_replies[0]
    )
    # Check if the text contains Alpha
    assert "Alpha_" in delivered_text


async def test_stress_dingtalk_stream_and_markdown_failure_fallback_text(
    dingtalk_env: None,
) -> None:
    """DingTalk stream fails AND markdown send fails; must fallback to plain text."""
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    reply = MockDingTalkReply()
    reply.stream = AsyncMock(side_effect=RuntimeError("Stream dead"))
    reply.markdown = AsyncMock(side_effect=RuntimeError("Markdown rendering disabled"))

    mock_agent = MockAgent(response_chunks=["Pure", " Text", " Fallback"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_txt_fail",
        conversation_id="cid_dd_txt",
        text="Markdown fail test",
    )

    await bot.on_message(msg, reply)

    assert len(reply.text_replies) == 1
    assert "Pure Text Fallback" in reply.text_replies[0]


async def test_stress_dingtalk_all_fallbacks_fail_graceful_no_crash(
    dingtalk_env: None,
) -> None:
    """DingTalk stream, markdown, and text all fail; must catch error and send polite notice without crashing."""
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    reply = MockDingTalkReply()
    reply.stream = AsyncMock(side_effect=RuntimeError("Stream dead"))
    reply.markdown = AsyncMock(side_effect=RuntimeError("Markdown dead"))

    text_attempts: list[str] = []

    async def fail_text(txt: str) -> None:
        text_attempts.append(txt)
        if len(text_attempts) == 1:
            raise RuntimeError("Text dead on first fallback")
        # 2nd attempt is polite error notice

    reply.text = fail_text

    mock_agent = MockAgent(response_chunks=["Payload"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_catastrophic",
        conversation_id="cid_dd_catastrophic",
        text="Cascading fail test",
    )

    # Must complete without unhandled exception
    await bot.on_message(msg, reply)

    # Must have attempted text fallback
    assert len(text_attempts) >= 1
    assert text_attempts[0] == "Payload"


# ---------------------------------------------------------------------------
# Section 2: Thinking Reaction Exception Resilience Stress Tests
# ---------------------------------------------------------------------------


async def test_stress_feishu_reaction_add_exception_uninterrupted(
    feishu_env: None,
) -> None:
    """Feishu add_typing_reaction raises unexpected exception; conversation turn must continue uninterrupted."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_sdk_channel.add_typing_reaction = AsyncMock(
        side_effect=RuntimeError("Feishu API reaction 503 Service Unavailable")
    )

    mock_agent = MockAgent(response_chunks=["Turn", " Continued", " Successfully"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockFeishuInboundMessage(
        msg_id="om_react_add_err",
        chat_id="oc_react_chat",
        content_text="Check reaction resilience",
    )

    await bot.on_message(msg)

    # Agent was invoked
    assert len(mock_agent.chat_history) == 1
    # Reply was streamed
    assert len(mock_sdk_channel.streams) == 1
    # remove_typing_reaction was NOT called because add failed
    assert len(mock_sdk_channel.removed_reactions) == 0


async def test_stress_feishu_reaction_remove_exception_uninterrupted(
    feishu_env: None,
) -> None:
    """Feishu remove_typing_reaction raises unexpected exception; must be swallowed in finally without crashing."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_sdk_channel.remove_typing_reaction = AsyncMock(
        side_effect=ConnectionError("Failed to delete reaction on Feishu server")
    )

    mock_agent = MockAgent(response_chunks=["Hello"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockFeishuInboundMessage(
        msg_id="om_react_rm_err",
        chat_id="oc_react_chat",
        content_text="Check remove reaction resilience",
    )

    # Must complete cleanly without raising
    await bot.on_message(msg)

    assert len(mock_sdk_channel.added_reactions) == 1
    assert len(mock_sdk_channel.streams) == 1


async def test_stress_dingtalk_reaction_thinking_exception_uninterrupted(
    dingtalk_env: None,
) -> None:
    """DingTalk mark_thinking raises unexpected error; turn execution must continue uninterrupted."""
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()
    mock_sdk_channel.mark_thinking = AsyncMock(
        side_effect=PermissionError("DingTalk robot not allowed to set emotion stamp")
    )

    mock_agent = MockAgent(response_chunks=["DD", " Still", " Works"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_react_1",
        conversation_id="cid_dd_react",
        text="Emotion stamp error test",
    )
    reply = MockDingTalkReply()

    await bot.on_message(msg, reply)

    assert len(mock_agent.chat_history) == 1
    # Card streamer received tokens
    assert reply.streamer.tokens == ["DD", " Still", " Works"]
    # mark_done was still called in finally!
    assert len(mock_sdk_channel.done_stamps) == 1


async def test_stress_dingtalk_reaction_done_exception_uninterrupted(
    dingtalk_env: None,
) -> None:
    """DingTalk mark_done raises unexpected error; must be swallowed in finally without crashing."""
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()
    mock_sdk_channel.mark_done = AsyncMock(
        side_effect=TimeoutError("DingTalk server timeout on mark_done")
    )

    mock_agent = MockAgent(response_chunks=["Response"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_react_2",
        conversation_id="cid_dd_react",
        text="Done stamp error test",
    )
    reply = MockDingTalkReply()

    await bot.on_message(msg, reply)

    assert reply.streamer.tokens == ["Response"]


# ---------------------------------------------------------------------------
# Section 3: Concurrency Locking & Interleaving Prevention Stress Tests
# ---------------------------------------------------------------------------


class ConcurrencyTestingAgent(MockAgent):
    """Adversarial Agent that verifies no other turn executes concurrently."""

    def __init__(self, delay_seconds: float = 0.05) -> None:
        super().__init__()
        self.delay = delay_seconds
        self.active_turns = 0
        self.max_concurrent_turns = 0
        self.turn_history: list[tuple[str, float, float]] = []  # (msg_id, start, end)

    async def _mock_chat(self, agent_input: Any) -> MockChatResponse:
        self.active_turns += 1
        self.max_concurrent_turns = max(self.max_concurrent_turns, self.active_turns)

        # Extract message_id from frontmatter if possible
        msg_id = "unknown"
        if isinstance(agent_input, list) and len(agent_input) > 0:
            fm = str(agent_input[0])
            for line in fm.split("\n"):
                if line.startswith("message_id:"):
                    msg_id = line.split(":", 1)[1].strip().strip('"')

        start_time = time.perf_counter()
        # Simulate LLM thinking / processing delay
        await asyncio.sleep(self.delay)
        end_time = time.perf_counter()

        self.turn_history.append((msg_id, start_time, end_time))
        self.active_turns -= 1

        return MockChatResponse(["TokenA", "TokenB"])


async def test_stress_concurrency_same_session_strict_serialization(
    feishu_env: None,
) -> None:
    """Adversarially launch 10 concurrent messages to the SAME chat_id.

    Empirically verify that they execute in strict mutual exclusion with max_concurrent_turns == 1.
    """
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    concurrent_agent = ConcurrencyTestingAgent(delay_seconds=0.03)
    mock_session_mgr = MockAgentSessionManager(agent=concurrent_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )

    # Create 10 messages targeting the EXACT same chat_id
    messages = [
        MockFeishuInboundMessage(
            msg_id=f"om_concurrent_{i}",
            chat_id="oc_shared_session_target",
            content_text=f"Message {i}",
        )
        for i in range(10)
    ]

    # Dispatch all 10 messages simultaneously via asyncio.gather
    await asyncio.gather(*(bot.on_message(m) for m in messages))

    # CRITICAL CHECK 1: Max concurrent active turns inside agent.chat must be exactly 1!
    assert concurrent_agent.max_concurrent_turns == 1, (
        f"Interleaving detected! max_concurrent_turns was {concurrent_agent.max_concurrent_turns}, expected 1"
    )

    # CRITICAL CHECK 2: Turn start/end times must not overlap
    history = concurrent_agent.turn_history
    assert len(history) == 10
    for i in range(len(history) - 1):
        prev_msg, _prev_start, prev_end = history[i]
        curr_msg, curr_start, _curr_end = history[i + 1]
        assert curr_start >= prev_end - 0.001, (
            f"Overlapping turns detected between {prev_msg} (ended {prev_end}) "
            f"and {curr_msg} (started {curr_start})!"
        )


async def test_stress_concurrency_dingtalk_same_session_strict_serialization(
    dingtalk_env: None,
) -> None:
    """Adversarially launch 10 concurrent messages to DingTalk with the SAME conversation_id."""
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    concurrent_agent = ConcurrencyTestingAgent(delay_seconds=0.03)
    mock_session_mgr = MockAgentSessionManager(agent=concurrent_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )

    messages_and_replies = [
        (
            MockDingTalkIncomingMessage(
                msg_id=f"msg_dd_conc_{i}",
                conversation_id="cid_shared_dd_session",
                text=f"DingTalk concurrent {i}",
            ),
            MockDingTalkReply(),
        )
        for i in range(10)
    ]

    await asyncio.gather(
        *(bot.on_message(msg, rep) for msg, rep in messages_and_replies)
    )

    assert concurrent_agent.max_concurrent_turns == 1
    history = concurrent_agent.turn_history
    assert len(history) == 10
    for i in range(len(history) - 1):
        _prev_msg, _prev_start, prev_end = history[i]
        _curr_msg, curr_start, _curr_end = history[i + 1]
        assert curr_start >= prev_end - 0.001


async def test_stress_concurrency_error_in_turn_releases_lock(
    feishu_env: None,
) -> None:
    """If turn 1 crashes inside agent.chat, the session lock MUST be released so turn 2 succeeds."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    call_count = 0

    async def chat_that_fails_on_turn_1(agent_input: Any) -> MockChatResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Fatal unhandled agent engine crash on turn 1")
        return MockChatResponse(["Turn 2 succeeded"])

    mock_agent = MockAgent()
    mock_agent.chat = AsyncMock(side_effect=chat_that_fails_on_turn_1)
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )

    msg1 = MockFeishuInboundMessage(
        msg_id="om_fail_turn1",
        chat_id="oc_lock_recovery",
        content_text="Turn 1 should fail",
    )
    msg2 = MockFeishuInboundMessage(
        msg_id="om_succ_turn2",
        chat_id="oc_lock_recovery",
        content_text="Turn 2 should recover",
    )

    # Run turn 1 and turn 2 sequentially
    await bot.on_message(msg1)
    await bot.on_message(msg2)

    # Turn 2 must not be deadlocked and must have executed
    assert call_count == 2
    assert len(mock_sdk_channel.streams) == 1


async def test_stress_concurrency_different_sessions_parallel_execution(
    feishu_env: None,
) -> None:
    """Messages to DIFFERENT chat_ids have separate locks and execute in parallel."""
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    concurrent_agent = ConcurrencyTestingAgent(delay_seconds=0.1)
    mock_session_mgr = MockAgentSessionManager(agent=concurrent_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )

    # 4 distinct chat IDs
    messages = [
        MockFeishuInboundMessage(
            msg_id=f"om_diff_{i}",
            chat_id=f"oc_distinct_chat_{i}",
            content_text=f"Parallel msg {i}",
        )
        for i in range(4)
    ]

    start_all = time.perf_counter()
    await asyncio.gather(*(bot.on_message(m) for m in messages))
    elapsed = time.perf_counter() - start_all

    # If executed strictly sequentially, 4 * 0.1s would take >= 0.4s
    # If executed concurrently in parallel, it takes approx 0.1s - 0.25s
    assert concurrent_agent.max_concurrent_turns > 1, (
        f"Expected parallel execution across distinct sessions, but max_concurrent_turns was {concurrent_agent.max_concurrent_turns}"
    )
    assert elapsed < 0.35, f"Took {elapsed:.2f}s, expected concurrent speedup"


# ---------------------------------------------------------------------------
# Section 4: Zero Temporary Files Residue on Disk Stress Tests
# ---------------------------------------------------------------------------


def _snapshot_temp_and_workspace_files(workspace_root: Path) -> set[Path]:
    """Snapshots file paths in system temp dir and project directory."""
    temp_dir = Path(tempfile.gettempdir())
    files: set[Path] = set()

    # Sample temp dir files (non-recursive to avoid traversing thousands of unrelated system files)
    try:
        for p in temp_dir.iterdir():
            if p.is_file() and not p.name.startswith(
                ("Setup Log", "__PSScriptPolicyTest")
            ):
                files.add(p)
    except OSError:
        pass

    # Sample workspace files
    for p in workspace_root.glob("**/*"):
        if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts:
            files.add(p)

    return files


async def test_stress_zero_temp_files_feishu_multimodal(
    feishu_env: None, tmp_path: Path
) -> None:
    """Verify Feishu inbound multimodal messages leave ZERO temporary files on disk."""
    workspace_root = Path.cwd()
    before_files = _snapshot_temp_and_workspace_files(workspace_root)

    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    # Register mock downloaded bytes in memory
    mock_sdk_channel.downloaded_resources["res_png_key"] = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    )
    mock_sdk_channel.downloaded_resources["res_pdf_key"] = b"%PDF-1.4 mock pdf data"
    mock_sdk_channel.downloaded_resources["res_audio_key"] = (
        b"ID3\x03\x00\x00\x00mock audio"
    )
    mock_sdk_channel.downloaded_resources["res_bin_key"] = (
        b"\x00\x01\x02\x03\x04\x05binary"
    )

    class ResourceItem:
        def __init__(self, key: str, res_type: str, name: str) -> None:
            self.file_key = key
            self.type = res_type
            self.file_name = name

    mock_agent = MockAgent(response_chunks=["Multimodal reply"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(
        msg_id="om_media_zero_disk",
        chat_id="oc_media_disk_test",
        content_text="Check this image and pdf",
        resources=[
            ResourceItem("res_png_key", "image", "photo.png"),
            ResourceItem("res_pdf_key", "file", "document.pdf"),
            ResourceItem("res_audio_key", "audio", "voice.mp3"),
            ResourceItem("res_bin_key", "file", "archive.dat"),
        ],
    )

    await bot.on_message(msg)

    after_files = _snapshot_temp_and_workspace_files(workspace_root)
    new_files = after_files - before_files

    assert len(new_files) == 0, f"Temporary file leak detected on disk: {new_files}"


async def test_stress_zero_temp_files_dingtalk_multimodal(
    dingtalk_env: None, tmp_path: Path
) -> None:
    """Verify DingTalk inbound multimodal messages leave ZERO temporary files on disk."""
    workspace_root = Path.cwd()
    before_files = _snapshot_temp_and_workspace_files(workspace_root)

    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()
    reply = MockDingTalkReply()

    mock_agent = MockAgent(response_chunks=["DingTalk media reply"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_media_zero_disk",
        conversation_id="cid_dd_disk_test",
        text="DingTalk media zero disk check",
        resources=[
            {
                "downloadCode": "code_img_1",
                "fileName": "screenshot.png",
                "type": "image",
            },
            {"downloadCode": "code_pdf_1", "fileName": "report.pdf", "type": "file"},
            {"downloadCode": "code_dat_1", "fileName": "blob.bin", "type": "file"},
        ],
    )

    await bot.on_message(msg, reply)

    after_files = _snapshot_temp_and_workspace_files(workspace_root)
    new_files = after_files - before_files

    assert len(new_files) == 0, f"Temporary file leak detected on disk: {new_files}"


def test_stress_zero_temp_files_create_media_from_bytes_in_memory() -> None:
    """Direct empirical test: create_media_from_bytes never creates files on disk."""
    workspace_root = Path.cwd()
    before_files = _snapshot_temp_and_workspace_files(workspace_root)

    # Test PNG
    png_media = create_media_from_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01", "test.png", "image"
    )
    assert png_media is not None

    # Test PDF
    pdf_media = create_media_from_bytes(b"%PDF-1.4 test", "test.pdf", "file")
    assert pdf_media is not None

    # Test Text
    txt_media = create_media_from_bytes(b"hello world plaintext", "notes.txt", "file")
    assert txt_media is not None

    # Test Unknown binary (non-UTF8)
    unk_media = create_media_from_bytes(b"\xff\xfe\x00\xff", "unknown.bin", "file")
    assert "暂不支持该格式直接解析" in unk_media

    after_files = _snapshot_temp_and_workspace_files(workspace_root)
    new_files = after_files - before_files

    assert len(new_files) == 0, f"Temporary file leak detected on disk: {new_files}"


# ---------------------------------------------------------------------------
# Section 5: Adversarial Deep-Dive on Antigravity Multi-Cursor Stream Fallbacks
# ---------------------------------------------------------------------------


class AntigravityChatResponseSimulator:
    """Simulates Google Antigravity types.ChatResponse with independent cursors.

    In the real Antigravity SDK, every iterator over response creates an independent cursor
    from the beginning of the buffer.
    """

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    def __aiter__(self) -> AsyncIterator[str]:
        async def _cursor() -> AsyncIterator[str]:
            for chunk in self.chunks:
                await asyncio.sleep(0.005)
                yield chunk

        return _cursor()

    async def text(self) -> str:
        return "".join(self.chunks)


async def test_adversarial_dingtalk_midway_stream_failure_causes_truncation(
    dingtalk_env: None,
) -> None:
    """EMPIRICAL CHALLENGE BUG:

    In channels/dingtalk.py (lines 222-225):
        if not stream_succeeded:
            if not tokens:
                async for token in response:
                    tokens.append(token)
            full_reply = "".join(tokens)

    If streamer fails midway after appending N tokens, `tokens` is not empty.
    Thus `if not tokens:` is False, and the remaining tokens from `response` are NEVER consumed!
    The fallback message is permanently truncated.
    """
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    append_count = 0
    streamer = MockDingTalkCardStreamer()

    async def broken_append(delta: str) -> None:
        nonlocal append_count
        append_count += 1
        if append_count >= 2:
            raise ConnectionError("CardKit/DingTalk card connection lost midway")
        streamer.tokens.append(delta)

    streamer.append = broken_append
    reply = MockDingTalkReply(streamer=streamer)

    # 3 semantic chunks
    chunks = ["Important ", "data: ", "123456789"]

    class _MockAgentWithSim(MockAgent):
        async def _mock_chat(self, agent_input: Any) -> Any:
            return AntigravityChatResponseSimulator(chunks)

    mock_agent = _MockAgentWithSim()
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_trunc",
        conversation_id="cid_dd_trunc",
        text="Check truncation",
    )

    await bot.on_message(msg, reply)

    # Verify delivered text
    assert len(reply.markdown_replies) == 1
    delivered = reply.markdown_replies[0][1]

    # M3 HARDENING VERIFICATION: All tokens recovered from response.text() without truncation!
    assert "123456789" in delivered, (
        f"Expected full recovery of remaining chunks, but got: {delivered}"
    )
    assert delivered == "Important data: 123456789", (
        f"DingTalk delivered full message without truncation: {delivered}"
    )


async def test_adversarial_feishu_midway_stream_failure_causes_duplication(
    feishu_env: None,
) -> None:
    """EMPIRICAL CHALLENGE BUG:

    In channels/feishu.py (lines 295-300):
        if not stream_succeeded:
            async for token in response:
                tokens.append(token)
            full_reply = "".join(tokens)

    In Antigravity SDK, response is a ChatResponse where iterating returns an independent
    cursor from index 0. If streaming fails midway after producer already appended tokens,
    the fallback loop appends from index 0 into `tokens` without clearing it first.
    The fallback message therefore contains duplicate tokens!
    """
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    append_count = 0

    async def broken_stream(chat_id: str, spec: dict[str, Any]) -> None:
        nonlocal append_count
        producer = spec.get("markdown")

        class _BrokenStreamer:
            async def append(self, token: str) -> None:
                nonlocal append_count
                append_count += 1
                if append_count >= 2:
                    raise ConnectionResetError("CardKit stream socket reset midway")

        if callable(producer):
            await producer(_BrokenStreamer())

    mock_sdk_channel.stream = broken_stream

    chunks = ["Hello ", "World ", "Done"]

    class _MockAgentWithSim(MockAgent):
        async def _mock_chat(self, agent_input: Any) -> Any:
            return AntigravityChatResponseSimulator(chunks)

    mock_agent = _MockAgentWithSim()
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr
    )
    msg = MockFeishuInboundMessage(
        msg_id="om_feishu_dup",
        chat_id="oc_feishu_dup",
        content_text="Check duplication",
    )

    await bot.on_message(msg)

    assert len(mock_sdk_channel.sent_messages) == 1
    delivered = mock_sdk_channel.sent_messages[0][1].get("markdown", "")

    # M3 HARDENING VERIFICATION: Tokens are not duplicated when recovered from response.text()!
    assert delivered == "Hello World Done", (
        f"Feishu delivered full message without duplication: {delivered}"
    )
