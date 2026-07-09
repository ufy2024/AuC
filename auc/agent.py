from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auc.checkpoint import CheckpointStore
from auc.context.compactor import CompactionConfig, SummarizingCompactor
from auc.context.window import ListContextWindow
from auc.events.bus import EventBus, RunEvent
from auc.loop.base import AgentLoopRunner, LoopConfig, LoopContext
from auc.loop.react import ReActLoop
from auc.messages import ChatMessage, RunRequest, RunResult
from auc.model.client import ModelClient
from auc.plan import READONLY_TOOL_NAMES, render_plan_context
from auc.policy.autonomy import AutonomyPolicy, normalize_autonomy
from auc.ports.approval import ApprovalPort
from auc.ports.memory import ContextComposer, MemoryPort
from auc.ports.package import ContextPackage, SlicerPolicy
from auc.ports.rules import ProjectRules, ProjectRulesPort
from auc.policy.privilege import ToolPrivilegeGate
from auc.tools.registry import DefaultToolRegistry
from auc.config import load_merged_settings
from auc.roles import build_role_system_prompt, load_role_catalog
from auc.types import AgentId, AutonomyLevel, RunId


@dataclass
class AgentConfig:
    agent_id: AgentId
    model: ModelClient
    tools: DefaultToolRegistry
    loop: ReActLoop | None = None
    memory: MemoryPort | None = None
    composer: ContextComposer | None = None
    rules: ProjectRulesPort | None = None
    approval: ApprovalPort | None = None
    privilege_gate: ToolPrivilegeGate | None = None
    slicer_policy: SlicerPolicy | None = None
    loop_config: LoopConfig = field(default_factory=LoopConfig)
    system_prompt: str | None = None
    sandbox_root: str | None = None
    autonomy: AutonomyLevel = "auto-edit"  # R6 默认级别，可被 metadata.autonomy 覆盖
    auto_approve: bool = False  # 全部通过（仅 full-auto + 本地门禁）
    enable_checkpoints: bool = True  # R4
    compaction: CompactionConfig | None = None  # R3，None 时按 loop_config 构造
    hooks: Any = None  # R14 生命周期钩子（auc.hooks.HookRunner）


