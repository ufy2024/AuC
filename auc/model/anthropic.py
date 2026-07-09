from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from auc.messages import ChatMessage, ToolCall
from auc.multimodal import anthropic_user_content
from auc.model.client import AssistantMessage, StreamChunk, TokenUsage
from auc.model.retry import (
    DEFAULT_MAX_ATTEMPTS,
    _RETRY_STATUS,
    _backoff_delay,
    _is_retryable_exception,
    _retry_after_of,
    _status_of,
    format_model_http_error,
    make_timeout,
    with_retry,
)
from auc.model.deepseek_anthropic import (
    deepseek_request_extra,
    inject_assistant_thinking_block,
    is_deepseek_anthropic_base,
)
from auc.model.json_util import PARSE_ERROR_KEY, safe_parse_tool_input
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


def _sanitize_tool_pairing(messages: list[ChatMessage]) -> list[ChatMessage]:
    """丢弃窗口中缺少前序 assistant tool_use 的 tool_result 行。

    当 tool_result 引用的 id 未出现在紧邻的上一条 assistant 消息中时，
    Anthropic / DeepSeek 会拒绝请求（常见于上下文压缩或历史损坏后）。
    """
    out: list[ChatMessage] = []
    pending_ids: set[str] = set()

    for m in messages:
        if m.role == "assistant":
            pending_ids = {tc.id for tc in (m.tool_calls or []) if tc.id}
            out.append(m)
            continue
        if m.role == "tool":
            tid = m.tool_call_id or ""
            if pending_ids and tid in pending_ids:
                out.append(m)
            continue
        if m.role == "user" and m.tool_call_id:
            tid = m.tool_call_id or ""
            if pending_ids and tid in pending_ids:
                out.append(m)
            continue
        pending_ids = set()
        out.append(m)

    # 去掉窗口开头残留的孤立 tool 消息
    while out and out[0].role == "tool":
        out.pop(0)
    return out


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
    *,
    deepseek: bool = False,
) -> tuple[str | None, list[dict[str, Any]]]:
    messages = _sanitize_tool_pairing(messages)
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    i = 0
    n = len(messages)

    while i < n:
        m = messages[i]
        if m.role == "system":
            system_parts.append(m.content)
            i += 1
            continue
        if m.role == "tool" and deepseek:
            results: list[dict[str, Any]] = []
            while i < n and messages[i].role == "tool":
                tm = messages[i]
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tm.tool_call_id or "",
                        "content": tm.content,
                    }
                )
                i += 1
            out.append({"role": "user", "content": results})
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
                out.append({"role": "user", "content": anthropic_user_content(m)})
            i += 1
            continue
        if m.role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            has_tools = bool(m.tool_calls)
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
            if deepseek:
                blocks = inject_assistant_thinking_block(
                    blocks, thinking=m.thinking, has_tool_use=has_tools
                )
            out.append({"role": "assistant", "content": blocks or None})
            i += 1
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
            i += 1
            continue
        i += 1

    system = "\n\n".join(system_parts) if system_parts else None
    return system, out


def _parse_anthropic_response(data: dict[str, Any]) -> AssistantMessage:
    content_blocks = data.get("content") or []
    texts: list[str] = []
    thinking_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        btype = block.get("type")
        if btype == "text":
            texts.append(block.get("text", ""))
        elif btype == "thinking":
            thinking_parts.append(block.get("thinking") or "")
        elif btype == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    arguments=dict(block.get("input") or {}),
                )
            )
    thinking = "\n".join(thinking_parts) if thinking_parts else None
    return AssistantMessage(
        content="\n".join(texts) if texts else None,
        tool_calls=tool_calls or None,
        raw=data,
        thinking=thinking if thinking or tool_calls else None,
        usage=TokenUsage.from_api(data.get("usage")),
        resolved_model=data.get("model") or None,
    )


async def _wrap_anthropic(func: Any) -> Any:
    return await with_retry(func, label="anthropic")


