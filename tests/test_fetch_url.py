"""fetch_url 工具与授权。"""

import asyncio
import tempfile

import pytest

from auc.tools.fetch import make_fetch_tool, validate_fetch_url
from auc.web.approval import WebApprovalPort

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auc.config import ModelConfig  # noqa: E402
from auc.chat_agent import build_chat_agent, ChatAgentOptions  # noqa: E402
from auc.web.server import create_app, init_web_state  # noqa: E402


def test_validate_fetch_url_blocks_localhost() -> None:
    with pytest.raises(ValueError, match="禁止"):
        validate_fetch_url("http://127.0.0.1/test")


def test_validate_fetch_url_allows_https() -> None:
    assert validate_fetch_url("https://example.com/article") == "https://example.com/article"


def test_validated_connect_ip_blocks_private_literal() -> None:
    from auc.tools.fetch import _validated_connect_ip

    for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1"):
        with pytest.raises(ValueError, match="禁止连接"):
            _validated_connect_ip(ip)


def test_validated_connect_ip_fail_closed_on_dns_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """连接期 DNS 解析失败必须拒绝（fail-closed），而非放行。"""
    import auc.tools.fetch as fetch_mod

    def _boom(host: str):
        raise ValueError(f"无法解析主机: {host}")

    monkeypatch.setattr(fetch_mod, "_resolve_host_ips", _boom)
    with pytest.raises(ValueError, match="无法解析主机"):
        fetch_mod._validated_connect_ip("public-but-unresolvable.example")


