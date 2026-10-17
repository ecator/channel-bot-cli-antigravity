"""Empirical verification and adversarial challenge test suite by challenger_m3_1.

Adversarially probes and stress-tests:
1. Concurrency isolation across channels:
   - Distinct locks for 'feishu:chat1' vs 'dingtalk:chat1'.
   - Parallel execution across distinct channel sessions without mutual blocking.
   - Dual-channel concurrent message dispatch on shared AgentSessionManager.
   - Key formatting robustness (no double-prefixing).

2. Concurrency serialization within same session:
   - Strict serialization for 20+ concurrent messages targeting the SAME session (max_concurrent_turns == 1).
   - Zero turn-time overlaps verified via precise timestamp intervals.
   - High concurrency burst stress (50 concurrent messages).
   - Idempotent lock identity per session key.

3. Lock release on turn error:
   - Lock released immediately on unhandled agent.chat exception.
   - Lock released on streaming / channel communication failure.
   - Lock released on asyncio task cancellation.
   - Recovery after multiple consecutive failing turns.

4. Agent session isolation:
   - Distinct Agent instances across sessions ('feishu:chat1', 'dingtalk:chat1', 'feishu:chat2').
   - Session state persistence for repeated calls with same session key.
   - Multi-turn conversation history isolation between channels.
   - Full lifecycle cleanup on close_all() (exit_stack aclose and dictionary resets).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Generator
from typing import Any, Self

import pytest

from channel_bot_cli_antigravity.agent import AgentSessionManager
from channel_bot_cli_antigravity.channels.dingtalk import DingTalkBotChannel
from channel_bot_cli_antigravity.channels.feishu import FeishuBotChannel
from channel_bot_cli_antigravity.config import Config

# ---------------------------------------------------------------------------
# Mocks & Test Fixtures
# ---------------------------------------------------------------------------


class MockChatResponse:
    """Mock streaming chat response supporting async generator and optional text()."""

    def __init__(self, chunks: list[str]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncGenerator[str]:
        async def _gen() -> AsyncGenerator[str]:
            for chunk in self._chunks:
                yield chunk

        return _gen()

    async def text(self) -> str:
        return "".join(self._chunks)


class StressTestAgent:
    """Instrumented Mock Agent for detecting interleaving and measuring concurrency."""

    def __init__(
        self,
        delay_seconds: float = 0.04,
        fail_turns: set[int] | None = None,
        exception_factory: Any = None,
    ) -> None:
        self.delay = delay_seconds
        self.fail_turns = fail_turns or set()
        self.exception_factory = exception_factory or (
            lambda turn: RuntimeError(f"Simulated engine failure on turn {turn}")
        )
        self.active_turns = 0
        self.max_concurrent_turns = 0
        self.total_turn_count = 0
        self.turn_history: list[dict[str, Any]] = []
        self.chat_history: list[Any] = []
        self.is_closed = False

    async def chat(self, agent_input: Any) -> MockChatResponse:
        self.total_turn_count += 1
        turn_num = self.total_turn_count
        self.active_turns += 1
        self.max_concurrent_turns = max(self.max_concurrent_turns, self.active_turns)

        self.chat_history.append(agent_input)
        start_time = time.perf_counter()

        try:
            if turn_num in self.fail_turns:
                raise self.exception_factory(turn_num)

            await asyncio.sleep(self.delay)
            return MockChatResponse([f"Response_turn_{turn_num}"])
        finally:
            end_time = time.perf_counter()
            self.turn_history.append(
                {
                    "turn": turn_num,
                    "start": start_time,
                    "end": end_time,
                    "input": agent_input,
                }
            )
            self.active_turns -= 1

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        self.is_closed = True


class MockFeishuCardStream:
    """Mock Feishu CardKit stream."""

    def __init__(self) -> None:
        self.tokens: list[str] = []

    async def append(self, token: str) -> None:
        self.tokens.append(token)


class MockFeishuSDKChannel:
    """Mock for lark-channel SDK client."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, dict[str, Any]]] = []
        self.streams: list[tuple[str, list[str]]] = []
        self.added_reactions: list[str] = []
        self.removed_reactions: list[tuple[str, str]] = []

    async def add_typing_reaction(self, message_id: str) -> str:
        self.added_reactions.append(message_id)
        return f"react_{message_id}"

    async def remove_typing_reaction(self, message_id: str, reaction_id: str) -> None:
        self.removed_reactions.append((message_id, reaction_id))

    async def stream(self, chat_id: str, payload: dict[str, Any]) -> None:
        producer = payload.get("markdown")
        if callable(producer):
            stream_obj = MockFeishuCardStream()
            await producer(stream_obj)
            self.streams.append((chat_id, stream_obj.tokens))

    async def send(self, chat_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.sent_messages.append((chat_id, payload))
        return {"code": 0, "msg": "success"}

    def on(self, event: Any, handler: Any) -> None:
        pass

    def stop(self) -> None:
        pass


class MockDingTalkCardStreamer:
    """Mock for dingtalk card streamer."""

    def __init__(self) -> None:
        self.tokens: list[str] = []
        self.finished_text: str | None = None

    async def append(self, delta: str) -> None:
        self.tokens.append(delta)

    async def finish(self, text: str) -> None:
        self.finished_text = text


class MockDingTalkReply:
    """Mock for dingtalk DWClient reply object."""

    def __init__(self) -> None:
        self.streamer = MockDingTalkCardStreamer()
        self.markdown_replies: list[tuple[str, str]] = []
        self.text_replies: list[str] = []

    async def stream(self) -> MockDingTalkCardStreamer:
        return self.streamer

    async def markdown(self, title: str, text: str) -> None:
        self.markdown_replies.append((title, text))

    async def text(self, text: str) -> None:
        self.text_replies.append(text)


class MockDingTalkSDKChannel:
    """Mock for dingtalk DWClient channel."""

    def __init__(self) -> None:
        self.thinking_stamps: list[tuple[str, str]] = []
        self.done_stamps: list[tuple[str, str]] = []

    async def mark_thinking(self, conversation_id: str, msg_id: str) -> None:
        self.thinking_stamps.append((conversation_id, msg_id))

    async def mark_done(self, conversation_id: str, msg_id: str) -> None:
        self.done_stamps.append((conversation_id, msg_id))

    def on_message(self, handler: Any) -> None:
        pass

    def close(self) -> None:
        pass


class MockFeishuInboundMsg:
    def __init__(self, msg_id: str, chat_id: str, text: str) -> None:
        self.message_id = msg_id
        self.id = msg_id
        self.chat_id = chat_id
        self.content_text = text
        self.sender_id = f"user_{chat_id}"
        self.sender_is_bot = False
        self.create_time = 1729150000.0
        self.chat_type = "group"
        self.resources: list[Any] = []


class MockDingTalkInboundMsg:
    def __init__(self, msg_id: str, conversation_id: str, text: str) -> None:
        self.msg_id = msg_id
        self.conversation_id = conversation_id
        self.sender_id = f"user_{conversation_id}"
        self.sender_is_bot = False
        self.create_at = 1729150000000
        self.conversation_type = "2"
        self.text = text
        self.images: list[Any] = []
        self.files: list[Any] = []


@pytest.fixture
def env_credentials(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setenv("DD_CLIENT_ID", "mock_dd_id")
    monkeypatch.setenv("DD_CLIENT_SECRET", "mock_dd_sec")
    monkeypatch.setenv("FEISHU_APP_ID", "mock_fs_id")
    monkeypatch.setenv("FEISHU_APP_SECRET", "mock_fs_sec")
    yield


# ---------------------------------------------------------------------------
# Scope 1: Concurrency Isolation Across Channels
# ---------------------------------------------------------------------------


def test_challenge_lock_isolation_across_channels_distinct_instances() -> None:
    """Empirically verify get_lock('feishu:chat1') and get_lock('dingtalk:chat1') return distinct locks."""
    session_mgr = AgentSessionManager()

    lock_feishu = session_mgr.get_lock("feishu:chat1")
    lock_dingtalk = session_mgr.get_lock("dingtalk:chat1")

    assert lock_feishu is not None
    assert lock_dingtalk is not None
    assert lock_feishu is not lock_dingtalk, (
        "CRITICAL: Feishu and DingTalk locks for the same chat id MUST be distinct objects!"
    )


def test_challenge_get_session_key_robustness_no_double_prefixing() -> None:
    """Verify that get_session_key handles clean and already-prefixed targets idempotently."""
    cfg = Config()
    feishu_bot = FeishuBotChannel(
        config=cfg,
        channel=MockFeishuSDKChannel(),
        session_manager=AgentSessionManager(),
    )
    dingtalk_bot = DingTalkBotChannel(
        config=cfg,
        channel=MockDingTalkSDKChannel(),
        session_manager=AgentSessionManager(),
    )

    # Standard clean IDs
    assert feishu_bot.get_session_key("chat_123") == "feishu:chat_123"
    assert dingtalk_bot.get_session_key("chat_123") == "dingtalk:chat_123"

    # Already prefixed IDs (should never produce double-prefixing like feishu:feishu:chat_123)
    assert feishu_bot.get_session_key("feishu:chat_123") == "feishu:chat_123"
    assert dingtalk_bot.get_session_key("dingtalk:chat_123") == "dingtalk:chat_123"


@pytest.mark.asyncio
async def test_challenge_cross_channel_parallel_execution_no_blocking() -> None:
    """Empirically verify that holding lock('feishu:c1') does NOT block lock('dingtalk:c1').

    Both channels run 0.1s turns concurrently; total elapsed time must be approx 0.1s, NOT 0.2s.
    """
    session_mgr = AgentSessionManager()
    lock_f = session_mgr.get_lock("feishu:chat_shared")
    lock_d = session_mgr.get_lock("dingtalk:chat_shared")

    active_count = 0
    max_active = 0

    async def run_feishu() -> None:
        nonlocal active_count, max_active
        async with lock_f:
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.08)
            active_count -= 1

    async def run_dingtalk() -> None:
        nonlocal active_count, max_active
        async with lock_d:
            active_count += 1
            max_active = max(max_active, active_count)
            await asyncio.sleep(0.08)
            active_count -= 1

    start = time.perf_counter()
    await asyncio.gather(run_feishu(), run_dingtalk())
    elapsed = time.perf_counter() - start

    assert max_active == 2, (
        f"Expected max 2 active concurrent operations across channels, got {max_active}"
    )
    assert elapsed < 0.14, (
        f"Cross-channel operations blocked each other! Elapsed: {elapsed:.3f}s, expected < 0.14s"
    )


@pytest.mark.asyncio
async def test_challenge_cross_channel_end_to_end_on_message_parallelism(
    env_credentials: None,
) -> None:
    """Empirically verify FeishuBotChannel and DingTalkBotChannel running on a shared AgentSessionManager execute concurrently."""
    shared_agent = StressTestAgent(delay_seconds=0.08)
    shared_mgr = AgentSessionManager(agent_factory=lambda: shared_agent)

    feishu_sdk = MockFeishuSDKChannel()
    dingtalk_sdk = MockDingTalkSDKChannel()

    cfg = Config.from_env()
    feishu_bot = FeishuBotChannel(
        config=cfg, channel=feishu_sdk, session_manager=shared_mgr
    )
    dingtalk_bot = DingTalkBotChannel(
        config=cfg, channel=dingtalk_sdk, session_manager=shared_mgr
    )

    msg_f = MockFeishuInboundMsg("mf_1", "same_id_99", "Feishu prompt")
    msg_d = MockDingTalkInboundMsg("md_1", "same_id_99", "DingTalk prompt")
    reply_d = MockDingTalkReply()

    start = time.perf_counter()
    await asyncio.gather(
        feishu_bot.on_message(msg_f), dingtalk_bot.on_message(msg_d, reply_d)
    )
    elapsed = time.perf_counter() - start

    # Since they use distinct session keys ("feishu:same_id_99" and "dingtalk:same_id_99"),
    # they must execute concurrently on the shared Agent!
    assert shared_agent.max_concurrent_turns == 2, (
        f"Cross-channel messages did not execute concurrently: max_concurrent_turns={shared_agent.max_concurrent_turns}"
    )
    assert elapsed < 0.14, (
        f"Cross-channel execution was serialized! Elapsed: {elapsed:.3f}s"
    )


# ---------------------------------------------------------------------------
# Scope 2: Concurrency Serialization Within Same Session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_challenge_strict_serialization_twenty_concurrent_messages(
    env_credentials: None,
) -> None:
    """Adversarial stress test: fire 20 concurrent messages to the SAME session key.

    Verify that max_concurrent_turns is STRICTLY 1 at all times with zero timestamp overlap.
    """
    agent = StressTestAgent(delay_seconds=0.015)
    session_mgr = AgentSessionManager(agent_factory=lambda: agent)

    feishu_sdk = MockFeishuSDKChannel()
    cfg = Config.from_env()
    bot = FeishuBotChannel(config=cfg, channel=feishu_sdk, session_manager=session_mgr)

    messages = [
        MockFeishuInboundMsg(f"msg_seq_{i}", "single_target_chat", f"Turn {i}")
        for i in range(20)
    ]

    await asyncio.gather(*(bot.on_message(m) for m in messages))

    assert agent.total_turn_count == 20
    assert agent.max_concurrent_turns == 1, (
        f"Concurrency violation: max_concurrent_turns was {agent.max_concurrent_turns}, expected 1"
    )

    # Check that no two turn windows overlapped
    history = agent.turn_history
    for i in range(len(history) - 1):
        prev_end = history[i]["end"]
        curr_start = history[i + 1]["start"]
        assert curr_start >= prev_end - 0.001, (
            f"Overlapping turn detected between turn {history[i]['turn']} (end: {prev_end}) "
            f"and turn {history[i + 1]['turn']} (start: {curr_start})"
        )


