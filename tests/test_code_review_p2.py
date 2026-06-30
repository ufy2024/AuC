"""代码审查 P2 修复项回归测试（HTTP 重试 / 选型 / 硬链接 / CSP / HMAC 等）。"""

from __future__ import annotations

import asyncio
import os

import pytest

from auc.context.window import ListContextWindow, TruncatePolicy
from auc.messages import ChatMessage, ToolCall
from auc.model.client import TokenUsage
from auc.model.factory import _is_anthropic_style_base
from auc.model.retry import with_retry


# --- HTTP 重试 ---------------------------------------------------------------


def test_with_retry_returns_on_success() -> None:
    async def ok() -> str:
        return "ok"

    assert asyncio.run(with_retry(ok)) == "ok"


def test_with_retry_propagates_non_retryable() -> None:
    calls = {"n": 0}

    async def boom() -> str:
        calls["n"] += 1
        raise ValueError("nope")

    with pytest.raises(ValueError):
        asyncio.run(with_retry(boom))
    assert calls["n"] == 1  # 非可重试错误不重试


def test_format_model_http_error_shortens_httpx_message() -> None:
    httpx = pytest.importorskip("httpx")
    from auc.model.retry import format_model_http_error

    req = httpx.Request("POST", "https://cooper-api.com/v1/chat/completions")
    resp = httpx.Response(503, request=req, text="upstream busy")
    exc = httpx.HTTPStatusError(
        "Server error '503 Service Unavailable' for url 'https://cooper-api.com/v1/chat/completions'",
        request=req,
        response=resp,
    )
    msg = format_model_http_error(exc)
    assert "503" in msg
    assert "服务不可用" in msg
    assert "/v1/chat/completions" in msg
    assert "developer.mozilla.org" not in msg


def test_with_retry_retries_then_raises_status() -> None:
    httpx = pytest.importorskip("httpx")
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        resp = httpx.Response(503, request=httpx.Request("GET", "http://x"))
        raise httpx.HTTPStatusError("503", request=resp.request, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(with_retry(flaky, max_attempts=3))
    assert calls["n"] == 3


# --- TokenUsage --------------------------------------------------------------


def test_token_usage_from_openai_shape() -> None:
    u = TokenUsage.from_api({"prompt_tokens": 10, "completion_tokens": 5})
    assert u is not None
    assert u.prompt_tokens == 10
    assert u.total_tokens == 15


def test_token_usage_from_anthropic_shape() -> None:
    u = TokenUsage.from_api({"input_tokens": 7, "output_tokens": 3})
    assert u is not None
    assert u.prompt_tokens == 7
    assert u.completion_tokens == 3


def test_token_usage_none_on_empty() -> None:
    assert TokenUsage.from_api(None) is None
    assert TokenUsage.from_api({}) is None


# --- DeepSeek / 选型 ---------------------------------------------------------


def test_anthropic_style_base_detection() -> None:
    assert _is_anthropic_style_base("https://api.deepseek.com/anthropic")
    assert _is_anthropic_style_base("https://api.anthropic.com")
    assert not _is_anthropic_style_base("https://api.deepseek.com/v1")
    assert not _is_anthropic_style_base("https://api.openai.com/v1")


def test_factory_routes_deepseek_anthropic_base() -> None:
    from auc.config import ModelConfig
    from auc.model.anthropic import AnthropicClient
    from auc.model.factory import create_model_client

    cfg = ModelConfig(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        base_url="https://api.deepseek.com/anthropic",
    )
    client = create_model_client(cfg)
    assert isinstance(client, AnthropicClient)


def test_factory_routes_deepseek_openai_base() -> None:
    from auc.config import ModelConfig
    from auc.model.openai import OpenAICompatibleClient
    from auc.model.factory import create_model_client

    cfg = ModelConfig(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        base_url="https://api.deepseek.com/v1",
    )
    client = create_model_client(cfg)
    assert isinstance(client, OpenAICompatibleClient)


# --- 硬链接 / 文件大小 -------------------------------------------------------


def test_read_rejects_hardlink(tmp_path) -> None:
    from auc.tools.files import make_file_tools

    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    sandbox = tmp_path / "box"
    sandbox.mkdir()
    link = sandbox / "link.txt"
    try:
        os.link(outside, link)
    except OSError:
        pytest.skip("hardlink not supported on this fs")

    tools = {t.name: (t, p) for t, p in make_file_tools(str(sandbox))}
    read_tool = tools["read_file"][0]
    result = asyncio.run(read_tool.invoke({"path": "link.txt"}))
    assert result.is_error
    assert "hardlink" in result.content or "multi-link" in result.content


def test_read_rejects_oversize(tmp_path) -> None:
    from auc.sandbox import assert_within_size_limit, SandboxViolationError

    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 100)
    with pytest.raises(SandboxViolationError):
        assert_within_size_limit(big, max_bytes=10)


