"""Telegram 二次授权：mock httpx 测发卡片与回调轮询。"""

from __future__ import annotations

import asyncio
import json

import pytest

httpx = pytest.importorskip("httpx")

from auc.integration.im_base import make_auc_callback  # noqa: E402
from auc.integration.telegram import TelegramApprovalPort  # noqa: E402
from auc.ports.approval import ApprovalRequest  # noqa: E402


def _req(rid: str = "tg-req-1") -> ApprovalRequest:
    return ApprovalRequest(
        request_id=rid,
        run_id="run-1",
        agent_id="agent",
        tool_name="fetch_url",
        arguments={"url": "https://example.com"},
        diff_text="",
        risk_summary="test",
    )


def _make_port(handler) -> TelegramApprovalPort:
    port = TelegramApprovalPort(bot_token="token", chat_id="42")
    port._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    port.poll_interval = 0.01
    return port


def test_request_approval_sends_card_with_buttons() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    async def _run() -> None:
        port = _make_port(handler)
        rid = await port.request_approval(_req())
        assert rid == "tg-req-1"
        await port.aclose()

    asyncio.run(_run())
    assert len(captured) == 1
    assert "sendMessage" in str(captured[0].url)
    body = json.loads(captured[0].content)
    assert body["chat_id"] == "42"
    assert "fetch_url" in body["text"]
    buttons = body["reply_markup"]["inline_keyboard"][0]
    datas = {b["callback_data"] for b in buttons}
    assert make_auc_callback("approve", "tg-req-1") in datas
    assert make_auc_callback("deny", "tg-req-1") in datas


def test_wait_decision_parses_callback_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "getUpdates" in url:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {
                            "update_id": 7,
                            "callback_query": {
                                "id": "cb-1",
                                "data": make_auc_callback("approve", "tg-req-2"),
                                "from": {"id": 99},
                            },
                        }
                    ],
                },
            )
        return httpx.Response(200, json={"ok": True})

    async def _run() -> None:
        port = _make_port(handler)
        decision = await port.wait_decision("tg-req-2", timeout=2.0)
        assert decision.approved is True
        assert decision.decided_by == "99"
        # 二次查询直接命中缓存
        again = await port.wait_decision("tg-req-2", timeout=0.1)
        assert again.approved is True
        await port.aclose()

    asyncio.run(_run())


def test_wait_decision_deny_and_irrelevant_updates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "getUpdates" in url:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {"update_id": 1, "message": {"text": "无关消息"}},
                        {
                            "update_id": 2,
                            "callback_query": {
                                "id": "cb-x",
                                "data": "not-auc-format",
                                "from": {"id": 1},
                            },
                        },
                        {
                            "update_id": 3,
                            "callback_query": {
                                "id": "cb-2",
                                "data": make_auc_callback("deny", "tg-req-3"),
                                "from": {"id": 7},
                            },
                        },
                    ],
                },
            )
        return httpx.Response(200, json={"ok": True})

    async def _run() -> None:
        port = _make_port(handler)
        decision = await port.wait_decision("tg-req-3", timeout=2.0)
        assert decision.approved is False
        assert decision.reason == "denied"
        await port.aclose()

    asyncio.run(_run())


def test_wait_decision_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": []})

    async def _run() -> None:
        port = _make_port(handler)
        decision = await port.wait_decision("tg-never", timeout=0.05)
        assert decision.approved is False
        assert decision.reason == "timeout"
        await port.aclose()

    asyncio.run(_run())
