from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from auc.terminal import bold, cyan, dim, green, red, yellow

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
    from auc.skills import SkillStore

    return EvolutionMemoryPort(
        sandbox_root=sandbox_root,
        default_role_id=role_id,
        skill_store=SkillStore(sandbox_root),
    )


def _register_chat_tools(
    registry: DefaultToolRegistry,
    sandbox_root: str,
    memory: EvolutionMemoryPort | None = None,
) -> None:
    from auc.tools.git import make_git_tools
    from auc.tools.index_tools import make_index_tools
    from auc.tools.roles import make_role_tools
    from auc.tools.search import make_search_tools
    from auc.tools.shell import make_shell_tool
    from auc.tools.todos import make_todos_tool

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
    todos_tool, todos_pol = make_todos_tool()
    registry.register(todos_tool, todos_pol)
    for tool, pol in make_git_tools(sandbox_root):
        registry.register(tool, pol)
    for tool, pol in make_index_tools(sandbox_root):
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
    mem = getattr(agent, "_config", None) and agent._config.memory
    if code == 0 and result.status == "completed" and mem is not None:
        from auc.multimodal import strip_images_for_memory

        await mem.remember(
            strip_images_for_memory(result.messages),
            run_id=result.run_id,
            agent_id=agent.agent_id,
        )
    # R20+R23：自动复盘 + 进化度量（结束后闭环；失败/取消也复盘归因）
    if mem is not None and result is not None:
        try:
            from auc.evolution_loop import run_evolution_cycle
            from auc.multimodal import strip_images_for_memory
            from auc.skills import SkillStore

            _sb = _chat_sandbox_root(args)
            run_evolution_cycle(
                mem,
                sandbox_root=_sb,
                status=result.status,
                messages=strip_images_for_memory(result.messages),
                run_id=result.run_id,
                agent_id=agent.agent_id,
                skill_store=SkillStore(_sb),
            )
        except Exception:  # noqa: BLE001 进化闭环不得影响主流程
            pass
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


def _resolve_chat_resume(
    sandbox: str, args: argparse.Namespace
) -> tuple[Any, str | None]:
    """根据 --continue/--resume 解析 CLI 会话持久化的 store 与起始对话 id。"""
    want_continue = bool(getattr(args, "continue_session", False))
    resume_id = getattr(args, "resume", None)
    if not want_continue and not resume_id:
        return None, None
    from auc.web.conversations import ConversationStore

    store = ConversationStore(sandbox)
    conv_id: str | None = None
    if resume_id:
        if store.exists(resume_id):
            conv_id = resume_id
        else:
            print(yellow(f"未找到对话 {resume_id}，将新建对话"))
    elif want_continue:
        conv_id = store.get_active_id()
        if conv_id is None:
            summaries = store.list_summaries()
            conv_id = summaries[0].id if summaries else None
        if conv_id is None:
            print(dim("无历史对话可续，将新建对话"))
    return store, conv_id


