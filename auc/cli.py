from __future__ import annotations

import argparse
import asyncio
import json
import sys

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
from auc.integration import AuMStack, ConsoleApprovalPort, SemanticSlicer, SpecialistRegistry, SpecialistSpec
from auc.integration.telegram import TelegramApprovalPort
from auc.messages import RunRequest
from auc.model import AssistantMessage
from auc.policy import ToolPrivilegeGate
from auc.ports import FileRulesPort, SlicerPolicy
from auc.tools import make_echo_tool, register_function_tools


async def _run_scripted(args: argparse.Namespace) -> int:
    registry = DefaultToolRegistry()
    tool, pol = make_echo_tool()
    registry.register(tool, pol)
    model = InMemoryModelClient(
        responses=[
            AssistantMessage(content=args.reply or "Hello from AuC CLI.", tool_calls=None),
        ],
    )
    approval = ConsoleApprovalPort() if args.approval == "console" else None
    agent = DefaultAgent(
        AgentConfig(
            agent_id="cli",
            model=model,
            tools=registry,
            rules=FileRulesPort() if args.repo else None,
            approval=approval,
            privilege_gate=ToolPrivilegeGate(approval=approval) if approval else None,
            slicer_policy=SlicerPolicy(require_package=False),
            system_prompt=args.system,
        )
    )
    req = RunRequest(input=args.message, metadata={"repo_root": args.repo} if args.repo else {})
    if args.stream:
        async for ev in agent.run_stream(req):
            print(json.dumps({"type": ev.type, "payload": ev.payload}, ensure_ascii=False))
        return 0
    result = await agent.run(req)
    print(json.dumps({"status": result.status, "output": result.output}, ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 1


async def _run_openai(args: argparse.Namespace) -> int:
    from auc.model.openai import OpenAICompatibleClient

    registry = DefaultToolRegistry()
    tool, pol = make_echo_tool()
    registry.register(tool, pol)
    model = OpenAICompatibleClient(model=args.model)
    try:
        agent = DefaultAgent(
            AgentConfig(
                agent_id="cli-openai",
                model=model,
                tools=registry,
                system_prompt=args.system,
            )
        )
        result = await agent.run(args.message)
        print(result.output)
        return 0 if result.status == "completed" else 1
    finally:
        await model.aclose()


async def _run_dispatch(args: argparse.Namespace) -> int:
    registry = SpecialistRegistry()
    reg = DefaultToolRegistry()
    tool, pol = make_echo_tool()
    reg.register(tool, pol)

    def _build_config() -> AgentConfig:
        return AgentConfig(
            agent_id="default",
            model=InMemoryModelClient(
                responses=[AssistantMessage(content="dispatched ok", tool_calls=None)]
            ),
            tools=reg,
        )

    registry.register(
        SpecialistSpec(agent_id="default", tags=["default"], config_builder=_build_config),
        default=True,
    )
    approval: ConsoleApprovalPort | TelegramApprovalPort
    if args.approval == "telegram":
        approval = TelegramApprovalPort()
    else:
        approval = ConsoleApprovalPort()

    stack = AuMStack.create(
        registry=registry,
        approval=approval,
        nuggets_path=args.nuggets,
        require_package=not args.no_require_package,
    )
    result = await stack.dispatcher.dispatch(
        args.intent,
        args.message,
        repo_root=args.repo,
        specialist_id=args.specialist,
    )
    print(json.dumps({"status": result.status, "output": result.output}, ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auc", description="AuC agent CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run with scripted in-memory model")
    p_run.add_argument("message", help="User message")
    p_run.add_argument("--reply", default="Hello from AuC CLI.")
    p_run.add_argument("--repo", default="", help="Repo root for .aurules")
    p_run.add_argument("--system", default=None)
    p_run.add_argument("--stream", action="store_true")
    p_run.add_argument("--approval", choices=("console",), default=None)

    p_oai = sub.add_parser("openai", help="Run with OpenAI-compatible API")
    p_oai.add_argument("message")
    p_oai.add_argument("--model", default="gpt-4o-mini")
    p_oai.add_argument("--system", default=None)

    p_slice = sub.add_parser("slice", help="Preview ContextPackage from SemanticSlicer")
    p_slice.add_argument("intent")
    p_slice.add_argument("--repo", required=True)

    p_disp = sub.add_parser("dispatch", help="AuM-style dispatch with slicer + specialist")
    p_disp.add_argument("intent", help="Task intent for slicing/routing")
    p_disp.add_argument("message", help="User message to agent")
    p_disp.add_argument("--repo", required=True)
    p_disp.add_argument("--specialist", default=None)
    p_disp.add_argument("--nuggets", default=None, help="Path to au-nuggets.yaml")
    p_disp.add_argument("--approval", choices=("console", "telegram"), default="console")
    p_disp.add_argument("--no-require-package", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "slice":
        pkg = asyncio.run(SemanticSlicer().slice(args.intent, args.repo))
        print(
            json.dumps(
                {
                    "package_id": pkg.package_id,
                    "intent_summary": pkg.intent_summary,
                    "snippets": [
                        {"path": s.path, "lines": s.line_range} for s in pkg.snippets
                    ],
                    "token_estimate": pkg.token_estimate,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.cmd == "openai":
        return asyncio.run(_run_openai(args))
    if args.cmd == "dispatch":
        return asyncio.run(_run_dispatch(args))
    return asyncio.run(_run_scripted(args))


if __name__ == "__main__":
    sys.exit(main())
