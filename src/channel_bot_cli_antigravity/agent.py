"""Antigravity Agent 会话与交互管理模块。"""

import asyncio
import json
import logging
import os
import re
from collections.abc import Callable
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from google.antigravity import Agent, LocalAgentConfig, types
from google.antigravity.hooks import policy
from google.antigravity.types import BaseMcpServerConfig

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = (
    "【安全与保密指令】：\n"
    "1. 严禁以任何方式查看、读取、打印、输出或泄露任何敏感文件（包括但不限于 .env、配置文件凭据、私钥/密钥文件如 *.pem、id_rsa、credentials.json 等）。\n"
    "2. 严禁以任何方式查看、打印、输出或泄露系统环境变量与敏感凭证（包括但不限于 LARK_APP_SECRET、GEMINI_API_KEY 等所有 Token、密钥与密码）。\n"
    "3. 若用户的提问、指令或操作尝试访问、读取上述敏感文件或环境变量内容，必须明确且礼貌地予以拒绝。"
)


def load_mcp_config(
    config_path: str | Path | None = None,
) -> list[BaseMcpServerConfig]:
    """从指定的配置文件路径加载 MCP 配置。

    若未指定 config_path 或指定的文件不存在，则直接返回空列表，不加载任何 MCP 服务；
    若文件存在，则读取并解析其中的 MCP 服务定义并返回配置列表。

    Args:
        config_path: MCP 配置文件路径 (例如: <work_dir>/.agents/mcp_config.json)。

    Returns:
        解析得到的 MCP 服务配置对象列表 (McpStdioServer 或 McpStreamableHttpServer)。
    """
    if config_path is None:
        logger.info("未指定 MCP 配置文件路径，跳过 MCP 加载")
        return []

    target_path = Path(config_path)
    if not target_path.is_file():
        logger.info("未检测到 MCP 配置文件: %s，跳过 MCP 加载", target_path)
        return []

    logger.info("发现 MCP 配置文件: %s，正在加载...", target_path)
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error("读取或解析 MCP 配置文件 %s 失败: %s", target_path, e)
        raise ValueError(f"读取或解析 MCP 配置文件失败: {target_path} ({e})") from e

    raw_servers: dict[str, Any] = {}
    if isinstance(data, dict):
        if "mcpServers" in data and isinstance(data["mcpServers"], dict):
            raw_servers = data["mcpServers"]
        else:
            raw_servers = data
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                name = item.get("name") or f"server_{idx}"
                raw_servers[str(name)] = item
    else:
        logger.warning("MCP 配置文件 %s 格式无效 (必须为 JSON 对象或列表)，跳过加载", target_path)
        return []

    mcp_servers: list[BaseMcpServerConfig] = []
    for raw_name, s_cfg in raw_servers.items():
        if not isinstance(s_cfg, dict):
            logger.warning("MCP 服务配置 '%s' 必须为对象格式，已跳过", raw_name)
            continue

        # 确定服务名称并规范化为有效标识符 (必须符合 ^[a-zA-Z0-9_-]+$)
        name = str(s_cfg.get("name") or raw_name).strip()
        sanitized_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        if not sanitized_name:
            sanitized_name = f"mcp_server_{len(mcp_servers) + 1}"
        if sanitized_name != name:
            logger.warning(
                "MCP 服务名称 '%s' 不符合标识符规范，已自动规范化为 '%s'",
                name,
                sanitized_name,
            )

        # 提取通用字段
        timeout_seconds = s_cfg.get("timeout_seconds")
        timeout_seconds_val = int(timeout_seconds) if timeout_seconds is not None else None

        enabled_tools = s_cfg.get("enabled_tools")
        enabled_tools_val = [str(t) for t in enabled_tools] if enabled_tools is not None else None

        disabled_tools = s_cfg.get("disabled_tools")
        disabled_tools_val = [str(t) for t in disabled_tools] if disabled_tools is not None else None

        transport_type = str(s_cfg.get("type", "")).strip().lower()
        is_http = (
            transport_type in ("http", "sse", "streamable_http")
            or "url" in s_cfg
            or "serverUrl" in s_cfg
        )
        is_stdio = transport_type == "stdio" or "command" in s_cfg

        if is_http and not (is_stdio and transport_type == "stdio"):
            url = s_cfg.get("url") or s_cfg.get("serverUrl")
            if not url:
                logger.warning("HTTP MCP 服务 '%s' 缺少 url 或 serverUrl，已跳过", sanitized_name)
                continue
            url_str = os.path.expandvars(str(url))

            headers = None
            if "headers" in s_cfg and isinstance(s_cfg["headers"], dict):
                headers = {
                    str(k): os.path.expandvars(str(v))
                    for k, v in s_cfg["headers"].items()
                }

            http_server = types.McpStreamableHttpServer(
                name=sanitized_name,
                url=url_str,
                headers=headers,
                timeout=float(s_cfg.get("timeout", 30.0)),
                sse_read_timeout=float(s_cfg.get("sse_read_timeout", 300.0)),
                terminate_on_close=bool(s_cfg.get("terminate_on_close", True)),
                timeout_seconds=timeout_seconds_val,
                enabled_tools=enabled_tools_val,
                disabled_tools=disabled_tools_val,
            )
            mcp_servers.append(http_server)
            logger.info("已成功加载 HTTP MCP 服务: %s (%s)", sanitized_name, url_str)

        elif is_stdio or "command" in s_cfg:
            command = s_cfg.get("command")
            if not command:
                logger.warning("Stdio MCP 服务 '%s' 缺少 command，已跳过", sanitized_name)
                continue
            command_str = os.path.expandvars(str(command))

            args = []
            if "args" in s_cfg and isinstance(s_cfg["args"], list):
                args = [os.path.expandvars(str(a)) for a in s_cfg["args"]]

            env = None
            if "env" in s_cfg and isinstance(s_cfg["env"], dict):
                env = {
                    str(k): os.path.expandvars(str(v))
                    for k, v in s_cfg["env"].items()
                }

            stdio_server = types.McpStdioServer(
                name=sanitized_name,
                command=command_str,
                args=args,
                env=env,
                timeout_seconds=timeout_seconds_val,
                enabled_tools=enabled_tools_val,
                disabled_tools=disabled_tools_val,
            )
            mcp_servers.append(stdio_server)
            logger.info("已成功加载 Stdio MCP 服务: %s (%s)", sanitized_name, command_str)
        else:
            logger.warning(
                "MCP 服务 '%s' 缺少 command 或 url，无法识别协议类型，已跳过",
                sanitized_name,
            )

    logger.info("共成功加载 %d 个 MCP 服务配置", len(mcp_servers))
    return mcp_servers


