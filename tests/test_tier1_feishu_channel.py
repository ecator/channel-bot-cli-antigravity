"""Tier 1: Feature Coverage - FeishuBotChannel adapter mock flow & lifecycle."""

from pathlib import Path
from unittest.mock import AsyncMock

from channel_bot_cli_antigravity.config import Config

from .conftest import (
    MockAgent,
    MockAgentSessionManager,
    MockFeishuChannel,
    MockFeishuInboundMessage,
)

try:
    from channel_bot_cli_antigravity.channels.feishu import FeishuBotChannel
except ImportError:
    try:
        from channel_bot_cli_antigravity.channel import FeishuBotChannel
    except ImportError:
        FeishuBotChannel = None  # type: ignore[assignment,misc]


def _get_feishu_channel_cls() -> type:
    assert FeishuBotChannel is not None, (
        "FeishuBotChannel must be implemented in src/channel_bot_cli_antigravity/channels/feishu.py"
    )
    return FeishuBotChannel


def test_feishu_channel_initialization(feishu_env: None) -> None:
    """Verify FeishuBotChannel initialization and channel_name attribute."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    bot = cls(config=cfg, channel=mock_sdk_channel)
    assert getattr(bot, "channel_name", "feishu") == "feishu"
    assert bot.channel is mock_sdk_channel


async def test_feishu_channel_drops_self_echo(feishu_env: None) -> None:
    """Verify FeishuBotChannel ignores messages when sender_is_bot is True."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_session_mgr = MockAgentSessionManager()

    bot = cls(config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr)

    msg = MockFeishuInboundMessage(
        msg_id="om_echo_1",
        chat_id="oc_test",
        sender_is_bot=True,
        content_text="Echo message",
    )
    await bot.on_message(msg)

    # Must not invoke Agent, must not send any reply, must not add reaction
    assert len(mock_session_mgr.agent.chat_history) == 0
    assert len(mock_sdk_channel.sent_messages) == 0
    assert len(mock_sdk_channel.added_reactions) == 0


async def test_feishu_channel_respects_filter_chat_id(feishu_env: None) -> None:
    """Verify FeishuBotChannel filters out messages not matching filter_chat_id."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_session_mgr = MockAgentSessionManager()

    bot = cls(
        config=cfg,
        filter_chat_id="oc_target_only",
        channel=mock_sdk_channel,
        session_manager=mock_session_mgr,
    )

    msg_ignored = MockFeishuInboundMessage(
        chat_id="oc_other_chat", content_text="Hello"
    )
    await bot.on_message(msg_ignored)

    assert len(mock_session_mgr.agent.chat_history) == 0
    assert len(mock_sdk_channel.sent_messages) == 0


async def test_feishu_channel_streaming_flow(feishu_env: None) -> None:
    """Verify FeishuBotChannel streaming typewriter flow with typing reaction."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_agent = MockAgent(response_chunks=["Card", "Kit", " Stream"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = cls(config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr)

    msg = MockFeishuInboundMessage(
        msg_id="om_stream_test",
        chat_id="oc_stream_chat",
        content_text="Write a poem",
    )
    await bot.on_message(msg)

    # Reaction added and then removed
    assert len(mock_sdk_channel.added_reactions) == 1
    assert len(mock_sdk_channel.removed_reactions) == 1
    assert mock_sdk_channel.removed_reactions[0][0] == "om_stream_test"

    # Stream called with markdown producer
    assert len(mock_sdk_channel.streams) == 1
    assert mock_sdk_channel.streams[0][0] == "oc_stream_chat"


async def test_feishu_channel_streaming_fallback_to_markdown(feishu_env: None) -> None:
    """Verify FeishuBotChannel falls back to standard markdown message if CardKit stream fails."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    # Force stream() to raise permission error (cardkit:card:write missing)
    mock_sdk_channel.stream = AsyncMock(
        side_effect=PermissionError("Missing cardkit:card:write")
    )

    mock_agent = MockAgent(response_chunks=["Fallback", " Markdown", " Content"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)

    bot = cls(config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr)

    msg = MockFeishuInboundMessage(
        msg_id="om_fallback_test",
        chat_id="oc_fallback_chat",
        content_text="Hello",
    )
    await bot.on_message(msg)

    # Should fall back to sending markdown message
    assert len(mock_sdk_channel.sent_messages) >= 1
    target_chat, content = mock_sdk_channel.sent_messages[0]
    assert target_chat == "oc_fallback_chat"
    assert "Fallback Markdown Content" in (
        content.get("markdown") or content.get("text", "")
    )


async def test_feishu_channel_send_message_image_and_caption(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify FeishuBotChannel send_message merges single image with message into caption."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    bot = cls(config=cfg, channel=mock_sdk_channel)
    await bot.send_message(
        chat_id="oc_dest_1",
        message="Look at this picture",
        file_paths=str(sample_files["png"]),
    )

    assert len(mock_sdk_channel.sent_messages) == 1
    _, content = mock_sdk_channel.sent_messages[0]
    assert "image" in content
    assert content.get("caption") == "Look at this picture"


async def test_feishu_channel_send_message_multiple_files(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify FeishuBotChannel send_message sends multiple files individually."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()

    bot = cls(config=cfg, channel=mock_sdk_channel)
    await bot.send_message(
        chat_id="oc_dest_2",
        message="Multiple files attached",
        file_paths=[str(sample_files["png"]), str(sample_files["pdf"])],
    )

    # 1 image, 1 file, 1 markdown text
    assert len(mock_sdk_channel.sent_messages) == 3
    assert "image" in mock_sdk_channel.sent_messages[0][1]
    assert "file" in mock_sdk_channel.sent_messages[1][1]
    assert "markdown" in mock_sdk_channel.sent_messages[2][1]


async def test_feishu_channel_close_releases_resources(feishu_env: None) -> None:
    """Verify FeishuBotChannel close() stops SDK connection and frees sessions."""
    cls = _get_feishu_channel_cls()
    cfg = Config.from_env()
    mock_sdk_channel = MockFeishuChannel()
    mock_session_mgr = MockAgentSessionManager()

    bot = cls(config=cfg, channel=mock_sdk_channel, session_manager=mock_session_mgr)
    await bot.close()

    assert mock_sdk_channel.is_stopped is True
    assert mock_session_mgr.close_all.called
