"""Tier 1: Feature Coverage - DingTalkBotChannel adapter mock flow & lifecycle."""

from pathlib import Path
from unittest.mock import AsyncMock

from channel_bot_cli_antigravity.config import Config

from .conftest import (
    MockAgent,
    MockAgentSessionManager,
    MockDingTalkCardStreamer,
    MockDingTalkChannel,
    MockDingTalkIncomingMessage,
    MockDingTalkReply,
)

try:
    from channel_bot_cli_antigravity.channels.dingtalk import DingTalkBotChannel
except ImportError:
    DingTalkBotChannel = None  # type: ignore[assignment,misc]


def _get_dingtalk_channel_cls() -> type:
    assert DingTalkBotChannel is not None, (
        "DingTalkBotChannel must be implemented in src/channel_bot_cli_antigravity/channels/dingtalk.py"
    )
    return DingTalkBotChannel


def test_dingtalk_channel_initialization(dingtalk_env: None) -> None:
    """Verify DingTalkBotChannel initialization and channel_name attribute."""
    cls = _get_dingtalk_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    bot = cls(config=cfg, channel=mock_sdk_channel)
    assert getattr(bot, "channel_name", "dingtalk") == "dingtalk"
    assert bot.channel is mock_sdk_channel


async def test_dingtalk_channel_filter_chat_id(dingtalk_env: None) -> None:
    """Verify DingTalkBotChannel ignores messages not matching filter_chat_id."""
    cls = _get_dingtalk_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()
    mock_session_mgr = MockAgentSessionManager()

    bot = cls(
        config=cfg,
        filter_chat_id="cid_target_only",
        channel=mock_sdk_channel,
        session_manager=mock_session_mgr,
    )

    msg_ignored = MockDingTalkIncomingMessage(
        conversation_id="cid_other_group", text="Hello"
    )
    reply = MockDingTalkReply()

    await bot.on_message(msg_ignored, reply)

    assert len(mock_session_mgr.agent.chat_history) == 0
    assert len(reply.text_replies) == 0
    assert len(mock_sdk_channel.thinking_stamps) == 0


async def test_dingtalk_channel_emotion_stamps_and_suppression(
    dingtalk_env: None,
) -> None:
    """Verify DingTalkBotChannel calls mark_thinking/mark_done and suppresses stamp errors."""
    cls = _get_dingtalk_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()
    # Simulate API failure on mark_thinking (e.g. system message 500 error)
    mock_sdk_channel.mark_thinking = AsyncMock(
        side_effect=RuntimeError("500 system event")
    )

    mock_agent = MockAgent(response_chunks=["Test", " DingTalk", " Reply"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = cls(config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr)

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_stamp_01",
        conversation_id="cid_group_stamp",
        text="Hello with stamp",
    )
    reply = MockDingTalkReply()

    # Must complete successfully without raising exception from mark_thinking
    await bot.on_message(msg, reply)

    assert len(mock_sdk_channel.done_stamps) == 1
    assert mock_sdk_channel.done_stamps[0] == ("cid_group_stamp", "msg_stamp_01")


async def test_dingtalk_channel_streaming_card_flow(dingtalk_env: None) -> None:
    """Verify DingTalkBotChannel AI Card streaming typewriter updates."""
    cls = _get_dingtalk_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    mock_agent = MockAgent(response_chunks=["Token1 ", "Token2 ", "Finished!"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = cls(config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr)

    msg = MockDingTalkIncomingMessage(
        msg_id="msg_dd_stream",
        conversation_id="cid_stream_room",
        text="Please stream reply",
    )
    streamer = MockDingTalkCardStreamer()
    reply = MockDingTalkReply(streamer=streamer)

    await bot.on_message(msg, reply)

    # Card streamer should have received all tokens and finished with combined text
    assert streamer.tokens == ["Token1 ", "Token2 ", "Finished!"]
    assert streamer.finished_content == "Token1 Token2 Finished!"
    assert streamer.failed_error is None


async def test_dingtalk_channel_send_message_target_resolution(
    dingtalk_env: None,
) -> None:
    """Verify send_message distinguishes group conversation_id vs direct user_id."""
    cls = _get_dingtalk_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    bot = cls(config=cfg, channel=mock_sdk_channel)

    # 1. Group chat (starts with cid)
    await bot.send_message(
        chat_id="cid_enterprise_group_01", message="Group announcement"
    )
    assert len(mock_sdk_channel.sent_markdowns) >= 1
    target1, _, _ = mock_sdk_channel.sent_markdowns[0]
    # target should have conversation_id set
    assert getattr(
        target1, "conversation_id", None
    ) == "cid_enterprise_group_01" or str(target1).endswith("cid_enterprise_group_01")

    # 2. Direct user chat (staff ID, doesn't start with cid or chat)
    await bot.send_message(
        chat_id="staff_12345",
        message="Private direct message",
        message_type="text",
    )
    assert len(mock_sdk_channel.sent_texts) >= 1
    target2, _ = mock_sdk_channel.sent_texts[0]
    assert getattr(target2, "user_id", None) == "staff_12345" or str(target2).endswith(
        "staff_12345"
    )


async def test_dingtalk_channel_send_message_media_upload(
    dingtalk_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify DingTalkBotChannel send_message uploads files and dispatches appropriate messages."""
    cls = _get_dingtalk_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()

    bot = cls(config=cfg, channel=mock_sdk_channel)

    # Send image file
    await bot.send_message(
        chat_id="cid_test_media",
        file_paths=str(sample_files["png"]),
    )
    assert len(mock_sdk_channel.oapi.uploads) >= 1
    assert mock_sdk_channel.oapi.uploads[0][0] == "image"
    assert mock_sdk_channel.oapi.uploads[0][3] == "image/png"
    assert len(mock_sdk_channel.sent_images) >= 1
    assert mock_sdk_channel.sent_images[0][1] == f"@media_{sample_files['png'].name}"

    # Verify stripped mediaId from real dingtalk-channel-sdk gets '@' prefix restored
    mock_sdk_channel.oapi.upload_media = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "mediaId": "lALPM1y8RZw9SEkICA",
            "downloadUrl": "https://down.dingtalk.com/media/lALPM1y8RZw9SEkICA",
        }
    )
    await bot.send_message(
        chat_id="cid_test_media",
        file_paths=str(sample_files["png"]),
    )
    assert mock_sdk_channel.sent_images[-1][1] == "@lALPM1y8RZw9SEkICA"

    # Restore mock upload_media and send PDF file
    from .conftest import MockDingTalkOApi

    mock_sdk_channel.oapi = MockDingTalkOApi()
    await bot.send_message(
        chat_id="cid_test_media",
        file_paths=str(sample_files["pdf"]),
    )
    assert len(mock_sdk_channel.oapi.uploads) == 1
    assert mock_sdk_channel.oapi.uploads[0][0] == "file"


async def test_dingtalk_channel_close_releases_resources(dingtalk_env: None) -> None:
    """Verify DingTalkBotChannel close() closes SDK client and frees session manager."""
    cls = _get_dingtalk_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockDingTalkChannel()
    mock_session_mgr = MockAgentSessionManager()

    bot = cls(config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr)
    await bot.close()

    assert mock_sdk_channel.is_closed is True
    assert mock_session_mgr.close_all.called
