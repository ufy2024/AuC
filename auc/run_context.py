"""当前 Run 的轻量上下文（工具回调内可读 agent_id / LoopContext）。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from auc.types import AgentId

if TYPE_CHECKING:
    from auc.loop.base import LoopContext

current_agent_id: ContextVar[AgentId | None] = ContextVar("current_agent_id", default=None)

# R10/R13：工具回调内可达当前 LoopContext（用于 update_todos 等需要 emit 事件/读写状态的工具）。
current_loop_context: ContextVar["LoopContext | None"] = ContextVar(
    "current_loop_context", default=None
)
