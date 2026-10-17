"""工具类模块，提供日志配置与内存文件解析功能。"""

import logging
import mimetypes
from datetime import datetime

from google.antigravity import types


def format_iso_time(timestamp: float | str | None) -> str:
    """将时间戳（毫秒或秒）转换为带当前时区的 ISO 8601 标准时间字符串。"""
    if timestamp is None or timestamp == "":
        return ""
    try:
        ts = float(timestamp)
        # 兼容毫秒级时间戳（如 13 位数字，> 10^11）
        if ts > 1e11:
            ts /= 1000.0
        return datetime.fromtimestamp(ts).astimezone().isoformat()
    except Exception:
        return str(timestamp)


def setup_logging(level: str = "INFO") -> None:
    """初始化标准 logging 配置。"""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# 常见纯文本/代码文件扩展名
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".json", ".csv", ".xml", ".html", ".htm",
    ".css", ".js", ".ts", ".jsx", ".tsx", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".conf", ".sh", ".bash", ".bat", ".ps1", ".sql",
    ".env", ".c", ".cpp", ".cc", ".h", ".hpp", ".java", ".rs", ".go",
    ".php", ".rb", ".log",
}


def guess_mime_type(file_name: str | None, resource_type: str = "file") -> str:
    """根据文件名与资源类型推断 MIME 类型。"""
    if file_name:
        dot_index = file_name.rfind(".")
        ext = file_name[dot_index:].lower() if dot_index != -1 else ""

        if ext == ".json":
            return "application/json"
        if ext == ".csv":
            return "text/csv"
        if ext in {".html", ".htm"}:
            return "text/html"
        if ext == ".css":
            return "text/css"
        if ext == ".js":
            return "text/javascript"
        if ext == ".xml":
            return "text/xml"
        if ext == ".pdf":
            return "application/pdf"
        if ext in TEXT_EXTENSIONS:
            return "text/plain"

        guessed, _ = mimetypes.guess_type(file_name)
        if guessed:
            return guessed

    if resource_type == "image":
        return "image/png"
    if resource_type == "audio":
        return "audio/mp3"
    if resource_type == "video":
        return "video/mp4"

    return "application/octet-stream"


def create_media_from_bytes(
    data: bytes,
    file_name: str | None = None,
    resource_type: str = "file",
) -> types.Image | types.Document | types.Audio | types.Video | str:
    """
    将内存中的二进制文件字节转换为 Antigravity SDK 原生识别的多模态对象。
    若属于 Gemini SDK 支持的文件格式，直接构造对应的 Image / Document / Audio / Video；
    若为纯文本内容但扩展名未知，尝试 UTF-8 解码转为 Document(text/plain)；
    若完全不支持，则降级为带有文件描述的文本提示。
    """
    mime_type = guess_mime_type(file_name, resource_type)

    # 1. 尝试使用 types.from_bytes 构造（自动映射到 Image / Document / Audio / Video）
    try:
        return types.from_bytes(data=data, mime_type=mime_type, description=file_name)
    except ValueError:
        pass

    # 2. 尝试以 UTF-8 解码为纯文本 Document
    try:
        _ = data.decode("utf-8")
        return types.Document(data=data, mime_type="text/plain", description=file_name)
    except UnicodeDecodeError:
        pass

    # 3. Magic Number 兜底识别
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return types.Image(data=data, mime_type="image/png", description=file_name)
    if data.startswith(b"\xff\xd8\xff"):
        return types.Image(data=data, mime_type="image/jpeg", description=file_name)
    if data.startswith(b"%PDF"):
        return types.Document(data=data, mime_type="application/pdf", description=file_name)

    # 4. 无法直接解析的二进制文件，降级为文本提示
    desc = file_name or "未知文件名"
    return f"[用户上传了附件文件: {desc}，大小: {len(data)} 字节，暂不支持该格式直接解析]"
