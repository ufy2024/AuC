"""R13 子智能体工具测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from auc import (
    AgentConfig,
    DefaultAgent,
    DefaultToolRegistry,
    InMemoryModelClient,
    LoopConfig,
)
from auc.events.bus import EventBus, RunEvent
from auc.messages import ToolCall
from auc.model import AssistantMessage
from auc.run_context import current_loop_context
from auc.tools.shell import make_shell_tool
from auc.tools.subagent import make_subagent_tool


def _child_agent(tmp: Path) -> DefaultAgent:
    registry = DefaultToolRegistry()
    shell_tool, pol = make_shell_tool(str(tmp))
    registry.register(shell_tool, pol)
    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(id="t1", name="run_command", arguments={"command": "echo hi"}),
                ],
            ),
            AssistantMessage(content="子任务完成。", tool_calls=None),
        ]
    )
    return DefaultAgent(
        AgentConfig(
            agent_id="chat:default",
            model=model,
            tools=registry,
            sandbox_root=str(tmp),
            loop_config=LoopConfig(max_steps=5),
            autonomy="full-auto",
        )
    )


def _parent_ctx(events: EventBus, *, parent_run_id=None):
    return SimpleNamespace(
        run_id="parent-1",
        agent_id="chat:default",
        events=events,
        parent_run_id=parent_run_id,
    )


def _make_tool(tmp: Path):
    tool, _pol = make_subagent_tool(
        build_agent=lambda kind: _child_agent(tmp),
        sandbox=str(tmp),
        allowed_kinds=["default", "reviewer"],
        default_kind="default",
    )
    return tool


def test_spawn_returns_block_and_emits_events(tmp_path: Path) -> None:
    asyncio.run(_spawn_ok(tmp_path))


async def _spawn_ok(tmp_path: Path) -> None:
    events = EventBus()
    seen: list[RunEvent] = []
    events.subscribe(seen.append)
    tool = _make_tool(tmp_path)
    token = current_loop_context.set(_parent_ctx(events))
    try:
        result = await tool.invoke({"task": "跑个命令", "kind": "default"})
    finally:
        current_loop_context.reset(token)
    assert not result.is_error
    assert "status=completed" in result.content
    assert "echo hi" in result.content
    types = [e.type for e in seen]
    assert "subagent_start" in types
    assert "subagent_end" in types
    end = next(e for e in seen if e.type == "subagent_end")
    assert end.payload["kind"] == "default"
    assert end.payload["status"] == "completed"


def test_one_level_nesting_guard(tmp_path: Path) -> None:
    async def _run() -> None:
        tool = _make_tool(tmp_path)
        token = current_loop_context.set(_parent_ctx(EventBus(), parent_run_id="grandparent"))
        try:
            res = await tool.invoke({"task": "x", "kind": "default"})
        finally:
            current_loop_context.reset(token)
        assert res.is_error
        assert "一层嵌套" in res.content

    asyncio.run(_run())


def test_unknown_kind_rejected(tmp_path: Path) -> None:
    async def _run() -> None:
        tool = _make_tool(tmp_path)
        token = current_loop_context.set(_parent_ctx(EventBus()))
        try:
            res = await tool.invoke({"task": "x", "kind": "nope"})
        finally:
            current_loop_context.reset(token)
        assert res.is_error
        assert "未知 kind" in res.content

    asyncio.run(_run())


def test_empty_task_rejected(tmp_path: Path) -> None:
    async def _run() -> None:
        tool = _make_tool(tmp_path)
        token = current_loop_context.set(_parent_ctx(EventBus()))
        try:
            res = await tool.invoke({"task": "  ", "kind": "default"})
        finally:
            current_loop_context.reset(token)
        assert res.is_error

    asyncio.run(_run())


def test_subagent_tool_policy(tmp_path: Path) -> None:
    _tool, pol = make_subagent_tool(
        build_agent=lambda kind: _child_agent(tmp_path),
        sandbox=str(tmp_path),
        allowed_kinds=["default"],
        default_kind="default",
    )
    assert pol.privilege == "L2"
    assert pol.mutates_files is True
    assert pol.mutates_state is True


def test_build_chat_agent_registers_subagent(tmp_path: Path) -> None:
    pytest.importorskip("yaml", reason="role catalog 可能依赖 yaml")
    from auc.chat_agent import ChatAgentOptions, build_chat_agent
    from auc.config import ModelConfig

    cfg = ModelConfig(provider="openai", model="test", api_key="x")
    agent = build_chat_agent(cfg, ChatAgentOptions(sandbox=str(tmp_path), evolve=False))
    assert "spawn_subagent" in agent._config.tools._tools

    child_only = build_chat_agent(
        cfg, ChatAgentOptions(sandbox=str(tmp_path), evolve=False, enable_subagents=False)
    )
    assert "spawn_subagent" not in child_only._config.tools._tools
