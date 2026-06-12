"""当前 Run 的轻量上下文（工具回调内可读 agent_id）。"""

from __future__ import annotations

from contextvars import ContextVar

from auc.types import AgentId

current_agent_id: ContextVar[AgentId | None] = ContextVar("current_agent_id", default=None)
