from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from auc.types import MessageRole, RunId, RunStatus


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ChatMessage:
    role: MessageRole
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    thinking: str | None = None


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class RunRequest:
    input: str | list[ChatMessage]
    run_id: RunId | None = None
    context_package: Any | None = None  # ContextPackage; avoid circular import
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    output: str
    messages: list[ChatMessage]
    status: RunStatus
    run_id: RunId
    error: str | None = None
