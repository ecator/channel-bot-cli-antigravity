"""Empirical verification test suite by challenger_m1_1.

Adversarially probes and stress-tests:
1. BaseBotChannel cannot be instantiated directly (ABC).
2. Double prefixing on get_session_key (feishu:chat123 -> feishu:chat123).
3. build_frontmatter across unusual chat_types ("1", "dm", "p2p", "single", "2", "group", "unknown").
4. get_channel with edge cases ("all", uppercase "FEISHU", "DD", invalid names).
5. validate_file_paths with non-existent files and directories.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from channel_bot_cli_antigravity.channels import (
    BaseBotChannel,
    DingTalkBotChannel,
    FeishuBotChannel,
    get_channel,
)
from channel_bot_cli_antigravity.config import Config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
class DummySubclassChannel(BaseBotChannel):
    """Minimal concrete implementation for testing base helper methods."""

    def __init__(self, name: str = "feishu", config: Config | None = None) -> None:
        self.channel_name = name
        self.config = config or Config()

    async def start_listening(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def send_message(
        self,
        chat_id: str,
        message: str | None = None,
        file_paths: list[str] | str | None = None,
        message_type: str = "markdown",
    ) -> Any:
        return {"chat_id": chat_id, "sent": True}


# ---------------------------------------------------------------------------
# Scope 1: BaseBotChannel cannot be instantiated directly
# ---------------------------------------------------------------------------
def test_base_bot_channel_cannot_be_instantiated_directly() -> None:
    """BaseBotChannel has abstract methods and must raise TypeError upon instantiation."""
    with pytest.raises(TypeError) as exc_info:
        BaseBotChannel(config=Config())
    err_msg = str(exc_info.value).lower()
    assert "abstract" in err_msg
    assert (
        "start_listening" in err_msg or "close" in err_msg or "send_message" in err_msg
    )


def test_base_bot_channel_partial_subclasses_raise_type_error() -> None:
    """Subclasses omitting any of the 3 abstract methods must raise TypeError."""

    class MissingStartListening(BaseBotChannel):
        channel_name = "test"

        async def close(self) -> None:
            pass

        async def send_message(self, chat_id: str, **kwargs: Any) -> Any:
            pass

    with pytest.raises(TypeError):
        MissingStartListening(config=Config())

    class MissingClose(BaseBotChannel):
        channel_name = "test"

        async def start_listening(self) -> None:
            pass

        async def send_message(self, chat_id: str, **kwargs: Any) -> Any:
            pass

    with pytest.raises(TypeError):
        MissingClose(config=Config())

    class MissingSendMessage(BaseBotChannel):
        channel_name = "test"

        async def start_listening(self) -> None:
            pass

        async def close(self) -> None:
            pass

    with pytest.raises(TypeError):
        MissingSendMessage(config=Config())


def test_base_bot_channel_full_subclass_succeeds() -> None:
    """Full subclass implementing all abstract methods instantiates without error."""
    instance = DummySubclassChannel(name="custom_bot")
    assert instance.channel_name == "custom_bot"


# ---------------------------------------------------------------------------
# Scope 2: Double prefixing on get_session_key
# ---------------------------------------------------------------------------
def test_get_session_key_prevents_double_prefixing() -> None:
    """get_session_key('feishu:chat123') must return 'feishu:chat123', not 'feishu:feishu:chat123'."""
    ch = DummySubclassChannel(name="feishu")
    assert ch.get_session_key("feishu:chat123") == "feishu:chat123"


def test_get_session_key_standard_unprefixed() -> None:
    """get_session_key('chat123') returns 'feishu:chat123'."""
    ch = DummySubclassChannel(name="feishu")
    assert ch.get_session_key("chat123") == "feishu:chat123"


def test_get_session_key_idempotence_loop() -> None:
    """Multiple applications of get_session_key must remain idempotent."""
    ch = DummySubclassChannel(name="feishu")
    key = "chat123"
    for _ in range(5):
        key = ch.get_session_key(key)
    assert key == "feishu:chat123"


def test_get_session_key_dingtalk() -> None:
    """DingTalk channel get_session_key correctly handles prefixed and unprefixed keys."""
    ch = DummySubclassChannel(name="dingtalk")
    assert ch.get_session_key("dingtalk:cid_xyz") == "dingtalk:cid_xyz"
    assert ch.get_session_key("cid_xyz") == "dingtalk:cid_xyz"


def test_get_session_key_edge_inputs() -> None:
    """Edge cases: empty string, colons inside chat_id, cross-channel prefix."""
    ch = DummySubclassChannel(name="feishu")
    assert ch.get_session_key("") == "feishu:"
    assert ch.get_session_key("feishu:") == "feishu:"
    assert ch.get_session_key("user:uuid:456") == "feishu:user:uuid:456"
    assert ch.get_session_key("dingtalk:chat123") == "feishu:dingtalk:chat123"


# ---------------------------------------------------------------------------
# Scope 3: build_frontmatter across unusual chat_types
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("chat_type_input", "expected_output"),
    [
        ("1", "p2p"),
        ("dm", "p2p"),
        ("p2p", "p2p"),
        ("single", "p2p"),
        ("2", "group"),
        ("group", "group"),
        ("unknown", "group"),
        ("  DM  ", "p2p"),
        ("P2P", "p2p"),
        ("Single", "p2p"),
        ("  1  ", "p2p"),
        (" GROUP ", "group"),
        ("  2  ", "group"),
        ("UNKNOWN", "group"),
        ("", "group"),
        (None, "group"),
        ("other_unsupported", "group"),
    ],
)
def test_build_frontmatter_chat_types(
    chat_type_input: Any, expected_output: str
) -> None:
    """Verify chat_type normalization across various inputs."""
    ch = DummySubclassChannel(name="feishu")
    fm = ch.build_frontmatter(
        chat_id="oc_test_chat",
        sender_id="ou_test_user",
        message_id="om_test_msg",
        create_time=1700000000.0,
        chat_type=chat_type_input,
    )
    assert fm.startswith("---\n")
    assert fm.endswith("---\n")

    data = yaml.safe_load(fm.strip("- \n"))
    assert data["chat_type"] == expected_output


def test_build_frontmatter_complete_fields_and_override() -> None:
    """Verify all frontmatter fields are present and channel override is honored."""
    ch = DummySubclassChannel(name="dingtalk")
    fm = ch.build_frontmatter(
        chat_id="cid_123",
        sender_id="user_456",
        message_id="msg_789",
        create_time=1700000000.5,
        chat_type="dm",
        channel="custom_channel",
    )
    data = yaml.safe_load(fm.strip("- \n"))
    assert data["channel"] == "custom_channel"
    assert data["chat_id"] == "cid_123"
    assert data["sender_id"] == "user_456"
    assert data["message_id"] == "msg_789"
    assert data["chat_type"] == "p2p"
    assert "create_time" in data


def test_build_frontmatter_special_characters_escaping() -> None:
    """Verify that YAML special characters do not corrupt frontmatter structure."""
    ch = DummySubclassChannel(name="feishu")
    fm = ch.build_frontmatter(
        chat_id="oc: special: chat: id",
        sender_id='user "with quotes"',
        message_id="msg\nwith\nnewlines",
        create_time="2026-10-17T05:00:00Z",
        chat_type="p2p",
    )
    data = yaml.safe_load(fm.strip("- \n"))
    assert data["chat_id"] == "oc: special: chat: id"
    assert data["sender_id"] == 'user "with quotes"'
    assert data["message_id"] == "msg\nwith\nnewlines"
    assert data["chat_type"] == "p2p"


# ---------------------------------------------------------------------------
# Scope 4: get_channel with edge cases
# ---------------------------------------------------------------------------
def test_get_channel_all_raises_value_error() -> None:
    """Channel 'all' is a multi-channel listening mode and cannot be instantiated directly."""
    cfg = Config()
    for name in ["all", "ALL", "  all  ", "All"]:
        with pytest.raises(ValueError) as exc_info:
            get_channel(name, config=cfg)
        assert "all" in str(exc_info.value).lower()


def test_get_channel_uppercase_and_aliases() -> None:
    """Verify get_channel handles uppercase and aliases correctly."""
    cfg = Config()
    mock_feishu = MagicMock()
    mock_dd = MagicMock()

    # Uppercase FEISHU
    feishu_ch = get_channel("FEISHU", config=cfg, channel=mock_feishu)
    assert isinstance(feishu_ch, FeishuBotChannel)
    assert feishu_ch.channel_name == "feishu"

    # Alias LARK (uppercase)
    lark_ch = get_channel("LARK", config=cfg, channel=mock_feishu)
    assert isinstance(lark_ch, FeishuBotChannel)
    assert lark_ch.channel_name == "feishu"

    # Alias DD (uppercase)
    dd_ch = get_channel("DD", config=cfg, channel=mock_dd)
    assert isinstance(dd_ch, DingTalkBotChannel)
    assert dd_ch.channel_name == "dingtalk"

    # Uppercase DINGTALK
    dingtalk_ch = get_channel("DINGTALK", config=cfg, channel=mock_dd)
    assert isinstance(dingtalk_ch, DingTalkBotChannel)
    assert dingtalk_ch.channel_name == "dingtalk"

    # Whitespace padded
    ws_ch = get_channel("  feishu  ", config=cfg, channel=mock_feishu)
    assert isinstance(ws_ch, FeishuBotChannel)


def test_get_channel_invalid_names_raise_value_error() -> None:
    """Invalid or unsupported channel names must raise ValueError."""
    cfg = Config()
    for invalid in ["wechat", "slack", "", "   ", None, "123", "unknown"]:
        with pytest.raises(ValueError) as exc_info:
            get_channel(invalid, config=cfg)  # type: ignore[arg-type]
        err_str = str(exc_info.value)
        assert "不支持" in err_str or "supported" in err_str.lower()


# ---------------------------------------------------------------------------
# Scope 5: validate_file_paths with non-existent files and directories
# ---------------------------------------------------------------------------
def test_validate_file_paths_existing_file() -> None:
    """Existing files (as str, Path, or list) pass validation and return list[Path]."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"data")
        temp_path = tf.name

    try:
        # Single string
        res1 = BaseBotChannel.validate_file_paths(temp_path)
        assert len(res1) == 1
        assert res1[0] == Path(temp_path)

        # Single Path
        res2 = BaseBotChannel.validate_file_paths(Path(temp_path))
        assert len(res2) == 1
        assert res2[0] == Path(temp_path)

        # List of strings
        res3 = BaseBotChannel.validate_file_paths([temp_path])
        assert len(res3) == 1
        assert res3[0] == Path(temp_path)
    finally:
        os.remove(temp_path)


