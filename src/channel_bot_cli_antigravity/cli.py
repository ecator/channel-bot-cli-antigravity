import argparse
import asyncio
import contextlib
import logging
import sys
from pathlib import Path

from . import __version__
from .channel import FeishuBotChannel
from .config import Config, load_env_file
from .utils import setup_logging

logger = logging.getLogger(__name__)


def create_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器。"""
    parser = argparse.ArgumentParser(
        description="基于 Antigravity SDK 的飞书私人 AI 助手工具",
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

    # 1. 监听消息子命令 (listen)
    listen_parser = subparsers.add_parser(
        "listen",
        aliases=["serve"],
        help="启动长连接网关监听飞书消息并调用 Agent 回复",
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
        help="主动向指定飞书会话发送消息或文件",
    )
    send_parser.add_argument(
        "--chat-id",
        "-c",
        dest="chat_id",
        required=True,
        help="必填。目标飞书会话 ID (chat_id)",
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
    """从标准输入读取消息内容，强制使用 UTF-8 编码解码以避免 Windows 默认编码（如 CP936/GBK）导致的乱码。"""
    if hasattr(sys.stdin, "buffer"):
        with contextlib.suppress(AttributeError, ValueError):
            raw_bytes = sys.stdin.buffer.read()
            try:
                return raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                return raw_bytes.decode(errors="replace")

    if hasattr(sys.stdin, "reconfigure"):
        with contextlib.suppress(Exception):
            sys.stdin.reconfigure(encoding="utf-8")

    return sys.stdin.read()


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
    work_dir: str | None = None,
) -> None:
    """运行监听服务。"""
    if work_dir is not None and not Path(work_dir).is_dir():
        raise FileNotFoundError(f"指定的工作目录不存在或不是有效目录: {work_dir}")
    channel = FeishuBotChannel(
        config=config,
        filter_chat_id=chat_id,
        work_dir=work_dir,
    )
    await channel.start_listening()


async def run_send(
    chat_id: str,
    message: str | None,
    file_paths: list[str] | None,
    message_type: str,
    config: Config,
) -> None:
    """运行主动发送消息。"""
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
        raise ValueError("主动发送消息必须提供 --message、--stdin 或 --file 至少一项参数。")

    channel = FeishuBotChannel(config=config)
    try:
        res = await channel.send_message(
            chat_id=chat_id,
            message=message,
            file_paths=file_paths,
            message_type=message_type,
        )
        print(f"[SUCCESS] 消息发送成功: {res}")
    finally:
        await channel.close()


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
            print(f"feishu-bot-cli-antigravity {__version__}")
        return 0


    # 统一在此处调用一次 load_env_file 加载环境变量：若指定了 work_dir 且存在 .env 则优先加载，否则从当前目录查找加载
    work_dir = getattr(args, "work_dir", None)
    target_env = None
    if work_dir is not None:
        work_path = Path(work_dir)
        if not work_path.is_dir():
            print(f"[ERROR] 指定的工作目录不存在或不是有效目录: {work_dir}", file=sys.stderr)
            return 1
        work_env = work_path / ".env"
        if work_env.is_file():
            target_env = work_env

    load_env_file(target_env)

    config = Config.from_env()
    if args.log_level:
        config.log_level = args.log_level

    setup_logging(config.log_level)

    try:
        config.validate()
    except ValueError as e:
        print(f"[ERROR] 配置错误: {e}", file=sys.stderr)
        return 1

    logger.info("版本<%s>开始运行...", __version__)
    try:
        if args.command in ("listen", "serve"):
            asyncio.run(run_listen(args.chat_id, config, work_dir=work_dir))
        elif args.command == "send":
            message = resolve_send_message(args)
            asyncio.run(
                run_send(
                    chat_id=args.chat_id,
                    message=message,
                    file_paths=args.file_paths,
                    message_type=args.message_type,
                    config=config,
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
