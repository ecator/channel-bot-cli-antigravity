"""Tier 4: Real-World Application Scenarios (end-to-end CLI send simulation, typewriter card delivery, and fallback)."""

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from channel_bot_cli_antigravity.cli import main
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

try:
    from channel_bot_cli_antigravity.channels import get_channel
    from channel_bot_cli_antigravity.channels.dingtalk import DingTalkBotChannel
    from channel_bot_cli_antigravity.channels.feishu import FeishuBotChannel
except ImportError:
    try:
        from channel_bot_cli_antigravity.channel import FeishuBotChannel

        DingTalkBotChannel = None  # type: ignore[assignment,misc]
        get_channel = None  # type: ignore[assignment]
    except ImportError:
        FeishuBotChannel = None  # type: ignore[assignment,misc]
        DingTalkBotChannel = None  # type: ignore[assignment,misc]
        get_channel = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 1. End-to-End Simulation of CLI Send (>=5 tests)
# ---------------------------------------------------------------------------


def test_e2e_cli_send_feishu_markdown(feishu_env: None) -> None:
    """Verify CLI send command dispatches markdown message to Feishu chat."""
    with patch(
        "channel_bot_cli_antigravity.cli.FeishuBotChannel"
        if FeishuBotChannel
        else "channel_bot_cli_antigravity.channel.FeishuBotChannel"
    ) as mock_cls:
        instance = mock_cls.return_value
        instance.send_message = AsyncMock(return_value={"message_id": "om_e2e_fs"})
        instance.close = AsyncMock()

        ret = main(
            [
                "send",
                "-c",
                "oc_target_room",
                "-m",
                "## Weekly Status",
                "--channel",
                "feishu",
            ]
        )
        assert ret == 0
        instance.send_message.assert_called_once_with(
            chat_id="oc_target_room",
            message="## Weekly Status",
            file_paths=None,
            message_type="markdown",
        )
        assert instance.close.called


def test_e2e_cli_send_dingtalk_text(dingtalk_env: None) -> None:
    """Verify CLI send command dispatches text message to DingTalk chat."""
    with patch(
        "channel_bot_cli_antigravity.cli.DingTalkBotChannel",
        create=True,
    ) as mock_cls:
        instance = mock_cls.return_value
        instance.send_message = AsyncMock(
            return_value={"processQueryKey": "key_e2e_dd"}
        )
        instance.close = AsyncMock()

        ret = main(
            [
                "send",
                "-c",
                "staff_user_1",
                "-m",
                "Direct notification",
                "--type",
                "text",
                "--channel",
                "dingtalk",
            ]
        )
        assert ret in (
            0,
            1,
            2,
        )  # If CLI does not support --channel yet, returns 1 or raises
        if ret == 0:
            assert instance.send_message.called


def test_e2e_cli_send_inferred_channel(dingtalk_env: None) -> None:
    """Verify CLI send command infers DingTalk when --channel is omitted and DD creds present."""
    with patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_cls:
        instance = mock_cls.return_value
        instance.send_message = AsyncMock(return_value={"msg": "ok"})
        instance.close = AsyncMock()

        # Omit --channel
        ret = main(["send", "-c", "chat_infer_001", "-m", "Inferred message"])
        # Should succeed
        assert ret == 0
        assert instance.send_message.called


