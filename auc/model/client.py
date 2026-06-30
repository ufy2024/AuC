from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

from auc.messages import ChatMessage, ToolCall
from auc.tools.base import ToolSchema


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_api(cls, raw: dict[str, Any] | None) -> "TokenUsage | None":
        if not isinstance(raw, dict):
            return None
        prompt = int(
            raw.get("prompt_tokens")
            or raw.get("input_tokens")
            or 0
        )
        completion = int(
            raw.get("completion_tokens")
            or raw.get("output_tokens")
            or 0
        )
        total = int(raw.get("total_tokens") or (prompt + completion))
        if not (prompt or completion or total):
            return None
        return cls(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


@dataclass
class AssistantMessage:
    content: str | None
    tool_calls: list[ToolCall] | None
    raw: dict[str, Any] | None = None
    thinking: str | None = None
    usage: TokenUsage | None = None
    resolved_model: str | None = None  # 网关实际选用的模型（智能路由 auto 时尤为重要）
    route_source: str | None = None  # 智能路由来源：'gateway'（网关选型）/'local'（本地选型）


@dataclass
class StreamChunk:
    delta_content: str | None = None
    delta_thinking: str | None = None
    delta_tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    resolved_model: str | None = None
    route_source: str | None = None


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
    """可脚本化的测试用模型：从队列中弹出预设响应。"""

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
            for ch in msg.content:
                yield StreamChunk(delta_content=ch)
            yield StreamChunk(finish_reason="stop", usage=msg.usage)
        if msg.tool_calls:
            yield StreamChunk(
                delta_tool_calls=msg.tool_calls,
                finish_reason="stop",
                usage=msg.usage,
            )
        if not msg.content and not msg.tool_calls and msg.usage is not None:
            yield StreamChunk(finish_reason="stop", usage=msg.usage)
