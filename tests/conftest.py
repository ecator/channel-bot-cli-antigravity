"""Shared fixtures, mock objects, and helpers for channel-bot-cli-antigravity test suite."""

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from types import TracebackType
from typing import Any, Self
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Environment Variable Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Fixture that clears all channel bot and Antigravity environment variables."""
    env_keys = [
        "DD_CLIENT_ID",
        "DD_CLIENT_SECRET",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_DOMAIN",
        "LARK_APP_ID",
        "LARK_APP_SECRET",
        "LARK_DOMAIN",
        "LOG_LEVEL",
        "AGY_MODEL",
        "AGY_IMAGE_MODEL",
        "GOOGLE_GENAI_USE_VERTEXAI",
        "GOOGLE_GENAI_USE_ENTERPRISE",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture
def dingtalk_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Fixture setting only DingTalk credentials."""
    clean_env.setenv("DD_CLIENT_ID", "suite_dd_client_id_123")
    clean_env.setenv("DD_CLIENT_SECRET", "suite_dd_client_secret_xyz")
    return clean_env


@pytest.fixture
def feishu_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Fixture setting only Feishu credentials."""
    clean_env.setenv("FEISHU_APP_ID", "cli_feishu_test_app_id")
    clean_env.setenv("FEISHU_APP_SECRET", "sec_feishu_test_app_secret")
    return clean_env


@pytest.fixture
def legacy_lark_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Fixture setting legacy Lark credentials."""
    clean_env.setenv("LARK_APP_ID", "cli_legacy_lark_app_id")
    clean_env.setenv("LARK_APP_SECRET", "sec_legacy_lark_app_secret")
    return clean_env


