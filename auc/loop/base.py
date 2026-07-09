from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from auc.context.window import ContextWindow, TruncatePolicy
from auc.events.bus import EventBus
from auc.messages import ChatMessage, RunResult, ToolResult
from auc.model.client import AssistantMessage, ModelClient
from auc.model.retry import format_model_http_error
from auc.policy.autonomy import AutonomyPolicy
from auc.ports.approval import ApprovalPort
from auc.ports.memory import ContextComposer, MemoryPort
from auc.ports.package import ContextPackage
from auc.ports.rules import ProjectRules
from auc.policy.privilege import ToolPrivilegeGate
from auc.tools.registry import DefaultToolRegistry
from auc.types import AgentId, RunId, RunStatus

if TYPE_CHECKING:
    from auc.checkpoint import CheckpointStore
    from auc.context.compactor import SummarizingCompactor


@dataclass
class LoopConfig:
    max_steps: int = 20
    stop_sequences: list[str] = field(default_factory=list)
    parallel_tool_calls: bool = True
    remember_each_step: bool = False
    max_window_messages: int = 80
    context_token_limit: int = 96_000  # R3：0 表示关闭自动压缩
    max_total_tokens: int = 0  # R11：累计 token 预算上限，0 表示不限
    write_receipt: bool = True  # R28：Run 结束落任务回执（无沙盒/空回执自动跳过）


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
    autonomy_policy: AutonomyPolicy | None = None  # R6 会话级自治
    checkpoints: CheckpointStore | None = None  # R4 写前快照
    compactor: SummarizingCompactor | None = None  # R3 自动压缩
    todos: list[dict[str, Any]] = field(default_factory=list)  # R10
    parent_run_id: RunId | None = None  # R13 子 Run 关联
    usage_tracker: Any = None  # R11 用量累计（auc.usage.UsageTracker）
    hooks: Any = None  # R14 生命周期钩子（auc.hooks.HookRunner）
    last_resolved_model: str | None = None  # 智能路由：网关上一次实际选用的模型


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
        thinking=assistant.thinking,
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
    usage = None
    tracker = getattr(ctx, "usage_tracker", None)
    if tracker is not None and getattr(tracker, "calls", 0) > 0:
        usage = tracker.snapshot()
    return RunResult(
        output=output,
        messages=messages,
        status=status,
        run_id=ctx.run_id,
        error=ctx.error,
        usage=usage,
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
    async def _end_run(self, ctx: LoopContext, status: str, *, error: str | None = None) -> None:
        """R28：先落回执并 emit receipt_ready（供流式消费），再 emit run_end。"""
        if ctx.config.write_receipt:
            try:
                from auc.receipt import finalize_receipt

                path = finalize_receipt(ctx, status)
                if path:
                    ctx.events.emit_typed(
                        "receipt_ready",
                        ctx.run_id,
                        ctx.agent_id,
                        {"path": path, "status": status},
                    )
            except Exception:  # noqa: BLE001 回执不得影响 Run 结束
                pass
        payload: dict[str, Any] = {"status": status}
        if error is not None:
            payload["error"] = error
        ctx.events.emit_typed("run_end", ctx.run_id, ctx.agent_id, payload)
        await self._run_lifecycle_hook(ctx, "run_end", dict(payload))

    @staticmethod
    async def _run_lifecycle_hook(ctx: LoopContext, event: str, payload: dict[str, Any]) -> None:
        hooks = getattr(ctx, "hooks", None)
        if hooks is None or not hooks.has(event):
            return
        try:
            await hooks.run_lifecycle(
                event,
                {"event": event, "run_id": ctx.run_id, "agent_id": ctx.agent_id, **payload},
            )
        except Exception:  # noqa: BLE001 钩子失败不影响 Run
            pass

    @staticmethod
    def _model_descriptor(ctx: LoopContext) -> dict[str, Any]:
        """本次 Run 实际使用的模型标识（供 UI 实时显示与切换提示）。"""
        return {
            "model": getattr(ctx.model, "model", None),
            "base_url": getattr(ctx.model, "base_url", None),
        }

    async def run_until_done(self, loop: AgentLoop, ctx: LoopContext) -> RunResult:
        start_payload = self._model_descriptor(ctx)
        ctx.events.emit_typed("run_start", ctx.run_id, ctx.agent_id, start_payload)
        await self._run_lifecycle_hook(ctx, "run_start", dict(start_payload))
        last: LoopStepResult | None = None

        while True:
            if ctx.config.max_window_messages > 0:
                ctx.window.truncate(TruncatePolicy(max_messages=ctx.config.max_window_messages))
            if ctx.cancelled:
                status = resolve_status(ctx, last)
                await self._end_run(ctx, status)
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
                ctx.error = format_model_http_error(exc)
                await self._end_run(ctx, "error", error=ctx.error)
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
        await self._end_run(ctx, status, error=ctx.error)
        return build_run_result(ctx, status, last)
