import asyncio
import json
import tempfile

import pytest

fastapi = pytest.importorskip("fastapi")
from starlette.requests import Request  # noqa: E402

from auc import InMemoryModelClient  # noqa: E402
from auc.config import ModelConfig  # noqa: E402
from auc.messages import ToolCall  # noqa: E402
from auc.model import AssistantMessage  # noqa: E402
from auc.web import server as web_server  # noqa: E402
from auc.web.server import create_app, init_web_state  # noqa: E402


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


async def _post_chat_stream(app, payload: dict) -> tuple[int, str]:
    route = next(r for r in app.routes if getattr(r, "path", None) == "/api/chat/stream")
    body = json.dumps(payload).encode()

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    req = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/chat/stream",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
        },
        receive,
    )
    resp = await route.endpoint(req)
    parts: list[str] = []
    async for chunk in resp.body_iterator:
        parts.append(chunk if isinstance(chunk, str) else chunk.decode())
    return resp.status_code, "".join(parts)


@pytest.fixture
def app():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        yield create_app()


def test_chat_stream_empty_message_returns_sse_error(app) -> None:
    status, text = asyncio.run(_post_chat_stream(app, {"message": "", "context": {}}))
    assert status == 200
    events = _parse_sse(text)
    assert any(e.get("type") == "error" for e in events)
    assert any(e.get("type") == "done" for e in events)


def _swap_model(responses: list[AssistantMessage]) -> None:
    session = web_server._state["session"]
    session.agent._config.model = InMemoryModelClient(responses=responses)  # noqa: SLF001


def test_chat_stream_full_flow_with_mock_llm(app) -> None:
    """端到端：用户消息 → 流式 model_delta → run_end → 对话持久化。"""
    _swap_model([AssistantMessage(content="收到任务", tool_calls=None)])
    status, text = asyncio.run(_post_chat_stream(app, {"message": "你好", "context": {}}))
    assert status == 200
    events = _parse_sse(text)
    types = [e.get("type") for e in events]
    assert "run_start" in types
    assert "run_end" in types
    assert "done" in types
    deltas = "".join(
        e["payload"].get("delta") or ""
        for e in events
        if e.get("type") == "model_delta"
    )
    assert deltas == "收到任务"
    session = web_server._state["session"]
    assert session.history[-1].role == "assistant"
    assert "收到任务" in str(session.history[-1].content)
    # 已落盘到对话存储
    saved = session.store.load_messages(session.active_conversation_id)
    assert any(m.role == "assistant" for m in saved)


def test_chat_stream_l3_tool_denied_via_approve_port(app) -> None:
    """端到端授权链：L3 工具挂起 → 拒绝 → 工具报错 → Run 中断（cancelled）。"""
    _swap_model(
        [
            AssistantMessage(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="t1",
                        name="fetch_url",
                        arguments={"url": "https://example.com"},
                    )
                ],
            ),
        ]
    )
    port = web_server._state["approval"]

    async def _deny_when_pending() -> None:
        for _ in range(500):
            pending = [rid for rid in port._pending if rid not in port._decisions]  # noqa: SLF001
            if pending:
                assert port.decide(pending[0], approved=False, reason="测试拒绝")
                return
            await asyncio.sleep(0.01)
        raise AssertionError("approval request never arrived")

    async def _run() -> tuple[int, str]:
        results = await asyncio.gather(
            _post_chat_stream(app, {"message": "抓取网页", "context": {}}),
            _deny_when_pending(),
        )
        return results[0]

    status, text = asyncio.run(_run())
    assert status == 200
    events = _parse_sse(text)
    types = [e.get("type") for e in events]
    assert "approval_required" in types
    assert "approval_denied" in types
    # 拒绝即中断：工具报错 + Run 取消（无任何外部抓取发生）
    tool_end = next(e for e in events if e.get("type") == "tool_end")
    assert tool_end["payload"]["is_error"] is True
    assert "测试拒绝" in tool_end["payload"]["summary"]
    run_end = next(e for e in events if e.get("type") == "run_end")
    assert run_end["payload"]["status"] == "cancelled"
    done = next(e for e in events if e.get("type") == "done")
    assert done["payload"]["status"] == "cancelled"


