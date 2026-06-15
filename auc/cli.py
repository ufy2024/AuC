from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path

from auc.terminal import dim, yellow

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient
from auc.tools import make_echo_tool
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
from auc.integration.qq import QQApprovalPort
from auc.integration.telegram import TelegramApprovalPort
from auc.messages import ChatMessage, RunRequest, RunResult
from auc.model import AssistantMessage
from auc.model.factory import aclose_model_client, create_model_client
from auc.policy import ToolPrivilegeGate
from auc.ports import FileRulesPort, SlicerPolicy
from auc.integration.evolution import EvolutionMemoryPort, make_evolution_tools
from auc.cli_ui import ClaudeCodeStreamPrinter, StreamSpinner, run_interactive_repl
from auc.tools.files import make_file_tools

from auc.chat_agent import build_chat_system_prompt
from auc.roles import DEFAULT_ROLE_ID, load_role_catalog


def _chat_sandbox_root(args: argparse.Namespace) -> str:
    if getattr(args, "sandbox", None):
        return str(Path(args.sandbox).expanduser().resolve())
    if getattr(args, "repo", None):
        return str(Path(args.repo).expanduser().resolve())
    return str(Path.cwd().resolve())


def _chat_settings(args: argparse.Namespace) -> dict:
    try:
        from auc.config import load_merged_settings

        settings, _ = load_merged_settings(
            getattr(args, "config", None),
            Path(args.repo) if getattr(args, "repo", None) else None,
        )
        return settings
    except Exception:  # noqa: BLE001
        return {}


def _chat_catalog(args: argparse.Namespace, sandbox: str):
    return load_role_catalog(sandbox=sandbox, settings=_chat_settings(args))


def _chat_memory(
    sandbox_root: str, evolve: bool, *, role_id: str = DEFAULT_ROLE_ID
) -> EvolutionMemoryPort | None:
    if not evolve:
        return None
    return EvolutionMemoryPort(sandbox_root=sandbox_root, default_role_id=role_id)


def _register_chat_tools(
    registry: DefaultToolRegistry,
    sandbox_root: str,
    memory: EvolutionMemoryPort | None = None,
) -> None:
    from auc.tools.roles import make_role_tools
    from auc.tools.search import make_search_tools
    from auc.tools.shell import make_shell_tool

    for tool, pol in make_file_tools(sandbox_root):
        registry.register(tool, pol)
    shell_tool, shell_pol = make_shell_tool(sandbox_root)
    registry.register(shell_tool, shell_pol)
    for tool, pol in make_search_tools(sandbox_root):
        registry.register(tool, pol)
    if memory is not None:
        for tool, pol in make_evolution_tools(memory):
            registry.register(tool, pol)
    for tool, pol in make_role_tools(sandbox_root):
        registry.register(tool, pol)


def _chat_role_id(args: argparse.Namespace, catalog=None) -> str:
    cat = catalog or getattr(args, "_role_catalog", None)
    if cat is None:
        cat = _chat_catalog(args, _chat_sandbox_root(args))
    raw = getattr(args, "role", None) or cat.default_role_id
    return cat.resolve(raw)


def _chat_system_prompt(
    args: argparse.Namespace, sandbox: str, catalog=None
) -> str:
    if args.system:
        return args.system
    cat = catalog or getattr(args, "_role_catalog", None) or _chat_catalog(args, sandbox)
    return build_chat_system_prompt(
        sandbox, role_id=_chat_role_id(args, cat), catalog=cat
    )


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


def _print_run_failure(result: RunResult | None) -> None:
    if result is None:
        print("\n[失败] 未收到运行结果", file=sys.stderr)
        return
    print(f"\n[失败] status={result.status}", file=sys.stderr)
    if result.error:
        print(f"原因: {result.error}", file=sys.stderr)


async def _consume_chat_stream(
    agent: DefaultAgent,
    req: RunRequest,
    args: argparse.Namespace,
) -> tuple[int, RunResult | None, int]:
    if getattr(args, "stream_events", False):
        async for ev in agent.run_stream(req):
            print(
                json.dumps(
                    {"type": ev.type, "payload": ev.payload},
                    ensure_ascii=False,
                )
            )
        result = agent.last_run_result
        ok = result and result.status == "completed"
        return (0 if ok else 1), result, 0

    printer = ClaudeCodeStreamPrinter(show_tools=not args.no_tools)
    spinner = StreamSpinner()
    run_id: str | None = None
    interrupt_count = 0
    loop = asyncio.get_running_loop()
    use_signals = sys.platform != "win32" and loop.add_signal_handler is not None

    def _on_sigint() -> None:
        nonlocal interrupt_count, run_id
        interrupt_count += 1
        if run_id and interrupt_count == 1:
            agent.cancel(run_id)
            sys.stdout.write(yellow("\n  ⊘ 取消中…\n"))
            sys.stdout.flush()
        elif interrupt_count >= 2:
            raise KeyboardInterrupt

    if use_signals:
        try:
            loop.add_signal_handler(signal.SIGINT, _on_sigint)
        except (NotImplementedError, RuntimeError):
            use_signals = False

    await spinner.start()
    try:
        async for ev in agent.run_stream(req):
            if ev.type == "run_start":
                run_id = ev.run_id
            await spinner.stop()
            printer.feed(ev)
    finally:
        await spinner.stop()
        printer.finish_reply()
        if use_signals:
            loop.remove_signal_handler(signal.SIGINT)

    result = agent.last_run_result
    if result is None:
        return 1, None, printer.tool_count
    ok = result.status in ("completed", "cancelled")
    code = 0 if ok else 1
    if code != 0 and result.status != "cancelled":
        _print_run_failure(result)
    return code, result, printer.tool_count


