"""飞书消息通道适配器模块。

基于 lark-channel-sdk 实现 WebSocket 长连接监听、CardKit 流式打字机卡片回显、
打字中表情状态反馈、内存多模态附件处理与主动消息投递。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from lark_channel import (
    AudioContent,
    Events,
    FeishuChannel,
    FileContent,
    ImageContent,
    InboundMessage,
    MediaContent,
)
from lark_channel.core import LogLevel

from ..agent import AgentSessionManager
from ..config import Config
from ..utils import create_media_from_bytes
from .base import BaseBotChannel

logger = logging.getLogger(__name__)


class FeishuBotChannel(BaseBotChannel):
    """飞书机器人通道管理类。"""

    channel_name: str = "feishu"

    def __init__(
        self,
        config: Config,
        filter_chat_id: str | None = None,
        session_manager: AgentSessionManager | None = None,
        channel: FeishuChannel | None = None,
        work_dir: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            config=config,
            filter_chat_id=filter_chat_id,
            session_manager=session_manager,
            work_dir=work_dir,
        )

        if channel is not None:
            self.channel = channel
        else:
            if hasattr(self.config, "validate_channel"):
                self.config.validate_channel("feishu")

            app_id = (
                getattr(self.config, "feishu_app_id", None)
                or getattr(self.config, "lark_app_id", "")
                or os.getenv("FEISHU_APP_ID", "")
                or os.getenv("LARK_APP_ID", "")
            ).strip()
            app_secret = (
                getattr(self.config, "feishu_app_secret", None)
                or getattr(self.config, "lark_app_secret", "")
                or os.getenv("FEISHU_APP_SECRET", "")
                or os.getenv("LARK_APP_SECRET", "")
            ).strip()
            domain = getattr(self.config, "feishu_domain", None) or getattr(
                self.config, "lark_domain", None
            )

            if not app_id or not app_secret:
                raise ValueError(
                    "请在环境变量或 .env 中配置 FEISHU_APP_ID (或 LARK_APP_ID) 与 FEISHU_APP_SECRET (或 LARK_APP_SECRET)"
                )

            log_level_map = {
                "DEBUG": LogLevel.DEBUG,
                "INFO": LogLevel.INFO,
                "WARNING": LogLevel.WARNING,
                "ERROR": LogLevel.ERROR,
            }
            sdk_log_level = log_level_map.get(
                getattr(self.config, "log_level", "INFO").upper(), LogLevel.INFO
            )
            self.channel = FeishuChannel(
                app_id=app_id,
                app_secret=app_secret,
                domain=domain,
                log_level=sdk_log_level,
            )

    async def _download_inbound_files(self, msg: InboundMessage) -> list[Any]:
        """将消息中的所有文件/多媒体资源下载至内存，并转换为 Antigravity 多模态对象。"""
        media_items: list[Any] = []
        msg_id = getattr(msg, "id", None)

        # 1. 优先遍历 resources 列表
        resources = getattr(msg, "resources", None) or []
        for res in resources:
            file_key = getattr(res, "file_key", None)
            res_type = getattr(res, "type", "file")
            file_name = getattr(res, "file_name", None)

            if not file_key:
                continue

            try:
                data = await self.channel.download_resource(
                    file_key=file_key,
                    resource_type=res_type,
                    message_id=msg_id,
                )
                if data:
                    media_obj = create_media_from_bytes(
                        data=data,
                        file_name=file_name,
                        resource_type=res_type,
                    )
                    media_items.append(media_obj)
                    logger.info(
                        "成功下载附件到内存 | chat_id: %s | 类型: %s | 文件名: %s | 大小: %d 字节",
                        getattr(msg, "chat_id", ""),
                        res_type,
                        file_name or "未指定",
                        len(data),
                    )
                else:
                    logger.warning("下载附件失败 (返回空数据) | file_key: %s", file_key)
            except Exception as e:
                logger.error("下载附件异常 | file_key: %s: %s", file_key, e)

        # 2. 如果 resources 未解析出资源，兜底检查 content 结构
        if not media_items:
            content = getattr(msg, "content", None)
            if isinstance(content, FileContent) and getattr(content, "file_key", None):
                try:
                    data = await self.channel.download_resource(
                        file_key=content.file_key,
                        resource_type="file",
                        message_id=msg_id,
                    )
                    if data:
                        media_items.append(
                            create_media_from_bytes(data, content.file_name, "file")
                        )
                except Exception as e:
                    logger.error("兜底下载 FileContent 异常: %s", e)
            elif isinstance(content, ImageContent) and getattr(
                content, "image_key", None
            ):
                try:
                    data = await self.channel.download_resource(
                        file_key=content.image_key,
                        resource_type="image",
                        message_id=msg_id,
                    )
                    if data:
                        media_items.append(create_media_from_bytes(data, None, "image"))
                except Exception as e:
                    logger.error("兜底下载 ImageContent 异常: %s", e)
            elif isinstance(content, AudioContent) and getattr(
                content, "file_key", None
            ):
                try:
                    data = await self.channel.download_resource(
                        file_key=content.file_key,
                        resource_type="audio",
                        message_id=msg_id,
                    )
                    if data:
                        media_items.append(
                            create_media_from_bytes(
                                data, getattr(content, "file_name", None), "audio"
                            )
                        )
                except Exception as e:
                    logger.error("兜底下载 AudioContent 异常: %s", e)
            elif isinstance(content, MediaContent) and getattr(
                content, "file_key", None
            ):
                try:
                    data = await self.channel.download_resource(
                        file_key=content.file_key,
                        resource_type="video",
                        message_id=msg_id,
                    )
                    if data:
                        media_items.append(
                            create_media_from_bytes(
                                data, getattr(content, "file_name", None), "video"
                            )
                        )
                except Exception as e:
                    logger.error("兜底下载 MediaContent 异常: %s", e)

        return media_items

    async def on_message(self, msg: InboundMessage) -> None:
        """处理飞书收到的消息。"""
        # 忽略机器人自身发送的消息，防止消息回环死循环
        if getattr(msg, "sender_is_bot", False):
            return

        chat_id = getattr(msg, "chat_id", "")
        msg_id = getattr(msg, "message_id", None) or getattr(msg, "id", "")

        # 如果配置了 filter_chat_id，则仅响应该指定的会话
        if self.should_filter_chat(chat_id):
            return

        # 提取用户文本
        prompt = (getattr(msg, "content_text", None) or "").strip()

        # 下载附件到内存中
        media_items = await self._download_inbound_files(msg)

        if not prompt and not media_items:
            logger.info(
                "收到来自 %s 的空消息且无可用附件，跳过处理",
                getattr(msg, "sender_id", ""),
            )
            return

        logger.info(
            "收到消息 | chat_id: %s | sender_id: %s | content_text: %s | media_items: %d",
            chat_id,
            getattr(msg, "sender_name", None) or getattr(msg, "sender_id", ""),
            prompt or "[无文本]",
            len(media_items),
        )

        # 通过 BaseBotChannel 统一生成 YAML Frontmatter
        frontmatter = self.build_frontmatter(
            chat_id=chat_id,
            sender_id=getattr(msg, "sender_id", ""),
            message_id=msg_id,
            create_time=getattr(msg, "create_time", None),
            chat_type=getattr(msg, "chat_type", "p2p"),
        )

        # 组装给 Agent 的输入
        agent_input: list[Any] = [frontmatter]
        if prompt:
            agent_input.append(prompt)
        if media_items:
            agent_input.extend(media_items)

        # 使用基于 channel:chat_id 的隔离锁
        session_key = self.get_session_key(chat_id)
        lock = self.session_manager.get_lock(session_key)

        async with lock:
            typing_reaction_id = None
            try:
                # 提示用户 Agent 正在思考中 (防崩容错)
                if msg_id:
                    try:
                        typing_reaction_id = await self.channel.add_typing_reaction(
                            msg_id
                        )
                    except Exception as reaction_err:
                        logger.debug("添加打字中表情失败 (已忽略): %s", reaction_err)

                # 获取常驻 Agent 并生成回复
                agent = await self.session_manager.get_or_create_agent(session_key)
                response = await agent.chat(agent_input)

                tokens: list[str] = []
                stream_succeeded = False

                # 尝试 CardKit 流式打字机卡片输出
                try:

                    async def producer(stream: Any) -> None:
                        async for token in response:
                            tokens.append(token)
                            await stream.append(token)

                    await self.channel.stream(chat_id, {"markdown": producer})
                    stream_succeeded = True
                except Exception as stream_err:
                    logger.warning(
                        "流式输出未生效 (%s)，自动降级为标准消息发送。"
                        "提示：如需打字机卡片流式输出，请在飞书开放平台申请 [cardkit:card:write] 权限。",
                        stream_err,
                    )

                # 降级发送完整消息
                if not stream_succeeded:
                    full_reply = ""
                    if hasattr(response, "text"):
                        try:
                            full_reply = await response.text()
                        except Exception as text_err:
                            logger.debug(
                                "通过 response.text() 获取完整回复异常: %s", text_err
                            )
                            full_reply = ""

                    if not full_reply:
                        tokens.clear()
                        async for token in response:
                            tokens.append(token)
                        full_reply = "".join(tokens)

                    if full_reply:
                        try:
                            await self.channel.send(chat_id, {"markdown": full_reply})
                        except Exception as md_err:
                            logger.warning(
                                "Markdown 发送失败 (%s)，降级为纯文本...", md_err
                            )
                            await self.channel.send(chat_id, {"text": full_reply})

                logger.info("回复完成 | chat_id: %s", chat_id)

            except Exception as e:
                logger.error("Agent 处理出错: %s", e, exc_info=True)
                try:
                    await self.channel.send(
                        chat_id, {"text": f"抱歉，处理您的请求时出现异常: {e}"}
                    )
                except Exception as send_err:
                    logger.error("发送错误提示失败: %s", send_err)
            finally:
                if typing_reaction_id and msg_id:
                    try:
                        await self.channel.remove_typing_reaction(
                            msg_id, typing_reaction_id
                        )
                    except Exception as remove_err:
                        logger.debug("移除打字中表情失败 (已忽略): %s", remove_err)

    async def start_listening(self) -> None:
        """启动飞书长连接监听服务。"""
        self.channel.on(Events.MESSAGE, self.on_message)

        try:
            filter_hint = (
                f" (过滤会话: {self.filter_chat_id})" if self.filter_chat_id else ""
            )
            logger.info("飞书机器人服务启动中，正在连接长连接网关%s...", filter_hint)
            await self.channel.connect()
        except asyncio.CancelledError, KeyboardInterrupt:
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        """关闭通道与释放所有资源。"""
        try:
            self.channel.stop()
        except Exception as err:
            logger.debug("停止飞书连接异常 (已忽略): %s", err)

        if hasattr(self.session_manager, "close_all"):
            await self.session_manager.close_all()

        logger.info("飞书机器人已安全断开并退出。")

    async def send_message(
        self,
        chat_id: str,
        message: str | None = None,
        file_paths: list[str] | str | None = None,
        message_type: str = "markdown",
    ) -> Any:
        """主动向飞书会话发送消息或多个文件 (支持文件与文本组合发送)。"""
        target_id = chat_id.strip()
        if target_id.startswith(f"{self.channel_name}:"):
            target_id = target_id[len(self.channel_name) + 1 :]

        results: list[Any] = []
        valid_paths = self.validate_file_paths(file_paths)
        paths = [str(p) for p in valid_paths]

        for fp in paths:
            with open(fp, "rb") as f:
                file_bytes = f.read()

            file_name = os.path.basename(fp)
            dot_index = file_name.rfind(".")
            ext = file_name[dot_index:].lower() if dot_index != -1 else ""

            # 判断是否为图片
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
                # 仅在发送单张图片且附带 message 时，合并为图文消息
                if len(paths) == 1 and message:
                    logger.info(
                        "正在向 %s 发送带说明的图片文件: %s", target_id, file_name
                    )
                    res = await self.channel.send(
                        target_id,
                        {"image": {"source": file_bytes}, "caption": message},
                    )
                    results.append(res)
                    message = None  # 图片已带 caption，无需重复发送单独的文本
                else:
                    logger.info("正在向 %s 发送图片文件: %s", target_id, file_name)
                    res = await self.channel.send(
                        target_id,
                        {"image": {"source": file_bytes}},
                    )
                    results.append(res)
            else:
                logger.info("正在向 %s 发送附件文件: %s", target_id, file_name)
                res = await self.channel.send(
                    target_id,
                    {"file": {"source": file_bytes, "file_name": file_name}},
                )
                results.append(res)

        # 发送附带的文本/Markdown 消息
        if message:
            logger.info("正在向 %s 发送消息: %s", target_id, message)
            if message_type == "text":
                res = await self.channel.send(target_id, {"text": message})
            else:
                res = await self.channel.send(target_id, {"markdown": message})
            results.append(res)

        return results[0] if len(results) == 1 else results
