"""Tier 1: Feature Coverage - CLI argument parsing and subcommand validation."""

import pytest

from channel_bot_cli_antigravity.cli import create_parser


def test_cli_version_parsing() -> None:
    """Verify version subcommand parsing with and without --short flag."""
    parser = create_parser()

    args_normal = parser.parse_args(["version"])
    assert args_normal.command == "version"
    assert getattr(args_normal, "short", False) is False

    args_short = parser.parse_args(["version", "--short"])
    assert args_short.command == "version"
    assert args_short.short is True

    args_short_flag = parser.parse_args(["version", "-s"])
    assert args_short_flag.short is True


def test_cli_send_channel_argument() -> None:
    """Verify send subcommand accepts --channel with dingtalk and feishu."""
    parser = create_parser()

    # Channel explicitly provided as dingtalk
    args_dd = parser.parse_args(
        ["send", "-c", "oc_123", "--channel", "dingtalk", "-m", "hi"]
    )
    assert hasattr(args_dd, "channel"), (
        "send subcommand must support --channel argument"
    )
    assert args_dd.channel == "dingtalk"

    # Channel explicitly provided as feishu
    args_fs = parser.parse_args(
        ["send", "-c", "oc_123", "--channel", "feishu", "-m", "hi"]
    )
    assert args_fs.channel == "feishu"

    # Channel omitted (should default to None for runtime inference)
    args_none = parser.parse_args(["send", "-c", "oc_123", "-m", "hi"])
    assert getattr(args_none, "channel", None) is None


def test_cli_send_required_chat_id() -> None:
    """Verify send subcommand requires --chat-id / -c."""
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["send", "-m", "hello without chat-id"])


def test_cli_send_mutually_exclusive_message_and_stdin() -> None:
    """Verify send subcommand rejects supplying both --message and --stdin."""
    parser = create_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["send", "-c", "chat_1", "-m", "text", "--stdin"])


def test_cli_send_multiple_files() -> None:
    """Verify send subcommand accepts multiple file paths via --file / -f."""
    parser = create_parser()
    args = parser.parse_args(
        ["send", "-c", "chat_1", "-f", "doc1.pdf", "img2.png", "data.csv"]
    )
    assert args.file_paths == ["doc1.pdf", "img2.png", "data.csv"]


def test_cli_send_message_type_choice() -> None:
    """Verify send subcommand accepts --type with markdown or text (defaults to markdown)."""
    parser = create_parser()

    args_default = parser.parse_args(["send", "-c", "chat_1", "-m", "msg"])
    assert args_default.message_type == "markdown"

    args_text = parser.parse_args(
        ["send", "-c", "chat_1", "-m", "msg", "--type", "text"]
    )
    assert args_text.message_type == "text"

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["send", "-c", "chat_1", "-m", "msg", "--type", "invalid_type"]
        )


def test_cli_listen_channel_argument() -> None:
    """Verify listen subcommand accepts --channel [dingtalk|feishu|all]."""
    parser = create_parser()

    # --channel dingtalk
    args_dd = parser.parse_args(["listen", "--channel", "dingtalk"])
    assert hasattr(args_dd, "channel"), (
        "listen subcommand must support --channel argument"
    )
    assert args_dd.channel == "dingtalk"

    # --channel feishu
    args_fs = parser.parse_args(["listen", "--channel", "feishu"])
    assert args_fs.channel == "feishu"

    # --channel all
    args_all = parser.parse_args(["listen", "--channel", "all"])
    assert args_all.channel == "all"


def test_cli_listen_optional_chat_id_and_work_dir() -> None:
    """Verify listen subcommand accepts optional --chat-id and top-level --work-dir."""
    parser = create_parser()
    args = parser.parse_args(["-w", "./my_workspace", "listen", "-c", "filter_chat_99"])
    assert args.command == "listen"
    assert args.chat_id == "filter_chat_99"
    assert args.work_dir == "./my_workspace"