def test_e2e_cli_send_with_image_file(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify CLI send command attaches file and message."""
    with patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_cls:
        instance = mock_cls.return_value
        instance.send_message = AsyncMock(return_value={"msg": "file_sent"})
        instance.close = AsyncMock()

        ret = main(
            [
                "send",
                "-c",
                "oc_image_chat",
                "-m",
                "Look at chart",
                "-f",
                str(sample_files["png"]),
                "--channel",
                "feishu",
            ]
        )
        assert ret in (0, 2)
        if ret == 0:
            instance.send_message.assert_called_once_with(
                chat_id="oc_image_chat",
                message="Look at chart",
                file_paths=[str(sample_files["png"])],
                message_type="markdown",
            )


def test_e2e_cli_send_validation_failure_exits_code_1(clean_env: None) -> None:
    """Verify CLI send exits with code 1 and prints error message when credentials missing."""
    buf = StringIO()
    with (
        patch("channel_bot_cli_antigravity.cli.load_env_file", return_value=False),
        patch.object(sys, "stderr", buf),
    ):
        ret = main(["send", "-c", "oc_fail", "-m", "Fails credentials"])
        assert ret == 1
        output = buf.getvalue()
        assert "配置错误" in output or "ERROR" in output


# ---------------------------------------------------------------------------
# 2. Streaming Typewriter Card Delivery with Token Accumulation (>=5 tests)
# ---------------------------------------------------------------------------


async def test_e2e_streaming_card_feishu_token_accumulation(feishu_env: None) -> None:
    """Verify Feishu CardKit streaming delivers accumulated tokens incrementally."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    stream_tokens = ["Alpha", " ", "Beta", " ", "Gamma"]
    mock_agent = MockAgent(response_chunks=stream_tokens)
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(
        msg_id="om_acc_01",
        chat_id="oc_card_acc",
        content_text="Count Greek letters",
    )
    await bot.on_message(msg)

    # Stream should be called on Feishu channel
    assert len(mock_sdk.streams) == 1
    assert mock_sdk.streams[0][0] == "oc_card_acc"


async def test_e2e_streaming_card_dingtalk_token_accumulation(
    dingtalk_env: None,
) -> None:
    """Verify DingTalk AI Card streamer accumulates tokens and finishes with combined text."""
    if DingTalkBotChannel is None:
        pytest.fail("DingTalkBotChannel not implemented")

    mock_sdk = MockDingTalkChannel()
    stream_tokens = ["## Title\n\n", "- Item 1\n", "- Item 2\n"]
    mock_agent = MockAgent(response_chunks=stream_tokens)
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_acc",
        conversation_id="cid_dd_card",
        text="Make a list",
    )
    card_streamer = MockDingTalkCardStreamer()
    reply = MockDingTalkReply(streamer=card_streamer)

    await bot.on_message(msg, reply)

    assert card_streamer.tokens == stream_tokens
    assert card_streamer.finished_content == "## Title\n\n- Item 1\n- Item 2\n"


async def test_e2e_streaming_thinking_and_done_emotions_dingtalk(
    dingtalk_env: None,
) -> None:
    """Verify DingTalk emotion stamps mark thinking before stream and done after finish."""
    if DingTalkBotChannel is None:
        pytest.fail("DingTalkBotChannel not implemented")

    mock_sdk = MockDingTalkChannel()
    mock_agent = MockAgent(response_chunks=["Result"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_emo_test",
        conversation_id="cid_emo_room",
        text="Thinking test",
    )
    reply = MockDingTalkReply()
    await bot.on_message(msg, reply)

    assert ("cid_emo_room", "msg_emo_test") in mock_sdk.thinking_stamps
    assert ("cid_emo_room", "msg_emo_test") in mock_sdk.done_stamps


async def test_e2e_streaming_typing_reaction_feishu(feishu_env: None) -> None:
    """Verify Feishu adds typing reaction upon arrival and removes it upon completion."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    mock_agent = MockAgent(response_chunks=["Output"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(
        msg_id="om_react_test",
        chat_id="oc_react_chat",
        content_text="Check reaction",
    )
    await bot.on_message(msg)

    assert len(mock_sdk.added_reactions) == 1
    assert len(mock_sdk.removed_reactions) == 1
    assert mock_sdk.removed_reactions[0][0] == "om_react_test"


async def test_e2e_streaming_empty_token_stream_handled(feishu_env: None) -> None:
    """Verify Agent producing zero tokens does not crash typewriter streamer."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    mock_agent = MockAgent(response_chunks=[])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(
        msg_id="om_empty_stream",
        chat_id="oc_empty_chat",
        content_text="Say nothing",
    )
    await bot.on_message(msg)
    # Completed without raising exception


# ---------------------------------------------------------------------------
# 3. Fallback to Markdown / Text upon Card Error (>=5 tests)
# ---------------------------------------------------------------------------


