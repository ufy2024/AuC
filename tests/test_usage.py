"""R11 用量追踪与预算测试。"""

from __future__ import annotations

import asyncio

from auc.context.window import ListContextWindow
from auc.events.bus import EventBus, RunEvent
from auc.loop.base import LoopConfig, LoopContext
from auc.loop.react import ReActLoop
from auc.model.client import AssistantMessage, InMemoryModelClient, TokenUsage
from auc.tools.registry import DefaultToolRegistry
from auc.usage import UsageTracker, billed_cost_usd, price_for


def test_price_for_prefix_match() -> None:
    assert price_for("gpt-4o-mini") == (0.15, 0.60)
    assert price_for("gpt-4o-2024-08-06") == (2.50, 10.00)
    assert price_for("deepseek-chat") == (0.27, 1.10)
    assert price_for("unknown-model") == (0.0, 0.0)


def test_billed_cost_multiplier() -> None:
    assert billed_cost_usd(0.1) == 0.15
    assert billed_cost_usd(0) == 0.0


def test_tracker_accumulates_and_costs() -> None:
    tr = UsageTracker(model="gpt-4o-mini")
    assert tr.add(TokenUsage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500))
    tr.add(TokenUsage(prompt_tokens=2000, completion_tokens=0, total_tokens=2000))
    assert tr.prompt_tokens == 3000
    assert tr.completion_tokens == 500
    assert tr.total_tokens == 3500
    assert tr.last_prompt_tokens == 2000
    # cost: prompt 3000/1e6*0.15 + completion 500/1e6*0.60
    assert abs(tr.cost_usd - (3000 / 1e6 * 0.15 + 500 / 1e6 * 0.60)) < 1e-9
    assert not tr.add(None)


def _ctx_with_usage(usage: TokenUsage, *, budget: int = 0):
    model = InMemoryModelClient(
        responses=[AssistantMessage(content="done", tool_calls=None, usage=usage)]
    )
    bus = EventBus()
    events: list[RunEvent] = []
    bus.subscribe(events.append)
    ctx = LoopContext(
        agent_id="t",
        run_id="r",
        window=ListContextWindow(),
        tools=DefaultToolRegistry(),
        model=model,
        events=bus,
        config=LoopConfig(max_total_tokens=budget, context_token_limit=0),
        usage_tracker=UsageTracker(model="gpt-4o-mini"),
    )
    return ctx, events


def test_react_emits_usage_updated() -> None:
    ctx, events = _ctx_with_usage(
        TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    )
    asyncio.run(ReActLoop().step(ctx))
    usage_events = [e for e in events if e.type == "usage_updated"]
    assert len(usage_events) == 1
    assert usage_events[0].payload["total_tokens"] == 120
    assert usage_events[0].payload["budget_exceeded"] is False


def test_budget_exceeded_cancels() -> None:
    ctx, events = _ctx_with_usage(
        TokenUsage(prompt_tokens=900, completion_tokens=200, total_tokens=1100),
        budget=1000,
    )
    asyncio.run(ReActLoop().step(ctx))
    usage_events = [e for e in events if e.type == "usage_updated"]
    assert usage_events[0].payload["budget_exceeded"] is True
    assert ctx.cancelled is True
    assert ctx.error and "预算" in ctx.error