@dataclass
class AnthropicClient:
    """Anthropic Messages API 客户端。"""

    model: str = "claude-sonnet-4-20250514"
    api_key: str | None = None
    base_url: str = "https://api.anthropic.com"
    max_tokens: int = 8192
    timeout: float = 120.0
    api_version: str = "2023-06-01"
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_httpx()
        if self.api_key is None:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required for AnthropicClient")

    @property
    def _deepseek(self) -> bool:
        return is_deepseek_anthropic_base(self.base_url)

    def _get_client(self) -> Any:
        if self._client is None:
            headers = {
                "x-api-key": self.api_key or "",
                "anthropic-version": self.api_version,
                "content-type": "application/json",
            }
            if self._deepseek:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers=headers,
                timeout=make_timeout(self.timeout),
            )
        return self._client

    def _build_body(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        system, api_messages = _to_anthropic_messages(
            messages, deepseek=self._deepseek
        )
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
            "stream": stream,
        }
        if system:
            body["system"] = system
        api_tools = _tools_to_anthropic(tools)
        if api_tools:
            body["tools"] = api_tools
        if self._deepseek:
            body.update(deepseek_request_extra())
        return body

    @staticmethod
    async def _raise_api_error(resp: Any) -> None:
        try:
            detail = (await resp.aread()).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            detail = ""
        msg = f"HTTP {resp.status_code}"
        if detail:
            msg = f"{msg}: {detail[:800]}"
        raise RuntimeError(msg)

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AssistantMessage:
        client = self._get_client()
        body = self._build_body(messages, tools, stream=False)

        async def _do() -> Any:
            resp = await client.post("/v1/messages", json=body)
            resp.raise_for_status()
            return resp.json()

        try:
            data = await _wrap_anthropic(_do)
        except Exception as exc:  # noqa: BLE001
            resp = getattr(exc, "response", None)
            if resp is not None and isinstance(getattr(resp, "status_code", None), int):
                await self._raise_api_error(resp)
            raise exc
        return _parse_anthropic_response(data)

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """流式补全，接入与 OpenAI 对称的重试。

        仅在**尚未产出任何 chunk** 时对瞬时/限流/5xx 错误退避重试，
        避免半途重试导致重复输出。
        """
        client = self._get_client()
        body = self._build_body(messages, tools, stream=True)
        emitted = False
        last_exc: BaseException | None = None
        for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
            try:
                async for chunk in self._iter_completion_stream(client, body):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:  # noqa: BLE001
                status = _status_of(exc)
                retryable = _is_retryable_exception(exc) or (
                    status is not None and status in _RETRY_STATUS
                )
                if emitted or not retryable or attempt >= DEFAULT_MAX_ATTEMPTS:
                    last_exc = exc
                    break
                await asyncio.sleep(_backoff_delay(attempt, _retry_after_of(exc)))
        raise RuntimeError(format_model_http_error(last_exc)) from last_exc

    async def _iter_completion_stream(
        self, client: Any, body: dict[str, Any]
    ) -> AsyncIterator[StreamChunk]:
        tool_blocks: dict[int, dict[str, Any]] = {}
        current_tool_idx: int | None = None
        thinking_parts: list[str] = []

        async with client.stream("POST", "/v1/messages", json=body) as resp:
            if resp.status_code >= 400:
                # 5xx/429 等瞬时错误抛 HTTPStatusError 以便上层退避重试；
                # 其余客户端错误透出响应体里的具体原因。
                if resp.status_code in _RETRY_STATUS:
                    await resp.aread()
                    resp.raise_for_status()
                await self._raise_api_error(resp)
            event_type = ""
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                    continue
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue

                if event_type == "error":
                    err = data.get("error") or data
                    msg = err.get("message") if isinstance(err, dict) else str(err)
                    raise RuntimeError(f"Anthropic stream error: {msg}")

                if event_type == "content_block_start":
                    block = data.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        current_tool_idx = data.get("index", 0)
                        tool_blocks[current_tool_idx] = {
                            "id": block.get("id", ""),
                            "name": block.get("name", ""),
                            "input_json": "",
                        }
                elif event_type == "content_block_delta":
                    delta = data.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        text = delta.get("text")
                        if text:
                            yield StreamChunk(delta_content=text)
                    elif delta.get("type") == "thinking_delta":
                        text = delta.get("thinking")
                        if text:
                            thinking_parts.append(text)
                            yield StreamChunk(delta_thinking=text)
                    elif delta.get("type") == "input_json_delta":
                        idx = current_tool_idx if current_tool_idx is not None else 0
                        entry = tool_blocks.setdefault(
                            idx, {"id": "", "name": "", "input_json": ""}
                        )
                        entry["input_json"] += delta.get("partial_json") or ""
                elif event_type == "content_block_stop":
                    idx = data.get("index", current_tool_idx or 0)
                    block = data.get("content_block") or {}
                    if block.get("type") == "tool_use":
                        inp = block.get("input")
                        if isinstance(inp, dict) and inp:
                            tool_blocks[idx] = {
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "input_dict": inp,
                            }
                    elif idx in tool_blocks and tool_blocks[idx].get("input_json"):
                        entry = tool_blocks[idx]
                        try:
                            entry["input_dict"] = safe_parse_tool_input(
                                entry["input_json"],
                                tool_name=str(entry.get("name") or ""),
                            )
                        except ValueError:
                            pass
                elif event_type == "message_start":
                    message = data.get("message") or {}
                    resolved = message.get("model")
                    if resolved:
                        yield StreamChunk(resolved_model=str(resolved))
                    usage = TokenUsage.from_api(message.get("usage"))
                    if usage is not None:
                        yield StreamChunk(usage=usage)
                elif event_type == "message_delta":
                    usage = TokenUsage.from_api(data.get("usage"))
                    if usage is not None:
                        yield StreamChunk(usage=usage)
                    stop = (data.get("delta") or {}).get("stop_reason")
                    if stop:
                        yield StreamChunk(finish_reason=stop)

        if tool_blocks:
            calls: list[ToolCall] = []
            for idx in sorted(tool_blocks.keys()):
                entry = tool_blocks[idx]
                if "input_dict" in entry:
                    args = entry["input_dict"]
                else:
                    raw = entry.get("input_json") or "{}"
                    try:
                        args = safe_parse_tool_input(
                            raw, tool_name=str(entry.get("name") or "")
                        )
                    except ValueError as exc:
                        # 解析失败转为工具错误反馈给模型自纠，而非终止整个 run
                        args = {PARSE_ERROR_KEY: str(exc)}
                calls.append(
                    ToolCall(
                        id=str(entry.get("id") or f"call_{idx}"),
                        name=str(entry.get("name") or ""),
                        arguments=args if isinstance(args, dict) else {},
                    )
                )
            yield StreamChunk(
                delta_tool_calls=calls,
                finish_reason="tool_use",
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