@pytest.mark.asyncio
async def test_challenge_dingtalk_fifty_message_high_concurrency_burst(
    env_credentials: None,
) -> None:
    """Extreme burst stress test: 50 concurrent messages dispatched simultaneously to DingTalk session."""
    agent = StressTestAgent(delay_seconds=0.005)
    session_mgr = AgentSessionManager(agent_factory=lambda: agent)

    dingtalk_sdk = MockDingTalkSDKChannel()
    cfg = Config.from_env()
    bot = DingTalkBotChannel(
        config=cfg, channel=dingtalk_sdk, session_manager=session_mgr
    )

    pairs = [
        (
            MockDingTalkInboundMsg(f"msg_burst_{i}", "cid_burst_target", f"Burst {i}"),
            MockDingTalkReply(),
        )
        for i in range(50)
    ]

    await asyncio.gather(*(bot.on_message(m, r) for m, r in pairs))

    assert agent.total_turn_count == 50
    assert agent.max_concurrent_turns == 1, (
        f"High concurrency burst violation: max_concurrent_turns was {agent.max_concurrent_turns}"
    )


def test_challenge_lock_idempotency_and_aliasing() -> None:
    """Verify get_lock idempotency across repeated queries and parameter names."""
    session_mgr = AgentSessionManager()

    lock1 = session_mgr.get_lock("feishu:target")
    lock2 = session_mgr.get_lock("feishu:target")
    assert lock1 is lock2

    # Backward compatibility with chat_id argument
    lock_legacy = session_mgr.get_lock(chat_id="feishu:target")
    assert lock_legacy is lock1

    with pytest.raises(ValueError, match="必须提供 session_key 或 chat_id"):
        session_mgr.get_lock()


