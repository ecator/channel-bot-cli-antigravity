"""Empirical verification and adversarial challenge test suite by challenger_m2_2.

Adversarially probes and stress-tests:
1. CLI send with explicit --channel vs inferred channel:
   - Explicit dingtalk (with DD creds vs missing DD creds).
   - Explicit feishu (with Feishu creds vs missing Feishu creds).
   - Inferred channel with dual creds (DingTalk priority rule).
   - Inferred channel with Feishu only.
   - Inferred channel with neither (fallback to DingTalk then error).
   - Multiple files and message types.
   - Empty message validation.

2. CLI listen with --channel all mock lifecycle:
   - Concurrent lifecycle of both FeishuBotChannel and DingTalkBotChannel.
   - Shared AgentSessionManager identity across channels.
   - Clean teardown (both close() called even if one fails or cancels).
   - Credential validation for 'all' (requires both DingTalk and Feishu).
   - Channel inference on listen.
   - 'serve' alias behavior.
   - Invalid work directory rejection.

3. Stdin pipeline with UTF-8 BOM, emojis, and CRLF:
   - UTF-8 BOM stripping.
   - 4-byte emojis and multi-byte Chinese character preservation.
   - CRLF and multiline structure preservation.
   - Corrupted byte sequences graceful replacement without crash.
   - Fallback when sys.stdin has no buffer (text mode BOM stripping).
   - CLI send with --stdin flag and with '-m -'.
   - Empty stdin with and without files.

4. CLI help menus and error exits on invalid arguments:
   - SystemExit code 2 on missing required args, mutually exclusive flags, invalid choices.
   - Code 1 on configuration and runtime errors.
   - Version subcommand outputs.
"""

from __future__ import annotations

