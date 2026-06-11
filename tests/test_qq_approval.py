"""QQ IM 二次授权：回调解析、卡片格式、OneBot 发消息与 Webhook 路由。"""

from __future__ import annotations

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from auc.integration.im_base import make_auc_callback, parse_auc_callback  # noqa: E402
from auc.integration.im_card import format_approval_card  # noqa: E402
from auc.integration.qq import QQApprovalPort, register_qq_callback  # noqa: E402
from auc.ports.approval import ApprovalRequest  # noqa: E402


def test_parse_auc_callback_roundtrip() -> None:
    rid = "req-abc"
    assert parse_auc_callback(make_auc_callback("approve", rid)) == ("approve", rid)
    assert parse_auc_callback(make_auc_callback("deny", rid)) == ("deny", rid)
    assert parse_auc_callback("invalid") is None


def test_format_approval_card_contains_tool() -> None:
    req = ApprovalRequest(
        request_id="1",
        run_id="run-1",
        agent_id="agent",
        tool_name="fetch_url",
        arguments={"url": "https://example.com"},
        diff_text="",
        risk_summary="test",
    )
    card = format_approval_card(req)
    assert "fetch_url" in card
    assert "run-1" in card


def test_register_qq_callback() -> None:
    decision = register_qq_callback(make_auc_callback("approve", "qq-req-1"), decided_by="user-42")
    assert decision is not None
    assert decision.approved is True
    assert decision.decided_by == "user-42"


def test_register_qq_callback_invalid_returns_none() -> None:
    assert register_qq_callback("heartbeat") is None
    assert register_qq_callback("auc:unknown:rid") is None


def test_from_settings() -> None:
    port = QQApprovalPort.from_settings(
        {
            "qq": {
                "backend": "onebot11",
                "onebot_http_url": "http://127.0.0.1:5700",
                "target_group_id": "123456789",
            }
        }
    )
    assert port.backend == "onebot11"
    assert port.onebot_http_url == "http://127.0.0.1:5700"
    assert port.target_group_id == 123456789


def _qq_req(rid: str) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=rid,
        run_id="run-1",
        agent_id="agent",
        tool_name="run_command",
        arguments={"command": "git push"},
        diff_text="",
        risk_summary="dangerous",
    )


def test_onebot_send_group_card_and_wait_decision() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"status": "ok"})

    async def _run() -> None:
        port = QQApprovalPort(onebot_http_url="http://onebot.local", target_group_id=123)
        port._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        port.poll_interval = 0.01
        rid = await port.request_approval(_qq_req("qq-req-2"))
        assert rid == "qq-req-2"

        async def _approve_later() -> None:
            await asyncio.sleep(0.02)
            register_qq_callback(make_auc_callback("approve", "qq-req-2"), decided_by="u-1")

        decision, _ = await asyncio.gather(
            port.wait_decision("qq-req-2", timeout=2.0),
            _approve_later(),
        )
        assert decision.approved is True
        assert decision.decided_by == "u-1"
        await port.aclose()

    asyncio.run(_run())
    assert len(captured) == 1
    assert str(captured[0].url).endswith("/send_group_msg")
    body = json.loads(captured[0].content)
    assert body["group_id"] == 123
    assert "run_command" in body["message"]
    datas = {b["data"] for row in body["buttons"] for b in row}
    assert make_auc_callback("approve", "qq-req-2") in datas
    assert make_auc_callback("deny", "qq-req-2") in datas


def test_onebot_send_private_when_no_group() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"status": "ok"})

    async def _run() -> None:
        port = QQApprovalPort(onebot_http_url="http://onebot.local", target_user_id=777)
        port._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await port.request_approval(_qq_req("qq-req-3"))
        await port.aclose()

    asyncio.run(_run())
    assert str(captured[0].url).endswith("/send_private_msg")
    assert json.loads(captured[0].content)["user_id"] == 777


def test_qq_webhook_route_registers_decision() -> None:
    fastapi = pytest.importorskip("fastapi")
    del fastapi
    from fastapi.testclient import TestClient

    from auc.web.server import create_app

    client = TestClient(create_app())
    # 无关事件被静默忽略
    r = client.post("/api/qq/callback", json={"post_type": "meta_event"})
    assert r.status_code == 200
    assert r.json()["ignored"] is True
    # 合法回调登记决策
    r = client.post(
        "/api/qq/callback",
        json={"data": make_auc_callback("deny", "qq-wh-1"), "user_id": 42},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "approved": False}

    async def _wait() -> None:
        port = QQApprovalPort(onebot_http_url="http://onebot.local", target_group_id=1)
        port.poll_interval = 0.01
        decision = await port.wait_decision("qq-wh-1", timeout=1.0)
        assert decision.approved is False
        assert decision.decided_by == "42"

    asyncio.run(_wait())
