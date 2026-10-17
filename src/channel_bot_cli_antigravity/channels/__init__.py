"""通道抽象与平台适配层。

提供 BaseBotChannel 通用抽象基类、FeishuBotChannel、DingTalkBotChannel 适配器及 get_channel 工厂函数。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import BaseBotChannel
from .dingtalk import DingTalkBotChannel
from .feishu import FeishuBotChannel

if TYPE_CHECKING:
    from ..agent import AgentSessionManager
    from ..config import Config

SUPPORTED_CHANNELS = ("dingtalk", "feishu")


def get_channel(
    channel_name: str,
    config: Config,
    filter_chat_id: str | None = None,
    session_manager: AgentSessionManager | None = None,
    work_dir: str | Path | None = None,
    **kwargs: Any,
) -> BaseBotChannel:
    """根据通道标识获取对应的机器人通道实例。

    Args:
        channel_name: 通道名称，支持 "feishu" (别名 "lark") 与 "dingtalk" (别名 "dd")。
        config: 全局配置对象 (包含凭据与模型配置)。
        filter_chat_id: 可选的会话过滤 ID。
        session_manager: 可选的共享 AgentSessionManager 实例。
        work_dir: 可选的工作目录路径。
        **kwargs: 透传给具体通道构造函数的其他参数 (例如 channel mock 实例)。

    Returns:
        BaseBotChannel 的具体子类实例 (FeishuBotChannel 或 DingTalkBotChannel)。

    Raises:
        ValueError: 当 channel_name 不受支持或为 "all" 时抛出。
    """
    normalized = (channel_name or "").strip().lower()

    if normalized == "all":
        raise ValueError(
            "通道 'all' 表示同时运行飞书与钉钉多通道，请分别调用 get_channel 实例化具体通道或使用双通道调度逻辑。"
        )

    if normalized in ("feishu", "lark"):
        return FeishuBotChannel(
            config=config,
            filter_chat_id=filter_chat_id,
            session_manager=session_manager,
            work_dir=work_dir,
            **kwargs,
        )

    if normalized in ("dingtalk", "dd"):
        return DingTalkBotChannel(
            config=config,
            filter_chat_id=filter_chat_id,
            session_manager=session_manager,
            work_dir=work_dir,
            **kwargs,
        )

    raise ValueError(
        f"不支持的通道类型: {channel_name!r}。当前仅支持 {SUPPORTED_CHANNELS} (别名: 'lark' / 'dd')。"
    )


__all__ = [
    "SUPPORTED_CHANNELS",
    "BaseBotChannel",
    "DingTalkBotChannel",
    "FeishuBotChannel",
    "get_channel",
]
