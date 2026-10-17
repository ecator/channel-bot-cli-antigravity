"""飞书消息通道向后兼容模块。

本模块保留以维护向后兼容性，所有实际实现已重构至 `channels.feishu` 与 `channels.base`。
"""

from .channels.feishu import FeishuBotChannel

__all__ = ["FeishuBotChannel"]
