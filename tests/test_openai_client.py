import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

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