def test_validate_file_paths_non_existent_file() -> None:
    """Non-existent file path must raise FileNotFoundError."""
    missing = "non_existent_file_challenger_99999.xyz"
    with pytest.raises(FileNotFoundError) as exc_info:
        BaseBotChannel.validate_file_paths(missing)
    assert missing in str(exc_info.value) or "未找到待发送的文件" in str(exc_info.value)


def test_validate_file_paths_directory_raises_file_not_found_error() -> None:
    """Passing a directory must raise FileNotFoundError (directories are not files)."""
    with tempfile.TemporaryDirectory() as td:
        with pytest.raises(FileNotFoundError) as exc_info:
            BaseBotChannel.validate_file_paths(td)
        assert td in str(exc_info.value) or "未找到待发送的文件" in str(exc_info.value)


def test_validate_file_paths_mixed_valid_and_missing() -> None:
    """A list containing a valid file and a missing file must raise FileNotFoundError."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(b"data")
        temp_path = tf.name

    try:
        with pytest.raises(FileNotFoundError):
            BaseBotChannel.validate_file_paths([temp_path, "missing_sibling.dat"])
    finally:
        os.remove(temp_path)


def test_validate_file_paths_empty_and_none() -> None:
    """None, empty list, and empty string return empty list without error."""
    assert BaseBotChannel.validate_file_paths(None) == []
    assert BaseBotChannel.validate_file_paths([]) == []
    assert BaseBotChannel.validate_file_paths("") == []


def test_validate_file_paths_whitespace_raises_file_not_found_error() -> None:
    """Whitespace-only string must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        BaseBotChannel.validate_file_paths("   ")


