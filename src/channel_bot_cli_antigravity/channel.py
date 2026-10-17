"""飞书消息通道模块，负责消息监听、多模态附件下载及主动消息发送。"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from lark_channel import (
    Events,
    FeishuChannel,
    FileContent,
    ImageContent,
    InboundMessage,
)
from lark_channel.core import LogLevel

from .agent import AgentSessionManager
from .config import Config
from .utils import create_media_from_bytes, format_iso_time

logger = logging.getLogger(__name__)


class FeishuBotChannel:
    """飞书机器人通道管理类。"""

    def __init__(
        self,
        config: Config,
        filter_chat_id: str | None = None,
        session_manager: AgentSessionManager | None = None,
        channel: FeishuChannel | None = None,
        work_dir: str | Path | None = None,
    ):
        self.config = config
        self.config.validate()

        self.filter_chat_id = filter_chat_id.strip() if filter_chat_id else None
        self.session_manager = session_manager or AgentSessionManager(
            work_dir=work_dir,
            model=self.config.agy_model,
            image_model=self.config.agy_image_model,
        )

        if channel:
            self.channel = channel
        else:
            log_level_map = {
                "DEBUG": LogLevel.DEBUG,
                "INFO": LogLevel.INFO,
                "WARNING": LogLevel.WARNING,
                "ERROR": LogLevel.ERROR,
            }
            sdk_log_level = log_level_map.get(
                self.config.log_level.upper(), LogLevel.INFO
            )
            self.channel = FeishuChannel(
                app_id=self.config.lark_app_id,
                app_secret=self.config.lark_app_secret,
                domain=self.config.lark_domain,
                log_level=sdk_log_level,
            )

    async def _download_inbound_files(self, msg: InboundMessage) -> list[Any]:
        """将消息中的所有文件/多媒体资源下载至内存，并转换为 Antigravity 多模态对象。"""
        media_items: list[Any] = []
        msg_id = msg.id

        # 1. 优先遍历 resources 列表
        resources = msg.resources or []
        for res in resources:
            try:
                data = await self.channel.download_resource(
                    file_key=res.file_key,
                    resource_type=res.type,
                    message_id=msg_id,
                )
                if data:
                    media_obj = create_media_from_bytes(
                        data=data,
                        file_name=res.file_name,
                        resource_type=res.type,
                    )
                    media_items.append(media_obj)
                    logger.info(
                        "成功下载附件到内存 | chat_id: %s | 类型: %s | 文件名: %s | 大小: %d 字节",
                        msg.chat_id,
                        res.type,
                        res.file_name or "未指定",
                        len(data),
                    )
                else:
                    logger.warning(
                        "下载附件失败 (返回空数据) | file_key: %s", res.file_key
                    )
            except Exception as e:
                logger.error("下载附件异常 | file_key: %s: %s", res.file_key, e)

        # 2. 如果 resources 未解析出资源，兜底检查 content 结构
        if not media_items:
            content = msg.content
            if isinstance(content, FileContent) and getattr(content, "file_key", None):
                try:
                    data = await self.channel.download_resource(
                        file_key=content.file_key,
                        resource_type="file",
                        message_id=msg_id,
                    )
                    if data:
                        media_items.append(
                            create_media_from_bytes(
                                data, content.file_name, "file"
                            )
                        )
                except Exception as e:
                    logger.error("兜底下载 FileContent 异常: %s", e)
            elif isinstance(content, ImageContent) and getattr(content, "image_key", None):
                try:
                    data = await self.channel.download_resource(
                        file_key=content.image_key,
                        resource_type="image",
                        message_id=msg_id,
                    )
                    if data:
                        media_items.append(
                            create_media_from_bytes(data, None, "image")
                        )
                except Exception as e:
                    logger.error("兜底下载 ImageContent 异常: %s", e)

        return media_items

    async def on_message(self, msg: InboundMessage) -> None:
        """处理飞书收到的消息。"""
        # 忽略机器人自身发送的消息，防止消息回环死循环
        if msg.sender_is_bot:
            return

        chat_id = msg.chat_id
        msg_id = msg.id

        # 如果配置了 filter_chat_id，则仅响应该指定的会话
        if self.filter_chat_id and chat_id != self.filter_chat_id:
            logger.debug(
                "跳过非目标会话消息 | 当前 chat_id: %s | 目标 chat_id: %s",
                chat_id,
                self.filter_chat_id,
            )
            return

        # 消息元数据
        message_metadata = {
            "from": "feishu",
            "chat_id": chat_id,
            "sender_id": msg.sender_id,
            "message_id": msg_id,
            "create_time": format_iso_time(msg.create_time),
            "chat_type": msg.chat_type,
        }

        # 提取用户文本
        prompt = (msg.content_text or "").strip()

        # 下载附件到内存中
        media_items = await self._download_inbound_files(msg)

        if not prompt and not media_items:
            logger.info("收到来自 %s 的空消息且无可用附件，跳过处理", msg.sender_id)
            return

        logger.info(
            "收到消息 | chat_id: %s | sender_id: %s | content_text: %s | media_items: %d",
            chat_id,
            msg.sender_name or msg.sender_id,
            prompt or "[无文本]",
            len(media_items),
        )

        # 组装给 Agent 的输入
        agent_input = [
            "---\n"
            + yaml.safe_dump(message_metadata, allow_unicode=True, sort_keys=False)
            + "---\n"
        ]
        if prompt:
            agent_input.append(prompt)
        if media_items:
            agent_input.extend(media_items)

        lock = self.session_manager.get_lock(chat_id)

        async with lock:
            typing_reaction_id = None
            try:
                # 提示用户 Agent 正在思考中
                if msg_id:
                    typing_reaction_id = await self.channel.add_typing_reaction(msg_id)

                # 获取常驻 Agent 并生成回复
                agent = await self.session_manager.get_or_create_agent(chat_id)
                response = await agent.chat(agent_input)

                tokens = []
                stream_succeeded = False

                # 尝试 CardKit 流式打字机卡片输出
                try:
                    async def producer(stream):
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
                    async for token in response:
                        tokens.append(token)
                    full_reply = "".join(tokens)
                    if not full_reply and hasattr(response, "text"):
                        full_reply = await response.text()

                    if full_reply:
                        try:
                            await self.channel.send(chat_id, {"markdown": full_reply})
                        except Exception:
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
                    await self.channel.remove_typing_reaction(
                        msg_id, typing_reaction_id
                    )

    async def start_listening(self) -> None:
        """启动飞书长连接监听服务。"""
        self.channel.on(Events.MESSAGE, self.on_message)

        try:
            filter_hint = f" (过滤会话: {self.filter_chat_id})" if self.filter_chat_id else ""
            logger.info("飞书机器人服务启动中，正在连接长连接网关%s...", filter_hint)
            await self.channel.connect()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        """关闭通道与释放所有资源。"""
        self.channel.stop()
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
        results = []

        # 归一化为文件路径列表
        paths: list[str] = []
        if file_paths:
            if isinstance(file_paths, str):
                paths.append(file_paths)
            else:
                paths.extend(file_paths)

        for fp in paths:
            if not os.path.exists(fp):
                raise FileNotFoundError(f"未找到待发送的文件: {fp}")

            with open(fp, "rb") as f:
                file_bytes = f.read()

            file_name = os.path.basename(fp)
            dot_index = file_name.rfind(".")
            ext = file_name[dot_index:].lower() if dot_index != -1 else ""

            # 判断是否为图片
            if ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
                # 仅在仅发送单张图片且附带 message 时，合并为图文消息
                if len(paths) == 1 and message:
                    logger.info("正在向 %s 发送带说明的图片文件: %s", chat_id, file_name)
                    res = await self.channel.send(
                        chat_id,
                        {"image": {"source": file_bytes}, "caption": message},
                    )
                    results.append(res)
                    message = None  # 图片已带 caption，无需重复发送单独的文本
                else:
                    logger.info("正在向 %s 发送图片文件: %s", chat_id, file_name)
                    res = await self.channel.send(
                        chat_id,
                        {"image": {"source": file_bytes}},
                    )
                    results.append(res)
            else:
                logger.info("正在向 %s 发送附件文件: %s", chat_id, file_name)
                res = await self.channel.send(
                    chat_id,
                    {"file": {"source": file_bytes, "file_name": file_name}},
                )
                results.append(res)

        # 发送附带的文本/Markdown 消息
        if message:
            logger.info("正在向 %s 发送消息: %s", chat_id, message)
            if message_type == "text":
                res = await self.channel.send(chat_id, {"text": message})
            else:
                res = await self.channel.send(chat_id, {"markdown": message})
            results.append(res)

        return results[0] if len(results) == 1 else results
