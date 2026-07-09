from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from auc.messages import ChatMessage, ToolCall
from auc.multimodal import openai_message_content
from auc.model.client import AssistantMessage, StreamChunk, TokenUsage
from auc.model.json_util import PARSE_ERROR_KEY, safe_parse_tool_input
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
from auc.tools.base import ToolSchema

logger = logging.getLogger("auc.model.openai")

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]


def _require_httpx() -> Any:
    if httpx is None:
        from auc.extras import hint_for

        raise ImportError(hint_for("llm", "all"))
    return httpx


# 流式累积/历史中偶发出现空 tool_call name（网关未回传 function.name），
# 直接回送会触发 400；用占位名保证 ≥1 字符且保留 id 以维持工具结果配对。
_FALLBACK_TOOL_NAME = "unknown_tool"


def _message_text(m: ChatMessage) -> str:
    if m.role == "user":
        raw = openai_message_content(m)
        return raw if isinstance(raw, str) else str(raw or "")
    return str(m.content or "")


def _messages_to_api(messages: list[ChatMessage]) -> tuple[list[dict[str, Any]], str | None]:
    """OpenAI Chat Completions 消息体；system 提取到顶层 ``system`` 字段。

    许多 Anthropic 兼容网关（含 inferera 路由的 Claude）拒绝 ``messages`` 内的
    ``role: system``，要求使用顶层 ``system`` 参数。
    """
    system_parts: list[str] = []
    out: list[dict[str, Any]] = []
    seen_dialogue = False
    for m in messages:
        if m.role == "system":
            text = _message_text(m).strip()
            if not text:
                continue
            if not seen_dialogue:
                system_parts.append(text)
            else:
                # 压缩摘要等中途 system：改写为 user 注记，避免 400
                out.append({"role": "user", "content": f"[system]\n{text}"})
            continue
        seen_dialogue = True
        content = openai_message_content(m) if m.role == "user" else m.content
        item: dict[str, Any] = {"role": m.role, "content": content}
        if m.name:
            item["name"] = m.name
        if m.tool_call_id:
            item["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            item["tool_calls"] = [
                {
                    "id": tc.id or f"call_{i}",
                    "type": "function",
                    "function": {
                        # 空 name 会被 Anthropic 兼容网关拒绝
                        # （tool_use.name: String should have at least 1 character）
                        "name": tc.name or _FALLBACK_TOOL_NAME,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for i, tc in enumerate(m.tool_calls)
            ]
        out.append(item)
    system = "\n\n".join(system_parts) if system_parts else None
    return out, system


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


_MODEL_UNAVAILABLE_RE = re.compile(
    r"(model[^\n]{0,40}(not found|not exist|does not exist|doesn't exist|"
    r"unknown|unsupported|invalid|no such|disabled)|"
    r"no such model|unknown model|invalid model|unsupported model|"
    r"模型.{0,8}(不存在|无效|不支持|未找到|不可用)|不支持.{0,8}模型)",
    re.IGNORECASE,
)


def _looks_like_model_unavailable(exc: BaseException) -> bool:
    """错误是否意味着「网关不认识该模型名」（典型：填 auto 但网关无智能路由）。

    仅当响应体/异常文本明确指向模型无效时才判定；普通 400（参数、配额等）不触发本地路由。
    """
    msg = str(exc)
    status = _status_of(exc)
    if status == 404:
        return True
    if status == 422 and _MODEL_UNAVAILABLE_RE.search(msg):
        return True
    if _MODEL_UNAVAILABLE_RE.search(msg):
        return True
    if status == 400 and re.search(
        r"\b(not found|does not exist|unknown model|unsupported model|invalid model)\b",
        msg,
        re.I,
    ):
        return True
    return False


def _gateway_lists_auto(models: list[str]) -> bool:
    """网关模型列表含 ``auto`` 时，说明已支持侧智能路由，AuC 不应再本地顶替。"""
    for mid in models:
        head = str(mid or "").strip().lower().split(":", 1)[0]
        if head == "auto":
            return True
    return False


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
                name=str(fn.get("name", "")) or _FALLBACK_TOOL_NAME,
                arguments=args,
            )
        )
    return calls or None