def test_validated_connect_ip_blocks_rebinding_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解析结果含内网 IP（DNS rebinding）→ 拒绝。"""
    import auc.tools.fetch as fetch_mod

    monkeypatch.setattr(fetch_mod, "_resolve_host_ips", lambda h: ["93.184.216.34", "127.0.0.1"])
    with pytest.raises(ValueError, match="禁止连接"):
        fetch_mod._validated_connect_ip("evil.example")


def test_validated_connect_ip_returns_public(monkeypatch: pytest.MonkeyPatch) -> None:
    import auc.tools.fetch as fetch_mod

    monkeypatch.setattr(fetch_mod, "_resolve_host_ips", lambda h: ["93.184.216.34"])
    assert fetch_mod._validated_connect_ip("example.com") == "93.184.216.34"


def test_guarded_backend_pins_and_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """连接期后端：内网目标在真正连接前即被拒（不触网）。"""
    import asyncio

    import httpx

    import auc.tools.fetch as fetch_mod

    transport = fetch_mod._make_guarded_transport(httpx)
    backend = transport._pool._network_backend

    # 解析到内网 → connect_tcp 在调用真实后端前就抛错
    monkeypatch.setattr(fetch_mod, "_resolve_host_ips", lambda h: ["10.1.2.3"])
    with pytest.raises(ValueError, match="禁止连接"):
        asyncio.run(backend.connect_tcp("intranet.example", 443))

    # unix socket 一律拒绝
    with pytest.raises(ValueError, match="unix socket"):
        asyncio.run(backend.connect_unix_socket("/tmp/x.sock"))


def test_web_approval_port_decide() -> None:
    port = WebApprovalPort()

    async def _run() -> None:
        from auc.ports.approval import ApprovalRequest

        req = ApprovalRequest(
            request_id="r1",
            run_id="run",
            agent_id="chat",
            tool_name="fetch_url",
            arguments={"url": "https://example.com"},
            diff_text="",
            risk_summary="test",
        )
        await port.request_approval(req)

        async def decide_later() -> None:
            await asyncio.sleep(0.05)
            port.decide("r1", approved=True)

        task = asyncio.create_task(decide_later())
        decision = await port.wait_decision("r1", timeout=2.0)
        await task
        assert decision.approved is True

    asyncio.run(_run())


def test_fetch_url_registered_in_chat_agent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        agent = build_chat_agent(
            cfg,
            ChatAgentOptions(sandbox=tmp, evolve=False),
            approval=WebApprovalPort(),
        )
        assert agent._config.tools.get("fetch_url") is not None


def _make_fetch(tmp: str, handler) -> tuple:
    """构造 fetch_url 工具并把 httpx.AsyncClient 替换为 MockTransport。"""
    import httpx

    [(tool, pol)] = make_fetch_tool(tmp)
    real_client = httpx.AsyncClient

    def patched(**kwargs):  # noqa: ANN003, ANN202
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    return tool, pol, patched


def test_fetch_url_html_strips_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<html><body><h1>Title</h1><p>hello world</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    with tempfile.TemporaryDirectory() as tmp:
        tool, _, patched = _make_fetch(tmp, handler)
        monkeypatch.setattr(httpx, "AsyncClient", patched)
        res = asyncio.run(tool.invoke({"url": "https://example.com/a"}))
        assert res.is_error is False
        assert "Status: 200" in res.content
        assert "Title hello world" in res.content
        assert "<h1>" not in res.content


def test_fetch_url_plain_text_and_save_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from pathlib import Path

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content="纯文本内容".encode(),
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    with tempfile.TemporaryDirectory() as tmp:
        tool, _, patched = _make_fetch(tmp, handler)
        monkeypatch.setattr(httpx, "AsyncClient", patched)
        res = asyncio.run(
            tool.invoke({"url": "https://example.com/t.txt", "save_path": "saved/t.txt"})
        )
        assert res.is_error is False
        assert "纯文本内容" in res.content
        assert "已保存到沙盒" in res.content
        saved = Path(tmp) / "saved" / "t.txt"
        assert saved.is_file()
        assert "纯文本内容" in saved.read_text(encoding="utf-8")


def test_fetch_url_http_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"not found")

    with tempfile.TemporaryDirectory() as tmp:
        tool, _, patched = _make_fetch(tmp, handler)
        monkeypatch.setattr(httpx, "AsyncClient", patched)
        res = asyncio.run(tool.invoke({"url": "https://example.com/missing"}))
        assert res.is_error is True
        assert "HTTP 404" in res.content


def test_fetch_url_redirect_to_internal_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, content=b"internal data")

    with tempfile.TemporaryDirectory() as tmp:
        tool, _, patched = _make_fetch(tmp, handler)
        monkeypatch.setattr(httpx, "AsyncClient", patched)
        res = asyncio.run(tool.invoke({"url": "https://example.com/r"}))
        assert res.is_error is True
        assert "127.0.0.1" in res.content


def test_fetch_url_truncates_large_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    big = b"x" * 600_000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=big, headers={"content-type": "text/plain"}
        )

    with tempfile.TemporaryDirectory() as tmp:
        tool, _, patched = _make_fetch(tmp, handler)
        monkeypatch.setattr(httpx, "AsyncClient", patched)
        res = asyncio.run(tool.invoke({"url": "https://example.com/big"}))
        assert res.is_error is False
        assert "(内容已截断)" in res.content
        assert len(res.content) < 600_000


def test_fetch_url_save_path_escape_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data", headers={"content-type": "text/plain"})

    with tempfile.TemporaryDirectory() as tmp:
        tool, _, patched = _make_fetch(tmp, handler)
        monkeypatch.setattr(httpx, "AsyncClient", patched)
        res = asyncio.run(
            tool.invoke({"url": "https://example.com/x", "save_path": "../escape.txt"})
        )
        assert res.is_error is True
        from pathlib import Path

        assert not (Path(tmp).parent / "escape.txt").exists()


def test_chat_approve_api() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        from auc.web import server as web_server

        port: WebApprovalPort = web_server._state["approval"]

        async def _prep() -> None:
            from auc.ports.approval import ApprovalRequest

            await port.request_approval(
                ApprovalRequest(
                    request_id="req-1",
                    run_id="r",
                    agent_id="chat",
                    tool_name="fetch_url",
                    arguments={"url": "https://example.com"},
                    diff_text="",
                    risk_summary="x",
                )
            )

        asyncio.run(_prep())
        client = TestClient(create_app())
        ok = client.post("/api/chat/approve", json={"request_id": "req-1", "approved": True})
        assert ok.status_code == 200
        assert ok.json()["approved"] is True
