"""Tier 2: Boundary & Corner Cases (empty messages, missing credentials, invalid channels, corrupt stdin, missing attachments, duplicate session keys)."""

import argparse
import asyncio
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.antigravity import types

from channel_bot_cli_antigravity.agent import AgentSessionManager
from channel_bot_cli_antigravity.cli import (
    create_parser,
    read_stdin_content,
    resolve_send_message,
)
from channel_bot_cli_antigravity.config import Config

from .conftest import (
    MockAgent,
    MockAgentSessionManager,
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
# 1. Empty Messages (>=5 tests)
# ---------------------------------------------------------------------------


async def test_empty_inbound_message_feishu_skipped(feishu_env: None) -> None:
    """Verify FeishuBotChannel skips inbound message when text is empty and no attachments."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    mock_sdk = MockFeishuChannel()
    mock_session_mgr = MockAgentSessionManager()
    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(content_text="", resources=[])
    await bot.on_message(msg)

    assert len(mock_session_mgr.agent.chat_history) == 0
    assert len(mock_sdk.sent_messages) == 0


async def test_whitespace_inbound_message_dingtalk_skipped(dingtalk_env: None) -> None:
    """Verify DingTalkBotChannel skips inbound message with only whitespace and no resources."""
    if DingTalkBotChannel is None:
        pytest.fail("DingTalkBotChannel not implemented")
    mock_sdk = MockDingTalkChannel()
    mock_session_mgr = MockAgentSessionManager()
    bot = DingTalkBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockDingTalkIncomingMessage(text="   \n\t  \r\n", resources=[])
    reply = MockDingTalkReply()
    await bot.on_message(msg, reply)

    assert len(mock_session_mgr.agent.chat_history) == 0
    assert len(reply.text_replies) == 0


async def test_none_text_with_no_attachments_skipped(feishu_env: None) -> None:
    """Verify inbound message with None text and empty resources is skipped."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    mock_sdk = MockFeishuChannel()
    mock_session_mgr = MockAgentSessionManager()
    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    msg = MockFeishuInboundMessage(content_text=None, resources=[])
    await bot.on_message(msg)

    assert len(mock_session_mgr.agent.chat_history) == 0


def test_empty_stdin_in_cli_raises_value_error() -> None:
    """Verify resolve_send_message raises ValueError when stdin produces only whitespace."""
    args = argparse.Namespace(message=None, read_stdin=True, file_paths=None)
    with (
        patch(
            "channel_bot_cli_antigravity.cli.read_stdin_content", return_value="   \n  "
        ),
        pytest.raises(ValueError, match="为空"),
    ):
        resolve_send_message(args)


async def test_empty_message_with_valid_image_attachment_processed(
    feishu_env: None,
) -> None:
    """Verify empty text message WITH an image attachment is processed normally by Agent."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    mock_sdk = MockFeishuChannel()
    mock_sdk.downloaded_resources["res_key_img"] = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    )

    mock_agent = MockAgent(response_chunks=["I", " see", " an", " image"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    # Empty text, but has image resource
    res_obj = argparse.Namespace(
        file_key="res_key_img", type="image", file_name="sample.png"
    )
    msg = MockFeishuInboundMessage(content_text="", resources=[res_obj])

    await bot.on_message(msg)
    assert len(mock_session_mgr.agent.chat_history) == 1
    # Check that image object was included in prompt items
    input_items = mock_session_mgr.agent.chat_history[0]
    has_image = any(isinstance(item, types.Image) for item in input_items)
    assert has_image is True


# ---------------------------------------------------------------------------
# 2. Missing Credentials (>=5 tests)
# ---------------------------------------------------------------------------


def test_missing_dingtalk_client_id_raises(clean_env: pytest.MonkeyPatch) -> None:
    """Verify validate_channel('dingtalk') fails when DD_CLIENT_ID is empty."""
    clean_env.setenv("DD_CLIENT_SECRET", "only_secret")
    cfg = Config.from_env()
    assert hasattr(cfg, "validate_channel"), "Config must have validate_channel"
    with pytest.raises(ValueError, match="DD_CLIENT_ID|钉钉"):
        cfg.validate_channel("dingtalk")


def test_missing_dingtalk_client_secret_raises(clean_env: pytest.MonkeyPatch) -> None:
    """Verify validate_channel('dingtalk') fails when DD_CLIENT_SECRET is empty."""
    clean_env.setenv("DD_CLIENT_ID", "only_id")
    cfg = Config.from_env()
    with pytest.raises(ValueError, match="DD_CLIENT_SECRET|钉钉"):
        cfg.validate_channel("dingtalk")


def test_missing_feishu_app_id_raises(clean_env: pytest.MonkeyPatch) -> None:
    """Verify validate_channel('feishu') fails when FEISHU_APP_ID is empty."""
    clean_env.setenv("FEISHU_APP_SECRET", "only_secret")
    cfg = Config.from_env()
    with pytest.raises(ValueError, match="FEISHU_APP_ID|LARK_APP_ID|飞书"):
        cfg.validate_channel("feishu")


def test_missing_feishu_app_secret_raises(clean_env: pytest.MonkeyPatch) -> None:
    """Verify validate_channel('feishu') fails when FEISHU_APP_SECRET is empty."""
    clean_env.setenv("FEISHU_APP_ID", "only_id")
    cfg = Config.from_env()
    with pytest.raises(ValueError, match="FEISHU_APP_SECRET|LARK_APP_SECRET|飞书"):
        cfg.validate_channel("feishu")


def test_missing_credentials_on_all_channel_raises(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Verify validate_channel('all') raises if either channel credentials are missing."""
    # Only DD present, Feishu missing
    clean_env.setenv("DD_CLIENT_ID", "dd_id")
    clean_env.setenv("DD_CLIENT_SECRET", "dd_sec")
    cfg = Config.from_env()
    with pytest.raises(ValueError, match="FEISHU_APP_ID|LARK_APP_ID|飞书"):
        cfg.validate_channel("all")


# ---------------------------------------------------------------------------
# 3. Invalid Channels (>=5 tests)
# ---------------------------------------------------------------------------


def test_cli_rejects_unsupported_send_channel() -> None:
    """Verify CLI parser rejects unsupported channel values on send."""
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            ["send", "-c", "chat1", "--channel", "telegram", "-m", "hello"]
        )