async def _run_chat_turn(
    agent: DefaultAgent,
    cfg: ModelConfig,
    args: argparse.Namespace,
    message: str | ChatMessage,
    history: list[ChatMessage],
) -> tuple[int, list[ChatMessage], int]:
    from auc.work_mode import enrich_user_turn

    meta = {"repo_root": args.repo} if args.repo else {}
    if getattr(args, "autonomy", None):
        meta["autonomy"] = args.autonomy
    if getattr(args, "_work_mode", None):
        meta["work_mode"] = args._work_mode
    if getattr(args, "_approved_plan", None):
        meta["approved_plan"] = args._approved_plan
    catalog = getattr(args, "_role_catalog", None) or _chat_catalog(
        args, _chat_sandbox_root(args)
    )
    role_id = _chat_role_id(args, catalog)
    meta["role_id"] = role_id
    if args.system:
        meta["apply_role_prompt"] = False
    if isinstance(message, ChatMessage):
        user_msg = message
    else:
        enriched, _, _ = enrich_user_turn(message, selected=getattr(args, "_work_mode", None))
        user_msg = ChatMessage(role="user", content=enriched)
    history = [*history, user_msg]
    req = RunRequest(input=history, metadata=meta)

    if args.no_stream:
        result = await agent.run(req)
        code = await _print_chat_result(result, cfg, as_json=args.json)
        return code, list(result.messages), 0

    code, result, tool_count = await _consume_chat_stream(agent, req, args)
    if result is None:
        return code, history, tool_count
    if code == 0 and result.status == "completed":
        mem = getattr(agent, "_config", None) and agent._config.memory
        if mem is not None:
            from auc.multimodal import strip_images_for_memory

            await mem.remember(
                strip_images_for_memory(result.messages),
                run_id=result.run_id,
                agent_id=agent.agent_id,
            )
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
    return code, list(result.messages), tool_count


async def _run_chat_interactive(
    agent: DefaultAgent,
    cfg: ModelConfig,
    args: argparse.Namespace,
) -> int:
    return await run_interactive_repl(
        agent=agent,
        cfg=cfg,
        args=args,
        sandbox=_chat_sandbox_root(args),
        run_turn=_run_chat_turn,
    )


async def _run_chat(args: argparse.Namespace) -> int:
    cfg = _resolve_cfg(args)
    sandbox = _chat_sandbox_root(args)
    evolve = not getattr(args, "no_evolve", False)
    catalog = _chat_catalog(args, sandbox)
    args._role_catalog = catalog
    if not getattr(args, "role", None):
        args.role = catalog.default_role_id
    memory = (
        _chat_memory(sandbox, evolve, role_id=_chat_role_id(args, catalog))
        if not args.no_tools
        else None
    )
    registry = DefaultToolRegistry()
    if not args.no_tools:
        _register_chat_tools(registry, sandbox, memory)

    model = create_model_client(cfg)
    # 交互式终端默认启用控制台审批（shell/写文件确认与 L3 授权都依赖审批通道）
    if args.approval == "console" or (
        args.approval is None and sys.stdin.isatty() and args.message is None
    ):
        approval = ConsoleApprovalPort()
    else:
        approval = None  # "none" 或非交互管道模式
    try:
        from auc.loop.base import LoopConfig
        from auc.ports.memory import DefaultComposer

        agent = DefaultAgent(
            AgentConfig(
                agent_id=f"chat:{_chat_role_id(args, catalog)}",
                model=model,
                tools=registry,
                memory=memory,
                composer=DefaultComposer(),
                rules=FileRulesPort() if args.repo else None,
                approval=approval,
                privilege_gate=ToolPrivilegeGate(approval=approval) if approval else None,
                slicer_policy=SlicerPolicy(require_package=False),
                system_prompt=_chat_system_prompt(args, sandbox, catalog),
                sandbox_root=sandbox,
                loop_config=LoopConfig(max_steps=40),
            )
        )
        message = args.message
        if message is None and not sys.stdin.isatty():
            message = sys.stdin.read().strip()
        if message is None:
            return await _run_chat_interactive(agent, cfg, args)
        code, _, _ = await _run_chat_turn(agent, cfg, args, message, [])
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
    approval: ConsoleApprovalPort | TelegramApprovalPort | QQApprovalPort
    if args.approval == "telegram":
        approval = TelegramApprovalPort()
    elif args.approval == "qq":
        settings, _ = load_merged_settings(
            getattr(args, "config", None),
            Path(args.repo) if getattr(args, "repo", None) else None,
        )
        approval = QQApprovalPort.from_settings(settings)
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


