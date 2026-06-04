import asyncio
from unittest.mock import AsyncMock, MagicMock

from auc.messages import ChatMessage
from auc.model.anthropic import AnthropicClient


def test_anthropic_parses_tool_use() -> None:
    mock_response = {
        "content": [
            {"type": "text", "text": "I'll echo."},
            {
                "type": "tool_use",
                "id": "tu_1",
                "name": "echo",
                "input": {"x": 2},
            },
        ],
    }

    async def _go():
        client = AnthropicClient(api_key="key")
        mock_http = AsyncMock()
        mock_resp = MagicMock()
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
    assert result.tool_calls[0].arguments == {"x": 2}