def test_write_rejects_oversize(tmp_path) -> None:
    from auc.tools.files import make_file_tools

    tools = {t.name: (t, p) for t, p in make_file_tools(str(tmp_path))}
    write_tool = tools["write_file"][0]
    huge = "a" * (5_000_001)
    result = asyncio.run(write_tool.invoke({"path": "x.txt", "content": huge}))
    assert result.is_error
    assert "too large" in result.content


# --- 工具 schema 校验 / 错误泛化 --------------------------------------------


def test_tool_rejects_unknown_argument(tmp_path) -> None:
    from auc.tools.files import make_file_tools

    tools = {t.name: (t, p) for t, p in make_file_tools(str(tmp_path))}
    read_tool = tools["read_file"][0]
    result = asyncio.run(read_tool.invoke({"path": "a", "bogus": 1}))
    assert result.is_error
    assert "unexpected argument" in result.content


def test_tool_reports_missing_required(tmp_path) -> None:
    from auc.tools.files import make_file_tools

    tools = {t.name: (t, p) for t, p in make_file_tools(str(tmp_path))}
    write_tool = tools["write_file"][0]
    result = asyncio.run(write_tool.invoke({"path": "a"}))
    assert result.is_error
    assert "missing required argument" in result.content


def test_tool_generalizes_unexpected_error() -> None:
    from auc.tools.base import tool_from_function

    def boom() -> str:
        raise RuntimeError("super secret internal detail")

    tool, _ = tool_from_function(boom, name="boom")
    result = asyncio.run(tool.invoke({}))
    assert result.is_error
    assert "super secret" not in result.content
    assert "internal error" in result.content


# --- QQ HMAC / 锁定 ----------------------------------------------------------


def test_qq_signature_roundtrip() -> None:
    import hashlib
    import hmac

    from auc.integration.qq import verify_qq_signature

    secret = "topsecret"
    body = b'{"hello":"world"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_qq_signature(secret, body, sig)
    assert not verify_qq_signature(secret, body, "deadbeef")
    assert not verify_qq_signature("", body, sig)


def test_qq_callback_first_decision_locked() -> None:
    from auc.integration import qq
    from auc.integration.im_base import make_auc_callback

    rid = "req-lock-1"
    qq._interaction_store.pop(rid, None)
    d1 = qq.register_qq_callback(make_auc_callback("approve", rid))
    d2 = qq.register_qq_callback(make_auc_callback("deny", rid))
    assert d1 is not None and d1.approved
    assert d2 is not None and d2.approved  # 后续被锁定，沿用首条
    qq._interaction_store.pop(rid, None)


# --- 预览安全头 --------------------------------------------------------------


def test_preview_security_headers() -> None:
    from auc.web.preview import preview_security_headers

    headers = preview_security_headers()
    assert "Content-Security-Policy" in headers
    assert "frame-ancestors 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Frame-Options"] == "SAMEORIGIN"
    assert headers["X-Content-Type-Options"] == "nosniff"


# --- 上下文 max_tokens 截断 --------------------------------------------------


def test_window_truncate_by_tokens_preserves_pairs() -> None:
    window = ListContextWindow()
    window.append(ChatMessage(role="system", content="s" * 300))
    for i in range(6):
        window.append(
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[ToolCall(id=f"t{i}", name="x", arguments={"a": "b" * 100})],
            )
        )
        window.append(
            ChatMessage(role="tool", content="r" * 200, tool_call_id=f"t{i}")
        )
    window.truncate(TruncatePolicy(max_tokens=200))
    view = window.view()
    # 不应以孤立 tool 消息开头
    assert not (view and view[0].role == "tool")
    # 每个 tool 必有前置 assistant
    for idx, m in enumerate(view):
        if m.role == "tool":
            assert idx > 0 and view[idx - 1].role == "assistant"