def test_chat_stream_run_error_not_duplicated_in_sse(app) -> None:
    class _FailModel:
        async def complete_stream(self, messages, tools=None):
            raise RuntimeError("gateway down")
            yield  # pragma: no cover

    session = web_server._state["session"]
    session.agent._config.model = _FailModel()  # noqa: SLF001
    status, text = asyncio.run(_post_chat_stream(app, {"message": "hi", "context": {}}))
    assert status == 200
    events = _parse_sse(text)
    done = next(e for e in events if e.get("type") == "done")
    assert done["payload"]["status"] == "error"
    assert done["payload"]["error"] == "gateway down"
    dup = [
        e
        for e in events
        if e.get("type") == "error" and (e.get("payload") or {}).get("message") == "gateway down"
    ]
    assert not dup


def test_chat_stream_with_image_upload(app) -> None:
    """图片附件上传：base64 payload 进入用户消息并随对话持久化。"""
    import base64

    _swap_model([AssistantMessage(content="收到图片", tool_calls=None)])
    png_1px = base64.b64encode(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
            "53de0000000c4944415408d763f8cfc000000301010018dd8db00000000049"
            "454e44ae426082"
        )
    ).decode()
    status, text = asyncio.run(
        _post_chat_stream(
            app,
            {
                "message": "看这张图",
                "context": {},
                "images": [
                    {"mime_type": "image/png", "data_base64": png_1px, "name": "dot.png"}
                ],
            },
        )
    )
    assert status == 200
    events = _parse_sse(text)
    types = [e.get("type") for e in events]
    assert "run_end" in types
    done = next(e for e in events if e.get("type") == "done")
    assert done["payload"]["status"] == "completed"
    session = web_server._state["session"]
    user_msgs = [m for m in session.history if m.role == "user"]
    assert user_msgs[-1].images
    assert user_msgs[-1].images[0].mime_type == "image/png"


def test_chat_stream_invalid_image_payload_errors(app) -> None:
    _swap_model([AssistantMessage(content="ok", tool_calls=None)])
    status, text = asyncio.run(
        _post_chat_stream(
            app,
            {"message": "图", "context": {}, "images": [{"name": "no-data.png"}]},
        )
    )
    assert status == 200
    events = _parse_sse(text)
    assert any(e.get("type") == "error" for e in events)


def test_chat_approve_endpoint_unknown_request(app) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    r = client.post("/api/chat/approve", json={"request_id": "nope", "approved": True})
    assert r.status_code == 404
    r = client.post("/api/chat/approve", json={"approved": True})
    assert r.status_code == 400


def test_chat_approve_endpoint_grants_pending_request(app) -> None:
    from fastapi.testclient import TestClient

    from auc.ports.approval import ApprovalRequest

    port = web_server._state["approval"]
    req = ApprovalRequest(
        request_id="web-req-1",
        run_id="run-1",
        agent_id="agent",
        tool_name="fetch_url",
        arguments={"url": "https://example.com"},
        diff_text="",
        risk_summary="test",
    )
    asyncio.run(port.request_approval(req))
    client = TestClient(app)
    r = client.post(
        "/api/chat/approve",
        json={"request_id": "web-req-1", "approved": True},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "approved": True}
    decision = asyncio.run(port.wait_decision("web-req-1", timeout=0.5))
    assert decision.approved is True
    assert decision.decided_by == "web"


def test_chat_stream_accepts_context_without_message(app) -> None:
    status, text = asyncio.run(
        _post_chat_stream(
            app,
            {
                "message": "",
                "context": {
                    "auto_attach": True,
                    "active_file": "a.py",
                    "file_content": "x=1",
                },
            },
        )
    )
    assert status == 200
    events = _parse_sse(text)
    types = [e.get("type") for e in events]
    assert "done" in types
    assert "error" not in types or "run_start" in types
