"""CLI 命令行入口与服务启动调度模块。

支持通过命令行参数进行主动消息发送 (send)，以及启动长连接网关监听 (listen/serve)。
提供飞书 (Feishu) 与钉钉 (DingTalk) 双渠道支持与自动推断，以及管道输入 (stdin) 与多文件附件发送。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
from pathlib import Path

from . import __version__
from .agent import AgentSessionManager
from .channels import DingTalkBotChannel, FeishuBotChannel, get_channel
from .config import Config, load_env_file
from .utils import setup_logging

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="基于 Antigravity SDK 的企业级多渠道 (飞书 / 钉钉) IM 智能助手与服务网关",
    )
    parser.add_argument(
        "--work-dir",
        "-w",
        dest="work_dir",
        default=None,
        help="工作目录路径 (默认: 当前路径，影响 .env、mcp、skills 与 AGENTS.md 的加载)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志输出级别 (覆盖环境变量 LOG_LEVEL，默认: INFO)",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        help="支持的子命令",
    )

    # 1. 监听消息子命令 (listen / serve)
    listen_parser = subparsers.add_parser(
        "listen",
        aliases=["serve"],
        help="启动长连接网关监听消息并调用 Agent 回复",
    )
    listen_parser.add_argument(
        "--channel",
        choices=["dingtalk", "feishu", "all"],
        default=None,
        help="监听通道: dingtalk、feishu 或 all (默认按环境变量自动推断，优先 dingtalk)",
    )
    listen_parser.add_argument(
        "--chat-id",
        "-c",
        dest="chat_id",
        default=None,
        help="可选。若指定则仅响应该 chat_id 的消息，未指定则响应所有群/单聊",
    )

    # 2. 命令行主动发送消息子命令 (send)
    send_parser = subparsers.add_parser(
        "send",
        help="主动向指定会话发送消息或文件",
    )
    send_parser.add_argument(
        "--channel",
        choices=["dingtalk", "feishu"],
        default=None,
        help="目标 IM 渠道: dingtalk 或 feishu (默认按环境变量自动推断，优先 dingtalk)",
    )
    send_parser.add_argument(
        "--chat-id",
        "-c",
        dest="chat_id",
        required=True,
        help="必填。目标会话 ID (chat_id)",
    )
    msg_group = send_parser.add_mutually_exclusive_group()
    msg_group.add_argument(
        "--message",
        "-m",
        dest="message",
        default=None,
        help="要发送的消息内容 (支持 Markdown)。若指定为 '-' 则从标准输入读取",
    )
    msg_group.add_argument(
        "--stdin",
        "-s",
        dest="read_stdin",
        action="store_true",
        help="从标准输入 (stdin) 读取消息内容",
    )
    send_parser.add_argument(
        "--file",
        "-f",
        dest="file_paths",
        nargs="+",
        default=None,
        help="要发送的本地文件路径 (支持同时指定多个文件)",
    )
    send_parser.add_argument(
        "--type",
        "-t",
        dest="message_type",
        choices=["markdown", "text"],
        default="markdown",
        help="消息类型: markdown (默认) 或 text",
    )

    # 3. 版本信息子命令 (version)
    version_parser = subparsers.add_parser(
        "version",
        help="输出当前版本信息",
    )
    version_parser.add_argument(
        "--short",
        "-s",
        action="store_true",
        help="仅输出版本号",
    )

    return parser


def read_stdin_content() -> str:
    """从标准输入读取消息内容，强制使用 UTF-8/UTF-8-SIG 解码以避免 Windows 平台编码乱码。"""
    if hasattr(sys.stdin, "buffer"):
        with contextlib.suppress(AttributeError, ValueError, OSError):
            raw_bytes = sys.stdin.buffer.read()
            if isinstance(raw_bytes, bytes):
                try:
                    return raw_bytes.decode("utf-8-sig")
                except UnicodeDecodeError:
                    return raw_bytes.decode("utf-8-sig", errors="replace")
            elif isinstance(raw_bytes, str):
                return raw_bytes

    if hasattr(sys.stdin, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")

    content = sys.stdin.read()
    content = content.removeprefix("\ufeff")
    return content


def resolve_send_message(args: argparse.Namespace) -> str | None:
    """从命令行参数或标准输入中解析待发送的消息内容。"""
    is_stdin_requested = getattr(args, "read_stdin", False) or args.message == "-"

    if is_stdin_requested:
        if sys.stdin.isatty():
            eof_hint = "Ctrl+Z 回车" if sys.platform == "win32" else "Ctrl+D"
            print(
                f"[INFO] 正在从标准输入读取消息内容 (按 {eof_hint} 结束输入)...",
                file=sys.stderr,
            )
        content = read_stdin_content()
        if not content.strip() and not args.file_paths:
            raise ValueError("从标准输入读取到的内容为空。")
        return content

    if args.message is not None:
        return args.message

    # 当未显式指定 --message / --stdin 且未指定 --file 时，若检测到管道/重定向输入，则自动读取 stdin
    if not args.file_paths and not sys.stdin.isatty():
        content = read_stdin_content()
        return content if content.strip() else None

    return None


async def run_listen(
    chat_id: str | None,
    config: Config,
    channel: str | None = None,
    work_dir: str | None = None,
) -> None:
    """运行长连接监听服务。

    Args:
        chat_id: 可选的会话过滤 ID。
        config: 全局配置对象。
        channel: 监听通道 ('dingtalk' / 'feishu' / 'all')，若为 None 则从 config 推断。
        work_dir: 可选的工作目录路径。
    """
    if work_dir is not None and not Path(work_dir).is_dir():
        raise FileNotFoundError(f"指定的工作目录不存在或不是有效目录: {work_dir}")

    target_channel = channel or config.infer_default_channel()
    config.validate_channel(target_channel)

    if target_channel == "all":
        shared_session_manager = AgentSessionManager(
            work_dir=Path(work_dir) if work_dir else None,
            model=getattr(config, "agy_model", None),
            image_model=getattr(config, "agy_image_model", None),
        )
        feishu_channel = FeishuBotChannel(
            config=config,
            filter_chat_id=chat_id,
            session_manager=shared_session_manager,
            work_dir=work_dir,
        )
        dingtalk_channel = DingTalkBotChannel(
            config=config,
            filter_chat_id=chat_id,
            session_manager=shared_session_manager,
            work_dir=work_dir,
        )
        try:
            await asyncio.gather(
                feishu_channel.start_listening(),
                dingtalk_channel.start_listening(),
            )
        finally:
            await asyncio.gather(
                feishu_channel.close(),
                dingtalk_channel.close(),
                return_exceptions=True,
            )
    elif target_channel in ("feishu", "lark"):
        bot = FeishuBotChannel(
            config=config,
            filter_chat_id=chat_id,
            work_dir=work_dir,
        )
        try:
            await bot.start_listening()
        finally:
            await bot.close()
    elif target_channel in ("dingtalk", "dd"):
        bot = DingTalkBotChannel(
            config=config,
            filter_chat_id=chat_id,
            work_dir=work_dir,
        )
        try:
            await bot.start_listening()
        finally:
            await bot.close()
    else:
        bot = get_channel(
            target_channel,
            config=config,
            filter_chat_id=chat_id,
            work_dir=work_dir,
        )
        try:
            await bot.start_listening()
        finally:
            await bot.close()


async def run_send(
    chat_id: str,
    message: str | None,
    file_paths: list[str] | None,
    message_type: str,
    config: Config,
    channel: str | None = None,
) -> None:
    """运行主动发送消息。

    Args:
        chat_id: 目标会话 ID。
        message: 待发送文本/Markdown 内容。
        file_paths: 本地待发送文件路径列表。
        message_type: 消息类型 ('markdown' 或 'text')。
        config: 全局配置对象。
        channel: 目标 IM 渠道 ('dingtalk' 或 'feishu')，若为 None 则从 config 推断。
    """
    if message == "-":
        if sys.stdin.isatty():
            eof_hint = "Ctrl+Z 回车" if sys.platform == "win32" else "Ctrl+D"
            print(
                f"[INFO] 正在从标准输入读取消息内容 (按 {eof_hint} 结束输入)...",
                file=sys.stderr,
            )
        content = read_stdin_content()
        if not content.strip() and not file_paths:
            raise ValueError("从标准输入读取到的内容为空。")
        message = content

    if not message and not file_paths:
        raise ValueError(
            "主动发送消息必须提供 --message、--stdin 或 --file 至少一项参数。"
        )

    target_channel = channel or config.infer_default_channel()
    config.validate_channel(target_channel)

    if target_channel in ("feishu", "lark"):
        channel_bot = FeishuBotChannel(config=config)
    elif target_channel in ("dingtalk", "dd"):
        channel_bot = DingTalkBotChannel(config=config)
    else:
        channel_bot = get_channel(target_channel, config=config)

    try:
        res = await channel_bot.send_message(
            chat_id=chat_id,
            message=message,
            file_paths=file_paths,
            message_type=message_type,
        )
        print(f"[SUCCESS] 消息发送成功: {res}")
    finally:
        await channel_bot.close()


def main(argv: list[str] | None = None) -> int:
    """CLI 主入口函数。"""
    if hasattr(sys.stdout, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = create_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        if getattr(args, "short", False):
            print(__version__)
        else:
            print(f"channel-bot-cli-antigravity {__version__}")
        return 0

    # 统一在此处调用一次 load_env_file 加载环境变量：若指定了 work_dir 且存在 .env 则优先加载，否则从当前目录查找加载
    work_dir = getattr(args, "work_dir", None)
    target_env = None
    if work_dir is not None:
        work_path = Path(work_dir)
        if not work_path.is_dir():
            print(
                f"[ERROR] 指定的工作目录不存在或不是有效目录: {work_dir}",
                file=sys.stderr,
            )
            return 1
        work_env = work_path / ".env"
        if work_env.is_file():
            target_env = work_env

    load_env_file(target_env)

    config = Config.from_env()
    if args.log_level:
        config.log_level = args.log_level

    setup_logging(config.log_level)

    channel = getattr(args, "channel", None) or config.infer_default_channel()
    try:
        config.validate_channel(channel)
    except ValueError as e:
        print(f"[ERROR] 配置错误: {e}", file=sys.stderr)
        return 1

    logger.info("版本<%s>开始运行... 渠道: %s", __version__, channel)
    try:
        if args.command in ("listen", "serve"):
            asyncio.run(
                run_listen(
                    chat_id=args.chat_id,
                    config=config,
                    channel=channel,
                    work_dir=work_dir,
                )
            )
        elif args.command == "send":
            message = resolve_send_message(args)
            asyncio.run(
                run_send(
                    chat_id=args.chat_id,
                    message=message,
                    file_paths=args.file_paths,
                    message_type=args.message_type,
                    config=config,
                    channel=channel,
                )
            )
        return 0
    except KeyboardInterrupt:
        print("\n[INFO] 用户中断，程序已退出。")
        return 0
    except Exception as e:
        print(f"[ERROR] 执行失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