class DefaultAgent:
    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._loop = config.loop or ReActLoop()
        self._runner = AgentLoopRunner()
        self._cancelled_runs: set[RunId] = set()
        self._active_events: dict[RunId, EventBus] = {}
        self._active_ctx: dict[RunId, LoopContext] = {}
        self._last_run_result: RunResult | None = None

    @property
    def agent_id(self) -> AgentId:
        return self._config.agent_id

    def cancel(self, run_id: RunId) -> None:
        self._cancelled_runs.add(run_id)
        ctx = self._active_ctx.get(run_id)
        if ctx is not None:
            ctx.cancelled = True

    async def run(self, request: RunRequest | str | list[ChatMessage]) -> RunResult:
        ctx, bus = await self._prepare_context(self._normalize_request(request))
        self._active_events[ctx.run_id] = bus
        self._active_ctx[ctx.run_id] = ctx
        try:
            return await self._runner.run_until_done(self._loop, ctx)
        finally:
            self._active_events.pop(ctx.run_id, None)
            self._active_ctx.pop(ctx.run_id, None)
            self._cancelled_runs.discard(ctx.run_id)

    async def run_stream(
        self, request: RunRequest | str | list[ChatMessage]
    ) -> AsyncIterator[RunEvent]:
        ctx, bus = await self._prepare_context(self._normalize_request(request))
        queue = bus.create_stream_queue()
        self._active_events[ctx.run_id] = bus
        self._active_ctx[ctx.run_id] = ctx

        async def _run() -> RunResult:
            return await self._runner.run_until_done(self._loop, ctx)

        task = asyncio.create_task(_run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
                if event.type == "run_end":
                    break
        finally:
            bus.close_stream_queue(queue)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            try:
                self._last_run_result = await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                self._last_run_result = RunResult(
                    output="",
                    messages=ctx.window.view(),
                    status="error",
                    run_id=ctx.run_id,
                    error=str(ctx.error or "cancelled"),
                )
            self._active_events.pop(ctx.run_id, None)
            self._active_ctx.pop(ctx.run_id, None)
            self._cancelled_runs.discard(ctx.run_id)

    @property
    def last_run_result(self) -> RunResult | None:
        return self._last_run_result

    @staticmethod
    def _normalize_request(
        request: RunRequest | str | list[ChatMessage],
    ) -> RunRequest:
        if isinstance(request, RunRequest):
            return request
        return RunRequest(input=request)

    async def _prepare_context(
        self, request: RunRequest
    ) -> tuple[LoopContext, EventBus]:
        run_id = request.run_id or str(uuid.uuid4())
        if self._config.slicer_policy and self._config.slicer_policy.require_package:
            if request.context_package is None:
                raise ValueError(
                    "context_package required by SlicerPolicy.require_package"
                )

        window = ListContextWindow()
        approved_plan = request.metadata.get("approved_plan")
        if isinstance(approved_plan, dict):
            window.append(
                ChatMessage(role="system", content=render_plan_context(approved_plan))
            )
        if isinstance(request.input, str):
            window.append(ChatMessage(role="user", content=request.input))
        else:
            for msg in request.input:
                window.append(msg)

        tools = self._config.tools
        project_rules: ProjectRules | None = None
        repo_root = request.metadata.get("repo_root")
        if self._config.rules and repo_root:
            project_rules = await self._config.rules.load_rules(str(repo_root))
            if project_rules.tool_policy:
                tools = DefaultToolRegistry()
                for t in self._config.tools._tools.values():
                    tools.register(t, self._config.tools._policies.get(t.name))
                tools.merge_tool_policy(project_rules.tool_policy)

        sandbox = self._config.sandbox_root or (
            str(Path(repo_root).resolve()) if repo_root else None
        )
        if sandbox:
            if project_rules is None:
                project_rules = ProjectRules(sandbox_root=sandbox)
            elif not project_rules.sandbox_root:
                project_rules.sandbox_root = sandbox

        package: ContextPackage | None = request.context_package
        if package is None and request.metadata.get("context_package"):
            package = request.metadata["context_package"]

        bus = EventBus()
        gate = self._config.privilege_gate or ToolPrivilegeGate(
            approval=self._config.approval
        )

        # R5：计划模式收窄为只读工具集（按白名单过滤，动态注册工具同样受限）
        if (
            request.metadata.get("work_mode") == "plan"
            or request.metadata.get("readonly_tools") is True
        ):
            tools = tools.filtered_view(READONLY_TOOL_NAMES)

        # R6：会话级授权模式（metadata 覆盖配置默认值）
        auto_approve = bool(request.metadata.get("auto_approve"))
        if "auto_approve" not in request.metadata:
            auto_approve = self._config.auto_approve
        autonomy = AutonomyPolicy(
            level=normalize_autonomy(
                str(request.metadata.get("autonomy") or self._config.autonomy)
            ),
            auto_approve=auto_approve,
        )

        # R4：写前检查点（沙盒内 .auc/checkpoints/，框架特权 IO）
        checkpoints: CheckpointStore | None = None
        if sandbox and self._config.enable_checkpoints:
            checkpoints = CheckpointStore(sandbox)

        # R3：上下文自动压缩
        compactor: SummarizingCompactor | None = None
        token_limit = self._config.loop_config.context_token_limit
        if self._config.compaction is not None:
            compactor = SummarizingCompactor(
                self._config.model, self._config.compaction
            )
        elif token_limit and token_limit > 0:
            compactor = SummarizingCompactor(
                self._config.model, CompactionConfig(token_limit=token_limit)
            )

        agent_id: AgentId = self._config.agent_id
        system_prompt = self._config.system_prompt
        role_id = request.metadata.get("role_id")
        if role_id:
            settings: dict = {}
            if sandbox:
                try:
                    settings, _ = load_merged_settings(
                        None,
                        Path(str(repo_root)) if repo_root else Path(sandbox),
                    )
                except Exception:  # noqa: BLE001
                    logging.getLogger("auc.agent").warning(
                        "failed to load settings for role resolution", exc_info=True
                    )
                    settings = {}
            catalog = load_role_catalog(sandbox=sandbox, settings=settings)
            rid = catalog.resolve(str(role_id))
            agent_id = f"chat:{rid}"
            if sandbox and request.metadata.get("apply_role_prompt", True):
                system_prompt = build_role_system_prompt(
                    sandbox, rid, catalog=catalog
                )
        # R22：追加已生效的提示覆盖层（人审落盘的 .auc/prompts/active.md）
        if sandbox:
            try:
                from auc.prompt_optimizer import load_active_overlay

                overlay = load_active_overlay(sandbox)
                if overlay:
                    system_prompt = (
                        f"{system_prompt}\n\n{overlay}" if system_prompt else overlay
                    )
            except Exception:  # noqa: BLE001 覆盖层加载失败不影响运行
                pass

        from auc.usage import UsageTracker

        usage_tracker = UsageTracker(
            model=str(getattr(self._config.model, "model", "") or "")
        )

        memory = self._config.memory
        if memory is not None and hasattr(memory, "set_skill_prefs"):
            from auc.skills import SkillPrefs

            skill_mode = str(request.metadata.get("skill_mode") or "auto")
            pinned_raw = request.metadata.get("skill_ids") or request.metadata.get("pinned_skills") or []
            pinned = [str(x) for x in pinned_raw] if isinstance(pinned_raw, list) else []
            memory.set_skill_prefs(
                SkillPrefs(
                    mode="manual" if skill_mode == "manual" else "auto",
                    pinned=pinned,
                )
            )

        ctx = LoopContext(
            agent_id=agent_id,
            run_id=run_id,
            window=window,
            tools=tools,
            model=self._config.model,
            events=bus,
            config=self._config.loop_config,
            memory=memory,
            composer=self._config.composer,
            context_package=package,
            project_rules=project_rules,
            privilege_gate=gate,
            approval=self._config.approval,
            system_prompt=system_prompt,
            cancelled=run_id in self._cancelled_runs,
            autonomy_policy=autonomy,
            checkpoints=checkpoints,
            compactor=compactor,
            parent_run_id=request.metadata.get("parent_run_id"),
            usage_tracker=usage_tracker,
            hooks=self._config.hooks,
        )
        return ctx, bus