# ---------------------------------------------------------------------------
# Scope 6: Extra Channel Boundary Stress Tests
# ---------------------------------------------------------------------------
def test_should_filter_chat() -> None:
    """Verify should_filter_chat behavior when filter is set vs unset."""
    cfg = Config()
    ch_unfiltered = DummySubclassChannel(name="feishu", config=cfg)
    ch_unfiltered.filter_chat_id = None
    assert not ch_unfiltered.should_filter_chat("any_chat_id")

    ch_filtered = DummySubclassChannel(name="feishu", config=cfg)
    ch_filtered.filter_chat_id = "allowed_chat"
    assert not ch_filtered.should_filter_chat("allowed_chat")
    assert ch_filtered.should_filter_chat("other_chat")


def test_normalize_file_paths() -> None:
    """Verify normalize_file_paths handles various iterable and scalar types."""
    assert BaseBotChannel.normalize_file_paths(None) == []
    assert BaseBotChannel.normalize_file_paths([]) == []
    assert BaseBotChannel.normalize_file_paths("") == []
    assert BaseBotChannel.normalize_file_paths("file.txt") == ["file.txt"]
    assert BaseBotChannel.normalize_file_paths(Path("file.txt")) == ["file.txt"]
    assert BaseBotChannel.normalize_file_paths(["a.txt", Path("b.txt"), ""]) == [
        "a.txt",
        "b.txt",
    ]


def test_dingtalk_resolve_send_target() -> None:
    """Verify DingTalk send target resolution strips channel prefix and classifies target."""
    from dingtalk_channel_sdk import SendTarget

    cfg = Config()
    mock_sdk = MagicMock()
    dt = DingTalkBotChannel(config=cfg, channel=mock_sdk)

    # Conversation targets (group)
    t1 = dt._resolve_send_target("cid_12345")
    assert isinstance(t1, SendTarget)
    assert t1.conversation_id == "cid_12345"

    t2 = dt._resolve_send_target("chat_67890")
    assert t2.conversation_id == "chat_67890"

    # With dingtalk prefix
    t3 = dt._resolve_send_target("dingtalk:cid_prefixed")
    assert t3.conversation_id == "cid_prefixed"

    # User targets (p2p)
    t4 = dt._resolve_send_target("user_alice")
    assert t4.user_id == "user_alice"

    t5 = dt._resolve_send_target("dingtalk:user_bob")
    assert t5.user_id == "user_bob"
