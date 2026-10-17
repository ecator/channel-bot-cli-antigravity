"""基于 Google Antigravity SDK 的多渠道企业级 IM 智能助手与服务网关。"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("channel-bot-cli-antigravity")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

from .agent import AgentSessionManager
from .channels import (
    BaseBotChannel,
    DingTalkBotChannel,
    FeishuBotChannel,
    get_channel,
)
from .config import Config, get_config
from .utils import create_media_from_bytes, setup_logging

__all__ = [
    "AgentSessionManager",
    "BaseBotChannel",
    "Config",
    "DingTalkBotChannel",
    "FeishuBotChannel",
    "__version__",
    "create_media_from_bytes",
    "get_channel",
    "get_config",
    "setup_logging",
]
