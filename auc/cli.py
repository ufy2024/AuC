from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
from auc.config import (
    ModelConfig,
    config_template_for_provider,
    default_config_path,
    discover_config_layers,
    discover_config_path,
    load_merged_settings,
    load_model_config,
    migrate_yaml_to_json,
    mask_settings_secrets,
    model_config_to_settings_dict,
    save_config_file,
)
from auc.integration import AuMStack, ConsoleApprovalPort, SemanticSlicer, SpecialistRegistry, SpecialistSpec
from auc.integration.telegram import TelegramApprovalPort
from auc.messages import ChatMessage, RunRequest, RunResult
from auc.model import AssistantMessage
from auc.model.factory import aclose_model_client, create_model_client
from auc.policy import ToolPrivilegeGate
from auc.ports import FileRulesPort, SlicerPolicy
from auc.stream_display import ChatStreamPrinter
from auc.tools import make_echo_tool


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        "-c",
        help="Settings JSON path (default: ~/.Au/AuC/settings.json)",
    )
    parser.add_argument(
        "--provider",
        "-p",
        choices=("openai", "anthropic", "deepseek"),
        help="LLM provider (overrides file/env)",
    )
    parser.add_argument("--model", "-m", help="Model id")
    parser.add_argument("--api-key", help="API key (overrides env/file)")
    parser.add_argument("--base-url", help="API base URL")
    parser.add_argument("--timeout", type=float, help="HTTP timeout seconds")
    parser.add_argument("--max-tokens", type=int, help="Max output tokens (anthropic)")


def _resolve_cfg(args: argparse.Namespace) -> ModelConfig:
    repo = getattr(args, "repo", None) or None
    return load_model_config(
        config_path=getattr(args, "config", None),
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        api_key=getattr(args, "api_key", None),
        base_url=getattr(args, "base_url", None),
        timeout=getattr(args, "timeout", None),
        max_tokens=getattr(args, "max_tokens", None),
        repo_root=repo if repo else None,
    )


def _chat_banner(cfg: ModelConfig) -> str:
    label = cfg.config_name or cfg.config_id or cfg.model
    return f"AuC · {label} ({cfg.provider}/{cfg.model})"


