from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from auc.types import MessageRole, RunId, RunStatus

if TYPE_CHECKING:
    from auc.ports.package import ContextPackage


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ImageAttachment:
    """多模态图片附件（base64）。"""

    mime_type: str
    data_base64: str
    name: str | None = None
    source_path: str | None = None


@dataclass
class ChatMessage:
    role: MessageRole
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    thinking: str | None = None
    images: list[ImageAttachment] | None = None


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
    context_package: ContextPackage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunResult:
    output: str
    messages: list[ChatMessage]
    status: RunStatus
    run_id: RunId
    error: str | None = None
    usage: dict[str, Any] | None = None