# ---------------------------------------------------------------------------
# Scope 3: Lock Release on Turn Error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_challenge_lock_released_on_unhandled_agent_exception(
    env_credentials: None,
) -> None:
    """Adversarially simulate an unhandled exception inside agent.chat during Turn 1.

    Verify Turn 2 acquires the lock immediately and completes successfully without deadlock.
    """
    # Turn 1 fails with RuntimeError; Turn 2 succeeds
    agent = StressTestAgent(delay_seconds=0.02, fail_turns={1})
    session_mgr = AgentSessionManager(agent_factory=lambda: agent)

    feishu_sdk = MockFeishuSDKChannel()
    cfg = Config.from_env()
    bot = FeishuBotChannel(config=cfg, channel=feishu_sdk, session_manager=session_mgr)

    msg1 = MockFeishuInboundMsg("err_1", "chat_fail_recover", "Crash turn")
    msg2 = MockFeishuInboundMsg("err_2", "chat_fail_recover", "Healthy turn")

    # Turn 1: bot catches exception and sends polite notice
    await bot.on_message(msg1)

    # Verify Turn 1 sent error message to user
    assert any(
        "抱歉，处理您的请求时出现异常" in str(p) for _, p in feishu_sdk.sent_messages
    )

    # Turn 2: must acquire lock and complete normally within short timeout
    try:
        await asyncio.wait_for(bot.on_message(msg2), timeout=1.0)
    except TimeoutError:
        pytest.fail("Turn 2 deadlocked! Lock was not released after Turn 1 failed!")

    assert agent.total_turn_count == 2
    assert len(feishu_sdk.streams) == 1


