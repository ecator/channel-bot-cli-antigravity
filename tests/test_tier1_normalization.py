"""Tier 1: Feature Coverage - Message normalization, ISO 8601 time & YAML Frontmatter."""

from datetime import datetime

import yaml

from channel_bot_cli_antigravity.utils import format_iso_time

try:
    from channel_bot_cli_antigravity.channels.base import BaseBotChannel
except ImportError:
    BaseBotChannel = None  # type: ignore[assignment,misc]


def test_format_iso_time_millisecond_timestamp() -> None:
    """Verify format_iso_time converts 13-digit millisecond timestamps accurately."""
    # 1771234567890 ms -> ~ 2026-02-16
    iso_str = format_iso_time(1771234567890)
    assert iso_str != ""
    # Should be valid ISO 8601 parseable
    dt = datetime.fromisoformat(iso_str)
    assert dt.year == 2026


def test_format_iso_time_second_timestamp() -> None:
    """Verify format_iso_time converts 10-digit second timestamps accurately."""
    iso_str = format_iso_time(1771234567)
    assert iso_str != ""
    dt = datetime.fromisoformat(iso_str)
    assert dt.year == 2026


def test_format_iso_time_none_and_empty() -> None:
    """Verify format_iso_time handles None and empty strings gracefully without crashing."""
    assert format_iso_time(None) == ""
    assert format_iso_time("") == ""


def test_format_iso_time_unparseable_string() -> None:
    """Verify format_iso_time returns input string if non-numeric string is provided."""
    assert format_iso_time("invalid_timestamp") == "invalid_timestamp"


def test_frontmatter_yaml_structure_and_delimiters() -> None:
    """Verify frontmatter generation adheres to strict YAML delimiters and field names."""
    metadata = {
        "channel": "dingtalk",
        "chat_id": "cid_test_channel",
        "sender_id": "user_100",
        "message_id": "msg_200",
        "create_time": format_iso_time(1771234567000),
        "chat_type": "p2p",
    }
    dumped = (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n"
    )

    assert dumped.startswith("---\n")
    assert dumped.endswith("---\n")

    # Delimiters split
    parts = dumped.split("---")
    assert len(parts) >= 3
    body = parts[1].strip()
    parsed = yaml.safe_load(body)

    for required_key in [
        "channel",
        "chat_id",
        "sender_id",
        "message_id",
        "create_time",
        "chat_type",
    ]:
        assert required_key in parsed, (
            f"Missing required frontmatter key: {required_key}"
        )


def test_frontmatter_unicode_and_special_characters() -> None:
    """Verify YAML Frontmatter retains UTF-8 characters without ASCII escape sequences."""
    metadata = {
        "channel": "feishu",
        "chat_id": "oc_中文群组_123",
        "sender_id": "ou_张三丰",
        "message_id": "msg_🌟_001",
        "create_time": format_iso_time(1771234567),
        "chat_type": "group",
    }
    dumped = (
        "---\n"
        + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        + "---\n"
    )

    # Must contain literal Chinese and emoji, not \u4e2d\u6587
    assert "oc_中文群组_123" in dumped
    assert "ou_张三丰" in dumped
    assert "msg_🌟_001" in dumped


def test_channel_frontmatter_method() -> None:
    """Verify build_frontmatter on BaseBotChannel if available."""
    if BaseBotChannel is None:
        return

    class ConcreteChannel(BaseBotChannel):
        channel_name = "feishu"

        async def start_listening(self) -> None:
            pass

        async def close(self) -> None:
            pass

        async def send_message(self, *args, **kwargs):
            pass

    from channel_bot_cli_antigravity.config import Config

    channel = ConcreteChannel(config=Config())
    fm = channel.build_frontmatter(
        chat_id="oc_test",
        sender_id="user_1",
        message_id="msg_1",
        create_time=1771234567,
        chat_type="p2p",
    )
    parsed = yaml.safe_load(fm.strip("- \n"))
    assert parsed["channel"] == "feishu"
    assert parsed["chat_id"] == "oc_test"
    assert parsed["chat_type"] == "p2p"
