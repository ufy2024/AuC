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
