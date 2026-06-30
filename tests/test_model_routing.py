from __future__ import annotations

import asyncio

from auc.model.routing import (
    DEFAULT_STRATEGY,
    canonical_auto_model,
    is_auto_model,
    parse_auto_model,
    routing_options,
    strategy_label,
)


def test_is_auto_model() -> None:
    assert is_auto_model("auto")
    assert is_auto_model("AUTO")
    assert is_auto_model(" auto:quality_first ")
    assert not is_auto_model("gpt-4o")
    assert not is_auto_model("autopilot")  # 前缀但非 auto 段
    assert not is_auto_model(None)


def test_parse_auto_model_default_and_explicit() -> None:
    assert parse_auto_model("auto") == (True, DEFAULT_STRATEGY)
    assert parse_auto_model("auto:") == (True, DEFAULT_STRATEGY)
    assert parse_auto_model("auto:quality_first") == (True, "quality_first")
    assert parse_auto_model("auto:balanced") == (True, "balanced")
    assert parse_auto_model("auto:latency_critical") == (True, "latency_critical")
    # 未知策略回退默认
    assert parse_auto_model("auto:nonsense") == (True, DEFAULT_STRATEGY)
    # 非 auto
    assert parse_auto_model("deepseek-chat") == (False, "")


def test_canonical_auto_model() -> None:
    assert canonical_auto_model("auto") == "auto:cost_optimized"
    assert canonical_auto_model("auto:quality_first") == "auto:quality_first"
    assert canonical_auto_model("auto:bogus") == "auto:cost_optimized"
    assert canonical_auto_model("gpt-4o") == "gpt-4o"


def test_strategy_label_and_options() -> None:
    assert strategy_label("quality_first") == "质量优先"
    assert strategy_label("unknown") == "unknown"
    opts = routing_options()
    assert {o["strategy"] for o in opts} == {
        "cost_optimized",
        "balanced",
        "quality_first",
        "latency_critical",
    }
    default = [o for o in opts if o["default"]]
    assert len(default) == 1 and default[0]["strategy"] == DEFAULT_STRATEGY


def test_factory_normalizes_auto_to_canonical() -> None:
    from auc.config import ModelConfig
    from auc.model.factory import create_model_client

    cfg = ModelConfig(
        provider="openai",
        model="auto",
        api_key="sk-x",
        base_url="http://relay/api",
    )
    client = create_model_client(cfg)
    assert client.model == "auto:cost_optimized"


def test_model_resolved_event_emitted_for_auto() -> None:
    asyncio.run(_run_auto_resolved())


async def _run_auto_resolved() -> None:
    from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
    from auc.model import AssistantMessage

    model = InMemoryModelClient(
        responses=[AssistantMessage(content="ok", tool_calls=None)],
    )
    model.model = "auto:quality_first"  # type: ignore[attr-defined]
    # InMemoryModelClient.complete_stream 不产出 resolved_model，这里手动注入到流
    real_stream = model.complete_stream

    async def _stream(messages, tools=None):  # type: ignore[no-untyped-def]
        from auc.model.client import StreamChunk

        yield StreamChunk(resolved_model="deepseek-reasoner")
        async for ch in real_stream(messages, tools=tools):
            yield ch

    model.complete_stream = _stream  # type: ignore[assignment]

    agent = DefaultAgent(
        AgentConfig(agent_id="s", model=model, tools=DefaultToolRegistry()),
    )
    resolved_events = [
        ev.payload async for ev in agent.run_stream("hi") if ev.type == "model_resolved"
    ]
    assert resolved_events
    assert resolved_events[0]["resolved"] == "deepseek-reasoner"
    assert resolved_events[0]["configured"] == "auto:quality_first"
    assert resolved_events[0]["strategy"] == "quality_first"
    # 未标注来源时默认按网关选型展示
    assert resolved_events[0].get("source") == "gateway"


def test_model_resolved_event_marks_local_source() -> None:
    asyncio.run(_run_auto_resolved_local())


async def _run_auto_resolved_local() -> None:
    from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
    from auc.model import AssistantMessage

    model = InMemoryModelClient(
        responses=[AssistantMessage(content="ok", tool_calls=None)],
    )
    model.model = "auto:cost_optimized"  # type: ignore[attr-defined]
    real_stream = model.complete_stream

    async def _stream(messages, tools=None):  # type: ignore[no-untyped-def]
        from auc.model.client import StreamChunk

        # 本地路由：网关无 auto，客户端本地选定并标注 source=local
        yield StreamChunk(resolved_model="gpt-4o-mini", route_source="local")
        async for ch in real_stream(messages, tools=tools):
            yield ch

    model.complete_stream = _stream  # type: ignore[assignment]

    agent = DefaultAgent(
        AgentConfig(agent_id="s", model=model, tools=DefaultToolRegistry()),
    )
    resolved_events = [
        ev.payload async for ev in agent.run_stream("hi") if ev.type == "model_resolved"
    ]
    assert resolved_events
    assert resolved_events[0]["resolved"] == "gpt-4o-mini"
    assert resolved_events[0]["source"] == "local"


def test_model_resolved_event_skipped_for_fixed_model() -> None:
    asyncio.run(_run_fixed_no_resolved())


async def _run_fixed_no_resolved() -> None:
    from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
    from auc.model import AssistantMessage

    model = InMemoryModelClient(
        responses=[AssistantMessage(content="ok", tool_calls=None)],
    )
    model.model = "gpt-4o"  # type: ignore[attr-defined]
    real_stream = model.complete_stream

    async def _stream(messages, tools=None):  # type: ignore[no-untyped-def]
        from auc.model.client import StreamChunk

        yield StreamChunk(resolved_model="gpt-4o-2024-08-06")
        async for ch in real_stream(messages, tools=tools):
            yield ch

    model.complete_stream = _stream  # type: ignore[assignment]

    agent = DefaultAgent(
        AgentConfig(agent_id="s", model=model, tools=DefaultToolRegistry()),
    )
    resolved = [
        ev async for ev in agent.run_stream("hi") if ev.type == "model_resolved"
    ]
    # 非 auto 配置不上报 model_resolved（避免噪声）
    assert resolved == []
