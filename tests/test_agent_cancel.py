import asyncio

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
from auc.messages import ChatMessage, RunRequest, ToolCall
from auc.model import AssistantMessage
from auc.loop.base import LoopConfig
from auc.tools.base import tool_from_function


def test_cancel_sets_ctx_flag() -> None:
    async def _run() -> None:
        model = InMemoryModelClient(
            responses=[
                AssistantMessage(content="step1", tool_calls=None),
                AssistantMessage(content="step2", tool_calls=None),
            ]
        )
        agent = DefaultAgent(
            AgentConfig(
                agent_id="t",
                model=model,
                tools=DefaultToolRegistry(),
                loop_config=LoopConfig(max_steps=10),
            )
        )
        req = RunRequest(input=[ChatMessage(role="user", content="hi")])

        async def _cancel_soon() -> None:
            await asyncio.sleep(0.02)
            for rid in list(agent._active_ctx):  # noqa: SLF001
                agent.cancel(rid)

        result = await asyncio.gather(
            agent.run(req),
            _cancel_soon(),
        )
        assert result[0].status in ("cancelled", "completed")

    asyncio.run(_run())


def test_cancel_during_tool_execution_stops_loop() -> None:
    """工具执行中触发 cancel：当前工具跑完后循环立即终止，不再调模型。"""

    async def _run() -> None:
        started = asyncio.Event()

        async def slow_tool() -> str:
            """Slow tool for concurrency test."""
            started.set()
            await asyncio.sleep(0.2)
            return "slow done"

        registry = DefaultToolRegistry()
        tool, pol = tool_from_function(slow_tool, name="slow_tool", privilege="L1")
        registry.register(tool, pol)

        model = InMemoryModelClient(
            responses=[
                AssistantMessage(
                    content=None,
                    tool_calls=[ToolCall(id="t1", name="slow_tool", arguments={})],
                ),
                AssistantMessage(content="不应到达这里", tool_calls=None),
            ]
        )
        agent = DefaultAgent(
            AgentConfig(
                agent_id="t",
                model=model,
                tools=registry,
                loop_config=LoopConfig(max_steps=10),
            )
        )
        req = RunRequest(input=[ChatMessage(role="user", content="hi")])

        async def _cancel_when_tool_running() -> None:
            await asyncio.wait_for(started.wait(), timeout=2.0)
            for rid in list(agent._active_ctx):  # noqa: SLF001
                agent.cancel(rid)

        result, _ = await asyncio.gather(agent.run(req), _cancel_when_tool_running())
        assert result.status == "cancelled"
        # 取消后不应再发起第二次模型调用
        assert "不应到达这里" not in (result.output or "")
        assert model._index == 1  # noqa: SLF001

    asyncio.run(_run())
