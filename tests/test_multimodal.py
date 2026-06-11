import asyncio
import base64
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from auc.messages import ChatMessage, ImageAttachment
from auc.model.openai import OpenAICompatibleClient
from auc.multimodal import (
    anthropic_user_content,
    openai_message_content,
    prepare_user_input,
    strip_images_for_memory,
)


def test_openai_multimodal_content() -> None:
    msg = ChatMessage(
        role="user",
        content="describe",
        images=[
            ImageAttachment(mime_type="image/png", data_base64="abc123", name="a.png")
        ],
    )
    parts = openai_message_content(msg)
    assert isinstance(parts, list)
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert "abc123" in parts[1]["image_url"]["url"]


def test_anthropic_multimodal_content() -> None:
    msg = ChatMessage(
        role="user",
        content="hi",
        images=[ImageAttachment(mime_type="image/jpeg", data_base64="qqq")],
    )
    blocks = anthropic_user_content(msg)
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"]["media_type"] == "image/jpeg"


def test_prepare_user_input_image() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "shot.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        prepared = prepare_user_input("看看 @shot.png", tmp)
        assert len(prepared.images) == 1
        assert prepared.images[0].mime_type == "image/png"
        assert any("shot" in n for n in prepared.notes)


def test_strip_images_for_memory() -> None:
    msgs = [
        ChatMessage(
            role="user",
            content="x",
            images=[ImageAttachment(mime_type="image/png", data_base64="a")],
        )
    ]
    out = strip_images_for_memory(msgs)
    assert out[0].images is None
    assert "image" in out[0].content


def test_openai_complete_with_image_message() -> None:
    captured: dict = {}

    async def _go() -> None:
        client = OpenAICompatibleClient(api_key="test-key")
        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok", "tool_calls": None}}]
        }

        async def _post(url, json=None, **kwargs):  # noqa: ANN001
            captured["body"] = json
            return mock_resp

        mock_http.post = _post
        client._client = mock_http
        msg = ChatMessage(
            role="user",
            content="what is this",
            images=[
                ImageAttachment(mime_type="image/png", data_base64="Zm9v")
            ],
        )
        await client.complete([msg])
        await client.aclose()

    asyncio.run(_go())
    body = captured["body"]
    content = body["messages"][0]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "image_url"
