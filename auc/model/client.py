from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from auc.messages import ChatMessage, ToolCall
from auc.tools.base import ToolSchema


@dataclass
class AssistantMessage:
    content: str | None
    tool_calls: list[ToolCall] | None
    raw: dict[str, Any] | None = None


@dataclass
class StreamChunk:
    delta_content: str | None = None
    delta_tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None


class ModelClient(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AssistantMessage: ...

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamChunk]: ...


@dataclass
class InMemoryModelClient:
    """Scriptable model for tests: pop responses from a queue."""

    responses: list[AssistantMessage] = field(default_factory=list)
    _index: int = 0

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AssistantMessage:
        del messages, tools
        if self._index >= len(self.responses):
            return AssistantMessage(
                content="(no more scripted responses)",
                tool_calls=None,
            )
        msg = self.responses[self._index]
        self._index += 1
        return msg

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        msg = await self.complete(messages, tools)
        if msg.content:
            yield StreamChunk(delta_content=msg.content, finish_reason="stop")
        if msg.tool_calls:
            yield StreamChunk(delta_tool_calls=msg.tool_calls, finish_reason="stop")
