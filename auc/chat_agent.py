from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry
from auc.config import ModelConfig, load_merged_settings
from auc.integration.evolution import EvolutionMemoryPort, make_evolution_tools
from auc.loop.base import LoopConfig
from auc.model.factory import create_model_client
from auc.policy.autonomy import normalize_autonomy
from auc.policy.escalation import merge_escalation_settings
from auc.policy.privilege import ToolPrivilegeGate
from auc.ports import FileRulesPort, SlicerPolicy
from auc.ports.memory import DefaultComposer
from auc.roles import (
    CHAT_SHARED_TOOLS,
    DEFAULT_ROLE_ID,
    build_role_system_prompt,
    get_role,
    load_role_catalog,
)
from auc.tools.fetch import make_fetch_tool
from auc.tools.files import make_file_tools
from auc.tools.search import make_search_tools
from auc.tools.roles import make_role_tools
from auc.tools.shell import make_shell_tool

if TYPE_CHECKING:
    from auc.ports.approval import ApprovalPort
from auc.work_mode import WORK_MODE_OVERVIEW

# 兼容测试与外部引用：含 {sandbox} 占位符的完整模板
DEFAULT_CHAT_BASE = (
    get_role(DEFAULT_ROLE_ID).persona.format(sandbox="{sandbox}") + "\n\n" + CHAT_SHARED_TOOLS
)
DEFAULT_CHAT_SYSTEM = DEFAULT_CHAT_BASE + "\n\n" + WORK_MODE_OVERVIEW


def build_chat_system_prompt(
    sandbox: str,
    *,
    extra: str | None = None,
    include_work_mode: bool = True,
    role_id: str | None = None,
    catalog=None,
) -> str:
    return build_role_system_prompt(
        sandbox,
        role_id,
        include_work_mode=include_work_mode,
        extra=extra,
        catalog=catalog,
    )


@dataclass
class ChatAgentOptions:
    sandbox: str
    repo: str | None = None
    system_prompt: str | None = None
    evolve: bool = True
    no_tools: bool = False
    max_steps: int = 40
    include_work_mode: bool = True
    role_id: str | None = None


def resolve_sandbox_root(*, sandbox: str | None = None, repo: str | None = None) -> str:
    if sandbox:
        return str(Path(sandbox).expanduser().resolve())
    if repo:
        return str(Path(repo).expanduser().resolve())
    return str(Path.cwd().resolve())


def build_chat_agent(
    cfg: ModelConfig,
    opts: ChatAgentOptions,
    *,
    approval: ApprovalPort | None = None,
) -> DefaultAgent:
    sandbox = resolve_sandbox_root(sandbox=opts.sandbox, repo=opts.repo)
    try:
        settings, _ = load_merged_settings(
            None, Path(opts.repo) if opts.repo else None
        )
    except Exception:  # noqa: BLE001
        settings = {}
    catalog = load_role_catalog(sandbox=sandbox, settings=settings)
    role_id = catalog.resolve(opts.role_id or str(settings.get("role") or DEFAULT_ROLE_ID))
    memory = (
        EvolutionMemoryPort(sandbox_root=sandbox, default_role_id=role_id)
        if opts.evolve and not opts.no_tools
        else None
    )
    shell_settings = settings.get("shell") or {}
    registry = DefaultToolRegistry()
    if not opts.no_tools:
        for tool, pol in make_file_tools(sandbox):
            registry.register(tool, pol)
        shell_tool, shell_pol = make_shell_tool(
            sandbox,
            default_timeout=float(shell_settings.get("default_timeout") or 120),
            max_timeout=float(shell_settings.get("max_timeout") or 600),
        )
        registry.register(shell_tool, shell_pol)
        for tool, pol in make_search_tools(sandbox):
            registry.register(tool, pol)
        if memory is not None:
            for tool, pol in make_evolution_tools(memory):
                registry.register(tool, pol)
        for tool, pol in make_role_tools(sandbox):
            registry.register(tool, pol)
        for tool, pol in make_fetch_tool(sandbox):
            registry.register(tool, pol)

    gate = ToolPrivilegeGate(
        approval=approval,
        escalation_rules=merge_escalation_settings(settings.get("escalations")),
    )
    system = opts.system_prompt or build_role_system_prompt(
        sandbox,
        role_id,
        include_work_mode=opts.include_work_mode,
        catalog=catalog,
    )
    model = create_model_client(cfg)
    compaction = settings.get("compaction") or {}
    loop_config = LoopConfig(
        max_steps=opts.max_steps,
        context_token_limit=int(compaction.get("token_limit") or 96_000),
    )
    return DefaultAgent(
        AgentConfig(
            agent_id=f"chat:{role_id}",
            model=model,
            tools=registry,
            memory=memory,
            composer=DefaultComposer(),
            rules=FileRulesPort() if opts.repo else None,
            slicer_policy=SlicerPolicy(require_package=False),
            system_prompt=system,
            sandbox_root=sandbox,
            approval=approval,
            privilege_gate=gate,
            loop_config=loop_config,
            autonomy=normalize_autonomy(str(settings.get("autonomy") or "")),
        )
    )
