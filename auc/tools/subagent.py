"""R13 子智能体工具：`spawn_subagent(task, kind)`。

在当前 Run 内派生一个**一层嵌套**的子智能体，拥有独立窗口/预算，运行结束后
返回精简回执块（paths/commands/tests，复用 R28）。子 Run 经检查点/回执沉淀，可
单独 `auc undo` / `auc receipt` 追溯。父 Run 上 emit `subagent_start`/`subagent_end`。

约束：
  - 仅一层嵌套：子智能体注册时不含本工具；运行期再以 `parent_run_id` 兜底拒绝。
  - 子 Run 复用父进程的模型客户端与沙盒，避免连接泄漏与越权。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable

from auc.messages import RunRequest
from auc.receipt import ReceiptStore, RunReceipt, render_receipt_block
from auc.run_context import current_loop_context
from auc.tools.base import ToolPolicy, tool_from_function

# kind(role_id) -> 已构建的子智能体（DefaultAgent）。
SubagentBuilder = Callable[[str], Any]

# 子 Run 默认硬超时（秒）：防止子智能体挂死拖住父 Run。0 表示不限。
_DEFAULT_SUBAGENT_TIMEOUT = 900.0
# 监督轮询间隔与取消/超时后的收尾宽限。
_SUPERVISE_POLL = 0.2
_CANCEL_GRACE = 10.0


def _try_cancel_child(child: Any, run_id: str) -> None:
    cancel = getattr(child, "cancel", None)
    if callable(cancel):
        try:
            cancel(run_id)
        except Exception:  # noqa: BLE001 子 Run 取消尽力而为
            pass


async def _await_or_force(task: "asyncio.Task[Any]", grace: float) -> Any | None:
    """给 task 一个收尾宽限；超时则强制取消并吞掉异常，返回 None。"""
    try:
        return await asyncio.wait_for(asyncio.shield(task), grace)
    except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        return None


async def _run_child_supervised(
    child: Any,
    request: RunRequest,
    parent_ctx: Any,
    child_run_id: str,
    timeout: float,
) -> Any:
    """运行子 Run 并监督：父 Run 取消联动停子 Run；超硬超时终止。

    父 Run 在等待本工具期间若被 `cancel()`（`parent_ctx.cancelled=True`），
    这里会调用 `child.cancel(child_run_id)` 让子 Run 在下个 step 边界优雅停止；
    超过 `timeout` 秒亦然。收尾宽限后仍未结束则强制取消 task。
    """
    task: asyncio.Task[Any] = asyncio.create_task(child.run(request))
    loop = asyncio.get_event_loop()
    start = loop.time()
    while True:
        done, _ = await asyncio.wait({task}, timeout=_SUPERVISE_POLL)
        if task in done:
            return task.result()
        if parent_ctx is not None and getattr(parent_ctx, "cancelled", False):
            _try_cancel_child(child, child_run_id)
            result = await _await_or_force(task, _CANCEL_GRACE)
            if result is not None:
                return result
            raise ValueError("子智能体因父 Run 取消而终止")
        if timeout and (loop.time() - start) > timeout:
            _try_cancel_child(child, child_run_id)
            result = await _await_or_force(task, _CANCEL_GRACE)
            if result is not None:
                return result
            raise ValueError(f"子智能体超时（>{timeout:g}s）已终止")


def make_subagent_tool(
    *,
    build_agent: SubagentBuilder,
    sandbox: str,
    allowed_kinds: list[str],
    default_kind: str,
    timeout: float = _DEFAULT_SUBAGENT_TIMEOUT,
) -> tuple[Any, ToolPolicy]:
    kinds = [k for k in allowed_kinds if k]
    kinds_text = ", ".join(kinds) if kinds else default_kind

    async def spawn_subagent(task: str, kind: str = "") -> str:
        task = (task or "").strip()
        if not task:
            raise ValueError("task 不能为空")
        ctx = current_loop_context.get()
        if ctx is not None and getattr(ctx, "parent_run_id", None):
            raise ValueError("子智能体不可再派生子智能体（仅支持一层嵌套）")

        rid = (kind or "").strip() or default_kind
        if kinds and rid not in kinds:
            raise ValueError(f"未知 kind={rid!r}；可选：{kinds_text}")

        child_run_id = f"sub-{uuid.uuid4().hex[:12]}"
        parent_run_id = str(ctx.run_id) if ctx is not None else child_run_id
        if ctx is not None:
            ctx.events.emit_typed(
                "subagent_start",
                ctx.run_id,
                ctx.agent_id,
                {"child_run_id": child_run_id, "kind": rid, "task": task[:200]},
            )

        child = build_agent(rid)
        # 子 Run 不得比父 Run 更宽松：继承父 Run 的自治级别。
        # 父级未知时不注入 autonomy，让子智能体沿用自身配置默认值，
        # 而非强制抬升为 full-auto（避免 L2 父 Run 派生出全自动子 Run）。
        child_meta: dict[str, Any] = {
            "parent_run_id": parent_run_id,
            "role_id": rid,
        }
        parent_policy = getattr(ctx, "autonomy_policy", None) if ctx is not None else None
        parent_level = getattr(parent_policy, "level", None)
        if parent_level:
            child_meta["autonomy"] = parent_level
        request = RunRequest(
            input=task,
            run_id=child_run_id,
            metadata=child_meta,
        )
        result = await _run_child_supervised(
            child, request, ctx, child_run_id, timeout
        )

        receipt = ReceiptStore(sandbox).read(child_run_id) or RunReceipt(
            run_id=child_run_id,
            agent_id=f"chat:{rid}",
            status=result.status,
            error=result.error,
        )
        block = render_receipt_block(receipt, output=result.output or "")

        if ctx is not None:
            ctx.events.emit_typed(
                "subagent_end",
                ctx.run_id,
                ctx.agent_id,
                {
                    "child_run_id": child_run_id,
                    "kind": rid,
                    "status": result.status,
                    "changed_files": [c.path for c in receipt.changed_files],
                    "commands": len(receipt.commands),
                },
            )
        return block

    return tool_from_function(
        spawn_subagent,
        name="spawn_subagent",
        description=(
            "派生一个子智能体完成相对独立的子任务（一层嵌套，独立上下文与预算）。"
            f"kind 选择角色：{kinds_text}。返回子 Run 的精简回执（改动文件/命令/验证），"
            "适合并行化或隔离探索；子 Run 可经 auc receipt/undo 追溯。"
        ),
        privilege="L2",
        mutates_files=True,
        mutates_state=True,
    )