from collections.abc import Generator
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from channel_bot_cli_antigravity import __version__
from channel_bot_cli_antigravity.agent import AgentSessionManager
from channel_bot_cli_antigravity.cli import (
    create_parser,
    main,
    read_stdin_content,
    run_listen,
)
from channel_bot_cli_antigravity.config import Config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_dd_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Configures only DingTalk credentials and disables .env file loading."""
    monkeypatch.setenv("DD_CLIENT_ID", "mock_dd_client_id_123")
    monkeypatch.setenv("DD_CLIENT_SECRET", "mock_dd_client_secret_456")
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("LARK_APP_ID", raising=False)
    monkeypatch.delenv("LARK_APP_SECRET", raising=False)
    with patch("channel_bot_cli_antigravity.cli.load_env_file", return_value=False):
        yield


@pytest.fixture
def mock_feishu_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Configures only Feishu credentials and disables .env file loading."""
    monkeypatch.delenv("DD_CLIENT_ID", raising=False)
    monkeypatch.delenv("DD_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("FEISHU_APP_ID", "mock_feishu_app_id_789")
    monkeypatch.setenv("FEISHU_APP_SECRET", "mock_feishu_app_secret_012")
    with patch("channel_bot_cli_antigravity.cli.load_env_file", return_value=False):
        yield


@pytest.fixture
def mock_dual_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Configures both DingTalk and Feishu credentials and disables .env file loading."""
    monkeypatch.setenv("DD_CLIENT_ID", "mock_dd_client_id_123")
    monkeypatch.setenv("DD_CLIENT_SECRET", "mock_dd_client_secret_456")
    monkeypatch.setenv("FEISHU_APP_ID", "mock_feishu_app_id_789")
    monkeypatch.setenv("FEISHU_APP_SECRET", "mock_feishu_app_secret_012")
    with patch("channel_bot_cli_antigravity.cli.load_env_file", return_value=False):
        yield


@pytest.fixture
def mock_empty_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Clears all channel credentials and disables .env file loading."""
    monkeypatch.delenv("DD_CLIENT_ID", raising=False)
    monkeypatch.delenv("DD_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("LARK_APP_ID", raising=False)
    monkeypatch.delenv("LARK_APP_SECRET", raising=False)
    with patch("channel_bot_cli_antigravity.cli.load_env_file", return_value=False):
        yield


# ===========================================================================
# 1. CLI send: Explicit --channel vs Inferred Channel
# ===========================================================================
def test_cli_send_explicit_dingtalk_with_valid_creds(mock_dd_env: None) -> None:
    """Explicit --channel dingtalk invokes DingTalkBotChannel with exact parameters."""
    with patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt:
        instance = mock_dt.return_value
        instance.send_message = AsyncMock(return_value={"result": "ok"})
        instance.close = AsyncMock()

        ret = main(
            [
                "send",
                "--channel",
                "dingtalk",
                "-c",
                "cid_dt_target",
                "-m",
                "hello dingtalk",
            ]
        )
        assert ret == 0
        instance.send_message.assert_awaited_once_with(
            chat_id="cid_dt_target",
            message="hello dingtalk",
            file_paths=None,
            message_type="markdown",
        )
        instance.close.assert_awaited_once()


def test_cli_send_explicit_dingtalk_missing_creds(mock_feishu_env: None) -> None:
    """Explicit --channel dingtalk fails when DingTalk creds are missing (even if Feishu creds exist)."""
    stderr_buf = StringIO()
    with patch("sys.stderr", stderr_buf):
        ret = main(["send", "--channel", "dingtalk", "-c", "cid_dt", "-m", "hello"])
        assert ret == 1
    err_output = stderr_buf.getvalue()
    assert "配置错误" in err_output
    assert "DD_CLIENT_ID" in err_output


def test_cli_send_explicit_feishu_with_valid_creds(mock_feishu_env: None) -> None:
    """Explicit --channel feishu invokes FeishuBotChannel with exact parameters."""
    with patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs:
        instance = mock_fs.return_value
        instance.send_message = AsyncMock(return_value={"result": "ok"})
        instance.close = AsyncMock()

        ret = main(
            ["send", "--channel", "feishu", "-c", "oc_fs_target", "-m", "hello feishu"]
        )
        assert ret == 0
        instance.send_message.assert_awaited_once_with(
            chat_id="oc_fs_target",
            message="hello feishu",
            file_paths=None,
            message_type="markdown",
        )
        instance.close.assert_awaited_once()


def test_cli_send_explicit_feishu_missing_creds(mock_dd_env: None) -> None:
    """Explicit --channel feishu fails when Feishu creds are missing (even if DingTalk creds exist)."""
    stderr_buf = StringIO()
    with patch("sys.stderr", stderr_buf):
        ret = main(["send", "--channel", "feishu", "-c", "oc_fs", "-m", "hello"])
        assert ret == 1
    err_output = stderr_buf.getvalue()
    assert "配置错误" in err_output
    assert "FEISHU_APP_ID" in err_output


def test_cli_send_inferred_channel_dual_configured(mock_dual_env: None) -> None:
    """When both platforms are configured and --channel is omitted, DingTalk is prioritized."""
    with (
        patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt,
        patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs,
    ):
        dt_instance = mock_dt.return_value
        dt_instance.send_message = AsyncMock(return_value={"ok": True})
        dt_instance.close = AsyncMock()

        fs_instance = mock_fs.return_value
        fs_instance.send_message = AsyncMock()
        fs_instance.close = AsyncMock()

        ret = main(["send", "-c", "chat_infer_priority", "-m", "check priority"])
        assert ret == 0
        assert dt_instance.send_message.call_count == 1
        assert fs_instance.send_message.call_count == 0


def test_cli_send_inferred_channel_feishu_only(mock_feishu_env: None) -> None:
    """When only Feishu is configured and --channel is omitted, Feishu is inferred."""
    with (
        patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt,
        patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs,
    ):
        dt_instance = mock_dt.return_value
        dt_instance.send_message = AsyncMock()

        fs_instance = mock_fs.return_value
        fs_instance.send_message = AsyncMock(return_value={"ok": True})
        fs_instance.close = AsyncMock()

        ret = main(["send", "-c", "oc_inferred_fs", "-m", "check feishu infer"])
        assert ret == 0
        assert fs_instance.send_message.call_count == 1
        assert dt_instance.send_message.call_count == 0


def test_cli_send_inferred_channel_neither_configured(mock_empty_env: None) -> None:
    """When neither channel is configured and --channel is omitted, infers dingtalk and reports error."""
    stderr_buf = StringIO()
    with patch("sys.stderr", stderr_buf):
        ret = main(["send", "-c", "chat_no_creds", "-m", "check failure"])
        assert ret == 1
    err_output = stderr_buf.getvalue()
    assert "配置错误" in err_output
    assert "DD_CLIENT_ID" in err_output


def test_cli_send_multiple_files_and_type_text(mock_dd_env: None) -> None:
    """CLI send passes multiple files and custom message type correctly."""
    with patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt:
        instance = mock_dt.return_value
        instance.send_message = AsyncMock(return_value={"sent": True})
        instance.close = AsyncMock()

        ret = main(
            [
                "send",
                "--channel",
                "dingtalk",
                "-c",
                "cid_multi_file",
                "-m",
                "Please review attached items",
                "-f",
                "report.pdf",
                "table.csv",
                "summary.txt",
                "-t",
                "text",
            ]
        )
        assert ret == 0
        instance.send_message.assert_awaited_once_with(
            chat_id="cid_multi_file",
            message="Please review attached items",
            file_paths=["report.pdf", "table.csv", "summary.txt"],
            message_type="text",
        )


def test_cli_send_missing_content_and_files_raises(mock_dd_env: None) -> None:
    """CLI send fails when neither message, stdin, nor file is specified."""
    stderr_buf = StringIO()
    with patch("sys.stderr", stderr_buf):
        # Empty string message and no files
        ret = main(["send", "-c", "cid_empty_msg", "-m", ""])
        assert ret == 1
    assert "主动发送消息必须提供" in stderr_buf.getvalue()


# ===========================================================================
# 2. CLI listen: --channel all Mock Lifecycle & Concurrency
# ===========================================================================
@pytest.mark.asyncio
async def test_run_listen_all_concurrent_lifecycle_and_shared_session_manager(
    mock_dual_env: None,
) -> None:
    """Listen with --channel all starts both channels concurrently sharing one AgentSessionManager."""
    cfg = Config.from_env()

    with (
        patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs_cls,
        patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt_cls,
    ):
        fs_instance = mock_fs_cls.return_value
        fs_instance.start_listening = AsyncMock()
        fs_instance.close = AsyncMock()

        dt_instance = mock_dt_cls.return_value
        dt_instance.start_listening = AsyncMock()
        dt_instance.close = AsyncMock()

        await run_listen(chat_id="filter_chat_1", config=cfg, channel="all")

        # Verify instantiation arguments: both must receive the SAME shared session_manager
        assert mock_fs_cls.call_count == 1
        assert mock_dt_cls.call_count == 1

        fs_kwargs = mock_fs_cls.call_args.kwargs
        dt_kwargs = mock_dt_cls.call_args.kwargs

        assert fs_kwargs["session_manager"] is not None
        assert isinstance(fs_kwargs["session_manager"], AgentSessionManager)
        # Shared session manager identity
        assert fs_kwargs["session_manager"] is dt_kwargs["session_manager"]
        assert fs_kwargs["filter_chat_id"] == "filter_chat_1"
        assert dt_kwargs["filter_chat_id"] == "filter_chat_1"

        # Both channels started listening
        fs_instance.start_listening.assert_awaited_once()
        dt_instance.start_listening.assert_awaited_once()

        # Both channels closed cleanly in finally block
        fs_instance.close.assert_awaited_once()
        dt_instance.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_listen_all_clean_teardown_when_one_channel_raises(
    mock_dual_env: None,
) -> None:
    """When one channel crashes in --channel all, teardown closes BOTH channels without unhandled crash."""
    cfg = Config.from_env()

    with (
        patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs_cls,
        patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt_cls,
    ):
        fs_instance = mock_fs_cls.return_value
        fs_instance.start_listening = AsyncMock(
            side_effect=RuntimeError("Feishu connection lost")
        )
        fs_instance.close = AsyncMock()

        dt_instance = mock_dt_cls.return_value
        dt_instance.start_listening = AsyncMock()
        dt_instance.close = AsyncMock()

        with pytest.raises(RuntimeError, match="Feishu connection lost"):
            await run_listen(chat_id=None, config=cfg, channel="all")

        # Crucial check: DingTalk and Feishu close() MUST BOTH be awaited even after exception
        fs_instance.close.assert_awaited_once()
        dt_instance.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_listen_all_teardown_survives_close_exception(
    mock_dual_env: None,
) -> None:
    """If one channel's close() raises an error during teardown, the other channel is still closed."""
    cfg = Config.from_env()

    with (
        patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs_cls,
        patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt_cls,
    ):
        fs_instance = mock_fs_cls.return_value
        fs_instance.start_listening = AsyncMock()
        # feishu close raises error
        fs_instance.close = AsyncMock(side_effect=Exception("Feishu close failed"))

        dt_instance = mock_dt_cls.return_value
        dt_instance.start_listening = AsyncMock()
        dt_instance.close = AsyncMock()

        # Does not raise because return_exceptions=True is used in teardown gather
        await run_listen(chat_id=None, config=cfg, channel="all")

        fs_instance.close.assert_awaited_once()
        dt_instance.close.assert_awaited_once()


def test_cli_listen_all_missing_credentials(mock_dd_env: None) -> None:
    """CLI listen --channel all fails if either channel's credentials are missing."""
    stderr_buf = StringIO()
    with patch("sys.stderr", stderr_buf):
        ret = main(["listen", "--channel", "all"])
        assert ret == 1
    assert "配置错误" in stderr_buf.getvalue()
    assert "FEISHU_APP_ID" in stderr_buf.getvalue()


def test_cli_listen_inferred_channel(mock_dual_env: None) -> None:
    """CLI listen without --channel infers DingTalk by default when both configured."""
    with (
        patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt,
        patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs,
    ):
        dt_instance = mock_dt.return_value
        dt_instance.start_listening = AsyncMock()
        dt_instance.close = AsyncMock()

        fs_instance = mock_fs.return_value
        fs_instance.start_listening = AsyncMock()

        ret = main(["listen", "-c", "cid_listen_infer"])
        assert ret == 0
        assert dt_instance.start_listening.call_count == 1
        assert fs_instance.start_listening.call_count == 0


def test_cli_listen_serve_alias(mock_feishu_env: None) -> None:
    """The 'serve' subcommand acts as an exact alias for 'listen'."""
    with patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs:
        instance = mock_fs.return_value
        instance.start_listening = AsyncMock()
        instance.close = AsyncMock()

        ret = main(["serve", "--channel", "feishu"])
        assert ret == 0
        assert instance.start_listening.call_count == 1
        assert instance.close.call_count == 1


def test_cli_listen_invalid_work_dir_exits_code_1(mock_dual_env: None) -> None:
    """CLI listen with non-existent work-dir fails with descriptive error."""
    stderr_buf = StringIO()
    with patch("sys.stderr", stderr_buf):
        ret = main(["--work-dir", "non_existent_dir_99999", "listen"])
        assert ret == 1
    assert "指定的工作目录不存在" in stderr_buf.getvalue()


# ===========================================================================
# 3. Stdin Pipeline: UTF-8 BOM, Emojis, and Robust Decoding
# ===========================================================================
def test_stdin_with_utf8_bom_and_chinese() -> None:
    """read_stdin_content correctly strips UTF-8 BOM and decodes Chinese text."""
    raw = b"\xef\xbb\xbf\xe4\xbd\xa0\xe5\xa5\xbd\xef\xbc\x8c\xe6\x9d\xad\xe5\xb7\x9e\xef\xbc\x81"
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = raw

    with patch("sys.stdin", mock_stdin):
        content = read_stdin_content()
    assert content == "你好，杭州！"
    assert not content.startswith("\ufeff")


def test_stdin_with_utf8_bom_and_emojis() -> None:
    """read_stdin_content preserves 4-byte UTF-8 emojis alongside BOM."""
    raw = b"\xef\xbb\xbf\xf0\x9f\x9a\x80 \xe2\x9c\xa8 \xf0\x9f\xa4\x96 \xf0\x9f\x91\x8d"
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = raw

    with patch("sys.stdin", mock_stdin):
        content = read_stdin_content()
    assert content == "🚀 ✨ 🤖 👍"


def test_stdin_with_crlf_and_multiline() -> None:
    """read_stdin_content preserves CRLF structure and blank lines."""
    raw = b"Heading\r\n\r\n- Item 1\r\n- Item 2\r\n\r\nFooter"
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = raw

    with patch("sys.stdin", mock_stdin):
        content = read_stdin_content()
    assert content == "Heading\r\n\r\n- Item 1\r\n- Item 2\r\n\r\nFooter"


def test_stdin_corrupted_bytes_replacement_fallback() -> None:
    """read_stdin_content gracefully falls back to replacement chars on corrupt bytes."""
    raw = b"Prefix \xff\xfe Suffix"
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = raw

    with patch("sys.stdin", mock_stdin):
        content = read_stdin_content()
    assert "Prefix " in content
    assert " Suffix" in content
    assert "\ufffd" in content


def test_stdin_text_mode_fallback_bom_stripping() -> None:
    """When sys.stdin has no buffer attribute, text mode still strips BOM."""
    mock_stdin = MagicMock(spec=["read", "reconfigure"])
    del mock_stdin.buffer
    mock_stdin.read.return_value = "\ufeffText mode fallback content"

    with patch("sys.stdin", mock_stdin):
        content = read_stdin_content()
    assert content == "Text mode fallback content"
    assert not content.startswith("\ufeff")


def test_cli_send_stdin_flag_e2e(mock_feishu_env: None) -> None:
    """CLI send with --stdin flag reads content from piped stdin."""
    with patch("channel_bot_cli_antigravity.cli.FeishuBotChannel") as mock_fs:
        instance = mock_fs.return_value
        instance.send_message = AsyncMock(return_value={"msg": "ok"})
        instance.close = AsyncMock()

        mock_stdin = MagicMock()
        mock_stdin.buffer.read.return_value = b"\xef\xbb\xbfMessage from piped stdin"
        mock_stdin.isatty.return_value = False

        with patch("sys.stdin", mock_stdin):
            ret = main(
                ["send", "--channel", "feishu", "-c", "oc_piped_chat", "--stdin"]
            )
            assert ret == 0
            instance.send_message.assert_awaited_once_with(
                chat_id="oc_piped_chat",
                message="Message from piped stdin",
                file_paths=None,
                message_type="markdown",
            )


def test_cli_send_dash_message_e2e(mock_dd_env: None) -> None:
    """CLI send with -m '-' reads content from stdin."""
    with patch("channel_bot_cli_antigravity.cli.DingTalkBotChannel") as mock_dt:
        instance = mock_dt.return_value
        instance.send_message = AsyncMock(return_value={"msg": "ok"})
        instance.close = AsyncMock()

        mock_stdin = MagicMock()
        mock_stdin.buffer.read.return_value = b"Dash message via stdin"
        mock_stdin.isatty.return_value = False

        with patch("sys.stdin", mock_stdin):
            ret = main(
                ["send", "--channel", "dingtalk", "-c", "cid_dash_chat", "-m", "-"]
            )
            assert ret == 0
            instance.send_message.assert_awaited_once_with(
                chat_id="cid_dash_chat",
                message="Dash message via stdin",
                file_paths=None,
                message_type="markdown",
            )


def test_cli_send_empty_stdin_without_files_raises(mock_dd_env: None) -> None:
    """CLI send with empty stdin and no files raises error."""
    mock_stdin = MagicMock()
    mock_stdin.buffer.read.return_value = b"   \r\n"
    mock_stdin.isatty.return_value = False

    stderr_buf = StringIO()
    with patch("sys.stdin", mock_stdin), patch("sys.stderr", stderr_buf):
        ret = main(["send", "--channel", "dingtalk", "-c", "cid_empty", "--stdin"])
        assert ret == 1
    assert "从标准输入读取到的内容为空" in stderr_buf.getvalue()


# ===========================================================================
# 4. CLI Help Menus & Error Exits on Invalid Arguments
# ===========================================================================
def test_cli_help_menus(capsys: pytest.CaptureFixture[str]) -> None:
    """All CLI help menus format correctly and include necessary options."""
    parser = create_parser()

    # Root help
    root_help = parser.format_help()
    assert "listen" in root_help
    assert "send" in root_help
    assert "version" in root_help
    assert "--work-dir" in root_help

    # Send help
    with pytest.raises(SystemExit) as exc_send:
        parser.parse_args(["send", "--help"])
    assert exc_send.value.code == 0
    send_help = capsys.readouterr().out
    assert "--channel" in send_help
    assert "dingtalk" in send_help
    assert "feishu" in send_help
    assert "--chat-id" in send_help
    assert "--message" in send_help
    assert "--stdin" in send_help
    assert "--file" in send_help
    assert "--type" in send_help

    # Listen help
    with pytest.raises(SystemExit) as exc_listen:
        parser.parse_args(["listen", "--help"])
    assert exc_listen.value.code == 0
    listen_help = capsys.readouterr().out
    assert "--channel" in listen_help
    assert "dingtalk" in listen_help
    assert "feishu" in listen_help
    assert "all" in listen_help


def test_cli_no_subcommand_exits_code_2() -> None:
    """Calling CLI without subcommands raises SystemExit with code 2."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([])
    assert exc_info.value.code == 2


def test_cli_invalid_subcommand_exits_code_2() -> None:
    """Calling CLI with an unknown subcommand raises SystemExit with code 2."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["unknown_command"])
    assert exc_info.value.code == 2


def test_cli_send_missing_chat_id_exits_code_2() -> None:
    """CLI send without required -c / --chat-id raises SystemExit with code 2."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["send", "-m", "hello"])
    assert exc_info.value.code == 2


def test_cli_send_invalid_channel_choice_exits_code_2() -> None:
    """CLI send with an invalid channel choice raises SystemExit with code 2."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["send", "--channel", "wechat", "-c", "cid_1", "-m", "hi"])
    assert exc_info.value.code == 2


def test_cli_send_invalid_type_choice_exits_code_2() -> None:
    """CLI send with an invalid type choice raises SystemExit with code 2."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["send", "-c", "cid_1", "-m", "hi", "-t", "html"])
    assert exc_info.value.code == 2


def test_cli_listen_invalid_channel_choice_exits_code_2() -> None:
    """CLI listen with an invalid channel choice raises SystemExit with code 2."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["listen", "--channel", "slack"])
    assert exc_info.value.code == 2


def test_cli_send_mutually_exclusive_message_and_stdin_exits_code_2() -> None:
    """CLI send with both --message and --stdin raises SystemExit with code 2."""
    parser = create_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["send", "-c", "cid_1", "-m", "hello", "--stdin"])
    assert exc_info.value.code == 2


def test_cli_version_outputs(capsys: pytest.CaptureFixture[str]) -> None:
    """CLI version output matches package name and __version__."""
    ret_full = main(["version"])
    assert ret_full == 0
    out_full = capsys.readouterr().out
    assert out_full.strip() == f"channel-bot-cli-antigravity {__version__}"

    ret_short = main(["version", "--short"])
    assert ret_short == 0
    out_short = capsys.readouterr().out
    assert out_short.strip() == __version__

    ret_s = main(["version", "-s"])
    assert ret_s == 0
    out_s = capsys.readouterr().out
    assert out_s.strip() == __version__
