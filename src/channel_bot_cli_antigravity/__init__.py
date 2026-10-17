"""feishu-bot-cli-antigravity package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("feishu-bot-cli-antigravity")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

from .agent import AgentSessionManager
from .channel import FeishuBotChannel
from .config import Config, get_config
from .utils import create_media_from_bytes, setup_logging

__all__ = [
    "AgentSessionManager",
    "Config",
    "FeishuBotChannel",
    "__version__",
    "create_media_from_bytes",
    "get_config",
    "setup_logging",
]

