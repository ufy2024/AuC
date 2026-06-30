from __future__ import annotations

import asyncio

import pytest

from auc.model.discovery import (
    ModelDiscoveryError,
    _anthropic_models_url,
    discover_models,
    parse_models_payload,
)


def test_parse_openai_style_payload() -> None:
    data = {"object": "list", "data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]}
    assert parse_models_payload(data) == ["gpt-4o", "gpt-4o-mini"]


def test_parse_plain_list_and_dedup() -> None:
    assert parse_models_payload(["a", "b", "a"]) == ["a", "b"]
    assert parse_models_payload({"models": ["x", "x", "y"]}) == ["x", "y"]


def test_parse_name_fallback_and_empty() -> None:
    assert parse_models_payload([{"name": "m1"}, {"model": "m2"}]) == ["m1", "m2"]
    assert parse_models_payload({"foo": "bar"}) == []
    assert parse_models_payload(None) == []


def test_anthropic_models_url() -> None:
    assert _anthropic_models_url("https://api.anthropic.com") == "https://api.anthropic.com/v1/models"
    assert _anthropic_models_url("https://relay.example/v1") == "https://relay.example/v1/models"


def test_discover_models_empty_base_or_key() -> None:
    with pytest.raises(ModelDiscoveryError):
        asyncio.run(discover_models(base_url="", api_key="k"))
    with pytest.raises(ModelDiscoveryError):
        asyncio.run(discover_models(base_url="http://x/api", api_key=""))


def test_discover_models_via_mock_transport() -> None:
    httpx = pytest.importorskip("httpx")

    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-coder"}]})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    import auc.model.discovery as disc

    orig = disc.httpx.AsyncClient
    disc.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        models = asyncio.run(
            discover_models(base_url="http://ailab.hcrdi.com/api", api_key="sk-xyz")
        )
    finally:
        disc.httpx.AsyncClient = orig  # type: ignore[assignment]

    assert models == ["deepseek-chat", "deepseek-coder"]
    assert captured["url"].endswith("/api/models")
    assert captured["auth"] == "Bearer sk-xyz"


def test_discover_models_raises_on_404() -> None:
    httpx = pytest.importorskip("httpx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    import auc.model.discovery as disc

    orig = disc.httpx.AsyncClient
    disc.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(ModelDiscoveryError) as exc:
            asyncio.run(discover_models(base_url="http://relay/api", api_key="k"))
    finally:
        disc.httpx.AsyncClient = orig  # type: ignore[assignment]
    assert "404" in str(exc.value)


def test_discover_models_falls_back_to_alt_endpoint_on_401() -> None:
    """首个端点 401（中转未实现），自动改试 /v1/models 成功。"""
    httpx = pytest.importorskip("httpx")

    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        hits.append(path)
        if path == "/api/models":
            return httpx.Response(401, text="unauthorized")
        if path == "/api/v1/models":
            return httpx.Response(200, json={"data": [{"id": "deepseek-chat"}]})
        return httpx.Response(404, text="nope")

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    import auc.model.discovery as disc

    orig = disc.httpx.AsyncClient
    disc.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        models = asyncio.run(
            discover_models(base_url="http://relay/api", api_key="k")
        )
    finally:
        disc.httpx.AsyncClient = orig  # type: ignore[assignment]
    assert models == ["deepseek-chat"]
    assert "/api/models" in hits and "/api/v1/models" in hits


def test_discover_models_401_message_lists_endpoints() -> None:
    """全部 401 时，错误信息汇总尝试过的端点，便于定位。"""
    httpx = pytest.importorskip("httpx")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    import auc.model.discovery as disc

    orig = disc.httpx.AsyncClient
    disc.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(ModelDiscoveryError) as exc:
            asyncio.run(discover_models(base_url="http://relay/api", api_key="k"))
    finally:
        disc.httpx.AsyncClient = orig  # type: ignore[assignment]
    msg = str(exc.value)
    assert "401" in msg
    assert "/models" in msg