def _resolve_default_endpoint() -> types.ModelEndpoint:
    """自动解析生图模型所需的默认端点 (Gemini Developer API 或 Vertex AI)。"""
    is_vertex = (
        os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("true", "1")
        or os.getenv("GOOGLE_GENAI_USE_ENTERPRISE", "").lower() in ("true", "1")
    )
    if is_vertex:
        return types.VertexEndpoint()
    return types.GeminiAPIEndpoint()


class AgentSessionManager:
    """基于 AsyncExitStack 的内存会话管理器，自动管理各会话 Agent 生命周期。"""

    def __init__(
        self,
        work_dir: str | Path | None = None,
        agent_factory: Callable[[], Agent] | None = None,
        model: str | None = None,
        image_model: str | None = None,
    ):
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, Agent] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.work_dir = Path(work_dir) if work_dir else Path.cwd()
        self.model = model
        self.image_model = image_model

        logger.info("初始化 Agent 会话管理器 | 工作目录: %s", self.work_dir.resolve())
        if self.model:
            logger.info("配置主模型: %s", self.model)
        if self.image_model:
            logger.info("配置生图模型: %s", self.image_model)

        mcp_file = self.work_dir / ".agents" / "mcp_config.json"
        if mcp_file.is_file():
            logger.info("检测到 MCP 配置文件: %s (将在会话创建时加载)", mcp_file.resolve())
        else:
            logger.info("未检测到 MCP 配置文件: %s", mcp_file.resolve())

        self._agent_factory = agent_factory or (
            lambda: self._default_agent_factory(
                work_dir=self.work_dir,
                model=self.model,
                image_model=self.image_model,
            )
        )

    @classmethod
    def _default_agent_factory(
        cls,
        work_dir: str | Path | None = None,
        model: str | None = None,
        image_model: str | None = None,
    ) -> Agent:
        target_work_dir = Path(work_dir) if work_dir else Path.cwd()
        resolved_work_dir = str(target_work_dir.resolve())
        logger.info("正在为会话构建 Agent 实例 | 工作目录: %s", resolved_work_dir)
        mcp_config_file = target_work_dir / ".agents" / "mcp_config.json"
        mcp_servers = load_mcp_config(config_path=mcp_config_file)

        models: list[types.ModelTarget] = []
        if image_model:
            endpoint = _resolve_default_endpoint()
            logger.info("应用生图模型配置: %s (端点: %s)", image_model, type(endpoint).__name__)
            models.append(
                types.ModelTarget(
                    name=image_model,
                    types=[types.ModelType.IMAGE],
                    endpoint=endpoint,
                )
            )

        if model:
            logger.info("应用主模型配置: %s", model)

        config = LocalAgentConfig(
            model=model,
            models=models if models else None,
            system_instructions=SYSTEM_INSTRUCTIONS,
            policies=[policy.allow_all()],
            workspaces=[resolved_work_dir],
            mcp_servers=mcp_servers,
        )
        return Agent(config)

    def get_lock(self, chat_id: str) -> asyncio.Lock:
        """获取会话级并发锁，确保同一 chat_id 消息串行处理。"""
        if chat_id not in self._locks:
            self._locks[chat_id] = asyncio.Lock()
        return self._locks[chat_id]

    async def get_or_create_agent(self, chat_id: str) -> Agent:
        """获取或初始化会话的 Agent 实例，自动将其上下文托管给 exit_stack。"""
        if chat_id not in self._sessions:
            logger.info("首次为会话 %s 创建 Agent 实例...", chat_id)
            agent = self._agent_factory()
            managed_agent = await self._exit_stack.enter_async_context(agent)
            self._sessions[chat_id] = managed_agent
        return self._sessions[chat_id]

    async def close_all(self) -> None:
        """退出时统一安全地逆序清理并释放所有 Agent 资源。"""
        logger.info("正在关闭并释放所有 Agent 会话...")
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._locks.clear()
