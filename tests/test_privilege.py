import asyncio

from auc import (
    AgentConfig,
    AutoApprovePort,
    DefaultAgent,
    DefaultToolRegistry,
    DenyApprovalPort,
    InMemoryModelClient,
    ToolPrivilegeGate,
)
from auc.tools import tool_from_function
from auc.messages import ToolCall
from auc.model import AssistantMessage
async def git_push(remote: str = "origin") -> str:
    return f"pushed to {remote}"


def test_l3_auto_approve() -> None:
    asyncio.run(_test_l3_auto_approve())


async def _test_l3_auto_approve() -> None:
    registry = DefaultToolRegistry()
    t, pol = tool_from_function(git_push, name="git_push", privilege="L3")
    registry.register(t, pol)

    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(id="1", name="git_push", arguments={"remote": "origin"}),
                ],
            ),
            AssistantMessage(content="done", tool_calls=None),
        ],
    )
    agent = DefaultAgent(
        AgentConfig(
            agent_id="a",
            model=model,
            tools=registry,
            approval=AutoApprovePort(),
            privilege_gate=ToolPrivilegeGate(approval=AutoApprovePort()),
        )
    )
    result = await agent.run("push")
    assert result.status == "completed"


def test_l3_denied() -> None:
    asyncio.run(_test_l3_denied())


async def _test_l3_denied() -> None:
    registry = DefaultToolRegistry()
    t, pol = tool_from_function(git_push, name="git_push", privilege="L3")
    registry.register(t, pol)

    approval = DenyApprovalPort()
    model = InMemoryModelClient(
        responses=[
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(id="1", name="git_push", arguments={}),
                ],
            ),
        ],
    )
    agent = DefaultAgent(
        AgentConfig(
            agent_id="a",
            model=model,
            tools=registry,
            approval=approval,
            privilege_gate=ToolPrivilegeGate(approval=approval),
        )
    )
    result = await agent.run("push")
    assert result.status in ("denied", "cancelled")
