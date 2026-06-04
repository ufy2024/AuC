"""Minimal AuC ReAct run with scripted model + echo tool."""

import asyncio

from auc import (
    AgentConfig,
    DefaultAgent,
    DefaultToolRegistry,
    InMemoryModelClient,
    LoopConfig,
    make_echo_tool,
)
from auc.messages import ToolCall
from auc.model import AssistantMessage


async def main() -> None:
    registry = DefaultToolRegistry()
    tool, pol = make_echo_tool()
    registry.register(tool, pol)

    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(id="1", name="echo", arguments={"msg": "hello auc"}),
                ],
            ),
            AssistantMessage(content="Echo completed.", tool_calls=None),
        ],
    )

    agent = DefaultAgent(
        AgentConfig(
            agent_id="demo",
            model=model,
            tools=registry,
            system_prompt="You are a concise assistant.",
            loop_config=LoopConfig(max_steps=10),
        )
    )

    result = await agent.run("Say hello via echo tool.")
    print("status:", result.status)
    print("output:", result.output)
    print("messages:", len(result.messages))


if __name__ == "__main__":
    asyncio.run(main())
