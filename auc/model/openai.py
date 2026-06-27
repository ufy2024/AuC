from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from auc.messages import ChatMessage, ToolCall
from auc.multimodal import openai_message_content
from auc.model.client import AssistantMessage, StreamChunk, TokenUsage
from auc.model.json_util import PARSE_ERROR_KEY, safe_parse_tool_input
from auc.model.retry import _RETRY_STATUS, make_timeout, with_retry
from auc.tools.base import ToolSchema

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


def _require_httpx() -> Any:
    if httpx is None:
        from auc.extras import hint_for

        raise ImportError(hint_for("llm", "all"))
    return httpx


def _messages_to_api(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        content = openai_message_content(m) if m.role == "user" else m.content
        item: dict[str, Any] = {"role": m.role, "content": content}
        if m.name:
            item["name"] = m.name
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            item["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in m.tool_calls
            ]
        out.append(item)
    return out


def _tools_to_api(tools: list[ToolSchema] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


def _format_api_error(status_code: int, body_text: str) -> str:
    """从 API 错误响应体提取可读原因（OpenAI 兼容多为 {"error":{"message":...}}）。"""
    detail = (body_text or "").strip()
    try:
        data = json.loads(body_text)
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                detail = str(err["message"])
            elif isinstance(err, str) and err:
                detail = err
            elif data.get("message"):
                detail = str(data["message"])
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    msg = f"OpenAI API {status_code} error"
    if detail:
        msg = f"{msg}: {detail[:1000]}"
    return msg


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall] | None:
    if not raw:
        return None
    calls: list[ToolCall] = []
    for item in raw:
        fn = item.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        if isinstance(args_raw, str):
            args = json.loads(args_raw) if args_raw else {}
        else:
            args = args_raw
        calls.append(
            ToolCall(
                id=str(item.get("id", "")),
                name=str(fn.get("name", "")),
                arguments=args,
            )
        )
    return calls or None


@dataclass
class OpenAICompatibleClient:
    """Chat Completions client for OpenAI and compatible APIs."""

    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 120.0
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_httpx()
        from auc.config import normalize_openai_compatible_base_url

        self.base_url = normalize_openai_compatible_base_url(self.base_url)
        if self.api_key is None:
            self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY required for OpenAICompatibleClient")

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=make_timeout(self.timeout),
            )
        return self._client

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AssistantMessage:
        client = self._get_client()
        body = self._build_body(messages, tools, stream=False)

        async def _do() -> Any:
            resp = await client.post("/chat/completions", json=body)
            if resp.is_error:
                # 5xx/429 等瞬时错误仍抛 HTTPStatusError 走重试；其余客户端错误
                # （400/401/403/404/422…）透出响应体里的具体原因，便于定位。
                if resp.status_code in _RETRY_STATUS:
                    resp.raise_for_status()
                raise RuntimeError(_format_api_error(resp.status_code, resp.text))
            return resp.json()

        data = await with_retry(_do, label="openai")
        if data.get("error"):
            err = data["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise RuntimeError(f"OpenAI API error: {msg}")
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenAI API returned no choices")
        choice = choices[0]["message"]
        return AssistantMessage(
            content=choice.get("content"),
            tool_calls=_parse_tool_calls(choice.get("tool_calls")),
            raw=data,
            usage=TokenUsage.from_api(data.get("usage")),
        )

    def _build_body(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": _messages_to_api(messages),
            "stream": stream,
        }
        api_tools = _tools_to_api(tools)
        if api_tools:
            body["tools"] = api_tools
            body["tool_choice"] = "auto"
        return body

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        body = self._build_body(messages, tools, stream=True)
        tool_acc: dict[int, dict[str, str]] = {}

        async with client.stream(
            "POST", "/chat/completions", json=body
        ) as resp:
            if resp.is_error:
                try:
                    body_text = (await resp.aread()).decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    body_text = ""
                if resp.status_code in _RETRY_STATUS:
                    resp.raise_for_status()
                raise RuntimeError(_format_api_error(resp.status_code, body_text))
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                if data.get("error"):
                    err = data["error"]
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise RuntimeError(f"OpenAI API error: {msg}")
                usage = TokenUsage.from_api(data.get("usage"))
                if usage is not None:
                    yield StreamChunk(usage=usage)
                for choice in data.get("choices") or []:
                    delta = choice.get("delta") or {}
                    text = delta.get("content")
                    if text:
                        yield StreamChunk(delta_content=text)
                    for tc in delta.get("tool_calls") or []:
                        idx = int(tc.get("index", 0))
                        entry = tool_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            entry["name"] = fn["name"]
                        if fn.get("arguments"):
                            entry["arguments"] += fn["arguments"]
                    if choice.get("finish_reason"):
                        yield StreamChunk(finish_reason=choice["finish_reason"])

        if tool_acc:
            calls = []
            for idx in sorted(tool_acc.keys()):
                entry = tool_acc[idx]
                raw = entry.get("arguments") or "{}"
                try:
                    args = safe_parse_tool_input(raw, tool_name=entry.get("name") or "")
                except ValueError as exc:
                    # 解析失败转为工具错误反馈给模型自纠，而非终止整个 run
                    args = {PARSE_ERROR_KEY: str(exc)}
                calls.append(
                    ToolCall(
                        id=entry.get("id") or f"call_{idx}",
                        name=entry.get("name") or "",
                        arguments=args,
                    )
                )
            yield StreamChunk(delta_tool_calls=calls, finish_reason="tool_calls")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
