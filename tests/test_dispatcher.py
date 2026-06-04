import asyncio
from pathlib import Path

from auc import AgentConfig, DefaultToolRegistry, InMemoryModelClient
from auc.integration import AuMStack, SpecialistRegistry, SpecialistSpec
from auc.integration.telegram import InMemoryCallbackApprovalPort
from auc.model import AssistantMessage


def test_aum_stack_dispatch() -> None:
    repo = Path(__file__).parent / "fixtures" / "sample_repo"
    nuggets = Path(__file__).parent / "fixtures" / "au-nuggets.yaml"
    reg = DefaultToolRegistry()
    approval = InMemoryCallbackApprovalPort()

    def build() -> AgentConfig:
        return AgentConfig(
            agent_id="quant",
            model=InMemoryModelClient(
                responses=[AssistantMessage(content="done", tool_calls=None)]
            ),
            tools=reg,
        )

    registry = SpecialistRegistry()
    registry.register(
        SpecialistSpec(agent_id="quant", tags=["stop_loss", "quant"], config_builder=build),
        default=True,
    )
    stack = AuMStack.create(
        registry=registry,
        approval=approval,
        nuggets_path=str(nuggets),
        require_package=True,
    )

    async def _go():
        return await stack.dispatcher.dispatch(
            "modify stop_loss",
            "update threshold",
            repo_root=str(repo),
        )

    result = asyncio.run(_go())
    assert result.status == "completed"
    assert result.output == "done"