@dataclass
class OpenAICompatibleClient:
    """OpenAI 及兼容 API 的 Chat Completions 客户端。"""

    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    timeout: float = 120.0
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_httpx()
        from auc.config import normalize_openai_compatible_base_url
        from auc.model.routing import is_auto_model, parse_auto_model

        self.base_url = normalize_openai_compatible_base_url(self.base_url)
        if self.api_key is None:
            self.api_key = os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY required for OpenAICompatibleClient")
        # 智能路由状态：配置为 auto 时，网关若不支持则本地选定真实模型并缓存。
        self._auto = is_auto_model(self.model)
        self._auto_strategy = parse_auto_model(self.model)[1] if self._auto else ""
        self._routed_model: str | None = None
        self._tried_models: set[str] = set()
        self._discovered_models: list[str] | None = None

    def _effective_model(self) -> str:
        """当前实际发往网关的模型：本地已选则用之，否则用配置（含 auto）。"""
        return self._routed_model or self.model

    def _route_source(self) -> str | None:
        if self._routed_model:
            return "local"
        return "gateway" if self._auto else None

    async def _maybe_local_route(self, exc: BaseException) -> bool:
        """网关不支持 auto（报模型无效）时，本地按策略选一个真实模型；成功返回 True。"""
        if not self._auto:
            return False
        if not _looks_like_model_unavailable(exc):
            return False
        try:
            from auc.model.discovery import discover_models
            from auc.model.local_routing import rank_models

            if self._discovered_models is None:
                self._discovered_models = await discover_models(
                    base_url=self.base_url, api_key=self.api_key, provider="openai"
                )
            models = self._discovered_models
        except Exception:  # noqa: BLE001 检索失败则无法本地路由，维持原错误
            return False
        if _gateway_lists_auto(models):
            logger.info(
                "gateway model list includes 'auto'; skip local routing (strategy=%s)",
                self._auto_strategy,
            )
            return False
        ranked = rank_models(models, self._auto_strategy)
        for chosen in ranked:
            if chosen in self._tried_models:
                continue
            self._tried_models.add(chosen)
            self._routed_model = chosen
            logger.warning(
                "gateway has no 'auto' routing; locally selected %s (strategy=%s, %d candidates)",
                chosen,
                self._auto_strategy,
                len(models),
            )
            return True
        return False

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
        while True:
            try:
                return await self._complete_once(messages, tools)
            except RuntimeError as exc:
                if not await self._maybe_local_route(exc):
                    raise

    async def _complete_once(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
    ) -> AssistantMessage:
        client = self._get_client()
        body = self._build_body(messages, tools, stream=False, model=self._effective_model())

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
            resolved_model=data.get("model") or self._routed_model or None,
            route_source=self._route_source(),
        )

    def _build_body(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None,
        *,
        stream: bool,
        model: str | None = None,
    ) -> dict[str, Any]:
        api_messages, system = _messages_to_api(messages)
        body: dict[str, Any] = {
            "model": model or self.model,
            "messages": api_messages,
            "stream": stream,
        }
        if system:
            body["system"] = system
        api_tools = _tools_to_api(tools)
        if api_tools:
            body["tools"] = api_tools
            body["tool_choice"] = "auto"
        return body

    async def _iter_completion_stream(
        self,
        client: Any,
        body: dict[str, Any],
    ) -> AsyncIterator[StreamChunk]:
        tool_acc: dict[int, dict[str, str]] = {}
        resolved_emitted = False

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
                if not resolved_emitted and data.get("model"):
                    resolved_emitted = True
                    yield StreamChunk(
                        resolved_model=str(data["model"]),
                        route_source=self._route_source(),
                    )
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
                    args = {PARSE_ERROR_KEY: str(exc)}
                calls.append(
                    ToolCall(
                        id=entry.get("id") or f"call_{idx}",
                        name=entry.get("name") or _FALLBACK_TOOL_NAME,
                        arguments=args,
                    )
                )
            yield StreamChunk(delta_tool_calls=calls, finish_reason="tool_calls")

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        client = self._get_client()
        while True:
            body = self._build_body(
                messages, tools, stream=True, model=self._effective_model()
            )
            emitted = False
            last_exc: BaseException | None = None
            succeeded = False
            for attempt in range(1, DEFAULT_MAX_ATTEMPTS + 1):
                try:
                    async for chunk in self._iter_completion_stream(client, body):
                        emitted = True
                        yield chunk
                    succeeded = True
                    break
                except Exception as exc:  # noqa: BLE001
                    status = _status_of(exc)
                    retryable = _is_retryable_exception(exc) or (
                        status is not None and status in _RETRY_STATUS
                    )
                    # 已产出过 chunk 则不重试/不回退，避免重复输出。
                    if emitted or not retryable or attempt >= DEFAULT_MAX_ATTEMPTS:
                        last_exc = exc
                        break
                    await asyncio.sleep(_backoff_delay(attempt, _retry_after_of(exc)))
            if succeeded:
                return
            # 未产出任何 chunk、配置为 auto 且网关不识别该模型 → 本地路由后重开流。
            if (
                not emitted
                and last_exc is not None
                and await self._maybe_local_route(last_exc)
            ):
                continue
            raise RuntimeError(format_model_http_error(last_exc)) from last_exc

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