async def _run_chat_interactive(
    agent: DefaultAgent,
    cfg: ModelConfig,
    args: argparse.Namespace,
) -> int:
    sandbox = _chat_sandbox_root(args)
    store, conv_id = _resolve_chat_resume(sandbox, args)
    return await run_interactive_repl(
        agent=agent,
        cfg=cfg,
        args=args,
        sandbox=sandbox,
        run_turn=_run_chat_turn,
        store=store,
        conversation_id=conv_id,
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
    mcp_setup = None
    try:
        from auc.hooks import load_hooks
        from auc.loop.base import LoopConfig
        from auc.ports.memory import DefaultComposer

        try:
            _hook_settings, _ = load_merged_settings(
                None, Path(args.repo) if getattr(args, "repo", None) else None
            )
        except Exception:  # noqa: BLE001
            _hook_settings = {}
        hooks = load_hooks(_hook_settings, sandbox)

        # R16：注册外部 MCP server 工具（前缀 mcp__<server>__<tool>，过裁决链）
        if not args.no_tools:
            try:
                from auc.integration.mcp import setup_mcp

                mcp_setup = await setup_mcp(registry, _hook_settings)
                if mcp_setup is not None:
                    for w in mcp_setup.warnings:
                        print(yellow(w), file=sys.stderr)
                    if mcp_setup.registered:
                        print(
                            dim(f"已接入 {mcp_setup.registered} 个 MCP 工具"),
                            file=sys.stderr,
                        )
            except Exception as exc:  # noqa: BLE001 MCP 失败不影响主流程
                print(yellow(f"MCP 初始化失败: {exc}"), file=sys.stderr)

        # R13：子智能体工具（复用父进程模型客户端；子 Run 不再含本工具）
        if not args.no_tools:
            from auc.tools.subagent import make_subagent_tool

            def _build_subagent(kind: str) -> DefaultAgent:
                child_reg = DefaultToolRegistry()
                _register_chat_tools(child_reg, sandbox, None)
                return DefaultAgent(
                    AgentConfig(
                        agent_id=f"chat:{kind}",
                        model=model,
                        tools=child_reg,
                        composer=DefaultComposer(),
                        rules=FileRulesPort() if args.repo else None,
                        system_prompt=build_chat_system_prompt(
                            sandbox, role_id=kind, catalog=catalog
                        ),
                        sandbox_root=sandbox,
                        approval=approval,
                        privilege_gate=ToolPrivilegeGate(approval=approval)
                        if approval
                        else None,
                        slicer_policy=SlicerPolicy(require_package=False),
                        loop_config=LoopConfig(max_steps=20),
                        hooks=hooks,
                    )
                )

            sub_tool, sub_pol = make_subagent_tool(
                build_agent=_build_subagent,
                sandbox=sandbox,
                allowed_kinds=catalog.role_ids(),
                default_kind=_chat_role_id(args, catalog),
            )
            registry.register(sub_tool, sub_pol)

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
                hooks=hooks,
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
        if mcp_setup is not None:
            await mcp_setup.aclose()
        await aclose_model_client(model)


def _git_diff_text(sandbox: str, *, staged: bool, path: str | None) -> str:
    import subprocess

    cmd = ["git", "--no-pager", "diff"]
    if staged:
        cmd.append("--cached")
    if path:
        cmd += ["--", path]
    try:
        out = subprocess.run(
            cmd, cwd=sandbox, capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError(f"git diff 失败: {exc}") from exc
    return out.stdout


def _save_review_report(sandbox: str, report: str) -> str | None:
    import time as _time

    try:
        out_dir = Path(sandbox) / ".auc" / "reviews"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{_time.strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text(report, encoding="utf-8")
        return str(path)
    except OSError:
        return None


async def _run_review(args: argparse.Namespace) -> int:
    """R27 多轮专项审查：reviewer 角色按 pass 序列只读评审，产出结构化报告。"""
    from auc.chat_agent import ChatAgentOptions, build_chat_agent
    from auc.review import (
        REVIEW_PASSES,
        ReviewResult,
        build_pass_prompt,
        findings_to_todos,
        parse_review_findings,
        render_review_report,
    )

    cfg = _resolve_cfg(args)
    sandbox = _chat_sandbox_root(args)

    diff_text: str | None = None
    if args.diff:
        try:
            diff_text = _git_diff_text(sandbox, staged=args.staged, path=args.path)
        except ValueError as exc:
            print(red(str(exc)), file=sys.stderr)
            return 2
        if not diff_text.strip():
            print(dim("没有检测到改动（工作区干净或路径无变更）"))
            return 0
        scope = "已暂存改动" if args.staged else "工作区改动"
        target_desc = f"git {scope}" + (f"（{args.path}）" if args.path else "")
    else:
        if not args.path:
            print(red("请提供要审查的路径，或用 --diff 审查 git 改动"), file=sys.stderr)
            return 2
        target_desc = args.path

    only = {p for p in (args.passes or "").split(",") if p} or None
    passes = [p for p in REVIEW_PASSES if only is None or p.id in only]
    if not passes:
        print(red(f"无匹配的审查维度: {args.passes}"), file=sys.stderr)
        return 2

    agent = build_chat_agent(
        cfg,
        ChatAgentOptions(
            sandbox=sandbox,
            repo=args.repo or None,
            evolve=False,
            role_id="reviewer",
        ),
    )
    result = ReviewResult(target=target_desc)
    print(bold(f"代码审查：{target_desc}"))
    try:
        for p in passes:
            print(cyan(f"\n▶ {p.label}"))
            meta: dict = {"readonly_tools": True, "role_id": "reviewer"}
            if args.repo:
                meta["repo_root"] = args.repo
            prompt = build_pass_prompt(p, target_desc, diff_text=diff_text)
            run_result = await agent.run(RunRequest(input=prompt, metadata=meta))
            findings = parse_review_findings(run_result.output, p)
            result.findings.extend(findings)
            result.passes_run.append(p.label)
            print(dim(f"  发现 {len(findings)} 个问题"))
    finally:
        await aclose_model_client(agent._config.model)

    report = render_review_report(result)
    print("\n" + report)
    saved = _save_review_report(sandbox, report)
    if saved:
        print(dim(f"报告已保存: {saved}"))
    if args.todos:
        todos = findings_to_todos(result.findings)
        print(green(f"\n可转为 {len(todos)} 条 Todo："))
        print(json.dumps({"todos": todos}, ensure_ascii=False, indent=2))
    if args.json:
        print(
            json.dumps(
                {
                    "target": result.target,
                    "passes": result.passes_run,
                    "findings": [f.to_dict() for f in result.findings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


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


def _cmd_receipt(args: argparse.Namespace) -> int:
    """R28：查看 Run 任务回执（.auc/receipts）。"""
    from auc.receipt import ReceiptStore

    sandbox = (
        str(Path(args.sandbox).expanduser().resolve())
        if args.sandbox
        else str(Path.cwd())
    )
    store = ReceiptStore(sandbox)
    runs = store.list_runs()
    if not runs:
        print("没有任务回执（.auc/receipts 为空）", file=sys.stderr)
        return 1
    if args.list:
        for rid in runs:
            print(rid)
        return 0
    run_id = args.run or runs[0]
    md = store.read_markdown(run_id)
    if md is None:
        print(f"未找到回执: {run_id}", file=sys.stderr)
        return 1
    print(md)
    return 0


def _cmd_mcp_list(args: argparse.Namespace) -> int:
    """R16：列出已配置的 MCP server 连接器卡片；--probe 实际连接列出工具。"""
    from auc.integration.mcp import (
        connector_card,
        default_connect,
        discover_and_register,
        parse_mcp_configs,
    )

    repo = Path(args.repo) if getattr(args, "repo", None) else None
    settings, _ = load_merged_settings(args.config, repo)
    configs = parse_mcp_configs(settings)
    if not configs:
        print("未配置 MCP server（settings.json 的 mcpServers / mcp.servers）", file=sys.stderr)
        return 1

    if args.json and not args.probe:
        cards = [connector_card(c) for c in configs]
        print(json.dumps(cards, ensure_ascii=False, indent=2))
        return 0

    if args.probe:

        async def _probe() -> int:
            from auc.tools.registry import DefaultToolRegistry

            result = await discover_and_register(
                DefaultToolRegistry(), configs, connect=default_connect
            )
            try:
                if args.json:
                    print(json.dumps(result.cards, ensure_ascii=False, indent=2))
                else:
                    _print_cards(result.cards)
            finally:
                await result.aclose()
            return 0

        return asyncio.run(_probe())

    _print_cards([connector_card(c) for c in configs])
    return 0


def _print_cards(cards: list[dict]) -> None:
    for c in cards:
        status = "" if c.get("enabled", True) else dim(" (disabled)")
        head = f"{bold(c['name'])} [{c['transport']}]{status}"
        print(head)
        if c.get("endpoint"):
            print(f"  endpoint: {c['endpoint']}")
        if c.get("owner"):
            print(f"  owner: {c['owner']}")
        print(f"  privilege: {c.get('privilege', 'L2')}")
        if c.get("allowed_tools"):
            print(f"  allow: {', '.join(c['allowed_tools'])}")
        if c.get("forbidden_tools"):
            print(f"  deny: {', '.join(c['forbidden_tools'])}")
        if c.get("error"):
            print(f"  {red('error: ' + str(c['error']))}")
        elif c.get("tools"):
            print(f"  tools ({c['tool_count']}): {', '.join(c['tools'])}")


def _jobs_sandbox(args: argparse.Namespace) -> str:
    raw = getattr(args, "sandbox", "") or getattr(args, "repo", "") or "."
    return str(Path(raw).expanduser().resolve())


def _cmd_chat_background(args: argparse.Namespace) -> int:
    """R17：把一次 chat Run 投递为后台作业。"""
    from auc.jobs import JobStore

    message = args.message
    if message is None and not sys.stdin.isatty():
        message = sys.stdin.read().strip()
    if not message:
        print(red("后台作业需要提供消息（位置参数或管道）"), file=sys.stderr)
        return 2
    sandbox = (
        str(Path(args.sandbox).expanduser().resolve())
        if getattr(args, "sandbox", "")
        else (
            str(Path(args.repo).expanduser().resolve())
            if getattr(args, "repo", "")
            else str(Path.cwd())
        )
    )
    store = JobStore(sandbox)
    job = store.enqueue(
        message,
        sandbox=sandbox,
        repo=getattr(args, "repo", "") or "",
        role=getattr(args, "role", None),
        model=getattr(args, "model", None),
        autonomy=getattr(args, "autonomy", None) or "full-auto",
        approval=getattr(args, "approval", None) or "none",
        isolation=getattr(args, "isolation", None) or "none",
        image=getattr(args, "image", None) or "",
    )
    print(green(f"已入队后台作业: {job.id}"))
    if job.isolation == "docker":
        from auc.isolation import docker_available

        if not docker_available():
            print(dim("提示：未检测到 docker，worker 执行时将降级为本机运行"))
    print(dim(f"运行 `auc jobs worker --sandbox {sandbox}` 处理队列；"
              f"`auc jobs show {job.id}` 查看状态"))
    return 0


def _cmd_jobs(args: argparse.Namespace) -> int:
    from auc.jobs import JobStore, run_worker

    sandbox = _jobs_sandbox(args)
    store = JobStore(sandbox)
    sub = args.jobs_cmd

    if sub == "list":
        jobs = store.list()
        if args.json:
            print(json.dumps([j.to_dict() for j in jobs], ensure_ascii=False, indent=2))
            return 0
        if not jobs:
            print("（无作业）", file=sys.stderr)
            return 0
        for j in jobs:
            msg = j.message.replace("\n", " ")
            if len(msg) > 50:
                msg = msg[:47] + "..."
            print(f"{_job_status_label(j.status)}  {bold(j.id)}  {msg}")
        return 0

    if sub == "show":
        job = store.get(args.job_id)
        if job is None:
            print(red(f"作业不存在: {args.job_id}"), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(job.to_dict(), ensure_ascii=False, indent=2))
            return 0
        print(f"{bold(job.id)}  [{_job_status_label(job.status)}]")
        print(f"  message: {job.message}")
        print(f"  sandbox: {job.sandbox}")
        if job.role:
            print(f"  role: {job.role}")
        print(f"  autonomy: {job.autonomy}  approval: {job.approval}")
        print(f"  created: {job.created_at}")
        if job.started_at:
            print(f"  started: {job.started_at}")
        if job.finished_at:
            print(f"  finished: {job.finished_at}")
        if job.exit_code is not None:
            print(f"  exit_code: {job.exit_code}")
        if job.run_id:
            print(f"  receipt: {job.run_id} ({job.receipt_path})")
        if job.error:
            print(f"  {red('error: ' + job.error)}")
        return 0

    if sub == "logs":
        log_path = store.log_path(args.job_id)
        if not log_path.is_file():
            print(red(f"无日志: {args.job_id}"), file=sys.stderr)
            return 1
        print(log_path.read_text(encoding="utf-8"))
        return 0

    if sub == "cancel":
        ok, msg = store.cancel(args.job_id)
        print((green if ok else red)(msg), file=sys.stderr if not ok else sys.stdout)
        return 0 if ok else 1

    if sub == "worker":
        def _on_event(kind: str, job) -> None:  # noqa: ANN001
            if kind == "start":
                print(dim(f"▶ 执行 {job.id}: {job.message[:60]}"), file=sys.stderr)
            else:
                print(
                    (green if job.status == "done" else red)(
                        f"■ {job.id} → {job.status}"
                    ),
                    file=sys.stderr,
                )

        routines = None
        if getattr(args, "routines", False):
            from auc.routines import RoutineStore

            routines = RoutineStore(sandbox)
        n = run_worker(
            store,
            once=args.once,
            interval=args.interval,
            on_event=_on_event,
            routines=routines,
        )
        if args.once:
            print(dim(f"已处理 {n} 个作业"), file=sys.stderr)
        return 0

    return 2


def _job_status_label(status: str) -> str:
    colors = {
        "queued": dim,
        "running": cyan,
        "done": green,
        "failed": red,
        "cancelled": yellow,
    }
    fn = colors.get(status, dim)
    return fn(f"{status:<9}")


def _cmd_routines(args: argparse.Namespace) -> int:
    """R17 增量：定时任务管理 add/list/remove/enable/disable/run-due。"""
    from auc.routines import RoutineStore, fire_due_routines

    sandbox = _jobs_sandbox(args)
    store = RoutineStore(sandbox)
    sub = args.routines_cmd

    if sub == "add":
        rt = store.add(
            args.message,
            args.every,
            sandbox=str(Path(args.sandbox).expanduser().resolve()) if args.sandbox else sandbox,
            repo=args.repo,
            role=args.role,
            model=args.model,
            autonomy=args.autonomy,
            approval=args.approval,
        )
        print(green(f"已新增定时任务 {rt.id}（每 {rt.interval_seconds}s）"))
        print(dim(f"  `auc jobs worker --routines --sandbox {sandbox}` 后台调度执行"))
        return 0

    if sub == "list":
        routines = store.list()
        if args.json:
            print(json.dumps([r.to_dict() for r in routines], ensure_ascii=False, indent=2))
            return 0
        if not routines:
            print(dim("暂无定时任务"))
            return 0
        for r in routines:
            state = green("on") if r.enabled else dim("off")
            print(
                f"{bold(r.id)} [{state}] 每{r.interval_seconds}s  下次:{r.next_run or '-'}  {r.message[:40]}"
            )
        return 0

    if sub == "remove":
        ok = store.remove(args.id)
        print(green("已删除") if ok else red("定时任务不存在"))
        return 0 if ok else 1

    if sub in {"enable", "disable"}:
        rt = store.set_enabled(args.id, sub == "enable")
        if rt is None:
            print(red("定时任务不存在"), file=sys.stderr)
            return 1
        print(green(f"已{'启用' if rt.enabled else '停用'} {rt.id}"))
        return 0

    if sub == "run-due":
        from auc.jobs import JobStore

        fired = fire_due_routines(store, JobStore(sandbox))
        print(green(f"已触发 {len(fired)} 个到点任务入队"))
        for j in fired:
            print(dim(f"  {j.id}: {j.message[:50]}"))
        return 0
    return 2


def _cmd_skills(args: argparse.Namespace) -> int:
    """R21/R15：技能库管理。"""
    from auc.skills import SkillStore

    sandbox = (
        str(Path(args.sandbox).expanduser().resolve())
        if getattr(args, "sandbox", "")
        else str(Path.cwd())
    )
    store = SkillStore(sandbox)
    sub = args.skills_cmd

    if sub == "list":
        skills = store.list(include_drafts=args.drafts)
        if args.json:
            print(json.dumps(
                [
                    {
                        "name": s.name,
                        "description": s.description,
                        "triggers": s.triggers,
                        "draft": s.draft,
                        "source": s.source,
                    }
                    for s in skills
                ],
                ensure_ascii=False,
                indent=2,
            ))
            return 0
        if not skills:
            print("（无技能）", file=sys.stderr)
            return 0
        for s in skills:
            tag = yellow(" [草案]") if s.draft else ""
            print(f"{bold(s.name)}{tag}  {s.description}")
            if s.triggers:
                print(dim(f"  触发: {', '.join(s.triggers)}"))
        return 0

    if sub == "show":
        sk = store.get(args.name, draft=args.draft)
        if sk is None:
            print(red(f"技能不存在: {args.name}"), file=sys.stderr)
            return 1
        print(sk.render_md())
        return 0

    if sub == "promote":
        sk = store.promote(args.name)
        if sk is None:
            print(red(f"草案不存在: {args.name}"), file=sys.stderr)
            return 1
        print(green(f"已晋升技能: {sk.name} → {sk.path}"))
        return 0

    if sub == "remove":
        ok = store.remove(args.name, draft=args.draft)
        print((green if ok else red)("已删除" if ok else "不存在"),
              file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    return 2


def _cmd_evolve_stats(args: argparse.Namespace) -> int:
    """R23：展示进化度量统计。"""
    from auc.evolution_loop import EvolutionMetrics

    sandbox = (
        str(Path(args.sandbox).expanduser().resolve())
        if getattr(args, "sandbox", "")
        else str(Path.cwd())
    )
    metrics = EvolutionMetrics(sandbox)
    if args.json:
        from dataclasses import asdict

        print(
            json.dumps(
                {
                    "entries": [asdict(s) for s in metrics.stats.values()],
                    "archive_candidates": metrics.archive_candidates(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(metrics.render())
    return 0


def _cmd_evolve_prompt(args: argparse.Namespace) -> int:
    """R22：提示与策略自优化 —— propose / drafts / eval / apply / revert。"""
    from auc.prompt_optimizer import PromptOptimizer

    sandbox = (
        str(Path(args.sandbox).expanduser().resolve())
        if getattr(args, "sandbox", "")
        else str(Path.cwd())
    )
    opt = PromptOptimizer(sandbox)
    cmd = args.evolve_cmd

    if cmd == "propose":
        memory = _chat_memory(sandbox, True, role_id=args.role)
        eval_failures: list[str] = []
        if getattr(args, "with_eval", False):
            from auc.evaluation import run_suite

            report = asyncio.run(run_suite())
            eval_failures = [r.case_id for r in report.results if not r.passed]
        draft = opt.propose(
            memory=memory, agent_id=f"chat:{args.role}", eval_failures=eval_failures
        )
        if args.json:
            print(json.dumps(draft.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(green(f"已生成草案 {draft.id}"))
            print(dim(draft.rationale))
            print(f"  路径：{opt.drafts_dir / (draft.id + '.md')}")
            print(dim("  跑 `auc evolve eval <id>` 防退化，再 `auc evolve apply <id> --yes`"))
        return 0

    if cmd == "drafts":
        drafts = opt.list_drafts()
        if args.json:
            print(json.dumps([d.to_dict() for d in drafts], ensure_ascii=False, indent=2))
            return 0
        if not drafts:
            print(dim("暂无提示草案"))
            return 0
        for d in drafts:
            print(f"{bold(d.id)}  {d.rationale}")
        return 0

    if cmd == "eval":
        cmp = opt.eval_draft(args.draft)
        if cmp is None:
            print(red(f"草案不存在：{args.draft}"), file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    {
                        "before": cmp.before_pass_rate,
                        "after": cmp.after_pass_rate,
                        "total": cmp.total,
                        "ok": cmp.ok,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                f"评测对比：改前 {cmp.before_pass_rate * 100:.0f}% → "
                f"改后 {cmp.after_pass_rate * 100:.0f}%（{cmp.total} 例）"
            )
            print(green("通过防退化闸门") if cmp.ok else red("出现退化，禁止 apply"))
        return 0 if cmp.ok else 1

    if cmd == "apply":
        if not args.yes:
            d = opt.read_draft(args.draft)
            if d is None:
                print(red(f"草案不存在：{args.draft}"), file=sys.stderr)
                return 1
            print(d.content)
            print(
                red("apply 为 L3 操作，需人工确认；确认后追加 --yes 重新执行"),
                file=sys.stderr,
            )
            return 2
        path = opt.apply(args.draft, approved=True)
        if path is None:
            print(red(f"草案不存在：{args.draft}"), file=sys.stderr)
            return 1
        print(green(f"已落盘生效：{path}"))
        return 0

    if cmd == "revert":
        ok = opt.revert()
        print(green("已回退提示覆盖层") if ok else dim("无可回退的覆盖层"))
        return 0
    return 1


def _cmd_eval(args: argparse.Namespace) -> int:
    """R19：跑确定性评测基线（InMemoryModelClient 回放）。"""
    from auc.evaluation import render_report, run_suite

    only = [c.strip() for c in (args.case or "").split(",") if c.strip()] or None
    report = asyncio.run(run_suite(args.dir or None, only=only))
    if report.total == 0:
        print(red("未找到评测用例"), file=sys.stderr)
        return 1
    if args.json:
        print(
            json.dumps(
                {
                    "total": report.total,
                    "passed": report.passed,
                    "failed": report.failed,
                    "pass_rate": report.pass_rate,
                    "results": [
                        {
                            "id": r.case_id,
                            "passed": r.passed,
                            "status": r.status,
                            "error": r.error,
                            "failed_checks": [
                                {"label": c.label, "detail": c.detail}
                                for c in r.failed_checks
                            ],
                        }
                        for r in report.results
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(render_report(report))
    threshold = args.min_pass_rate
    if report.pass_rate < threshold:
        print(
            red(f"通过率 {report.pass_rate * 100:.0f}% 低于阈值 {threshold * 100:.0f}%"),
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_worktree(args: argparse.Namespace) -> int:
    """R18：git worktree 多智能体隔离与并行编排。"""
    from auc.worktree import WorktreeManager, run_parallel

    repo = str(Path(getattr(args, "repo", "") or ".").expanduser().resolve())
    mgr = WorktreeManager(repo)
    sub = args.worktree_cmd

    if sub == "list":
        trees = mgr.list()
        if not trees:
            print("（无 worktree）", file=sys.stderr)
            return 0
        for w in trees:
            print(f"{bold(w.branch or '(detached)'):<28} {w.path}")
        return 0

    if sub == "add":
        wt = mgr.create(args.name, base=args.base)
        print(green(f"已创建 worktree: {wt.branch}"))
        print(dim(wt.path))
        return 0

    if sub == "remove":
        ok = mgr.remove(args.name, force=True)
        print((green if ok else red)("已移除" if ok else "移除失败"),
              file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    if sub == "merge":
        res = mgr.merge(args.name)
        if res.ok:
            print(green(f"已合并 {res.branch}"))
            return 0
        print(red(f"合并失败：{res.message}"), file=sys.stderr)
        for f in res.conflicted_files:
            print(f"  冲突: {f}", file=sys.stderr)
        return 1

    if sub == "run":
        tasks = []
        for spec in args.tasks:
            if "=" not in spec:
                print(red(f"任务格式应为 name=message：{spec}"), file=sys.stderr)
                return 2
            name, message = spec.split("=", 1)
            if not message.strip():
                print(red(f"任务 {name} 消息为空"), file=sys.stderr)
                return 2
            tasks.append((name.strip(), message.strip()))
        if not tasks:
            print(red("至少提供一个任务"), file=sys.stderr)
            return 2

        model = getattr(args, "model", None)
        role = getattr(args, "role", None)

        def _executor(worktree, message):  # noqa: ANN001
            from auc.jobs import JobStore, run_job

            store = JobStore(worktree.path)
            store.enqueue(message, sandbox=worktree.path, role=role, model=model)
            job = store.claim_next()
            done = run_job(job, store)
            return done.exit_code if done.exit_code is not None else (
                0 if done.status == "done" else 1
            )

        print(dim(f"并行执行 {len(tasks)} 个任务（worktree 隔离）..."), file=sys.stderr)
        results = run_parallel(
            repo,
            tasks,
            base=args.base,
            merge=args.merge,
            cleanup=args.cleanup,
            executor=_executor,
        )
        rc = 0
        for r in results:
            label = {"done": green, "failed": red, "error": red}.get(r.status, dim)
            print(f"{label(r.status):<8} {bold(r.name)}  "
                  f"改动 {len(r.changed_files)} 文件"
                  + (f"  分支 {r.worktree.branch}" if r.worktree else ""))
            if r.error:
                print(f"  {red(r.error)}", file=sys.stderr)
            if r.merge and not r.merge.ok:
                print(red(f"  合并冲突: {', '.join(r.merge.conflicted_files)}"),
                      file=sys.stderr)
            if r.status != "done":
                rc = 1
        return rc

    return 2


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
    p_chat.add_argument(
        "--background",
        action="store_true",
        help="投递为后台作业（落 .auc/jobs/，由 `auc jobs worker` 串行执行），即返 job_id",
    )
    p_chat.add_argument(
        "--isolation",
        choices=["none", "docker"],
        default="none",
        help="后台作业隔离方式（docker：容器内执行，缺 docker 自动降级）",
    )
    p_chat.add_argument(
        "--image",
        default="",
        help="docker 隔离镜像（默认 python:3.12-slim）",
    )
    p_chat.add_argument(
        "--continue",
        dest="continue_session",
        action="store_true",
        help="续接最近一次对话（读取 .auc/conversations/，交互模式生效）",
    )
    p_chat.add_argument(
        "--resume",
        default=None,
        metavar="ID",
        help="恢复指定对话 id（与 Web 共享 .auc/conversations/，交互模式生效）",
    )
    _add_model_args(p_chat)

    # review — 多轮专项审查（R27）
    p_review = sub.add_parser(
        "review", help="多轮专项代码审查（reviewer 角色，只读，正确性/安全/性能/风格）"
    )
    p_review.add_argument(
        "path", nargs="?", default=None, help="要审查的文件/目录（或配合 --diff）"
    )
    p_review.add_argument(
        "--diff", action="store_true", help="审查 git 改动而非指定路径"
    )
    p_review.add_argument(
        "--staged", action="store_true", help="配合 --diff：审查已暂存改动"
    )
    p_review.add_argument(
        "--passes",
        default="",
        help="仅运行指定维度（逗号分隔：correctness,security,performance,maintainability）",
    )
    p_review.add_argument(
        "--todos", action="store_true", help="额外输出可转为任务清单的 JSON"
    )
    p_review.add_argument("--json", action="store_true", help="输出结构化 JSON 结果")
    p_review.add_argument("--repo", default="", help="Repo root for .aurules")
    p_review.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    p_review.add_argument("--no-tools", action="store_true", help=argparse.SUPPRESS)
    _add_model_args(p_review)

    # undo — 检查点回滚（R4）
    p_undo = sub.add_parser("undo", help="回滚最近 Run 的文件修改（.auc/checkpoints）")
    p_undo.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    p_undo.add_argument("--run", default=None, help="run_id（默认最近一次）")
    p_undo.add_argument("--step", type=int, default=0, help="回滚到该步之前（默认 0 = 全部回滚）")
    p_undo.add_argument("--list", action="store_true", help="仅列出检查点，不执行回滚")

    # mcp — MCP 连接器治理（R16）
    p_mcp = sub.add_parser("mcp", help="MCP server 治理（连接器卡片）")
    mcp_sub = p_mcp.add_subparsers(dest="mcp_cmd", required=True)
    p_mcp_list = mcp_sub.add_parser("list", help="列出已配置的 MCP server")
    p_mcp_list.add_argument("--probe", action="store_true", help="实际连接并列出远端工具")
    p_mcp_list.add_argument("--json", action="store_true", help="输出 JSON")
    p_mcp_list.add_argument("--config", "-c", default=None, help="settings.json 路径")
    p_mcp_list.add_argument("--repo", default="", help="项目根（读 .auc/settings.json）")
    p_mcp_list.add_argument("--sandbox", default="", help="沙盒根目录（--probe 用）")

    # jobs — 后台作业（R17）
    p_jobs = sub.add_parser("jobs", help="后台作业（.auc/jobs）：list/show/cancel/logs/worker")
    jobs_sub = p_jobs.add_subparsers(dest="jobs_cmd", required=True)
    pj_list = jobs_sub.add_parser("list", help="列出作业")
    pj_list.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pj_list.add_argument("--json", action="store_true", help="输出 JSON")
    pj_show = jobs_sub.add_parser("show", help="查看单个作业详情")
    pj_show.add_argument("job_id")
    pj_show.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pj_show.add_argument("--json", action="store_true", help="输出 JSON")
    pj_logs = jobs_sub.add_parser("logs", help="查看作业日志")
    pj_logs.add_argument("job_id")
    pj_logs.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pj_cancel = jobs_sub.add_parser("cancel", help="取消作业（queued 直接取消 / running 杀进程）")
    pj_cancel.add_argument("job_id")
    pj_cancel.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pj_worker = jobs_sub.add_parser("worker", help="启动串行 worker 处理队列")
    pj_worker.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pj_worker.add_argument("--once", action="store_true", help="跑空队列一次后退出")
    pj_worker.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒")
    pj_worker.add_argument(
        "--routines", action="store_true", help="每轮触发到点的定时任务（R17 增量）"
    )

    # routines — 定时任务（R17 增量）
    p_rt = sub.add_parser("routines", help="定时任务（.auc/routines）：add/list/remove/enable/disable/run-due")
    rt_sub = p_rt.add_subparsers(dest="routines_cmd", required=True)
    rt_add = rt_sub.add_parser("add", help="新增定时任务（按固定间隔秒触发）")
    rt_add.add_argument("message", help="到点投递的指令")
    rt_add.add_argument("--every", type=int, required=True, help="触发间隔（秒）")
    rt_add.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    rt_add.add_argument("--repo", default="", help="仓库根目录")
    rt_add.add_argument("--role", default=None, help="角色 id")
    rt_add.add_argument("--model", default=None, help="模型")
    rt_add.add_argument("--autonomy", default="full-auto", help="自治级别")
    rt_add.add_argument("--approval", default="none", help="审批通道")
    rt_list = rt_sub.add_parser("list", help="列出定时任务")
    rt_list.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    rt_list.add_argument("--json", action="store_true", help="输出 JSON")
    rt_rm = rt_sub.add_parser("remove", help="删除定时任务")
    rt_rm.add_argument("id", help="routine id")
    rt_rm.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    rt_en = rt_sub.add_parser("enable", help="启用定时任务")
    rt_en.add_argument("id", help="routine id")
    rt_en.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    rt_dis = rt_sub.add_parser("disable", help="停用定时任务")
    rt_dis.add_argument("id", help="routine id")
    rt_dis.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    rt_run = rt_sub.add_parser("run-due", help="立即触发当前到点的定时任务入队")
    rt_run.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")

    # worktree — git worktree 并行隔离（R18）
    p_wt = sub.add_parser("worktree", help="git worktree 多智能体隔离与并行")
    wt_sub = p_wt.add_subparsers(dest="worktree_cmd", required=True)
    pw_list = wt_sub.add_parser("list", help="列出 worktree")
    pw_list.add_argument("--repo", default="", help="仓库根（默认当前目录）")
    pw_add = wt_sub.add_parser("add", help="新建 worktree（分支 auc/<name>）")
    pw_add.add_argument("name")
    pw_add.add_argument("--base", default="HEAD", help="基线 commit/分支")
    pw_add.add_argument("--repo", default="", help="仓库根（默认当前目录）")
    pw_rm = wt_sub.add_parser("remove", help="移除 worktree")
    pw_rm.add_argument("name")
    pw_rm.add_argument("--repo", default="", help="仓库根（默认当前目录）")
    pw_merge = wt_sub.add_parser("merge", help="把 worktree 分支合并回当前分支")
    pw_merge.add_argument("name")
    pw_merge.add_argument("--repo", default="", help="仓库根（默认当前目录）")
    pw_run = wt_sub.add_parser("run", help="并行执行多个任务（name=message ...）")
    pw_run.add_argument("tasks", nargs="+", help="任务，格式 name=message")
    pw_run.add_argument("--base", default="HEAD", help="基线 commit/分支")
    pw_run.add_argument("--merge", action="store_true", help="完成后自动合并回当前分支")
    pw_run.add_argument("--cleanup", action="store_true", help="完成后移除 worktree")
    pw_run.add_argument("--repo", default="", help="仓库根（默认当前目录）")
    pw_run.add_argument("--role", default=None, help="子作业角色 id")
    pw_run.add_argument("--model", "-m", default=None, help="子作业模型 id")

    # skills — 技能库（R21/R15）
    p_skills = sub.add_parser("skills", help="技能库 SKILL.md（list/show/promote/remove）")
    skills_sub = p_skills.add_subparsers(dest="skills_cmd", required=True)
    ps_list = skills_sub.add_parser("list", help="列出技能（含草案）")
    ps_list.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    ps_list.add_argument("--drafts", action="store_true", help="包含待审草案")
    ps_list.add_argument("--json", action="store_true", help="输出 JSON")
    ps_show = skills_sub.add_parser("show", help="查看单个技能正文")
    ps_show.add_argument("name")
    ps_show.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    ps_show.add_argument("--draft", action="store_true", help="查看草案版本")
    ps_promote = skills_sub.add_parser("promote", help="晋升草案为正式技能（L3 人审）")
    ps_promote.add_argument("name")
    ps_promote.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    ps_remove = skills_sub.add_parser("remove", help="删除技能或草案")
    ps_remove.add_argument("name")
    ps_remove.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    ps_remove.add_argument("--draft", action="store_true", help="删除草案而非正式技能")

    # evolve — 自进化闭环（R20 复盘 / R23 度量）
    p_evolve = sub.add_parser("evolve", help="自进化：复盘度量（stats）")
    evolve_sub = p_evolve.add_subparsers(dest="evolve_cmd", required=True)
    pv_stats = evolve_sub.add_parser("stats", help="查看进化度量（召回/采纳/成败/权重）")
    pv_stats.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pv_stats.add_argument("--json", action="store_true", help="输出 JSON")
    # R22：提示与策略自优化 propose/eval/apply/revert/drafts
    pv_prop = evolve_sub.add_parser("propose", help="生成提示覆盖层草案（复盘+评测）")
    pv_prop.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pv_prop.add_argument("--role", default=DEFAULT_ROLE_ID, help="角色 id")
    pv_prop.add_argument("--with-eval", action="store_true", help="纳入评测失败用例")
    pv_prop.add_argument("--json", action="store_true", help="输出 JSON")
    pv_drafts = evolve_sub.add_parser("drafts", help="列出提示草案")
    pv_drafts.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pv_drafts.add_argument("--json", action="store_true", help="输出 JSON")
    pv_peval = evolve_sub.add_parser("eval", help="以草案跑评测对比（防退化闸门）")
    pv_peval.add_argument("draft", help="草案 id")
    pv_peval.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pv_peval.add_argument("--json", action="store_true", help="输出 JSON")
    pv_apply = evolve_sub.add_parser("apply", help="L3 人审通过后落盘生效")
    pv_apply.add_argument("draft", help="草案 id")
    pv_apply.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    pv_apply.add_argument("--yes", action="store_true", help="确认人审通过（L3）")
    pv_revert = evolve_sub.add_parser("revert", help="回退到上一个提示覆盖层")
    pv_revert.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")

    # eval — 评测基线（R19）
    p_eval = sub.add_parser("eval", help="评测基线（确定性回归，防能力退化）")
    eval_sub = p_eval.add_subparsers(dest="eval_cmd", required=True)
    pe_run = eval_sub.add_parser("run", help="运行评测用例集")
    pe_run.add_argument("--dir", default="", help="用例目录（默认内置 tests/eval）")
    pe_run.add_argument("--case", default="", help="仅运行指定用例 id（逗号分隔）")
    pe_run.add_argument("--json", action="store_true", help="输出 JSON 报告")
    pe_run.add_argument(
        "--min-pass-rate",
        type=float,
        default=1.0,
        help="通过率阈值（低于则退出码非零，默认 1.0）",
    )

    # receipt — 任务回执（R28）
    p_receipt = sub.add_parser("receipt", help="查看 Run 任务回执（.auc/receipts）")
    p_receipt.add_argument("--sandbox", default="", help="沙盒根目录（默认当前目录）")
    p_receipt.add_argument("--run", default=None, help="run_id（默认最近一次）")
    p_receipt.add_argument("--list", action="store_true", help="仅列出回执 run_id")

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
    if args.cmd == "receipt":
        return _cmd_receipt(args)
    if args.cmd == "mcp":
        if args.mcp_cmd == "list":
            return _cmd_mcp_list(args)
    if args.cmd == "jobs":
        return _cmd_jobs(args)
    if args.cmd == "routines":
        return _cmd_routines(args)
    if args.cmd == "eval":
        if args.eval_cmd == "run":
            return _cmd_eval(args)
    if args.cmd == "worktree":
        return _cmd_worktree(args)
    if args.cmd == "evolve":
        if args.evolve_cmd == "stats":
            return _cmd_evolve_stats(args)
        if args.evolve_cmd in {"propose", "drafts", "eval", "apply", "revert"}:
            return _cmd_evolve_prompt(args)
    if args.cmd == "skills":
        return _cmd_skills(args)

    if args.cmd == "chat":
        if getattr(args, "background", False):
            return _cmd_chat_background(args)
        return asyncio.run(_run_chat(args))
    if args.cmd == "review":
        return asyncio.run(_run_review(args))
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