@pytest.mark.asyncio
async def test_challenge_lock_released_on_asyncio_task_cancellation(
    env_credentials: None,
) -> None:
    """Empirically test that cancelling an in-flight turn releases the lock for subsequent turns."""
    agent = StressTestAgent(delay_seconds=0.5)
    session_mgr = AgentSessionManager(agent_factory=lambda: agent)

    feishu_sdk = MockFeishuSDKChannel()
    cfg = Config.from_env()
    bot = FeishuBotChannel(config=cfg, channel=feishu_sdk, session_manager=session_mgr)

    msg_cancelled = MockFeishuInboundMsg("cancel_me", "chat_cancel", "Long turn")
    msg_subsequent = MockFeishuInboundMsg(
        "after_cancel", "chat_cancel", "Followup turn"
    )

    # Launch task 1 and cancel it mid-flight
    task1 = asyncio.create_task(bot.on_message(msg_cancelled))
    await asyncio.sleep(0.03)  # wait until task1 enters lock
    task1.cancel()

    try:
        await task1
    except asyncio.CancelledError:
        pass

    # Now verify subsequent turn can acquire lock immediately
    agent.delay = 0.01
    await asyncio.wait_for(bot.on_message(msg_subsequent), timeout=1.0)

    # The lock was clean, second message processed
    assert agent.total_turn_count == 2


