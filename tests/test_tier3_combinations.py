"""Tier 3: Cross-Feature Combinations (dual-channel listen --channel all, send with multiple files and markdown, credential fallback precedence)."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from channel_bot_cli_antigravity.agent import AgentSessionManager
from channel_bot_cli_antigravity.cli import create_parser, resolve_send_message
from channel_bot_cli_antigravity.config import Config

from .conftest import (
    MockDingTalkChannel,
    MockFeishuChannel,
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
# 1. Dual-Channel Listen (--channel all) (>=5 tests)
# ---------------------------------------------------------------------------


async def test_dual_channel_listen_both_channels_started(
    dual_channel_env: None,
) -> None:
    """Verify --channel all creates and runs both Feishu and DingTalk adapters concurrently."""
    if FeishuBotChannel is None or DingTalkBotChannel is None:
        pytest.fail("FeishuBotChannel or DingTalkBotChannel not implemented")

    cfg = Config.from_env()
    mock_fs_sdk = MockFeishuChannel()
    mock_dd_sdk = MockDingTalkChannel()

    fs_bot = FeishuBotChannel(config=cfg, channel=mock_fs_sdk)
    dd_bot = DingTalkBotChannel(config=cfg, channel=mock_dd_sdk)

    # Simulate running start_listening concurrently
    async def _run_dual() -> None:
        await asyncio.gather(
            fs_bot.start_listening(),
            dd_bot.start_listening(),
        )

    # Start and cancel task to verify both started
    task = asyncio.create_task(_run_dual())
    await asyncio.sleep(0.01)

    assert mock_fs_sdk.is_connected or len(mock_fs_sdk.handlers) > 0
    assert mock_dd_sdk.is_started or len(mock_dd_sdk.message_handlers) > 0

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.done()


def test_dual_channel_listen_shares_single_session_manager(
    dual_channel_env: None,
) -> None:
    """Verify both channel adapters share the exact same AgentSessionManager on --channel all."""
    if FeishuBotChannel is None or DingTalkBotChannel is None:
        pytest.fail("FeishuBotChannel or DingTalkBotChannel not implemented")

    cfg = Config.from_env()
    shared_session_manager = AgentSessionManager()

    fs_bot = FeishuBotChannel(config=cfg, session_manager=shared_session_manager)
    dd_bot = DingTalkBotChannel(config=cfg, session_manager=shared_session_manager)

    assert fs_bot.session_manager is dd_bot.session_manager
    assert fs_bot.session_manager is shared_session_manager


async def test_dual_channel_listen_graceful_shutdown_on_cancel(
    dual_channel_env: None,
) -> None:
    """Verify cancellation cleanly calls close() and frees sessions on both channels."""
    if FeishuBotChannel is None or DingTalkBotChannel is None:
        pytest.fail("FeishuBotChannel or DingTalkBotChannel not implemented")

    cfg = Config.from_env()
    mock_fs_sdk = MockFeishuChannel()
    mock_dd_sdk = MockDingTalkChannel()
    shared_session_manager = AgentSessionManager()
    shared_session_manager.close_all = AsyncMock()

    fs_bot = FeishuBotChannel(
        config=cfg, channel=mock_fs_sdk, session_manager=shared_session_manager
    )
    dd_bot = DingTalkBotChannel(
        config=cfg, channel=mock_dd_sdk, session_manager=shared_session_manager
    )

    await fs_bot.close()
    await dd_bot.close()

    assert mock_fs_sdk.is_stopped is True
    assert mock_dd_sdk.is_closed is True
    assert shared_session_manager.close_all.called


def test_dual_channel_listen_aborts_if_feishu_creds_missing(dingtalk_env: None) -> None:
    """Verify validate_channel('all') aborts when only DingTalk creds exist."""
    cfg = Config.from_env()
    assert hasattr(cfg, "validate_channel"), "Config must have validate_channel"
    with pytest.raises(ValueError, match="FEISHU_APP_ID|LARK_APP_ID|飞书"):
        cfg.validate_channel("all")


def test_dual_channel_listen_aborts_if_dingtalk_creds_missing(feishu_env: None) -> None:
    """Verify validate_channel('all') aborts when only Feishu creds exist."""
    cfg = Config.from_env()
    assert hasattr(cfg, "validate_channel"), "Config must have validate_channel"
    with pytest.raises(ValueError, match="DD_CLIENT_ID|钉钉"):
        cfg.validate_channel("all")


# ---------------------------------------------------------------------------
# 2. Send with Multiple Files and Markdown (>=5 tests)
# ---------------------------------------------------------------------------


async def test_cli_send_multiple_images_and_markdown(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify sending multiple images plus markdown sends each image and markdown message."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    bot = FeishuBotChannel(config=Config.from_env(), channel=mock_sdk)

    # 2 images + 1 message
    await bot.send_message(
        chat_id="oc_multi_img",
        message="Dual photo album",
        file_paths=[str(sample_files["png"]), str(sample_files["png"])],
        message_type="markdown",
    )

    # Should send image 1, image 2, then markdown text
    assert len(mock_sdk.sent_messages) == 3
    assert "image" in mock_sdk.sent_messages[0][1]
    assert "image" in mock_sdk.sent_messages[1][1]
    assert "markdown" in mock_sdk.sent_messages[2][1]
    assert mock_sdk.sent_messages[2][1]["markdown"] == "Dual photo album"


async def test_cli_send_image_and_pdf_and_markdown(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify sending mixed image, PDF document, and markdown text."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    bot = FeishuBotChannel(config=Config.from_env(), channel=mock_sdk)

    await bot.send_message(
        chat_id="oc_mixed",
        message="Here is your monthly invoice report",
        file_paths=[str(sample_files["png"]), str(sample_files["pdf"])],
        message_type="markdown",
    )

    assert len(mock_sdk.sent_messages) == 3
    assert "image" in mock_sdk.sent_messages[0][1]
    assert "file" in mock_sdk.sent_messages[1][1]
    assert "markdown" in mock_sdk.sent_messages[2][1]


async def test_cli_send_single_image_with_markdown_caption(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify single image with message merges into captioned image message in Feishu."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    bot = FeishuBotChannel(config=Config.from_env(), channel=mock_sdk)

    await bot.send_message(
        chat_id="oc_caption",
        message="Diagram caption",
        file_paths=str(sample_files["png"]),
    )

    assert len(mock_sdk.sent_messages) == 1
    content = mock_sdk.sent_messages[0][1]
    assert "image" in content
    assert content.get("caption") == "Diagram caption"


async def test_cli_send_single_non_image_file_with_markdown(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify single PDF file with message sends file first, then markdown message."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")

    mock_sdk = MockFeishuChannel()
    bot = FeishuBotChannel(config=Config.from_env(), channel=mock_sdk)

    await bot.send_message(
        chat_id="oc_pdf_only",
        message="Please sign attached document",
        file_paths=str(sample_files["pdf"]),
        message_type="markdown",
    )

    assert len(mock_sdk.sent_messages) == 2
    assert "file" in mock_sdk.sent_messages[0][1]
    assert "markdown" in mock_sdk.sent_messages[1][1]


def test_cli_send_stdin_pipe_with_file_attachment() -> None:
    """Verify resolve_send_message reads stdin text when combined with --file."""
    args = create_parser().parse_args(
        ["send", "-c", "oc_1", "-f", "doc.pdf", "--message", "-"]
    )
    with patch(
        "channel_bot_cli_antigravity.cli.read_stdin_content",
        return_value="Content piped through stdin",
    ):
        msg = resolve_send_message(args)
        assert msg == "Content piped through stdin"


# ---------------------------------------------------------------------------
# 3. Credential Fallback Precedence (>=5 tests)
# ---------------------------------------------------------------------------


def test_precedence_feishu_app_id_over_lark_app_id(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Verify FEISHU_APP_ID takes precedence over legacy LARK_APP_ID."""
    clean_env.setenv("FEISHU_APP_ID", "feishu_primary_id")
    clean_env.setenv("LARK_APP_ID", "lark_secondary_id")
    cfg = Config.from_env()

    actual_id = getattr(cfg, "feishu_app_id", None) or getattr(cfg, "lark_app_id", None)
    assert actual_id == "feishu_primary_id"


