from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
from auc.config import (
    DEFAULT_CONFIG_TEMPLATE,
    ModelConfig,
    discover_config_path,
    load_model_config,
    save_config_file,
)
from auc.integration import AuMStack, ConsoleApprovalPort, SemanticSlicer, SpecialistRegistry, SpecialistSpec
from auc.integration.telegram import TelegramApprovalPort
from auc.messages import RunRequest
from auc.model import AssistantMessage
from auc.model.factory import aclose_model_client, create_model_client
from auc.policy import ToolPrivilegeGate
from auc.ports import FileRulesPort, SlicerPolicy
from auc.tools import make_echo_tool


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        "-c",
        help="Config file path (.auc.yaml or ~/.config/auc/config.yaml)",
    )
    parser.add_argument(
        "--provider",
        "-p",
        choices=("openai", "anthropic"),
        help="LLM provider (overrides file/env)",
    )
    parser.add_argument("--model", "-m", help="Model id")
    parser.add_argument("--api-key", help="API key (overrides env/file)")
    parser.add_argument("--base-url", help="API base URL")
    parser.add_argument("--timeout", type=float, help="HTTP timeout seconds")
    parser.add_argument("--max-tokens", type=int, help="Max output tokens (anthropic)")


def _resolve_cfg(args: argparse.Namespace) -> ModelConfig:
    return load_model_config(
        config_path=getattr(args, "config", None),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        api_key=getattr(args, "api_key", None),
        base_url=getattr(args, "base_url", None),
        timeout=getattr(args, "timeout", None),
        max_tokens=getattr(args, "max_tokens", None),
    )