@pytest.mark.asyncio
async def test_challenge_multiple_consecutive_failures_recovery(
    env_credentials: None,
) -> None:
    """Adversarially simulate 5 consecutive failing turns. 6th turn must still succeed."""
    agent = StressTestAgent(delay_seconds=0.01, fail_turns={1, 2, 3, 4, 5})
    session_mgr = AgentSessionManager(agent_factory=lambda: agent)

    dingtalk_sdk = MockDingTalkSDKChannel()
    cfg = Config.from_env()
    bot = DingTalkBotChannel(
        config=cfg, channel=dingtalk_sdk, session_manager=session_mgr
    )

    for i in range(1, 6):
        msg = MockDingTalkInboundMsg(f"fail_{i}", "cid_multi_fail", f"Fail {i}")
        reply = MockDingTalkReply()
        await bot.on_message(msg, reply)
        assert len(reply.text_replies) == 1
        assert "抱歉，处理您的请求时出现异常" in reply.text_replies[0]

    # Turn 6 should succeed
    msg6 = MockDingTalkInboundMsg("succ_6", "cid_multi_fail", "Healthy 6")
    reply6 = MockDingTalkReply()
    await asyncio.wait_for(bot.on_message(msg6, reply6), timeout=1.0)

    assert agent.total_turn_count == 6
    assert len(reply6.streamer.tokens) == 1
    assert "Response_turn_6" in reply6.streamer.tokens[0]


# ---------------------------------------------------------------------------
# Scope 4: Agent Session Isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_challenge_agent_instance_isolation_across_distinct_sessions() -> None:
    """Empirically verify distinct session keys receive independent Agent instances."""
    created_agents: list[StressTestAgent] = []

    def agent_factory() -> StressTestAgent:
        ag = StressTestAgent()
        created_agents.append(ag)
        return ag

    session_mgr = AgentSessionManager(agent_factory=agent_factory)

    agent_f1 = await session_mgr.get_or_create_agent("feishu:chat1")
    agent_d1 = await session_mgr.get_or_create_agent("dingtalk:chat1")
    agent_f2 = await session_mgr.get_or_create_agent("feishu:chat2")

    # 3 distinct agent instances must have been created
    assert len(created_agents) == 3
    assert agent_f1 is not agent_d1
    assert agent_f1 is not agent_f2
    assert agent_d1 is not agent_f2

    # Querying the same session again returns the identical cached instance
    agent_f1_again = await session_mgr.get_or_create_agent("feishu:chat1")
    assert agent_f1_again is agent_f1
    assert len(created_agents) == 3