def test_precedence_feishu_app_secret_over_lark_app_secret(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Verify FEISHU_APP_SECRET takes precedence over legacy LARK_APP_SECRET."""
    clean_env.setenv("FEISHU_APP_SECRET", "feishu_primary_sec")
    clean_env.setenv("LARK_APP_SECRET", "lark_secondary_sec")
    cfg = Config.from_env()

    actual_sec = getattr(cfg, "feishu_app_secret", None) or getattr(
        cfg, "lark_app_secret", None
    )
    assert actual_sec == "feishu_primary_sec"


def test_precedence_feishu_domain_over_lark_domain(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Verify FEISHU_DOMAIN takes precedence over legacy LARK_DOMAIN."""
    clean_env.setenv("FEISHU_DOMAIN", "https://open.feishu.cn")
    clean_env.setenv("LARK_DOMAIN", "https://open.larksuite.com")
    cfg = Config.from_env()

    actual_dom = getattr(cfg, "feishu_domain", None) or getattr(
        cfg, "lark_domain", None
    )
    assert actual_dom == "https://open.feishu.cn"


def test_precedence_explicit_cli_channel_over_inferred(dual_channel_env: None) -> None:
    """Verify explicit CLI --channel feishu overrides default DingTalk inference."""
    parser = create_parser()
    args = parser.parse_args(
        ["send", "-c", "oc_test", "--channel", "feishu", "-m", "hi"]
    )
    assert getattr(args, "channel", None) == "feishu"


def test_precedence_dingtalk_priority_when_no_cli_flag(dual_channel_env: None) -> None:
    """Verify when --channel is omitted and both credentials exist, DingTalk is prioritized."""
    cfg = Config.from_env()
    assert hasattr(cfg, "infer_default_channel"), (
        "Config must implement infer_default_channel"
    )
    assert cfg.infer_default_channel() == "dingtalk"
