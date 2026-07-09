"""R16 MCP（Model Context Protocol）客户端。

将外部 MCP server（stdio / HTTP）的 tools 注册进 `ToolRegistry`，注册名加前缀
`mcp__<server>__<tool>`，默认 L2、统一过裁决链（与本地工具同权限模型）。资源
（resources）可经 `@mcp:<server>:<uri>` 引用注入。提供「连接器卡片」治理视图
（allowed/forbidden/owner/transport）。

守恒：核心包零新增硬依赖——官方 `mcp` SDK 为可选 extra（`pip install -e '.[mcp]'`）；
未安装或连接失败时本模块**安全降级**（不注册任何工具，仅返回告警），绝不影响主流程。

可测性：连接逻辑抽象为 `MCPSession` + `ConnectFn`，纯逻辑（配置解析 / 命名 / 治理
过滤 / 工具包装 / 连接器卡片）均可用内存假会话覆盖；真实 stdio/http 适配器惰性导入。
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from auc.messages import ToolResult
from auc.tools.base import ToolPolicy
from auc.tools.registry import DefaultToolRegistry
from auc.types import ToolPrivilege

logger = logging.getLogger("auc.integration.mcp")

_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")
_VALID_PRIVS = {"L1", "L2", "L3"}


# ── 配置 ──
@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"  # stdio | http
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    privilege: ToolPrivilege = "L2"
    enabled: bool = True
    allowed_tools: list[str] = field(default_factory=list)  # glob 白名单；空=全部
    forbidden_tools: list[str] = field(default_factory=list)  # glob 黑名单（优先）
    owner: str = ""
    # 安全默认：强制路径参数沙盒校验（即便配置为 L1 也生效）。仅在明确信任
    # 该 server 需访问沙盒外资源时，于配置里显式设 sandbox_only:false 关闭。
    sandbox_only: bool = True


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def _coerce_str_map(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    return {}


def parse_mcp_configs(settings: dict[str, Any] | None) -> list[MCPServerConfig]:
    """解析 settings：支持 Claude 式 `mcpServers` 映射与 `mcp.servers` 列表/映射。"""
    if not isinstance(settings, dict):
        return []
    raw_servers: dict[str, Any] = {}
    if isinstance(settings.get("mcpServers"), dict):
        raw_servers.update(settings["mcpServers"])
    mcp_section = settings.get("mcp")
    if isinstance(mcp_section, dict):
        servers = mcp_section.get("servers")
        if isinstance(servers, dict):
            raw_servers.update(servers)
        elif isinstance(servers, list):
            for item in servers:
                if isinstance(item, dict) and item.get("name"):
                    raw_servers[str(item["name"])] = item

    configs: list[MCPServerConfig] = []
    for name, raw in raw_servers.items():
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or "")
        transport = str(raw.get("transport") or ("http" if url else "stdio")).lower()
        priv = str(raw.get("privilege") or "L2").upper()
        if priv not in _VALID_PRIVS:
            priv = "L2"
        configs.append(
            MCPServerConfig(
                name=str(name),
                transport="http" if transport in ("http", "sse", "streamable-http") else "stdio",
                command=str(raw.get("command") or ""),
                args=_coerce_str_list(raw.get("args")),
                env=_coerce_str_map(raw.get("env")),
                url=url,
                headers=_coerce_str_map(raw.get("headers")),
                privilege=priv,  # type: ignore[arg-type]
                enabled=bool(raw.get("enabled", True)),
                allowed_tools=_coerce_str_list(raw.get("allowed_tools") or raw.get("allow")),
                forbidden_tools=_coerce_str_list(raw.get("forbidden_tools") or raw.get("deny")),
                owner=str(raw.get("owner") or ""),
                sandbox_only=bool(raw.get("sandbox_only", True)),
            )
        )
    return configs


def mcp_tool_name(server: str, tool: str) -> str:
    s = _NAME_RE.sub("_", server).strip("_") or "server"
    t = _NAME_RE.sub("_", tool).strip("_") or "tool"
    return f"mcp__{s}__{t}"


def tool_allowed(config: MCPServerConfig, tool_name: str) -> bool:
    for pat in config.forbidden_tools:
        if fnmatch.fnmatch(tool_name, pat):
            return False
    if config.allowed_tools:
        return any(fnmatch.fnmatch(tool_name, pat) for pat in config.allowed_tools)
    return True


# ── 会话抽象 ──
@dataclass
class MCPToolInfo:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResourceInfo:
    uri: str
    name: str = ""
    mime_type: str = ""


class MCPSession(Protocol):
    async def list_tools(self) -> list[MCPToolInfo]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str: ...
    async def list_resources(self) -> list[MCPResourceInfo]: ...
    async def read_resource(self, uri: str) -> str: ...
    async def aclose(self) -> None: ...


ConnectFn = Callable[[MCPServerConfig], Awaitable[MCPSession]]
ToolCaller = Callable[[str, dict[str, Any]], Awaitable[str]]


# ── 工具包装 ──
class _MCPTool:
    """把单个 MCP 远端工具包装成 auc Tool（经唯一裁决入口调用）。"""

    def __init__(
        self,
        *,
        registered_name: str,
        remote_name: str,
        description: str,
        parameters: dict[str, Any],
        caller: ToolCaller,
    ) -> None:
        self._name = registered_name
        self._remote = remote_name
        self._description = description
        self._parameters = parameters or {"type": "object", "properties": {}}

        self._caller = caller

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult:
        if not isinstance(arguments, dict):
            return ToolResult(
                tool_call_id="", name=self._name,
                content="arguments must be a JSON object", is_error=True,
            )
        try:
            content = await self._caller(self._remote, arguments)
        except Exception as exc:  # noqa: BLE001 远端错误归一为工具错误
            return ToolResult(
                tool_call_id="", name=self._name,
                content=f"MCP 调用失败: {exc}", is_error=True,
            )
        return ToolResult(tool_call_id="", name=self._name, content=content)


def connector_card(
    config: MCPServerConfig,
    *,
    tools: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """治理视图：单个 MCP server 的连接器卡片。"""
    return {
        "name": config.name,
        "transport": config.transport,
        "endpoint": config.url or config.command,
        "owner": config.owner,
        "privilege": config.privilege,
        "sandbox_only": config.sandbox_only,
        "enabled": config.enabled,
        "allowed_tools": list(config.allowed_tools),
        "forbidden_tools": list(config.forbidden_tools),
        "tools": tools or [],
        "tool_count": len(tools or []),
        "error": error,
    }


@dataclass
class MCPSetupResult:
    cards: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    registered: int = 0
    sessions: list[MCPSession] = field(default_factory=list)

    async def aclose(self) -> None:
        for s in self.sessions:
            try:
                await s.aclose()
            except Exception:  # noqa: BLE001
                pass


async def discover_and_register(
    registry: DefaultToolRegistry,
    configs: list[MCPServerConfig],
    *,
    connect: ConnectFn,
) -> MCPSetupResult:
    """连接各 server、列出并按治理过滤后注册工具；返回连接器卡片与活跃会话。"""
    result = MCPSetupResult()
    for config in configs:
        if not config.enabled:
            result.cards.append(connector_card(config, error="disabled"))
            continue
        try:
            session = await connect(config)
        except Exception as exc:  # noqa: BLE001
            msg = f"MCP server {config.name!r} 连接失败: {exc}"
            logger.warning(msg)
            result.warnings.append(msg)
            result.cards.append(connector_card(config, error=str(exc)))
            continue

        try:
            tools = await session.list_tools()
        except Exception as exc:  # noqa: BLE001
            msg = f"MCP server {config.name!r} 列出工具失败: {exc}"
            logger.warning(msg)
            result.warnings.append(msg)
            result.cards.append(connector_card(config, error=str(exc)))
            await _safe_close(session)
            continue

        registered_names: list[str] = []
        for info in tools:
            if not tool_allowed(config, info.name):
                continue
            reg_name = mcp_tool_name(config.name, info.name)

            async def _caller(
                remote: str, arguments: dict[str, Any], _s: MCPSession = session
            ) -> str:
                return await _s.call_tool(remote, arguments)

            tool = _MCPTool(
                registered_name=reg_name,
                remote_name=info.name,
                description=info.description or f"MCP 工具 {config.name}:{info.name}",
                parameters=info.input_schema,
                caller=_caller,
            )
            registry.register(
                tool,
                ToolPolicy(
                    name=reg_name,
                    privilege=config.privilege,
                    sandbox_only=config.sandbox_only,
                    mutates_state=True,
                ),
            )
            registered_names.append(reg_name)

        result.registered += len(registered_names)
        result.sessions.append(session)
        result.cards.append(connector_card(config, tools=registered_names))
    return result


async def _safe_close(session: MCPSession) -> None:
    try:
        await session.aclose()
    except Exception:  # noqa: BLE001
        pass


# ── 资源引用 @mcp:<server>:<uri> ──
_MCP_REF_RE = re.compile(r"@mcp:([A-Za-z0-9_\-]+):(\S+)")


def parse_resource_refs(text: str) -> list[tuple[str, str]]:
    """从文本提取 (server, uri) 引用。"""
    return [(m.group(1), m.group(2)) for m in _MCP_REF_RE.finditer(text or "")]


# ── 真实适配器（惰性导入官方 mcp SDK）──
async def default_connect(config: MCPServerConfig) -> MCPSession:
    """用官方 `mcp` SDK 建立持久会话；未安装则抛出可读错误。"""
    try:
        import mcp  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 取决于可选依赖
        raise RuntimeError(
            "未安装 MCP SDK；请 `pip install -e '.[mcp]'` 后重试"
        ) from exc
    return await _SdkSession.connect(config)  # pragma: no cover


class _SdkSession:  # pragma: no cover - 需真实 mcp SDK 与外部 server
    """官方 SDK 持久会话：进入 transport + ClientSession 异步上下文并保持。"""

    def __init__(self, session: Any, stack: Any) -> None:
        self._session = session
        self._stack = stack

    @classmethod
    async def connect(cls, config: MCPServerConfig) -> "_SdkSession":
        from contextlib import AsyncExitStack

        from mcp import ClientSession

        stack = AsyncExitStack()
        if config.transport == "http":
            from mcp.client.streamable_http import streamablehttp_client

            read, write, *_ = await stack.enter_async_context(
                streamablehttp_client(config.url, headers=config.headers or None)
            )
        else:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=config.command, args=config.args, env=config.env or None
            )
            read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        return cls(session, stack)

    async def list_tools(self) -> list[MCPToolInfo]:
        resp = await self._session.list_tools()
        return [
            MCPToolInfo(
                name=t.name,
                description=t.description or "",
                input_schema=getattr(t, "inputSchema", None) or {},
            )
            for t in resp.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        resp = await self._session.call_tool(name, arguments)
        parts: list[str] = []
        for item in getattr(resp, "content", []) or []:
            text = getattr(item, "text", None)
            parts.append(text if text is not None else str(item))
        return "\n".join(parts) if parts else "(无输出)"

    async def list_resources(self) -> list[MCPResourceInfo]:
        resp = await self._session.list_resources()
        return [
            MCPResourceInfo(
                uri=str(r.uri), name=r.name or "", mime_type=getattr(r, "mimeType", "") or ""
            )
            for r in resp.resources
        ]

    async def read_resource(self, uri: str) -> str:
        resp = await self._session.read_resource(uri)
        parts: list[str] = []
        for item in getattr(resp, "contents", []) or []:
            text = getattr(item, "text", None)
            parts.append(text if text is not None else str(item))
        return "\n".join(parts)

    async def aclose(self) -> None:
        await self._stack.aclose()


async def setup_mcp(
    registry: DefaultToolRegistry,
    settings: dict[str, Any] | None,
    *,
    connect: ConnectFn | None = None,
) -> MCPSetupResult | None:
    """便捷入口：解析配置并注册工具。无 MCP 配置返回 None。"""
    configs = parse_mcp_configs(settings)
    if not configs:
        return None
    return await discover_and_register(
        registry, configs, connect=connect or default_connect
    )