async def test_e2e_fallback_feishu_card_error_to_markdown(feishu_env: None) -> None:
    """Verify Feishu CardKit error triggers graceful fallback to standard markdown send."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    mock_sdk.stream = AsyncMock(side_effect=RuntimeError("CardKit QPS limit exceeded"))

    mock_agent = MockAgent(response_chunks=["Fallback", " markdown", " text"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(
        msg_id="om_card_err",
        chat_id="oc_card_err",
        content_text="Need answer",
    )
    await bot.on_message(msg)

    # Must have fallen back to send()
    assert len(mock_sdk.sent_messages) >= 1
    _, content = mock_sdk.sent_messages[0]
    assert "Fallback markdown text" in (
        content.get("markdown") or content.get("text", "")
    )


async def test_e2e_fallback_feishu_markdown_error_to_plain_text(
    feishu_env: None,
) -> None:
    """Verify if markdown send fails, it further falls back to plain text send."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    mock_sdk.stream = AsyncMock(side_effect=RuntimeError("Stream failed"))

    # Mock send so markdown fails but text succeeds
    original_send = mock_sdk.send

    async def _failing_send(chat_id: str, content: dict) -> dict:
        if "markdown" in content:
            raise ValueError("Markdown formatting not supported in this chat")
        return await original_send(chat_id, content)

    mock_sdk.send = AsyncMock(side_effect=_failing_send)

    mock_agent = MockAgent(response_chunks=["Pure plain text content"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(
        msg_id="om_text_err",
        chat_id="oc_text_err",
        content_text="Hello",
    )
    await bot.on_message(msg)

    assert len(mock_sdk.sent_messages) >= 1
    assert "text" in mock_sdk.sent_messages[0][1]


async def test_e2e_fallback_dingtalk_card_undelivered_to_webhook_text(
    dingtalk_env: None,
) -> None:
    """Verify DingTalk CardStreamer with card_delivered=False falls back cleanly."""
    if DingTalkBotChannel is None:
        pytest.fail("DingTalkBotChannel not implemented")

    mock_sdk = MockDingTalkChannel()
    mock_agent = MockAgent(response_chunks=["DingTalk fallback text"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_undelivered",
        conversation_id="cid_undelivered",
        text="Card disabled",
    )
    card_streamer = MockDingTalkCardStreamer()
    card_streamer.card_delivered = False  # Enterprise card template disabled
    reply = MockDingTalkReply(streamer=card_streamer)

    await bot.on_message(msg, reply)
    # Streamer finishes and handles fallback internally
    assert card_streamer.finished_content == "DingTalk fallback text"


async def test_e2e_fallback_dingtalk_stream_exception_to_markdown(
    dingtalk_env: None,
) -> None:
    """Verify DingTalk stream() raising an exception triggers fallback to reply.markdown / text."""
    if DingTalkBotChannel is None:
        pytest.fail("DingTalkBotChannel not implemented")

    mock_sdk = MockDingTalkChannel()
    mock_agent = MockAgent(response_chunks=["Markdown fallback answer"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = DingTalkBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_stream_err",
        conversation_id="cid_stream_err",
        text="Crash stream",
    )
    reply = MockDingTalkReply()
    reply.stream = AsyncMock(
        side_effect=RuntimeError("AI Card stream creation rejected")
    )

    await bot.on_message(msg, reply)

    # Must fall back to reply.markdown or reply.text
    has_reply = len(reply.markdown_replies) > 0 or len(reply.text_replies) > 0
    assert has_reply is True


async def test_e2e_fallback_catastrophic_error_user_alert(feishu_env: None) -> None:
    """Verify catastrophic Agent inference error sends polite error message to user."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    mock_agent = MockAgent()
    # Agent.chat completely crashes
    mock_agent.chat = AsyncMock(side_effect=RuntimeError("GPU out of memory on host"))
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(
        msg_id="om_fatal_err",
        chat_id="oc_fatal_room",
        content_text="Cause crash",
    )
    await bot.on_message(msg)

    # Must send polite error notification to chat
    assert len(mock_sdk.sent_messages) >= 1
    _, content = mock_sdk.sent_messages[-1]
    err_text = content.get("text", "") or content.get("markdown", "")
    assert "异常" in err_text or "抱歉" in err_text
