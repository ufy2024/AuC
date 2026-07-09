from __future__ import annotations

import pytest

from auc.integration.mcp import (
    MCPServerConfig,
    MCPToolInfo,
    connector_card,
    discover_and_register,
    mcp_tool_name,
    parse_mcp_configs,
    parse_resource_refs,
    setup_mcp,
    tool_allowed,
)
from auc.tools.registry import DefaultToolRegistry


class FakeSession:
    def __init__(self, tools=None, resources=None, results=None):
        self._tools = tools or []
        self._resources = resources or []
        self._results = results or {}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def list_tools(self):
        return self._tools

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self._results.get(name, f"called {name}")

    async def list_resources(self):
        return self._resources

    async def read_resource(self, uri):
        return f"resource:{uri}"

    async def aclose(self):
        self.closed = True


# ── 配置解析 ──
def test_parse_mcp_configs_claude_style():
    settings = {
        "mcpServers": {
            "fs": {"command": "mcp-fs", "args": ["--root", "/tmp"]},
            "api": {"url": "https://example.com/mcp", "privilege": "L3", "owner": "team-a"},
        }
    }
    configs = {c.name: c for c in parse_mcp_configs(settings)}
    assert configs["fs"].transport == "stdio"
    assert configs["fs"].command == "mcp-fs"
    assert configs["fs"].args == ["--root", "/tmp"]
    assert configs["api"].transport == "http"
    assert configs["api"].privilege == "L3"
    assert configs["api"].owner == "team-a"


def test_parse_mcp_configs_section_list_and_invalid_priv():
    settings = {
        "mcp": {
            "servers": [
                {"name": "db", "command": "x", "privilege": "BAD", "deny": ["drop*"]},
            ]
        }
    }
    cfg = parse_mcp_configs(settings)[0]
    assert cfg.name == "db"
    assert cfg.privilege == "L2"  # 非法值回退
    assert cfg.forbidden_tools == ["drop*"]


def test_parse_mcp_configs_empty():
    assert parse_mcp_configs(None) == []
    assert parse_mcp_configs({}) == []


# ── 命名 / 治理 ──
def test_mcp_tool_name_sanitizes():
    assert mcp_tool_name("my-server", "read.file") == "mcp__my_server__read_file"


def test_tool_allowed_forbidden_and_allow():
    cfg = MCPServerConfig(name="s", forbidden_tools=["danger*"], allowed_tools=["read*", "list*"])
    assert tool_allowed(cfg, "read_file")
    assert not tool_allowed(cfg, "danger_op")
    assert not tool_allowed(cfg, "write_file")  # 不在 allow 白名单
    # 仅黑名单
    cfg2 = MCPServerConfig(name="s", forbidden_tools=["x"])
    assert tool_allowed(cfg2, "y")
    assert not tool_allowed(cfg2, "x")


def test_connector_card_shape():
    cfg = MCPServerConfig(name="s", transport="http", url="u", owner="o", privilege="L1")
    card = connector_card(cfg, tools=["mcp__s__a"])
    assert card["name"] == "s"
    assert card["transport"] == "http"
    assert card["tool_count"] == 1
    assert card["privilege"] == "L1"
    assert card["error"] is None


# ── 注册 ──
@pytest.mark.asyncio
async def test_discover_and_register_filters_and_registers():
    cfg = MCPServerConfig(
        name="srv", privilege="L1", forbidden_tools=["secret"]
    )
    session = FakeSession(
        tools=[
            MCPToolInfo(name="echo", description="d", input_schema={"type": "object"}),
            MCPToolInfo(name="secret", description="x"),
        ],
        results={"echo": "hello"},
    )

    async def connect(_c):
        return session

    reg = DefaultToolRegistry()
    result = await discover_and_register(reg, [cfg], connect=connect)

    assert result.registered == 1
    assert reg.get("mcp__srv__echo") is not None
    assert reg.get("mcp__srv__secret") is None
    # 权限来自配置
    assert reg.get_policy("mcp__srv__echo").privilege == "L1"
    # 安全默认：MCP 工具默认 sandbox_only=True（即便 L1 也校验路径参数）
    assert reg.get_policy("mcp__srv__echo").sandbox_only is True

    # 调用走 session
    tool = reg.get("mcp__srv__echo")
    res = await tool.invoke({"x": 1})
    assert res.is_error is False
    assert res.content == "hello"
    assert session.calls == [("echo", {"x": 1})]

    await result.aclose()
    assert session.closed is True


@pytest.mark.asyncio
async def test_discover_disabled_server_skipped():
    cfg = MCPServerConfig(name="off", enabled=False)

    async def connect(_c):  # 不应被调用
        raise AssertionError("disabled server connected")

    reg = DefaultToolRegistry()
    result = await discover_and_register(reg, [cfg], connect=connect)
    assert result.registered == 0
    assert result.cards[0]["error"] == "disabled"


@pytest.mark.asyncio
async def test_discover_connect_failure_degrades():
    cfg = MCPServerConfig(name="bad")

    async def connect(_c):
        raise RuntimeError("boom")

    reg = DefaultToolRegistry()
    result = await discover_and_register(reg, [cfg], connect=connect)
    assert result.registered == 0
    assert result.warnings
    assert "boom" in result.cards[0]["error"]


@pytest.mark.asyncio
async def test_tool_invoke_remote_error_is_tool_error():
    cfg = MCPServerConfig(name="s")

    class Boom(FakeSession):
        async def call_tool(self, name, arguments):
            raise RuntimeError("remote fail")

    session = Boom(tools=[MCPToolInfo(name="t")])

    async def connect(_c):
        return session

    reg = DefaultToolRegistry()
    await discover_and_register(reg, [cfg], connect=connect)
    res = await reg.get("mcp__s__t").invoke({})
    assert res.is_error is True
    assert "remote fail" in res.content


@pytest.mark.asyncio
async def test_setup_mcp_none_when_no_config():
    reg = DefaultToolRegistry()
    assert await setup_mcp(reg, {}) is None


@pytest.mark.asyncio
async def test_setup_mcp_with_injected_connect():
    settings = {"mcpServers": {"s": {"command": "x"}}}
    session = FakeSession(tools=[MCPToolInfo(name="t")])

    async def connect(_c):
        return session

    reg = DefaultToolRegistry()
    result = await setup_mcp(reg, settings, connect=connect)
    assert result is not None
    assert result.registered == 1
    await result.aclose()


# ── 资源引用 ──
def test_parse_resource_refs():
    refs = parse_resource_refs("see @mcp:fs:/a/b.txt and @mcp:api:res://x then end")
    assert refs == [("fs", "/a/b.txt"), ("api", "res://x")]
    assert parse_resource_refs("") == []