async def _run_chat(args: argparse.Namespace) -> int:
    cfg = _resolve_cfg(args)
    registry = DefaultToolRegistry()
    if not args.no_tools:
        tool, pol = make_echo_tool()
        registry.register(tool, pol)

    model = create_model_client(cfg)
    approval = ConsoleApprovalPort() if args.approval == "console" else None
    try:
        agent = DefaultAgent(
            AgentConfig(
                agent_id="cli-chat",
                model=model,
                tools=registry,
                rules=FileRulesPort() if args.repo else None,
                approval=approval,
                privilege_gate=ToolPrivilegeGate(approval=approval) if approval else None,
                slicer_policy=SlicerPolicy(require_package=False),
                system_prompt=args.system,
            )
        )
        req = RunRequest(
            input=args.message,
            metadata={"repo_root": args.repo} if args.repo else {},
        )
        if args.stream:
            async for ev in agent.run_stream(req):
                print(
                    json.dumps(
                        {"type": ev.type, "payload": ev.payload},
                        ensure_ascii=False,
                    )
                )
            return 0
        result = await agent.run(req)
        if args.json:
            print(
                json.dumps(
                    {
                        "status": result.status,
                        "output": result.output,
                        "provider": cfg.provider,
                        "model": cfg.model,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(result.output)
        return 0 if result.status == "completed" else 1
    finally:
        await aclose_model_client(model)


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


async def _run_dispatch(args: argparse.Namespace) -> int:
    registry = SpecialistRegistry()
    reg = DefaultToolRegistry()
    tool, pol = make_echo_tool()
    reg.register(tool, pol)
    model_cfg = _resolve_cfg(args)

    def _build_config() -> AgentConfig:
        return AgentConfig(
            agent_id="default",
            model=create_model_client(model_cfg),
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


def _cmd_config_init(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    if path.exists() and not args.force:
        print(f"exists: {path} (use --force to overwrite)", file=sys.stderr)
        return 1
    if args.force and path.exists():
        path.unlink()
    if args.provider == "anthropic":
        path.write_text(
            DEFAULT_CONFIG_TEMPLATE.replace(
                "provider: openai",
                "provider: anthropic",
            )
            .replace("gpt-4o-mini", "claude-sonnet-4-20250514")
            .replace("OPENAI_API_KEY", "ANTHROPIC_API_KEY")
            .replace("https://api.openai.com/v1", "https://api.anthropic.com"),
            encoding="utf-8",
        )
    else:
        path.write_text(DEFAULT_CONFIG_TEMPLATE, encoding="utf-8")
    print(f"written: {path}")
    return 0


def _cmd_config_show(args: argparse.Namespace) -> int:
    cfg = load_model_config(config_path=args.config)
    print(
        json.dumps(
            {
                "config_path": cfg.config_path or discover_config_path(args.config),
                "provider": cfg.provider,
                "model": cfg.model,
                "api_key": cfg.masked_api_key(),
                "base_url": cfg.base_url,
                "timeout": cfg.timeout,
                "max_tokens": cfg.max_tokens,
                "env": {
                    "AUC_PROVIDER": os.environ.get("AUC_PROVIDER"),
                    "AUC_MODEL": os.environ.get("AUC_MODEL"),
                    "AUC_BASE_URL": os.environ.get("AUC_BASE_URL"),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_config_set(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser()
    existing = load_model_config(config_path=str(path) if path.is_file() else None)
    cfg = ModelConfig(
        provider=args.provider or existing.provider,
        model=args.model or existing.model,
        api_key=args.api_key or existing.api_key,
        base_url=args.base_url or existing.base_url,
        timeout=existing.timeout,
        max_tokens=existing.max_tokens,
    )
    save_config_file(path, cfg, overwrite=True)
    print(f"updated: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auc",
        description="AuC agent CLI — configure OpenAI or Anthropic via file/env/flags",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # chat — primary LLM entry
    p_chat = sub.add_parser("chat", help="Run agent with configured LLM (openai/anthropic)")
    p_chat.add_argument("message", help="User message")
    p_chat.add_argument("--repo", default="", help="Repo root for .aurules")
    p_chat.add_argument("--system", default=None)
    p_chat.add_argument("--stream", action="store_true")
    p_chat.add_argument("--json", action="store_true", help="Print JSON result")
    p_chat.add_argument("--no-tools", action="store_true")
    p_chat.add_argument("--approval", choices=("console",), default=None)
    _add_model_args(p_chat)

    # config
    p_cfg = sub.add_parser("config", help="Manage model configuration file")
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)

    p_init = cfg_sub.add_parser("init", help="Write example .auc.yaml")
    p_init.add_argument(
        "--path",
        default=".auc.yaml",
        help="Output path (default: ./.auc.yaml)",
    )
    p_init.add_argument(
        "--provider",
        choices=("openai", "anthropic"),
        default="openai",
    )
    p_init.add_argument("--force", action="store_true")

    p_show = cfg_sub.add_parser("show", help="Show merged configuration")
    p_show.add_argument("--config", "-c", default=None)

    p_set = cfg_sub.add_parser("set", help="Update configuration file")
    p_set.add_argument("--path", default=".auc.yaml")
    p_set.add_argument("--provider", choices=("openai", "anthropic"))
    p_set.add_argument("--model")
    p_set.add_argument("--api-key")
    p_set.add_argument("--base-url")

    # backward compatible openai subcommand
    p_oai = sub.add_parser("openai", help="Alias for: auc chat --provider openai")
    p_oai.add_argument("message")
    p_oai.add_argument("--system", default=None)
    _add_model_args(p_oai)

    p_run = sub.add_parser("run", help="Run with scripted in-memory model (no API)")
    p_run.add_argument("message")
    p_run.add_argument("--reply", default="Hello from AuC CLI.")
    p_run.add_argument("--repo", default="")
    p_run.add_argument("--system", default=None)
    p_run.add_argument("--stream", action="store_true")
    p_run.add_argument("--approval", choices=("console",), default=None)

    p_slice = sub.add_parser("slice", help="Preview ContextPackage")
    p_slice.add_argument("intent")
    p_slice.add_argument("--repo", required=True)

    p_disp = sub.add_parser("dispatch", help="AuM-style dispatch")
    p_disp.add_argument("intent")
    p_disp.add_argument("message")
    p_disp.add_argument("--repo", required=True)
    p_disp.add_argument("--specialist", default=None)
    p_disp.add_argument("--nuggets", default=None)
    p_disp.add_argument("--approval", choices=("console", "telegram"), default="console")
    p_disp.add_argument("--no-require-package", action="store_true")
    _add_model_args(p_disp)

    args = parser.parse_args(argv)

    if args.cmd == "config":
        if args.config_cmd == "init":
            return _cmd_config_init(args)
        if args.config_cmd == "show":
            return _cmd_config_show(args)
        if args.config_cmd == "set":
            return _cmd_config_set(args)

    if args.cmd == "slice":
        pkg = asyncio.run(SemanticSlicer().slice(args.intent, args.repo))
        print(json.dumps({"package_id": pkg.package_id, "snippets": len(pkg.snippets)}, indent=2))
        return 0

    if args.cmd == "openai":
        args.provider = "openai"
        if not args.model:
            args.model = "gpt-4o-mini"
        return asyncio.run(_run_chat(args))

    if args.cmd == "chat":
        return asyncio.run(_run_chat(args))
    if args.cmd == "dispatch":
        return asyncio.run(_run_dispatch(args))
    return asyncio.run(_run_scripted(args))


if __name__ == "__main__":
    sys.exit(main())
