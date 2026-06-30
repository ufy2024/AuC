import asyncio

from auc import (
    AgentConfig,
    ChatMessage,
    DefaultAgent,
    DefaultToolRegistry,
    InMemoryModelClient,
    LoopConfig,
    make_echo_tool,
)
from auc.messages import ToolCall
from auc.model import AssistantMessage


def test_react_two_step_tool_then_answer() -> None:
    asyncio.run(_test_react_two_step_tool_then_answer())


async def _test_react_two_step_tool_then_answer() -> None:
    registry = DefaultToolRegistry()
    echo_tool, pol = make_echo_tool()
    registry.register(echo_tool, pol)

    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(id="tc1", name="echo", arguments={"city": "北京"}),
                ],
            ),
            AssistantMessage(content="北京天气已查询。", tool_calls=None),
        ],
    )

    agent = DefaultAgent(
        AgentConfig(
            agent_id="test",
            model=model,
            tools=registry,
            loop_config=LoopConfig(max_steps=5),
        )
    )
    result = await agent.run("北京天气如何？")

    assert result.status == "completed"
    assert "北京" in result.output
    roles = [m.role for m in result.messages]
    assert "user" in roles
    assert "tool" in roles
    assert "assistant" in roles


def test_run_stream_emits_run_end() -> None:
    asyncio.run(_test_run_stream_emits_run_end())


async def _test_run_stream_emits_run_end() -> None:
    model = InMemoryModelClient(
        responses=[AssistantMessage(content="ok", tool_calls=None)],
    )
    agent = DefaultAgent(
        AgentConfig(agent_id="s", model=model, tools=DefaultToolRegistry()),
    )
    types: list[str] = []
    deltas: list[str] = []
    async for ev in agent.run_stream("hi"):
        types.append(ev.type)
        if ev.type == "model_delta" and ev.payload.get("delta"):
            deltas.append(ev.payload["delta"])
    assert "run_start" in types
    assert "run_end" in types
    assert "".join(deltas) == "ok"
    assert agent.last_run_result is not None
    assert agent.last_run_result.output == "ok"


def test_run_start_carries_model_descriptor() -> None:
    asyncio.run(_test_run_start_carries_model_descriptor())


async def _test_run_start_carries_model_descriptor() -> None:
    model = InMemoryModelClient(
        responses=[AssistantMessage(content="ok", tool_calls=None)],
    )
    # 模拟真实客户端暴露的 .model / .base_url 标识
    model.model = "deepseek-chat"  # type: ignore[attr-defined]
    model.base_url = "http://relay/api"  # type: ignore[attr-defined]
    agent = DefaultAgent(
        AgentConfig(agent_id="s", model=model, tools=DefaultToolRegistry()),
    )
    start_payload: dict | None = None
    async for ev in agent.run_stream("hi"):
        if ev.type == "run_start":
            start_payload = ev.payload
    assert start_payload is not None
    assert start_payload["model"] == "deepseek-chat"
    assert start_payload["base_url"] == "http://relay/api"


def test_run_start_model_descriptor_none_when_absent() -> None:
    asyncio.run(_test_run_start_model_descriptor_none_when_absent())


async def _test_run_start_model_descriptor_none_when_absent() -> None:
    model = InMemoryModelClient(
        responses=[AssistantMessage(content="ok", tool_calls=None)],
    )
    agent = DefaultAgent(
        AgentConfig(agent_id="s", model=model, tools=DefaultToolRegistry()),
    )
    payloads = [ev.payload async for ev in agent.run_stream("hi") if ev.type == "run_start"]
    assert payloads and payloads[0].get("model") is None
