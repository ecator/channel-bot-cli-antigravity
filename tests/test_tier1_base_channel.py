"""Tier 1: Feature Coverage - BaseBotChannel abstract contract & helper methods."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from channel_bot_cli_antigravity.config import Config

try:
    from channel_bot_cli_antigravity.channels.base import BaseBotChannel
except ImportError:
    BaseBotChannel = None  # type: ignore[assignment,misc]


def _check_base_channel() -> type:
    assert BaseBotChannel is not None, (
        "BaseBotChannel must be implemented in src/channel_bot_cli_antigravity/channels/base.py"
    )
    return BaseBotChannel


def test_base_bot_channel_cannot_be_instantiated_directly() -> None:
    """Verify that BaseBotChannel is an abstract class and cannot be directly instantiated."""
    cls = _check_base_channel()
    cfg = Config()
    with pytest.raises(TypeError):
        cls(config=cfg)


def test_concrete_subclass_instantiation() -> None:
    """Verify that a concrete subclass implementing all abstract methods can be instantiated."""
    base_cls = _check_base_channel()

    class ConcreteBotChannel(base_cls):
        channel_name = "test_im"

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

    cfg = Config()
    instance = ConcreteBotChannel(config=cfg, filter_chat_id="  target_chat_001  ")
    assert instance.channel_name == "test_im"
    assert instance.filter_chat_id == "target_chat_001"
    assert instance.session_manager is not None


def test_base_bot_channel_get_session_key() -> None:
    """Verify get_session_key(chat_id) returns f'{channel_name}:{chat_id}'."""
    base_cls = _check_base_channel()

    class MockFeishuChannel(base_cls):
        channel_name = "feishu"

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
            pass

    instance = MockFeishuChannel(config=Config())
    key = instance.get_session_key("oc_test_123")
    assert key == "feishu:oc_test_123"


def test_base_bot_channel_build_frontmatter_structure() -> None:
    """Verify build_frontmatter generates valid YAML frontmatter with correct metadata fields."""
    base_cls = _check_base_channel()

    class MockDingTalkChannel(base_cls):
        channel_name = "dingtalk"

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
            pass

    instance = MockDingTalkChannel(config=Config())
    fm_str = instance.build_frontmatter(
        chat_id="cid_group_999",
        sender_id="user_alice",
        message_id="msg_001",
        create_time=1771234567.0,
        chat_type="group",
    )
    assert fm_str.startswith("---\n")
    assert fm_str.endswith("---\n")

    # Parse YAML block
    yaml_content = fm_str.strip("- \n")
    data = yaml.safe_load(yaml_content)
    assert data["channel"] == "dingtalk"
    assert data["chat_id"] == "cid_group_999"
    assert data["sender_id"] == "user_alice"
    assert data["message_id"] == "msg_001"
    assert data["chat_type"] == "group"
    assert "create_time" in data


def test_base_bot_channel_build_frontmatter_chat_type_normalization() -> None:
    """Verify build_frontmatter normalizes chat_type: 'dm'/'p2p' -> 'p2p', others -> 'group'."""
    base_cls = _check_base_channel()

    class MockTestChannel(base_cls):
        channel_name = "test"

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
            pass

    instance = MockTestChannel(config=Config())

    # dm -> p2p
    dm_data = yaml.safe_load(
        instance.build_frontmatter("c", "s", "m", None, "dm").strip("- \n")
    )
    assert dm_data["chat_type"] == "p2p"

    # p2p -> p2p
    p2p_data = yaml.safe_load(
        instance.build_frontmatter("c", "s", "m", None, "p2p").strip("- \n")
    )
    assert p2p_data["chat_type"] == "p2p"

    # group -> group
    grp_data = yaml.safe_load(
        instance.build_frontmatter("c", "s", "m", None, "group").strip("- \n")
    )
    assert grp_data["chat_type"] == "group"


def test_base_bot_channel_work_dir_initialization(tmp_path: Path) -> None:
    """Verify BaseBotChannel accepts work_dir Path and passes it to session_manager."""
    base_cls = _check_base_channel()

    class MockTestChannel(base_cls):
        channel_name = "test"

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
            pass

    instance = MockTestChannel(config=Config(), work_dir=tmp_path)
    assert instance.session_manager.work_dir == tmp_path
