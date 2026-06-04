from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from auc.messages import ChatMessage, ToolCall
from auc.model.client import AssistantMessage, StreamChunk
from auc.tools.base import ToolSchema

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


def _require_httpx() -> Any:
    if httpx is None:
        raise ImportError("Install httpx: pip install 'auc[openai]'")
    return httpx


def _tools_to_anthropic(tools: list[ToolSchema] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.parameters,
        }
        for t in tools
    ]


def _to_anthropic_messages(
    messages: list[ChatMessage],
) -> tuple[str | None, list[dict[str, Any]]]:
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []

    for m in messages:
        if m.role == "system":
            system_parts.append(m.content)
            continue
        if m.role == "user":
            if m.tool_call_id:
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id,
                                "content": m.content,
                            }
                        ],
                    }
                )
            else:
                out.append({"role": "user", "content": m.content})
            continue
        if m.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            if m.tool_calls:
                for tc in m.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
            out.append({"role": "assistant", "content": blocks or ""})
            continue
        if m.role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id or "",
                            "content": m.content,
                        }
                    ],
                }
            )

    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def _parse_anthropic_response(data: dict[str, Any]) -> AssistantMessage:
    content_blocks = data.get("content") or []
    texts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            texts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    arguments=dict(block.get("input") or {}),
                )
            )
    return AssistantMessage(
        content="\n".join(texts) if texts else None,
        tool_calls=tool_calls or None,
        raw=data,
    )


@dataclass
class AnthropicClient:
    """Anthropic Messages API client."""

    model: str = "claude-sonnet-4-20250514"
    api_key: str | None = None
    base_url: str = "https://api.anthropic.com"
    max_tokens: int = 4096
    timeout: float = 120.0
    api_version: str = "2023-06-01"
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_httpx()
        if self.api_key is None:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required for AnthropicClient")

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers={
                    "x-api-key": self.api_key or "",
                    "anthropic-version": self.api_version,
                    "content-type": "application/json",
                },
                timeout=self.timeout,
            )
        return self._client

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AssistantMessage:
        client = self._get_client()
        system, api_messages = _to_anthropic_messages(messages)
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
        }
        if system:
            body["system"] = system
        api_tools = _tools_to_anthropic(tools)
        if api_tools:
            body["tools"] = api_tools

        resp = await client.post("/v1/messages", json=body)
        resp.raise_for_status()
        return _parse_anthropic_response(resp.json())

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        msg = await self.complete(messages, tools)
        if msg.content:
            yield StreamChunk(delta_content=msg.content, finish_reason="end_turn")
        if msg.tool_calls:
            yield StreamChunk(delta_tool_calls=msg.tool_calls, finish_reason="end_turn")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
