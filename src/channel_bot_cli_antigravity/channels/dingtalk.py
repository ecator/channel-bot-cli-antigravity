"""钉钉消息通道适配器模块，基于 dingtalk-channel-sdk 实现。

支持 WebSocket Stream 长连接监听、AI 卡片打字机流式回显、多模态附件内存流转与主动消息投递。
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

from dingtalk_channel_sdk import (
    DingTalkChannel,
    IncomingMessage,
    Reply,
    SendTarget,
)

from ..agent import AgentSessionManager
from ..config import Config
from ..utils import create_media_from_bytes
from .base import BaseBotChannel

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _first_line_title(text: str) -> str:
    """提取 Markdown 文本首行有意义字符作为通知卡片标题。"""
    for line in str(text or "").split("\n"):
        t = line.lstrip("#*-> \t")
        if t:
            return t[:20]
    return "通知"


class DingTalkBotChannel(BaseBotChannel):
    """钉钉机器人通道管理类，继承自 BaseBotChannel。"""

    channel_name: str = "dingtalk"

    def __init__(
        self,
        config: Config,
        filter_chat_id: str | None = None,
        session_manager: AgentSessionManager | None = None,
        work_dir: str | Path | None = None,
        channel: DingTalkChannel | None = None,
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
            # 校验钉钉凭据
            if hasattr(self.config, "validate_channel"):
                self.config.validate_channel("dingtalk")

            client_id = (
                getattr(self.config, "dd_client_id", None)
                or os.getenv("DD_CLIENT_ID", "")
            ).strip()
            client_secret = (
                getattr(self.config, "dd_client_secret", None)
                or os.getenv("DD_CLIENT_SECRET", "")
            ).strip()

            if not client_id or not client_secret:
                raise ValueError(
                    "请在环境变量或 .env 中配置 DD_CLIENT_ID 与 DD_CLIENT_SECRET"
                )

            self.channel = DingTalkChannel(
                client_id=client_id,
                client_secret=client_secret,
            )

    async def _download_inbound_files(
        self, msg: IncomingMessage, reply: Reply
    ) -> list[Any]:
        """将消息中的所有附件资源换取下载链接并拉取至内存，转为 Antigravity Media 对象。"""
        media_items: list[Any] = []
        resources = getattr(msg, "resources", None) or []
        msg_id = getattr(msg, "msg_id", "")

        for res in resources:
            if isinstance(res, dict):
                code = res.get("downloadCode")
                file_name = res.get("fileName")
                res_type = res.get("type", "file")
            else:
                code = getattr(res, "downloadCode", None)
                file_name = getattr(res, "fileName", None)
                res_type = getattr(res, "type", "file")

            if not code:
                continue

            try:
                download_url = await reply.download_url(code, msg_id)
                if not download_url:
                    logger.warning("换取附件下载链接失败 | downloadCode: %s", code)
                    continue

                raw_bytes = await self.channel.download_file(download_url)
                if raw_bytes:
                    media_obj = create_media_from_bytes(
                        data=raw_bytes,
                        file_name=file_name,
                        resource_type=res_type,
                    )
                    media_items.append(media_obj)
                    logger.info(
                        "成功下载钉钉附件到内存 | conversation_id: %s | 类型: %s | 文件名: %s | 大小: %d 字节",
                        getattr(msg, "conversation_id", ""),
                        res_type,
                        file_name or "未命名",
                        len(raw_bytes),
                    )
                else:
                    logger.warning("下载钉钉附件返回空数据 | downloadCode: %s", code)
            except Exception as e:
                logger.error("下载钉钉附件异常 | downloadCode: %s: %s", code, e)

        return media_items

    async def on_message(self, msg: IncomingMessage, reply: Reply) -> None:
        """处理钉钉入站消息核心事件。"""
        conversation_id = getattr(msg, "conversation_id", "")
        msg_id = getattr(msg, "msg_id", "")

        # 1. 过滤非目标会话
        if self.should_filter_chat(conversation_id):
            return

        # 2. 提取文本与下载内存附件
        prompt = (getattr(msg, "text", None) or "").strip()
        media_items = await self._download_inbound_files(msg, reply)

        if not prompt and not media_items:
            logger.info(
                "收到来自 %s 的空消息且无可用附件，跳过处理",
                getattr(msg, "sender_id", ""),
            )
            return

        sender_display = (
            getattr(msg, "sender_nick", None)
            or getattr(msg, "sender_staff_id", None)
            or getattr(msg, "sender_id", "")
        )
        logger.info(
            "收到钉钉消息 | conversation_id: %s | sender: %s | prompt: %s | attachments: %d",
            conversation_id,
            sender_display,
            prompt or "[无文本]",
            len(media_items),
        )

        # 3. 构造统一 YAML Frontmatter 元数据
        conv_type = getattr(msg, "conversation_type", "group")
        chat_type = "p2p" if conv_type in ("dm", "p2p", "1") else "group"
        frontmatter = self.build_frontmatter(
            chat_id=conversation_id,
            sender_id=getattr(msg, "sender_staff_id", None)
            or getattr(msg, "sender_id", ""),
            message_id=msg_id,
            create_time=getattr(msg, "create_at", None),
            chat_type=chat_type,
        )

        agent_input: list[Any] = [frontmatter]
        if prompt:
            agent_input.append(prompt)
        if media_items:
            agent_input.extend(media_items)

        # 4. 获取按 f"dingtalk:{conversation_id}" 隔离的并发锁与 Agent 实例
        session_key = self.get_session_key(conversation_id)
        lock = self.session_manager.get_lock(session_key)

        async with lock:
            # 5. 提示用户思考中状态
            try:
                if conversation_id and msg_id:
                    await self.channel.mark_thinking(conversation_id, msg_id)
            except Exception as e:
                logger.debug("设置 Thinking 状态失败 (忽略): %s", e)

            try:
                agent = await self.session_manager.get_or_create_agent(session_key)
                response = await agent.chat(agent_input)

                tokens: list[str] = []
                stream_succeeded = False

                # 6. AI 卡片打字机流式回显
                streamer = None
                try:
                    streamer = await reply.stream()
                    async for token in response:
                        tokens.append(token)
                        await streamer.append(token)
                    full_text = "".join(tokens)
                    await streamer.finish(full_text)
                    stream_succeeded = True
                except Exception as stream_err:
                    logger.warning(
                        "AI 卡片流式输出异常 (%s)，降级为 Markdown/文本回复", stream_err
                    )
                    # 终止卡片流式状态并回显错误，避免用户一直看到“回复中”
                    if streamer is not None:
                        partial_text = "".join(tokens)
                        error_text = f"⚠️ 流式输出异常: {stream_err}"
                        finish_text = (
                            f"{partial_text}\n\n{error_text}"
                            if partial_text
                            else error_text
                        )
                        try:
                            await streamer.finish(finish_text)
                        except Exception as finish_err:
                            logger.debug(
                                "流式异常后终止卡片失败 (忽略): %s", finish_err
                            )

                # 7. 优雅降级补发
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
                            await reply.markdown(
                                title=_first_line_title(full_reply), text=full_reply
                            )
                        except Exception as md_err:
                            logger.warning(
                                "Markdown 降级发送失败 (%s)，降级为纯文本", md_err
                            )
                            try:
                                await reply.text(full_reply)
                            except Exception as txt_err:
                                logger.error("纯文本降级发送失败: %s", txt_err)

                logger.info("钉钉消息回复完成 | conversation_id: %s", conversation_id)

            except Exception as e:
                logger.error("钉钉 Agent 处理出错: %s", e, exc_info=True)
                try:
                    await reply.text(f"抱歉，处理您的请求时出现异常: {e}")
                except Exception as reply_err:
                    logger.error("发送错误提示失败: %s", reply_err)
            finally:
                # 8. 收尾标记完成状态
                try:
                    if conversation_id and msg_id:
                        await self.channel.mark_done(conversation_id, msg_id)
                except Exception as e:
                    logger.debug("设置 Done 状态失败 (忽略): %s", e)

    async def start_listening(self) -> None:
        """启动钉钉 Stream 长连接监听服务。"""
        self.channel.on_message(self.on_message)

        try:
            filter_hint = (
                f" (过滤会话: {self.filter_chat_id})" if self.filter_chat_id else ""
            )
            logger.info(
                "钉钉机器人服务启动中，正在建立 Stream 长连接网关%s...", filter_hint
            )
            await self.channel.start()
        except asyncio.CancelledError, KeyboardInterrupt:
            pass
        finally:
            await self.close()

    async def close(self) -> None:
        """关闭钉钉通道连接并释放所有会话资源。"""
        try:
            self.channel.close()
        except Exception as err:
            logger.debug("关闭钉钉连接异常 (忽略): %s", err)

        if hasattr(self.session_manager, "close_all"):
            await self.session_manager.close_all()

        logger.info("钉钉机器人已安全断开并退出。")

    def _resolve_send_target(self, chat_id: str) -> SendTarget:
        """根据 chat_id 规则解析 SendTarget（群聊 openConversationId vs 单聊 userId）。"""
        cid = chat_id.strip()
        if cid.startswith(f"{self.channel_name}:"):
            cid = cid[len(self.channel_name) + 1 :]
        if cid.startswith(("cid", "chat")):
            return SendTarget(conversation_id=cid)
        return SendTarget(user_id=cid)

    async def send_message(
        self,
        chat_id: str,
        message: str | None = None,
        file_paths: list[str] | str | None = None,
        message_type: str = "markdown",
    ) -> Any:
        """主动向指定钉钉会话发送消息或文件。"""
        target = self._resolve_send_target(chat_id)
        results: list[Any] = []

        valid_paths = self.validate_file_paths(file_paths)
        paths = [str(p) for p in valid_paths]

        # 1. 发送文件与图片
        for fp in paths:
            with open(fp, "rb") as f:
                file_bytes = f.read()

            file_name = os.path.basename(fp)
            dot_index = file_name.rfind(".")
            ext = file_name[dot_index:].lower() if dot_index != -1 else ""

            if ext in IMAGE_EXTENSIONS:
                logger.info("正在上传图片并发送至 %s: %s", chat_id, file_name)
                content_type, _ = mimetypes.guess_type(file_name)
                upload_res = await self.channel.oapi.upload_media(
                    media_type="image",
                    filename=file_name,
                    data=file_bytes,
                    content_type=content_type or "image/jpeg",
                )
                media_id = (
                    upload_res.get("mediaId", "")
                    if isinstance(upload_res, dict)
                    else getattr(upload_res, "mediaId", "")
                )
                download_url = (
                    upload_res.get("downloadUrl", "")
                    if isinstance(upload_res, dict)
                    else getattr(upload_res, "downloadUrl", "")
                )
                if media_id:
                    photo_ref = media_id if media_id.startswith("@") else f"@{media_id}"
                else:
                    photo_ref = download_url
                res = await self.channel.send_image(target, photo_ref)
                results.append(
                    res or {"status": "ok", "type": "image", "file": file_name}
                )
            else:
                logger.info("正在上传附件并以链接形式发送至 %s: %s", chat_id, file_name)
                upload_res = await self.channel.oapi.upload_media(
                    media_type="file",
                    filename=file_name,
                    data=file_bytes,
                )
                download_url = (
                    upload_res.get("downloadUrl", "")
                    if isinstance(upload_res, dict)
                    else getattr(upload_res, "downloadUrl", "")
                )
                md_link = f"📎 **文件**：[{file_name}]({download_url}) ({len(file_bytes)} 字节)"
                res = await self.channel.send_markdown(
                    target,
                    title=file_name,
                    text=md_link,
                )
                results.append(
                    res or {"status": "ok", "type": "file", "file": file_name}
                )

        # 2. 发送附带的文本或 Markdown 消息
        if message:
            logger.info(
                "正在向 %s 发送 %s 消息: %s", chat_id, message_type, message[:60]
            )
            if message_type == "text":
                res = await self.channel.send_text(target, message)
            else:
                res = await self.channel.send_markdown(
                    target,
                    title=_first_line_title(message),
                    text=message,
                )
            results.append(res or {"status": "ok", "type": message_type})

        return results[0] if len(results) == 1 else results