def test_cli_rejects_unsupported_listen_channel() -> None:
    """Verify CLI parser rejects unsupported channel values on listen."""
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["listen", "--channel", "slack"])


def test_validate_channel_rejects_unknown_channel() -> None:
    """Verify Config.validate_channel raises ValueError on unsupported channel names."""
    cfg = Config()
    if hasattr(cfg, "validate_channel"):
        with pytest.raises(ValueError):
            cfg.validate_channel("wechat_work")


def test_channel_factory_rejects_unknown_channel() -> None:
    """Verify get_channel factory raises ValueError on unknown channel names."""
    if get_channel is None:
        pytest.fail("get_channel factory not implemented in channels")
    with pytest.raises((ValueError, KeyError)):
        get_channel("unsupported_im", Config())


def test_channel_factory_case_handling() -> None:
    """Verify channel names must match expected identifiers or handle case."""
    if get_channel is None:
        pytest.fail("get_channel factory not implemented in channels")
    # 'unknown' must fail
    with pytest.raises((ValueError, KeyError)):
        get_channel("  ", Config())


# ---------------------------------------------------------------------------
# 4. Corrupt UTF-8 Stdin (>=5 tests)
# ---------------------------------------------------------------------------


def test_stdin_strips_utf8_bom() -> None:
    """Verify read_stdin_content strips UTF-8 BOM cleanly."""
    bom_payload = b"\xef\xbb\xbfHello Antigravity Bot"
    mock_stdin = MagicMock()
    mock_stdin.buffer = BytesIO(bom_payload)
    mock_stdin.isatty.return_value = False

    with patch.object(sys, "stdin", mock_stdin):
        res = read_stdin_content()
        assert res == "Hello Antigravity Bot"
        assert not res.startswith("\ufeff")


