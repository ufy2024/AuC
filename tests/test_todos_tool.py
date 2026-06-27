"""R10：update_todos 工具与 todos_updated 事件测试。"""

from __future__ import annotations

import asyncio
import json

from auc.context.window import ListContextWindow
from auc.events.bus import EventBus, RunEvent
from auc.loop.base import LoopConfig, LoopContext
from auc.model.client import InMemoryModelClient
from auc.run_context import current_loop_context
from auc.tools.registry import DefaultToolRegistry
from auc.tools.todos import make_todos_tool


def _ctx() -> tuple[LoopContext, list[RunEvent]]:
    bus = EventBus()
    events: list[RunEvent] = []
    bus.subscribe(events.append)
    ctx = LoopContext(
        agent_id="t",
        run_id="r",
        window=ListContextWindow(),
        tools=DefaultToolRegistry(),
        model=InMemoryModelClient(responses=[]),
        events=bus,
        config=LoopConfig(),
    )
    return ctx, events


def test_update_todos_sets_ctx_and_emits() -> None:
    tool, policy = make_todos_tool()
    assert policy.privilege == "L1"
    ctx, events = _ctx()
    token = current_loop_context.set(ctx)
    try:
        result = asyncio.run(
            tool.invoke(
                {
                    "todos": [
                        {"id": "a", "content": "第一步", "status": "in_progress"},
                        {"id": "b", "content": "第二步", "status": "pending"},
                    ]
                }
            )
        )
    finally:
        current_loop_context.reset(token)

    assert not result.is_error
    data = json.loads(result.content)
    assert data["total"] == 2
    assert data["completed"] == 0
    assert len(ctx.todos) == 2
    emitted = [e for e in events if e.type == "todos_updated"]
    assert len(emitted) == 1
    assert emitted[0].payload["todos"][0]["id"] == "a"


def test_update_todos_merge_by_id() -> None:
    tool, _ = make_todos_tool()
    ctx, _ = _ctx()
    token = current_loop_context.set(ctx)
    try:
        asyncio.run(
            tool.invoke(
                {"todos": [{"id": "a", "content": "A", "status": "pending"}]}
            )
        )
        asyncio.run(
            tool.invoke(
                {
                    "todos": [{"id": "a", "content": "A", "status": "completed"}],
                    "merge": True,
                }
            )
        )
    finally:
        current_loop_context.reset(token)
    assert len(ctx.todos) == 1
    assert ctx.todos[0]["status"] == "completed"


def test_update_todos_rejects_bad_status() -> None:
    tool, _ = make_todos_tool()
    ctx, _ = _ctx()
    token = current_loop_context.set(ctx)
    try:
        result = asyncio.run(
            tool.invoke(
                {"todos": [{"id": "a", "content": "A", "status": "bogus"}]}
            )
        )
    finally:
        current_loop_context.reset(token)
    assert result.is_error
    assert "status" in result.content


def test_update_todos_without_context_is_safe() -> None:
    """无 LoopContext（直接调用）时不应崩溃，只返回结果。"""
    tool, _ = make_todos_tool()
    result = asyncio.run(
        tool.invoke({"todos": [{"id": "a", "content": "A", "status": "pending"}]})
    )
    assert not result.is_error
