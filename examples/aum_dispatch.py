"""AuM-style dispatch: slicer + nuggets + specialist registry."""

import asyncio
from pathlib import Path

from auc import AgentConfig, DefaultToolRegistry, InMemoryModelClient
from auc.integration import AuMStack, SpecialistRegistry, SpecialistSpec
from auc.integration.telegram import ConsoleApprovalPort
from auc.model import AssistantMessage

ROOT = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "sample_repo"
NUGGETS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "au-nuggets.yaml"


async def main() -> None:
    tools = DefaultToolRegistry()

    def build_config() -> AgentConfig:
        return AgentConfig(
            agent_id="quant",
            model=InMemoryModelClient(
                responses=[AssistantMessage(content="止损逻辑已更新。", tool_calls=None)]
            ),
            tools=tools,
        )

    registry = SpecialistRegistry()
    registry.register(
        SpecialistSpec(
            agent_id="quant",
            tags=["stop_loss", "quant"],
            description="量化风控专家",
            config_builder=build_config,
        ),
        default=True,
    )

    stack = AuMStack.create(
        registry=registry,
        approval=ConsoleApprovalPort(),
        nuggets_path=str(NUGGETS),
        require_package=True,
    )
    result = await stack.dispatcher.dispatch(
        intent="修改 stop_loss 阈值",
        message="将默认 pct 调整为 0.03",
        repo_root=str(ROOT),
    )
    print("status:", result.status)
    print("output:", result.output)


if __name__ == "__main__":
    asyncio.run(main())