def test_stdin_handles_corrupt_bytes_gracefully() -> None:
    """Verify read_stdin_content replaces corrupt byte sequences without crashing."""
    corrupt_bytes = b"Valid header \xff\xfe\x80\x81 valid footer"
    mock_stdin = MagicMock()
    mock_stdin.buffer = BytesIO(corrupt_bytes)
    mock_stdin.isatty.return_value = False

    with patch.object(sys, "stdin", mock_stdin):
        res = read_stdin_content()
        assert "Valid header" in res
        assert "valid footer" in res


def test_stdin_multiline_crlf_and_lf() -> None:
    """Verify read_stdin_content preserves CRLF and LF across lines."""
    multiline_bytes = b"Line 1\r\nLine 2\nLine 3\r\n"
    mock_stdin = MagicMock()
    mock_stdin.buffer = BytesIO(multiline_bytes)
    mock_stdin.isatty.return_value = False

    with patch.object(sys, "stdin", mock_stdin):
        res = read_stdin_content()
        assert "Line 1" in res
        assert "Line 2" in res
        assert "Line 3" in res


def test_stdin_chinese_and_emojis() -> None:
    """Verify read_stdin_content preserves UTF-8 Chinese characters and emojis."""
    utf8_content = "你好，世界！这是一条测试消息 🚀 🤖"
    mock_stdin = MagicMock()
    mock_stdin.buffer = BytesIO(utf8_content.encode("utf-8"))
    mock_stdin.isatty.return_value = False

    with patch.object(sys, "stdin", mock_stdin):
        res = read_stdin_content()
        assert res == utf8_content


def test_stdin_empty_stream() -> None:
    """Verify read_stdin_content handles empty input stream safely."""
    mock_stdin = MagicMock()
    mock_stdin.buffer = BytesIO(b"")
    mock_stdin.isatty.return_value = False

    with patch.object(sys, "stdin", mock_stdin):
        res = read_stdin_content()
        assert res == ""


# ---------------------------------------------------------------------------
# 5. Missing Attachments (>=5 tests)
# ---------------------------------------------------------------------------


async def test_send_message_missing_file_raises_filenotfound(feishu_env: None) -> None:
    """Verify send_message raises FileNotFoundError when target file is missing."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    bot = FeishuBotChannel(config=Config.from_env(), channel=MockFeishuChannel())
    with pytest.raises(FileNotFoundError, match="nonexistent_file_xyz123.txt"):
        await bot.send_message(
            chat_id="oc_1",
            file_paths="nonexistent_file_xyz123.txt",
        )


async def test_send_message_partial_missing_files_aborts_early(
    feishu_env: None, sample_files: dict[str, Path]
) -> None:
    """Verify send_message does not send valid files if one of the files is missing."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    mock_sdk = MockFeishuChannel()
    bot = FeishuBotChannel(config=Config.from_env(), channel=mock_sdk)

    with pytest.raises(FileNotFoundError):
        await bot.send_message(
            chat_id="oc_1",
            file_paths=[str(sample_files["png"]), "nonexistent_second_file.pdf"],
        )

    # Nothing should have been sent over the wire
    assert len(mock_sdk.sent_messages) == 0


async def test_inbound_missing_download_resource_logs_and_continues(
    feishu_env: None,
) -> None:
    """Verify inbound resource returning None does not crash message turn."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    mock_sdk = MockFeishuChannel()
    # Resource download returns None (file deleted or expired)
    mock_sdk.download_resource = AsyncMock(return_value=None)

    mock_agent = MockAgent(response_chunks=["Processed text"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    res_obj = argparse.Namespace(
        file_key="expired_key", type="file", file_name="test.txt"
    )
    msg = MockFeishuInboundMessage(content_text="Please summarize", resources=[res_obj])

    await bot.on_message(msg)
    # Turn succeeds with text prompt
    assert len(mock_session_mgr.agent.chat_history) == 1


async def test_inbound_download_exception_caught_and_continues(
    feishu_env: None,
) -> None:
    """Verify network exception during resource download is caught and logged."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    mock_sdk = MockFeishuChannel()
    mock_sdk.download_resource = AsyncMock(
        side_effect=ConnectionResetError("Socket reset")
    )

    mock_agent = MockAgent(response_chunks=["Handled"])
    mock_session_mgr = MockAgentSessionManager(agent=mock_agent)
    bot = FeishuBotChannel(
        config=Config.from_env(), channel=mock_sdk, session_manager=mock_session_mgr
    )

    res_obj = argparse.Namespace(file_key="err_key", type="image", file_name="test.png")
    msg = MockFeishuInboundMessage(content_text="Question", resources=[res_obj])

    await bot.on_message(msg)
    assert len(mock_session_mgr.agent.chat_history) == 1