def _cmd_undo(args: argparse.Namespace) -> int:
    from auc.checkpoint import CheckpointStore

    sandbox = str(Path(args.sandbox).expanduser().resolve()) if args.sandbox else str(Path.cwd())
    store = CheckpointStore(sandbox)
    runs = store.list_runs()
    if not runs:
        print("没有可回滚的检查点（.auc/checkpoints 为空）", file=sys.stderr)
        return 1
    run_id = args.run or runs[0]
    entries = store.list_entries(run_id)
    if not entries:
        print(f"run {run_id} 没有检查点条目", file=sys.stderr)
        return 1

    if args.list:
        print(f"run: {run_id}")
        for e in entries:
            target = e.path or e.command or ""
            print(f"  step {e.step:>3}  {e.op:<6} {e.tool:<14} {target}")
        return 0

    report = store.revert_to(run_id, args.step)
    for p in report.restored:
        print(f"恢复: {p}")
    for p in report.deleted:
        print(f"删除(回滚新建): {p}")
    for w in report.warnings:
        print(yellow(f"警告: {w}"))
    if not (report.restored or report.deleted):
        print("没有需要回滚的文件改动")
    return 0


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
    p_chat.add_argument("--repo", default="", help="Repo root for .aurules（并作为工作区）")
    p_chat.add_argument(
        "--sandbox",
        default="",
        help="文件工具沙盒根目录（默认：当前工作目录或 --repo）",
    )
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
    p_chat.add_argument(
        "--no-evolve",
        action="store_true",
        help="关闭进化能力（不召回/写入 .auc/evolution.yaml）",
    )
    p_chat.add_argument("--approval", choices=("console", "none"), default=None)
    p_chat.add_argument(
        "--autonomy",
        choices=("confirm-all", "auto-edit", "full-auto"),
        default=None,
        help="会话自治级别：confirm-all 每次写操作确认 / auto-edit 默认 / full-auto 沙盒内全自动（L3 仍需授权）",
    )
    p_chat.add_argument(
        "--role",
        default=None,
        metavar="ID",
        help="角色 id（内置或自定义，见 settings.json / .auc/roles.yaml）",
    )
    _add_model_args(p_chat)

    # undo — 检查点回滚（R4）
    p_undo = sub.add_parser("undo", help="回滚最近 Run 的文件修改（.auc/checkpoints）")
    p_undo.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    p_undo.add_argument("--run", default=None, help="run_id（默认最近一次）")
    p_undo.add_argument("--step", type=int, default=0, help="回滚到该步之前（默认 0 = 全部回滚）")
    p_undo.add_argument("--list", action="store_true", help="仅列出检查点，不执行回滚")

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
    p_disp.add_argument("--approval", choices=("console", "telegram", "qq"), default="console")
    p_disp.add_argument("--no-require-package", action="store_true")
    _add_model_args(p_disp)

    p_web = sub.add_parser("web", help="Launch web UI (Code + Chat modes)")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8765)
    p_web.add_argument("--sandbox", default="", help="Workspace root")
    p_web.add_argument("--repo", default="", help="Repo root for .aurules")
    p_web.add_argument("--no-evolve", action="store_true")
    _add_model_args(p_web)

    sub.add_parser("extras", help="Show optional install modes (pip install -e '.[mode]')")

    args = parser.parse_args(argv)

    if args.cmd == "extras":
        from auc.extras import INSTALL_EXAMPLES, INSTALL_MODES

        print("可选安装模式 [all] = 全部组件\n")
        for key, desc in INSTALL_MODES.items():
            print(f"  [{key:<8}] {desc}")
        print("\n示例:")
        for line in INSTALL_EXAMPLES:
            print(f"  {line}")
        return 0

    if args.cmd not in ("config", "undo", "extras", "web"):
        from auc.version_check import print_update_notice

        print_update_notice()

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

    if args.cmd == "undo":
        return _cmd_undo(args)

    if args.cmd == "chat":
        return asyncio.run(_run_chat(args))
    if args.cmd == "web":
        from auc.web.server import main as web_main

        wargv = []
        if args.host != "127.0.0.1":
            wargv += ["--host", args.host]
        if args.port != 8765:
            wargv += ["--port", str(args.port)]
        if args.sandbox:
            wargv += ["--sandbox", args.sandbox]
        if args.repo:
            wargv += ["--repo", args.repo]
        if args.config:
            wargv += ["--config", args.config]
        if args.provider:
            wargv += ["--provider", args.provider]
        if args.model:
            wargv += ["--model", args.model]
        if args.api_key:
            wargv += ["--api-key", args.api_key]
        if args.base_url:
            wargv += ["--base-url", args.base_url]
        if args.no_evolve:
            wargv += ["--no-evolve"]
        return web_main(wargv or None)
    if args.cmd == "dispatch":
        return asyncio.run(_run_dispatch(args))
    return asyncio.run(_run_scripted(args))


if __name__ == "__main__":
    sys.exit(main())
