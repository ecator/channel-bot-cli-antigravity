"""通道抽象基类与通用数据规范模块。"""

from __future__ import annotations

import abc
import logging
from pathlib import Path
from typing import Any

import yaml

from ..agent import AgentSessionManager
from ..config import Config
from ..utils import format_iso_time

logger = logging.getLogger(__name__)


class BaseBotChannel(abc.ABC):
    """企业 IM 机器人通道通用抽象基类。

    规范所有即时通讯平台通道的生命周期管理、会话隔离与统一消息规范。
    具体平台适配器（如 FeishuBotChannel、DingTalkBotChannel）必须继承此类并实现抽象方法。
    """

    channel_name: str = "base"

    def __init__(
        self,
        config: Config,
        filter_chat_id: str | None = None,
        session_manager: AgentSessionManager | None = None,
        work_dir: str | Path | None = None,
    ) -> None:
        """初始化通道基类。

        Args:
            config: 全局配置对象。
            filter_chat_id: 可选的会话过滤 ID。若指定，则仅响应该会话的消息。
            session_manager: 可选的 Agent 会话管理器。未传入时将自动根据配置初始化。
            work_dir: 可选的工作目录路径。
        """
        self.config = config
        self.filter_chat_id = filter_chat_id.strip() if filter_chat_id else None
        self.work_dir = Path(work_dir) if work_dir else None

        self._owns_session_manager = session_manager is None
        self.session_manager = session_manager or AgentSessionManager(
            work_dir=self.work_dir,
            model=getattr(self.config, "agy_model", None),
            image_model=getattr(self.config, "agy_image_model", None),
        )

    def get_session_key(self, chat_id: str) -> str:
        """获取带渠道前缀的隔离会话键。

        格式规范: {channel_name}:{chat_id}
        例如: feishu:oc_12345 或 dingtalk:cid_67890
        若传入键已包含当前渠道前缀，则直接返回以避免重复前缀。
        """
        prefix = f"{self.channel_name}:"
        if chat_id.startswith(prefix):
            return chat_id
        return f"{prefix}{chat_id}"

    def build_frontmatter(
        self,
        chat_id: str,
        sender_id: str,
        message_id: str,
        create_time: float | str | None,
        chat_type: str,
        channel: str | None = None,
    ) -> str:
        """格式化统一的 YAML Frontmatter 元数据块。

        元数据包含:
        - channel: 渠道标识 (如 feishu / dingtalk)
        - chat_id: 会话标识
        - sender_id: 发送者标识
        - message_id: 消息唯一标识
        - create_time: ISO 8601 格式的时间戳
        - chat_type: 会话类型 ("p2p" 或 "group")

        Returns:
            标准 YAML Frontmatter 字符串，以 "---\n" 开头并以 "---\n" 结尾。
        """
        raw_type = str(chat_type or "").lower().strip()
        normalized_chat_type = (
            "p2p" if raw_type in ("p2p", "dm", "1", "single") else "group"
        )

        metadata = {
            "channel": channel or self.channel_name,
            "chat_id": str(chat_id or ""),
            "sender_id": str(sender_id or ""),
            "message_id": str(message_id or ""),
            "create_time": format_iso_time(create_time),
            "chat_type": normalized_chat_type,
        }
        yaml_content = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
        return f"---\n{yaml_content}---\n"

    def should_filter_chat(self, chat_id: str) -> bool:
        """检查当前会话是否应被过滤忽略。"""
        if self.filter_chat_id and chat_id != self.filter_chat_id:
            logger.debug(
                "跳过非目标会话消息 | channel: %s | 当前 chat_id: %s | 目标 filter_chat_id: %s",
                self.channel_name,
                chat_id,
                self.filter_chat_id,
            )
            return True
        return False

    @staticmethod
    def normalize_file_paths(file_paths: list[str] | str | None) -> list[str]:
        """将文件路径输入归一化为纯字符串列表。"""
        if not file_paths:
            return []
        if isinstance(file_paths, (str, Path)):
            return [str(file_paths)]
        return [str(p) for p in file_paths if p]

    @classmethod
    def validate_file_paths(cls, file_paths: list[str] | str | None) -> list[Path]:
        """归一化并校验文件路径是否存在，若不存在则抛出 FileNotFoundError。"""
        raw_paths = cls.normalize_file_paths(file_paths)
        valid_paths: list[Path] = []
        for p in raw_paths:
            path_obj = Path(p)
            if not path_obj.is_file():
                raise FileNotFoundError(f"未找到待发送的文件: {p}")
            valid_paths.append(path_obj)
        return valid_paths

    @abc.abstractmethod
    async def start_listening(self) -> None:
        """启动长连接监听服务并处理消息。"""
        raise NotImplementedError

    @abc.abstractmethod
    async def close(self) -> None:
        """关闭通道连接并释放所有相关资源。"""
        raise NotImplementedError

    @abc.abstractmethod
    async def send_message(
        self,
        chat_id: str,
        message: str | None = None,
        file_paths: list[str] | str | None = None,
        message_type: str = "markdown",
    ) -> Any:
        """主动向指定会话发送消息或附件。

        Args:
            chat_id: 目标会话 ID (单聊用户 ID 或群聊会话 ID)。
            message: 可选。文本或 Markdown 格式的消息内容。
            file_paths: 可选。本地文件路径或文件路径列表。
            message_type: 消息类型，默认为 "markdown"，支持 "markdown" 或 "text"。

        Returns:
            发送结果 (平台特定的消息对象或结果列表)。
        """
        raise NotImplementedError