@pytest.fixture
def dual_channel_env(clean_env: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Fixture setting both DingTalk and Feishu credentials."""
    clean_env.setenv("DD_CLIENT_ID", "suite_dd_client_id_123")
    clean_env.setenv("DD_CLIENT_SECRET", "suite_dd_client_secret_xyz")
    clean_env.setenv("FEISHU_APP_ID", "cli_feishu_test_app_id")
    clean_env.setenv("FEISHU_APP_SECRET", "sec_feishu_test_app_secret")
    return clean_env


# ---------------------------------------------------------------------------
# Mock Antigravity Agent & ChatResponse
# ---------------------------------------------------------------------------


class MockChatResponse:
    """Mock asynchronous iterable response simulating Antigravity ChatResponse."""

    def __init__(self, chunks: list[str] | None = None) -> None:
        self.chunks = chunks if chunks is not None else ["Hello", ", ", "world!"]
        self.consumed = False

    def __aiter__(self) -> AsyncIterator[str]:
        async def _generator() -> AsyncIterator[str]:
            for chunk in self.chunks:
                await asyncio.sleep(0.001)
                yield chunk
            self.consumed = True

        return _generator()

    async def text(self) -> str:
        return "".join(self.chunks)


class MockAgent:
    """Mock Antigravity Agent instance."""

    def __init__(self, response_chunks: list[str] | None = None) -> None:
        self.response_chunks = response_chunks
        self.chat_history: list[Any] = []
        self.chat = AsyncMock(side_effect=self._mock_chat)

    async def _mock_chat(self, agent_input: Any) -> MockChatResponse:
        self.chat_history.append(agent_input)
        return MockChatResponse(self.response_chunks)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass


class MockAgentSessionManager:
    """Mock AgentSessionManager holding locks and managing mock agents."""

    def __init__(self, agent: MockAgent | None = None) -> None:
        self.agent = agent or MockAgent()
        self._locks: dict[str, asyncio.Lock] = {}
        self._sessions: dict[str, MockAgent] = {}
        self.close_all = AsyncMock()

    def get_lock(self, session_key: str) -> asyncio.Lock:
        if session_key not in self._locks:
            self._locks[session_key] = asyncio.Lock()
        return self._locks[session_key]

    async def get_or_create_agent(self, session_key: str) -> MockAgent:
        if session_key not in self._sessions:
            self._sessions[session_key] = self.agent
        return self._sessions[session_key]


# ---------------------------------------------------------------------------
# Mock Feishu Channel SDK Objects
# ---------------------------------------------------------------------------


class MockCardStreamAppender:
    """Mock stream appender for CardKit stream producer."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def append(self, token: str) -> None:
        self.tokens.append(token)


class MockFeishuChannel:
    """Mock FeishuChannel for opaque-box network isolation."""

    def __init__(self) -> None:
        self.handlers: dict[str, list[Callable[..., Any]]] = {}
        self.sent_messages: list[tuple[str, dict[str, Any]]] = []
        self.streams: list[tuple[str, Any]] = []
        self.added_reactions: list[str] = []
        self.removed_reactions: list[tuple[str, str]] = []
        self.downloaded_resources: dict[str, bytes] = {}
        self.is_connected = False
        self.is_stopped = False

    def on(self, event_name: str, handler: Callable[..., Any]) -> None:
        self.handlers.setdefault(str(event_name), []).append(handler)

    async def connect(self) -> None:
        self.is_connected = True

    def stop(self) -> None:
        self.is_stopped = True

    async def send(self, chat_id: str, content: dict[str, Any]) -> dict[str, Any]:
        self.sent_messages.append((chat_id, content))
        return {"message_id": f"om_mock_{len(self.sent_messages)}", "status": "ok"}

    async def stream(self, chat_id: str, spec: dict[str, Any]) -> None:
        self.streams.append((chat_id, spec))
        producer = spec.get("markdown")
        if callable(producer):
            mock_card_stream = MockCardStreamAppender()
            await producer(mock_card_stream)

    async def add_typing_reaction(self, message_id: str) -> str:
        reaction_id = f"reaction_{message_id}_{len(self.added_reactions)}"
        self.added_reactions.append(reaction_id)
        return reaction_id

    async def remove_typing_reaction(self, message_id: str, reaction_id: str) -> bool:
        self.removed_reactions.append((message_id, reaction_id))
        return True

    async def download_resource(
        self, file_key: str, resource_type: str, message_id: str
    ) -> bytes | None:
        return self.downloaded_resources.get(file_key, b"mock_feishu_file_bytes")


class MockFeishuInboundMessage:
    """Mock Feishu InboundMessage for event simulation."""

    def __init__(
        self,
        msg_id: str = "om_test_123",
        chat_id: str = "oc_test_chat_456",
        chat_type: str = "p2p",
        sender_id: str = "ou_user_789",
        sender_name: str = "Test User",
        sender_is_bot: bool = False,
        content_text: str = "Hello Bot",
        create_time: float | str | None = 1771234567.0,
        resources: list[Any] | None = None,
        content: Any = None,
    ) -> None:
        self.id = msg_id
        self.chat_id = chat_id
        self.chat_type = chat_type
        self.sender_id = sender_id
        self.sender_name = sender_name
        self.sender_is_bot = sender_is_bot
        self.content_text = content_text
        self.create_time = create_time
        self.resources = resources or []
        self.content = content


# ---------------------------------------------------------------------------
# Mock DingTalk Channel SDK Objects
# ---------------------------------------------------------------------------


class MockDingTalkCardStreamer:
    """Mock DingTalk CardStreamer."""

    def __init__(self) -> None:
        self.card_delivered = True
        self.tokens: list[str] = []
        self.finished_content: str | None = None
        self.failed_error: str | None = None

    async def append(self, delta: str) -> None:
        self.tokens.append(delta)

    async def finish(self, content: str) -> None:
        self.finished_content = content

    async def fail(self, err_msg: str) -> None:
        self.failed_error = err_msg


class MockDingTalkReply:
    """Mock DingTalk Reply object."""

    def __init__(self, streamer: MockDingTalkCardStreamer | None = None) -> None:
        self.streamer = streamer or MockDingTalkCardStreamer()
        self.text_replies: list[str] = []
        self.markdown_replies: list[tuple[str, str]] = []
        self.download_urls: dict[str, str] = {
            "test_code_1": "https://download.dingtalk.com/file1",
        }

    async def stream(self) -> MockDingTalkCardStreamer:
        return self.streamer

    async def text(self, text: str) -> None:
        self.text_replies.append(text)

    async def markdown(self, title: str, text: str) -> None:
        self.markdown_replies.append((title, text))

    async def download_url(self, code: str, msg_id: str) -> str:
        return self.download_urls.get(code, f"https://mock.dingtalk.com/dl/{code}")


class MockDingTalkIncomingMessage:
    """Mock DingTalk IncomingMessage object."""

    def __init__(
        self,
        msg_id: str = "msg_dd_001",
        conversation_id: str = "cid_test_group",
        conversation_type: str = "group",
        sender_id: str = "staff_999",
        sender_nick: str = "DingTalk User",
        text: str = "Hello DingTalk",
        resources: list[dict[str, Any]] | None = None,
        create_at: int = 1771234567890,
    ) -> None:
        self.msg_id = msg_id
        self.conversation_id = conversation_id
        self.conversation_type = conversation_type
        self.sender_id = sender_id
        self.sender_staff_id = sender_id
        self.sender_nick = sender_nick
        self.text = text
        self.resources = resources or []
        self.create_at = create_at


class MockDingTalkOApi:
    """Mock DingTalk OAPI client for media uploads."""

    def __init__(self) -> None:
        self.uploads: list[tuple[str, str, bytes, str]] = []

    async def upload_media(
        self,
        media_type: str,
        filename: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, str]:
        self.uploads.append((media_type, filename, data, content_type))
        return {
            "mediaId": f"@media_{filename}",
            "downloadUrl": f"https://oapi.dingtalk.com/media/@media_{filename}",
        }


class MockDingTalkChannel:
    """Mock DingTalkChannel for opaque-box network isolation."""

    def __init__(self) -> None:
        self.message_handlers: list[Callable[..., Any]] = []
        self.card_action_handlers: list[Callable[..., Any]] = []
        self.sent_texts: list[tuple[Any, str]] = []
        self.sent_markdowns: list[tuple[Any, str, str]] = []
        self.sent_images: list[tuple[Any, str]] = []
        self.thinking_stamps: list[tuple[str, str]] = []
        self.done_stamps: list[tuple[str, str]] = []
        self.oapi = MockDingTalkOApi()
        self.is_started = False
        self.is_closed = False

    def on_message(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        self.message_handlers.append(handler)
        return handler

    def on_card_action(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        self.card_action_handlers.append(handler)
        return handler

    async def start(self) -> None:
        self.is_started = True

    def close(self) -> None:
        self.is_closed = True

    async def mark_thinking(self, conversation_id: str, msg_id: str) -> None:
        self.thinking_stamps.append((conversation_id, msg_id))

    async def mark_done(self, conversation_id: str, msg_id: str) -> None:
        self.done_stamps.append((conversation_id, msg_id))

    async def download_file(self, url: str) -> bytes:
        return b"mock_dingtalk_downloaded_bytes"

    async def send_text(self, target: Any, text: str) -> dict[str, str]:
        self.sent_texts.append((target, text))
        return {"processQueryKey": "mock_text_proc_key"}

    async def send_markdown(self, target: Any, title: str, text: str) -> dict[str, str]:
        self.sent_markdowns.append((target, title, text))
        return {"processQueryKey": "mock_md_proc_key"}

    async def send_image(self, target: Any, image_url: str) -> dict[str, str]:
        self.sent_images.append((target, image_url))
        return {"processQueryKey": "mock_img_proc_key"}


# ---------------------------------------------------------------------------
# Temporary File Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_files(tmp_path: Path) -> dict[str, Path]:
    """Fixture creating temporary mock files (text, image, pdf, binary)."""
    txt_file = tmp_path / "hello.txt"
    txt_file.write_text("Hello World from text file", encoding="utf-8")

    png_file = tmp_path / "image.png"
    png_file.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    )

    pdf_file = tmp_path / "doc.pdf"
    pdf_file.write_bytes(b"%PDF-1.4 mock pdf content")

    bin_file = tmp_path / "archive.bin"
    bin_file.write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07")

    return {
        "txt": txt_file,
        "png": png_file,
        "pdf": pdf_file,
        "bin": bin_file,
    }
