import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from auc.messages import ChatMessage
from auc.model.openai import OpenAICompatibleClient


def test_openai_complete_parses_tool_calls() -> None:
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "echo",
                                "arguments": '{"x": 1}',
                            },
                        }
                    ],
                }
            }
        ]
    }

    async def _go():
        client = OpenAICompatibleClient(api_key="test-key")
        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.is_error = False
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._client = mock_http

        msg = await client.complete([ChatMessage(role="user", content="hi")])
        await client.aclose()
        return msg

    result = asyncio.run(_go())
    assert result.tool_calls is not None
    assert result.tool_calls[0].name == "echo"
    assert result.tool_calls[0].arguments == {"x": 1}


def test_complete_captures_resolved_model() -> None:
    """智能路由：响应体 model 字段作为网关实际选用模型回填。"""
    mock_response = {
        "model": "deepseek-reasoner",
        "choices": [{"message": {"content": "hi", "tool_calls": None}}],
    }

    async def _go():
        client = OpenAICompatibleClient(api_key="test-key", model="auto:quality_first")
        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.is_error = False
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._client = mock_http
        msg = await client.complete([ChatMessage(role="user", content="hi")])
        await client.aclose()
        return msg

    result = asyncio.run(_go())
    assert result.resolved_model == "deepseek-reasoner"


def test_local_route_fallback_when_gateway_has_no_auto() -> None:
    """网关不认识 auto（400 模型无效）→ 本地按策略选真实模型并重试成功。"""
    import auc.model.discovery as disc

    calls = {"n": 0}

    async def _fake_discover(**kwargs):
        return ["text-embedding-3-small", "gpt-4o-mini", "gpt-4o"]

    def _make_resp():
        calls["n"] += 1
        resp = MagicMock()
        if calls["n"] == 1:
            resp.is_error = True
            resp.status_code = 400
            resp.text = json.dumps(
                {"error": {"message": "model `auto:cost_optimized` does not exist"}}
            )
        else:
            resp.is_error = False
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "ok", "tool_calls": None}}],
            }
        return resp

    async def _go():
        client = OpenAICompatibleClient(api_key="k", model="auto:cost_optimized")
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=lambda *a, **k: _make_resp())
        client._client = mock_http
        try:
            return await client.complete([ChatMessage(role="user", content="hi")])
        finally:
            await client.aclose()

    orig = disc.discover_models
    disc.discover_models = _fake_discover  # type: ignore[assignment]
    try:
        result = asyncio.run(_go())
    finally:
        disc.discover_models = orig  # type: ignore[assignment]

    assert calls["n"] == 2  # 首次失败 + 本地路由后重试
    assert result.content == "ok"
    assert result.resolved_model == "gpt-4o-mini"  # cost_optimized → 便宜且达标
    assert result.route_source == "local"


def test_local_route_skipped_for_fixed_model() -> None:
    """非 auto 配置：网关 400 不触发本地路由，原样抛错。"""
    import auc.model.discovery as disc

    discover_calls = {"n": 0}

    async def _fake_discover(**kwargs):
        discover_calls["n"] += 1
        return ["gpt-4o"]

    async def _go():
        client = OpenAICompatibleClient(api_key="k", model="gpt-4o")
        mock_http = AsyncMock()
        resp = MagicMock()
        resp.is_error = True
        resp.status_code = 400
        resp.text = json.dumps({"error": {"message": "bad request"}})
        mock_http.post = AsyncMock(return_value=resp)
        client._client = mock_http
        try:
            await client.complete([ChatMessage(role="user", content="hi")])
        finally:
            await client.aclose()

    orig = disc.discover_models
    disc.discover_models = _fake_discover  # type: ignore[assignment]
    try:
        raised = False
        try:
            asyncio.run(_go())
        except RuntimeError:
            raised = True
    finally:
        disc.discover_models = orig  # type: ignore[assignment]
    assert raised
    assert discover_calls["n"] == 0  # 固定模型不应触发本地路由检索


def test_format_api_error_extracts_message() -> None:
    from auc.model.openai import _format_api_error

    body = json.dumps({"error": {"message": "Model Not Exist", "type": "invalid_request_error"}})
    msg = _format_api_error(400, body)
    assert "400" in msg
    assert "Model Not Exist" in msg

    # 非 JSON 体回退为原文
    msg2 = _format_api_error(400, "plain text error")
    assert "plain text error" in msg2

    # 空体也不崩
    assert "400" in _format_api_error(400, "")


def test_complete_surfaces_400_body() -> None:
    async def _go():
        client = OpenAICompatibleClient(api_key="test-key")
        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.is_error = True
        mock_resp.status_code = 400
        mock_resp.text = json.dumps({"error": {"message": "Model Not Exist"}})
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._client = mock_http
        try:
            await client.complete([ChatMessage(role="user", content="hi")])
        finally:
            await client.aclose()

    try:
        asyncio.run(_go())
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "Model Not Exist" in str(exc)
        assert "400" in str(exc)


def test_complete_retries_on_5xx() -> None:
    """5xx 仍抛 HTTPStatusError 以触发重试（而非吞掉为 RuntimeError）。"""
    import httpx

    calls = {"n": 0}
    ok_response = {"choices": [{"message": {"content": "ok"}}]}

    async def _go():
        client = OpenAICompatibleClient(api_key="test-key")
        mock_http = AsyncMock()

        def _make_resp():
            calls["n"] += 1
            resp = MagicMock()
            if calls["n"] == 1:
                resp.is_error = True
                resp.status_code = 503
                resp.headers = {}
                resp.raise_for_status = MagicMock(
                    side_effect=httpx.HTTPStatusError(
                        "503", request=MagicMock(), response=resp
                    )
                )
            else:
                resp.is_error = False
                resp.raise_for_status = MagicMock()
                resp.json.return_value = ok_response
            return resp

        mock_http.post = AsyncMock(side_effect=lambda *a, **k: _make_resp())
        client._client = mock_http
        msg = await client.complete([ChatMessage(role="user", content="hi")])
        await client.aclose()
        return msg

    result = asyncio.run(_go())
    assert result.content == "ok"
    assert calls["n"] == 2
