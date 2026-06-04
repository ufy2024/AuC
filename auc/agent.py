from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from auc.context.window import ListContextWindow
from auc.events.bus import EventBus, RunEvent
from auc.loop.base import AgentLoopRunner, LoopConfig, LoopContext
from auc.loop.react import ReActLoop
from auc.messages import ChatMessage, RunRequest, RunResult
from auc.model.client import ModelClient
from auc.ports.approval import ApprovalPort
from auc.ports.memory import ContextComposer, MemoryPort
from auc.ports.package import ContextPackage, SlicerPolicy
from auc.ports.rules import ProjectRules, ProjectRulesPort
from auc.policy.privilege import ToolPrivilegeGate
from auc.tools.registry import DefaultToolRegistry
from auc.types import AgentId, RunId


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


class DefaultAgent:
    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._loop = config.loop or ReActLoop()
        self._runner = AgentLoopRunner()
        self._cancelled_runs: set[RunId] = set()
        self._active_events: dict[RunId, EventBus] = {}
        self._last_run_result: RunResult | None = None

    @property
    def agent_id(self) -> AgentId:
        return self._config.agent_id

    def cancel(self, run_id: RunId) -> None:
        self._cancelled_runs.add(run_id)

    async def run(self, request: RunRequest | str | list[ChatMessage]) -> RunResult:
        ctx, bus = await self._prepare_context(self._normalize_request(request))
        self._active_events[ctx.run_id] = bus
        try:
            return await self._runner.run_until_done(self._loop, ctx)
        finally:
            self._active_events.pop(ctx.run_id, None)
            self._cancelled_runs.discard(ctx.run_id)

    async def run_stream(
        self, request: RunRequest | str | list[ChatMessage]
    ) -> AsyncIterator[RunEvent]:
        ctx, bus = await self._prepare_context(self._normalize_request(request))
        queue = bus.create_stream_queue()
        self._active_events[ctx.run_id] = bus

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
            self._last_run_result = await task
            self._active_events.pop(ctx.run_id, None)
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
        if isinstance(request.input, str):
            window.append(ChatMessage(role="user", content=request.input))
        else:
            for msg in request.input:
                window.append(msg)

        project_rules: ProjectRules | None = None
        repo_root = request.metadata.get("repo_root")
        if self._config.rules and repo_root:
            project_rules = await self._config.rules.load_rules(str(repo_root))
            self._config.tools.merge_tool_policy(project_rules.tool_policy)

        package: ContextPackage | None = request.context_package
        if package is None and request.metadata.get("context_package"):
            package = request.metadata["context_package"]

        bus = EventBus()
        gate = self._config.privilege_gate or ToolPrivilegeGate(
            approval=self._config.approval
        )

        ctx = LoopContext(
            agent_id=self._config.agent_id,
            run_id=run_id,
            window=window,
            tools=self._config.tools,
            model=self._config.model,
            events=bus,
            config=self._config.loop_config,
            memory=self._config.memory,
            composer=self._config.composer,
            context_package=package,
            project_rules=project_rules,
            privilege_gate=gate,
            approval=self._config.approval,
            system_prompt=self._config.system_prompt,
            cancelled=run_id in self._cancelled_runs,
        )
        return ctx, bus