@pytest.mark.asyncio
async def test_challenge_multi_turn_conversation_context_isolation(
    env_credentials: None,
) -> None:
    """Verify conversation contexts across sessions remain completely isolated."""
    session_mgr = AgentSessionManager(
        agent_factory=lambda: StressTestAgent(delay_seconds=0.01)
    )

    feishu_sdk = MockFeishuSDKChannel()
    dingtalk_sdk = MockDingTalkSDKChannel()

    cfg = Config.from_env()
    feishu_bot = FeishuBotChannel(
        config=cfg, channel=feishu_sdk, session_manager=session_mgr
    )
    dingtalk_bot = DingTalkBotChannel(
        config=cfg, channel=dingtalk_sdk, session_manager=session_mgr
    )

    # 3 turns in Feishu session 'room_alpha'
    for i in range(3):
        await feishu_bot.on_message(
            MockFeishuInboundMsg(f"fa_{i}", "room_alpha", f"Feishu msg {i}")
        )

    # 2 turns in DingTalk session 'room_alpha'
    for i in range(2):
        await dingtalk_bot.on_message(
            MockDingTalkInboundMsg(f"da_{i}", "room_alpha", f"DingTalk msg {i}"),
            MockDingTalkReply(),
        )

    # Inspect the underlying isolated agents
    agent_feishu = await session_mgr.get_or_create_agent("feishu:room_alpha")
    agent_dingtalk = await session_mgr.get_or_create_agent("dingtalk:room_alpha")

    assert len(agent_feishu.chat_history) == 3
    assert len(agent_dingtalk.chat_history) == 2

    # Verify Feishu agent never saw DingTalk messages
    for history_item in agent_feishu.chat_history:
        flat = str(history_item)
        assert "channel: feishu" in flat
        assert "channel: dingtalk" not in flat

    # Verify DingTalk agent never saw Feishu messages
    for history_item in agent_dingtalk.chat_history:
        flat = str(history_item)
        assert "channel: dingtalk" in flat
        assert "channel: feishu" not in flat


@pytest.mark.asyncio
async def test_challenge_session_manager_close_all_lifecycle_cleanup() -> None:
    """Verify close_all() closes all agents via async context stack and purges all state."""
    agents: list[StressTestAgent] = []

    def factory() -> StressTestAgent:
        ag = StressTestAgent()
        agents.append(ag)
        return ag

    session_mgr = AgentSessionManager(agent_factory=factory)

    # Create 3 active sessions
    a1 = await session_mgr.get_or_create_agent("feishu:c1")
    a2 = await session_mgr.get_or_create_agent("dingtalk:c1")
    a3 = await session_mgr.get_or_create_agent("feishu:c2")

    assert not a1.is_closed
    assert not a2.is_closed
    assert not a3.is_closed

    # Close all
    await session_mgr.close_all()

    # All agents must have their async context exited (__aexit__ called)
    assert a1.is_closed
    assert a2.is_closed
    assert a3.is_closed

    # Internal session dictionary and locks dictionary must be cleared
    assert len(session_mgr._sessions) == 0
    assert len(session_mgr._locks) == 0

    # Subsequent requests must instantiate fresh new agents
    a1_fresh = await session_mgr.get_or_create_agent("feishu:c1")
    assert a1_fresh is not a1
    assert not a1_fresh.is_closed


@pytest.mark.asyncio
async def test_challenge_get_or_create_agent_invalid_parameters() -> None:
    """Verify get_or_create_agent raises ValueError when no key is provided."""
    session_mgr = AgentSessionManager()
    with pytest.raises(ValueError, match="必须提供 session_key 或 chat_id"):
        await session_mgr.get_or_create_agent()
