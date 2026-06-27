"""视觉代理与模型能力检测。"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from auc.config import ModelConfig
from auc.messages import ImageAttachment
from auc.model.client import AssistantMessage
from auc.vision_proxy import (
    model_supports_vision,
    prepare_images_for_model,
    resolve_vision_config,
)


def test_deepseek_does_not_support_vision() -> None:
    cfg = ModelConfig(
        provider="deepseek",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/anthropic",
        api_key="x",
    )
    assert model_supports_vision(cfg) is False


def test_deepseek_anthropic_base_still_no_vision() -> None:
    cfg = ModelConfig(
        provider="anthropic",
        model="deepseek-chat",
        base_url="https://api.deepseek.com/anthropic",
        api_key="x",
    )
    assert model_supports_vision(cfg) is False


def test_gpt4o_supports_vision() -> None:
    cfg = ModelConfig(provider="openai", model="gpt-4o-mini", api_key="x")
    assert model_supports_vision(cfg) is True


def test_resolve_vision_config_from_settings() -> None:
    main = ModelConfig(provider="deepseek", model="deepseek-chat", api_key="ds")
    settings = {
        "vision": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "sk-test",
        }
    }
    v = resolve_vision_config(settings, main)
    assert v is not None
    assert v.model == "gpt-4o-mini"
    assert v.api_key == "sk-test"


def test_resolve_vision_config_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("AUC_VISION_MODEL", "gpt-4o-mini")
    main = ModelConfig(provider="deepseek", model="deepseek-chat", api_key="ds")
    v = resolve_vision_config({}, main)
    assert v is not None
    assert v.api_key == "sk-env"


def test_prepare_images_passthrough_for_vision_model() -> None:
    cfg = ModelConfig(provider="openai", model="gpt-4o-mini", api_key="x")
    imgs = [ImageAttachment(mime_type="image/png", data_base64="abc")]

    async def _go() -> None:
        text, out_imgs, notes = await prepare_images_for_model("hi", imgs, cfg)
        assert text == "hi"
        assert out_imgs == imgs
        assert notes == []

    asyncio.run(_go())


def test_prepare_images_proxy_for_deepseek(monkeypatch) -> None:
    cfg = ModelConfig(provider="deepseek", model="deepseek-chat", api_key="ds")
    imgs = [ImageAttachment(mime_type="image/png", data_base64="abc")]
    settings = {"vision": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk"}}

    mock_client = MagicMock()
    mock_client.complete = AsyncMock(
        return_value=AssistantMessage(content="图中有一个红色按钮", tool_calls=None)
    )

    async def _go() -> None:
        with patch("auc.vision_proxy.create_model_client", return_value=mock_client):
            with patch("auc.vision_proxy.aclose_model_client", new_callable=AsyncMock):
                text, out_imgs, notes = await prepare_images_for_model(
                    "分析", imgs, cfg, settings
                )
        assert out_imgs == []
        assert "红色按钮" in text
        assert any("转写" in n for n in notes)

    asyncio.run(_go())


def test_prepare_images_warns_without_proxy() -> None:
    cfg = ModelConfig(provider="deepseek", model="deepseek-chat", api_key="ds")
    imgs = [ImageAttachment(mime_type="image/png", data_base64="abc")]

    async def _go() -> None:
        text, out_imgs, notes = await prepare_images_for_model("hi", imgs, cfg, {})
        assert out_imgs == []
        assert any("不支持图片" in n for n in notes)
        assert text == "hi"

    asyncio.run(_go())
