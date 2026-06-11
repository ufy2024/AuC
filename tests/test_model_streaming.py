"""OpenAI / Anthropic 流式 SSE 解析路径（MockTransport fixture）。"""

from __future__ import annotations

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from auc.messages import ChatMessage  # noqa: E402
from auc.model.anthropic import AnthropicClient  # noqa: E402
from auc.model.openai import OpenAICompatibleClient  # noqa: E402


def _openai_sse(events: list[dict | str]) -> bytes:
    lines = []
    for ev in events:
        payload = ev if isinstance(ev, str) else json.dumps(ev, ensure_ascii=False)
        lines.append(f"data: {payload}\n\n")
    return "".join(lines).encode()


def _mock_client(content: bytes) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": "text/event-stream"},
        )

    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://mock.local/v1",
    )


def test_openai_stream_text_and_tool_calls() -> None:
    sse = _openai_sse(
        [
            {"choices": [{"delta": {"content": "你好"}}]},
            {"choices": [{"delta": {"content": "，世界"}}]},
            "not-json",
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {"name": "echo", "arguments": '{"ci'},
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": 'ty": "北京"}'}}
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
            "[DONE]",
        ]
    )

    async def _run() -> None:
        client = OpenAICompatibleClient(model="test", api_key="x")
        client._client = _mock_client(sse)
        texts: list[str] = []
        tool_chunks = []
        async for chunk in client.complete_stream(
            [ChatMessage(role="user", content="hi")]
        ):
            if chunk.delta_content:
                texts.append(chunk.delta_content)
            if chunk.delta_tool_calls:
                tool_chunks.append(chunk)
        assert "".join(texts) == "你好，世界"
        assert len(tool_chunks) == 1
        call = tool_chunks[0].delta_tool_calls[0]
        assert call.id == "call_1"
        assert call.name == "echo"
        assert call.arguments == {"city": "北京"}
        await client.aclose()

    asyncio.run(_run())


def _anthropic_sse(events: list[tuple[str, dict]]) -> bytes:
    lines = []
    for name, data in events:
        lines.append(f"event: {name}\n")
        lines.append(f"data: {json.dumps(data, ensure_ascii=False)}\n\n")
    return "".join(lines).encode()


def test_anthropic_stream_text_thinking_and_tool_use() -> None:
    sse = _anthropic_sse(
        [
            ("message_start", {"message": {"id": "msg_1"}}),
            ("content_block_start", {"index": 0, "content_block": {"type": "text"}}),
            (
                "content_block_delta",
                {"index": 0, "delta": {"type": "thinking_delta", "thinking": "想一想"}},
            ),
            (
                "content_block_delta",
                {"index": 0, "delta": {"type": "text_delta", "text": "调用工具"}},
            ),
            ("content_block_stop", {"index": 0}),
            (
                "content_block_start",
                {
                    "index": 1,
                    "content_block": {"type": "tool_use", "id": "tu_1", "name": "echo"},
                },
            ),
            (
                "content_block_delta",
                {"index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"city":'}},
            ),
            (
                "content_block_delta",
                {"index": 1, "delta": {"type": "input_json_delta", "partial_json": '"上海"}'}},
            ),
            ("content_block_stop", {"index": 1}),
            ("message_delta", {"delta": {"stop_reason": "tool_use"}}),
            ("message_stop", {}),
        ]
    )

    async def _run() -> None:
        client = AnthropicClient(model="test", api_key="x")
        client._client = _mock_client(sse)
        texts: list[str] = []
        thinking: list[str] = []
        final = None
        async for chunk in client.complete_stream(
            [ChatMessage(role="user", content="hi")]
        ):
            if chunk.delta_content:
                texts.append(chunk.delta_content)
            if chunk.delta_thinking:
                thinking.append(chunk.delta_thinking)
            if chunk.delta_tool_calls:
                final = chunk
        assert "".join(texts) == "调用工具"
        assert "想一想" in "".join(thinking)
        assert final is not None
        call = final.delta_tool_calls[0]
        assert call.id == "tu_1"
        assert call.name == "echo"
        assert call.arguments == {"city": "上海"}
        await client.aclose()

    asyncio.run(_run())


def test_anthropic_stream_error_event_raises() -> None:
    sse = _anthropic_sse(
        [
            ("message_start", {"message": {"id": "msg_1"}}),
            ("error", {"error": {"message": "overloaded"}}),
        ]
    )

    async def _run() -> None:
        client = AnthropicClient(model="test", api_key="x")
        client._client = _mock_client(sse)
        with pytest.raises(RuntimeError, match="overloaded"):
            async for _ in client.complete_stream(
                [ChatMessage(role="user", content="hi")]
            ):
                pass
        await client.aclose()

    asyncio.run(_run())