async def test_send_message_directory_path_raises_error(
    feishu_env: None, tmp_path: Path
) -> None:
    """Verify providing directory path instead of a file raises an error."""
    if FeishuBotChannel is None:
        pytest.fail("FeishuBotChannel not implemented")
    bot = FeishuBotChannel(config=Config.from_env(), channel=MockFeishuChannel())
    sub_dir = tmp_path / "a_directory"
    sub_dir.mkdir()

    with pytest.raises(
        (IsADirectoryError, PermissionError, ValueError, FileNotFoundError)
    ):
        await bot.send_message(chat_id="oc_1", file_paths=str(sub_dir))


# ---------------------------------------------------------------------------
# 6. Duplicate Session Keys & Concurrency (>=5 tests)
# ---------------------------------------------------------------------------


def test_different_channels_same_chat_id_isolated_locks() -> None:
    """Verify feishu:chat1 and dingtalk:chat1 receive distinct asyncio.Lock instances."""
    mgr = AgentSessionManager()
    lock_fs = mgr.get_lock("feishu:common_chat_id_100")
    lock_dd = mgr.get_lock("dingtalk:common_chat_id_100")

    assert lock_fs is not lock_dd, (
        "Locks for different channels must be strictly isolated to avoid cross-channel deadlock"
    )


def test_same_channel_same_chat_id_shares_lock() -> None:
    """Verify same channel and chat_id share the exact same lock."""
    mgr = AgentSessionManager()
    lock1 = mgr.get_lock("dingtalk:cid_room_200")
    lock2 = mgr.get_lock("dingtalk:cid_room_200")

    assert lock1 is lock2


async def test_concurrent_messages_same_session_serialized() -> None:
    """Verify concurrent messages on the same session execute sequentially."""
    mgr = AgentSessionManager()
    session_key = "feishu:oc_seq_test"
    execution_order = []

    async def task(task_id: int, delay: float) -> None:
        lock = mgr.get_lock(session_key)
        async with lock:
            execution_order.append(f"start_{task_id}")
            await asyncio.sleep(delay)
            execution_order.append(f"end_{task_id}")

    # Launch two tasks concurrently on the same session
    await asyncio.gather(task(1, 0.02), task(2, 0.01))

    # Must be sequential: start_1 -> end_1 -> start_2 -> end_2
    assert execution_order == ["start_1", "end_1", "start_2", "end_2"]


async def test_concurrent_messages_different_sessions_parallel() -> None:
    """Verify messages on different sessions execute concurrently in parallel."""
    mgr = AgentSessionManager()
    execution_order = []

    async def task(session_id: str, delay: float) -> None:
        lock = mgr.get_lock(session_id)
        async with lock:
            execution_order.append(f"start_{session_id}")
            await asyncio.sleep(delay)
            execution_order.append(f"end_{session_id}")

    # Launch on different sessions: session 1 takes 0.04s, session 2 takes 0.01s
    await asyncio.gather(
        task("feishu:session_1", 0.04), task("dingtalk:session_2", 0.01)
    )

    # Session 2 should finish before session 1 finishes because they are parallel
    assert execution_order[0] == "start_feishu:session_1"
    assert execution_order[1] == "start_dingtalk:session_2"
    assert execution_order[2] == "end_dingtalk:session_2"
    assert execution_order[3] == "end_feishu:session_1"


async def test_session_lock_released_on_agent_exception() -> None:
    """Verify session lock is released even if an unhandled exception occurs."""
    mgr = AgentSessionManager()
    session_key = "feishu:oc_err_lock"
    lock = mgr.get_lock(session_key)

    with pytest.raises(RuntimeError):
        async with lock:
            raise RuntimeError("Simulation of agent inference failure")

    # Lock must be unlocked
    assert not lock.locked()

    # Next message can acquire lock immediately
    acquired = False
    async with lock:
        acquired = True
    assert acquired is True
