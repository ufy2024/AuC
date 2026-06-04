from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

from auc.context.window import ContextWindow
from auc.events.bus import EventBus
from auc.messages import ChatMessage, RunResult, ToolResult
from auc.model.client import AssistantMessage, ModelClient
from auc.ports.approval import ApprovalPort
from auc.ports.memory import ContextComposer, MemoryPort
from auc.ports.package import ContextPackage
from auc.ports.rules import ProjectRules
from auc.policy.privilege import ToolPrivilegeGate
from auc.tools.registry import DefaultToolRegistry
from auc.types import AgentId, RunId, RunStatus


@dataclass
class LoopConfig:
    max_steps: int = 20
    stop_sequences: list[str] = field(default_factory=list)
    parallel_tool_calls: bool = True
    remember_each_step: bool = False


@dataclass
class LoopContext:
    agent_id: AgentId
    run_id: RunId
    window: ContextWindow
    tools: DefaultToolRegistry
    model: ModelClient
    events: EventBus
    config: LoopConfig
    memory: MemoryPort | None = None
    composer: ContextComposer | None = None
    context_package: ContextPackage | None = None
    project_rules: ProjectRules | None = None
    privilege_gate: ToolPrivilegeGate | None = None
    approval: ApprovalPort | None = None
    system_prompt: str | None = None
    cancelled: bool = False
    step_index: int = 0
    error: str | None = None


@dataclass
class LoopStepResult:
    assistant_message: AssistantMessage | None
    tool_results: list[ToolResult]
    step_index: int
    done: bool


class AgentLoop(Protocol):
    async def step(self, ctx: LoopContext) -> LoopStepResult: ...

    def should_continue(self, ctx: LoopContext, last: LoopStepResult) -> bool: ...


def _last_user_content(window: ContextWindow) -> str:
    for msg in reversed(window.view()):
        if msg.role == "user":
            return msg.content
    return ""


def _assistant_chat_message(assistant: AssistantMessage) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=assistant.content or "",
        tool_calls=assistant.tool_calls,
    )


def _tool_chat_message(tr: ToolResult) -> ChatMessage:
    return ChatMessage(
        role="tool",
        content=tr.content,
        tool_call_id=tr.tool_call_id,
        name=tr.name,
    )


async def default_compose(
    ctx: LoopContext,
    recall: list[ChatMessage],
) -> list[ChatMessage]:
    if ctx.composer is not None:
        return await ctx.composer.compose(
            ctx.window,
            recall,
            system_prompt=ctx.system_prompt,
            rules=ctx.project_rules,
            package=ctx.context_package,
        )
    from auc.ports.memory import DefaultComposer

    return await DefaultComposer().compose(
        ctx.window,
        recall,
        system_prompt=ctx.system_prompt,
        rules=ctx.project_rules,
        package=ctx.context_package,
    )


def build_run_result(
    ctx: LoopContext,
    status: RunStatus,
    last: LoopStepResult | None,
) -> RunResult:
    messages = ctx.window.view()
    output = ""
    if last and last.assistant_message and last.assistant_message.content:
        output = last.assistant_message.content
    elif messages:
        for msg in reversed(messages):
            if msg.role == "assistant" and msg.content and not msg.tool_calls:
                output = msg.content
                break
    return RunResult(
        output=output,
        messages=messages,
        status=status,
        run_id=ctx.run_id,
        error=ctx.error,
    )


def resolve_status(ctx: LoopContext, last: LoopStepResult | None) -> RunStatus:
    if ctx.error:
        return "error"
    if ctx.cancelled:
        if last and any(tr.is_error for tr in last.tool_results):
            for tr in last.tool_results:
                if "denied" in tr.content.lower():
                    return "denied"
        return "cancelled"
    if last is None:
        return "error"
    if ctx.step_index >= ctx.config.max_steps and not last.done:
        return "max_steps"
    if last.done:
        return "completed"
    return "max_steps"


class AgentLoopRunner:
    async def run_until_done(self, loop: AgentLoop, ctx: LoopContext) -> RunResult:
        ctx.events.emit_typed("run_start", ctx.run_id, ctx.agent_id, {})
        last: LoopStepResult | None = None

        while True:
            if ctx.cancelled:
                status = resolve_status(ctx, last)
                ctx.events.emit_typed(
                    "run_end", ctx.run_id, ctx.agent_id, {"status": status}
                )
                return build_run_result(ctx, status, last)

            ctx.events.emit_typed(
                "step_start",
                ctx.run_id,
                ctx.agent_id,
                {"index": ctx.step_index},
            )
            try:
                last = await loop.step(ctx)
            except Exception as exc:  # noqa: BLE001
                ctx.error = str(exc)
                ctx.events.emit_typed(
                    "run_end", ctx.run_id, ctx.agent_id, {"status": "error"}
                )
                return build_run_result(ctx, "error", last)

            ctx.step_index += 1
            ctx.events.emit_typed(
                "step_end",
                ctx.run_id,
                ctx.agent_id,
                {"index": ctx.step_index - 1, "done": last.done},
            )

            if not loop.should_continue(ctx, last):
                break

        status = resolve_status(ctx, last)
        ctx.events.emit_typed("run_end", ctx.run_id, ctx.agent_id, {"status": status})
        return build_run_result(ctx, status, last)