async def _print_chat_result(
    result,
    cfg: ModelConfig,
    *,
    as_json: bool,
) -> int:
    if as_json:
        print(
            json.dumps(
                {
                    "status": result.status,
                    "output": result.output,
                    "provider": cfg.provider,
                    "model": cfg.model,
                    "configName": cfg.config_name,
                    "configId": cfg.config_id,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(result.output)
    return 0 if result.status == "completed" else 1


async def _consume_chat_stream(
    agent: DefaultAgent,
    req: RunRequest,
    args: argparse.Namespace,
) -> tuple[int, RunResult | None]:
    if getattr(args, "stream_events", False):
        async for ev in agent.run_stream(req):
            print(
                json.dumps(
                    {"type": ev.type, "payload": ev.payload},
                    ensure_ascii=False,
                )
            )
        result = agent.last_run_result
        return (0 if result and result.status == "completed" else 1), result

    printer = ChatStreamPrinter(show_tools=not args.no_tools)
    async for ev in agent.run_stream(req):
        printer.feed(ev)
    printer.finish_line()
    result = agent.last_run_result
    if result is None:
        return 1, None
    code = 0 if result.status == "completed" else 1
    return code, result


async def _run_chat_turn(
    agent: DefaultAgent,
    cfg: ModelConfig,
    args: argparse.Namespace,
    message: str,
    history: list[ChatMessage],
) -> tuple[int, list[ChatMessage]]:
    meta = {"repo_root": args.repo} if args.repo else {}
    history = [*history, ChatMessage(role="user", content=message)]
    req = RunRequest(input=history, metadata=meta)

    if args.no_stream:
        result = await agent.run(req)
        code = await _print_chat_result(result, cfg, as_json=args.json)
        return code, list(result.messages)

    code, result = await _consume_chat_stream(agent, req, args)
    if result is None:
        return code, history
    if args.json and result:
        print(
            json.dumps(
                {
                    "status": result.status,
                    "output": result.output,
                    "provider": cfg.provider,
                    "model": cfg.model,
                    "configName": cfg.config_name,
                    "configId": cfg.config_id,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return code, list(result.messages)


async def _run_chat_interactive(
    agent: DefaultAgent,
    cfg: ModelConfig,
    args: argparse.Namespace,
) -> int:
    print(_chat_banner(cfg))
    print("交互模式：输入消息后回车；exit / quit 或 Ctrl+D 退出")
    history: list[ChatMessage] = []
    while True:
        try:
            line = await asyncio.to_thread(input, "you> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        text = line.strip()
        if not text:
            continue
        if text.lower() in ("exit", "quit", "/exit", "/quit", "q"):
            break
        code, history = await _run_chat_turn(agent, cfg, args, text, history)
        if code != 0:
            return code
    return 0


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
        message = args.message
        if message is None and not sys.stdin.isatty():
            message = sys.stdin.read().strip()
        if message is None:
            return await _run_chat_interactive(agent, cfg, args)
        code, _ = await _run_chat_turn(agent, cfg, args, message, [])
        return code
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


def _resolve_config_path_arg(path: str | None) -> Path:
    return Path(path).expanduser() if path else default_config_path()


def _cmd_config_init(args: argparse.Namespace) -> int:
    path = _resolve_config_path_arg(args.path)
    if path.suffix not in (".json",):
        path = path.with_suffix(".json")
    if path.exists() and not args.force:
        print(f"exists: {path} (use --force to overwrite)", file=sys.stderr)
        return 1
    if args.force and path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    from auc.config import config_template_dict

    data = config_template_dict(args.provider)
    if getattr(args, "config_name", None):
        data["configName"] = args.config_name
    if getattr(args, "config_id", None):
        data["configId"] = args.config_id
    if getattr(args, "description", None):
        data["description"] = args.description
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"written: {path}")
    return 0


def _cmd_config_show(args: argparse.Namespace) -> int:
    repo = Path(args.repo) if getattr(args, "repo", None) else None
    layers = discover_config_layers(args.config, repo)
    merged, _ = load_merged_settings(args.config, repo)
    cfg = load_model_config(config_path=args.config, repo_root=str(repo) if repo else None)
    effective = mask_settings_secrets(model_config_to_settings_dict(cfg))
    out = {
        "effective": effective,
        "layers": [str(p) for p in layers],
        "merged": mask_settings_secrets(merged),
        "processEnv": {
            "AUC_PROVIDER": os.environ.get("AUC_PROVIDER"),
            "AUC_MODEL": os.environ.get("AUC_MODEL"),
            "AUC_CONFIG": os.environ.get("AUC_CONFIG"),
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _cmd_config_migrate(args: argparse.Namespace) -> int:
    path = migrate_yaml_to_json(remove_yaml=args.remove_yaml)
    if path is None:
        print("no config.yaml to migrate", file=sys.stderr)
        return 1
    print(f"migrated: {path}")
    return 0


def _cmd_config_set(args: argparse.Namespace) -> int:
    path = _resolve_config_path_arg(args.path)
    if path.suffix not in (".json",):
        path = path.with_suffix(".json")
    existing = load_model_config(config_path=str(path) if path.is_file() else None)
    cfg = ModelConfig(
        provider=args.provider or existing.provider,
        model=args.model or existing.model,
        api_key=args.api_key or existing.api_key,
        base_url=args.base_url or existing.base_url,
        timeout=existing.timeout,
        max_tokens=existing.max_tokens,
        config_name=getattr(args, "config_name", None) or existing.config_name,
        config_id=getattr(args, "config_id", None) or existing.config_id,
        description=getattr(args, "description", None) or existing.description,
    )
    save_config_file(path, cfg, overwrite=True)
    print(f"updated: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auc",
        description="AuC agent CLI — OpenAI / Anthropic / DeepSeek via ~/.Au/AuC/settings.json",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # chat — primary LLM entry
    p_chat = sub.add_parser("chat", help="Run agent with configured LLM")
    p_chat.add_argument(
        "message",
        nargs="?",
        default=None,
        help="用户消息；省略则进入交互模式（或从管道读取 stdin）",
    )
    p_chat.add_argument("--repo", default="", help="Repo root for .aurules")
    p_chat.add_argument("--system", default=None)
    p_chat.add_argument(
        "--no-stream",
        action="store_true",
        help="关闭流式输出，等待完整回复后一次性打印",
    )
    p_chat.add_argument(
        "--stream-events",
        action="store_true",
        help="输出原始 JSON 事件流（调试）",
    )
    p_chat.add_argument("--json", action="store_true", help="结束时打印 JSON 结果")
    p_chat.add_argument("--no-tools", action="store_true")
    p_chat.add_argument("--approval", choices=("console",), default=None)
    _add_model_args(p_chat)

    # config
    p_cfg = sub.add_parser("config", help="Manage model configuration file")
    cfg_sub = p_cfg.add_subparsers(dest="config_cmd", required=True)

    p_init = cfg_sub.add_parser(
        "init", help="Write ~/.Au/AuC/settings.json (Claude Code style)"
    )
    p_init.add_argument(
        "--path",
        default=None,
        help="Output path (default: ~/.Au/AuC/settings.json)",
    )
    p_init.add_argument(
        "--provider",
        choices=("openai", "anthropic", "deepseek"),
        default="deepseek",
    )
    p_init.add_argument("--force", action="store_true")
    p_init.add_argument("--config-name", help="配置显示名 configName")
    p_init.add_argument("--config-id", help="配置唯一标识 configId")
    p_init.add_argument("--description", help="配置说明 description")

    p_show = cfg_sub.add_parser("show", help="Show merged settings as JSON")
    p_show.add_argument("--config", "-c", default=None)
    p_show.add_argument("--repo", default="", help="Project root for .auc/settings.json")

    p_migrate = cfg_sub.add_parser(
        "migrate", help="Migrate config.yaml → settings.json"
    )
    p_migrate.add_argument(
        "--remove-yaml", action="store_true", help="Delete config.yaml after migrate"
    )

    p_set = cfg_sub.add_parser("set", help="Update settings.json")
    p_set.add_argument(
        "--path",
        default=None,
        help="Settings path (default: ~/.Au/AuC/settings.json)",
    )
    p_set.add_argument("--provider", choices=("openai", "anthropic", "deepseek"))
    p_set.add_argument("--model")
    p_set.add_argument("--api-key")
    p_set.add_argument("--base-url")
    p_set.add_argument("--config-name")
    p_set.add_argument("--config-id")
    p_set.add_argument("--description")

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
        if args.config_cmd == "migrate":
            return _cmd_config_migrate(args)
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
