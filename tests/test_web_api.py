import tempfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auc.config import ModelConfig  # noqa: E402
from auc.web.server import create_app, init_web_state  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        app = create_app()
        yield TestClient(app)


def test_info_and_tree(client: TestClient) -> None:
    info = client.get("/api/info")
    assert info.status_code == 200
    data = info.json()
    assert "workspace" in data
    assert data["model"]["model"] == "test"
    assert data["agent"]["id"].startswith("chat:")
    assert "roles" in data
    role_ids = {r["id"] for r in data["roles"]}
    assert "coder" in role_ids
    assert "reviewer" in role_ids
    assert "work_modes" in data
    mode_ids = {m["id"] for m in data["work_modes"]}
    assert "auto" in mode_ids
    assert "implement" in mode_ids
    release = data.get("release") or {}
    assert release.get("current_version") == data["version"]
    assert "update_available" in release
    assert "install_cmd" in release
    tree = client.get("/api/workspace/tree")
    assert tree.status_code == 200
    assert "entries" in tree.json()


def test_api_release_endpoint(client: TestClient) -> None:
    data = client.get("/api/release").json()
    assert data["current_version"]
    assert "update_available" in data
    forced = client.get("/api/release?force=1").json()
    assert forced["current_version"] == data["current_version"]


def test_api_release_upgrade_skips_when_current(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "auc.web.upgrade.release_info",
        lambda **kwargs: {"update_available": False, "current_version": "0.2.10"},
    )
    resp = client.post("/api/release/upgrade")
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped"] is True


def test_index_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "AuC" in r.text
    assert 'id="lang-toggle"' in r.text
    assert "data-i18n" in r.text


def test_i18n_static(client: TestClient) -> None:
    r = client.get("/static/i18n.js")
    assert r.status_code == 200
    body = r.text
    assert "toggleLocale" in body
    assert '"zh"' in body
    assert '"en"' in body


def test_auc_api_routes_not_shadowed(client: TestClient) -> None:
    assert client.get("/api/info").status_code == 200
    assert client.get("/api/projects").status_code == 200


def test_sandbox_api_requires_backend(client: TestClient) -> None:
    r = client.get("/api/stats")
    assert r.status_code == 404
    assert "backend" in r.json()["detail"].lower()


def test_workspace_file_routes(client: TestClient) -> None:
    # 写入
    r = client.put("/api/workspace/file", json={"path": "a/b.txt", "content": "hello"})
    assert r.status_code == 200
    # 读回
    r = client.get("/api/workspace/file", params={"path": "a/b.txt"})
    assert r.status_code == 200
    assert r.json()["content"] == "hello"
    # 参数校验
    assert client.put("/api/workspace/file", json={"content": "x"}).status_code == 400
    assert (
        client.put("/api/workspace/file", json={"path": "a.txt", "content": 123}).status_code
        == 400
    )
    # 沙盒逃逸
    assert (
        client.put(
            "/api/workspace/file", json={"path": "../escape.txt", "content": "x"}
        ).status_code
        == 403
    )
    assert client.get("/api/workspace/file", params={"path": "../etc"}).status_code == 403
    # 不存在
    assert client.get("/api/workspace/file", params={"path": "nope.txt"}).status_code == 404


def test_workspace_document_file_meta(client: TestClient) -> None:
    client.put("/api/workspace/file", json={"path": "docs/report.pdf", "content": "%PDF"})
    meta = client.get("/api/workspace/file", params={"path": "docs/report.pdf"})
    assert meta.status_code == 200
    body = meta.json()
    assert body["kind"] == "document"
    assert body["doc_type"] == "pdf"
    assert body["previewable"] is True
    raw = client.get("/api/workspace/file/raw", params={"path": "docs/report.pdf"})
    assert raw.status_code == 200
    assert raw.content


def test_workspace_mkdir(client: TestClient) -> None:
    r = client.post("/api/workspace/mkdir", json={"path": "manual-dir"})
    assert r.status_code == 200
    assert r.json()["type"] == "dir"
    tree = client.get("/api/workspace/tree")
    names = [e["name"] for e in tree.json()["entries"]]
    assert "manual-dir" in names
    assert client.post("/api/workspace/mkdir", json={"path": "manual-dir"}).status_code == 409
    assert client.post("/api/workspace/mkdir", json={}).status_code == 400
    assert (
        client.post("/api/workspace/mkdir", json={"path": "../escape"}).status_code == 403
    )


def test_workspace_delete_and_rename(client: TestClient) -> None:
    client.put("/api/workspace/file", json={"path": "x.txt", "content": "1"})
    client.post("/api/workspace/mkdir", json={"path": "sub"})
    r = client.post(
        "/api/workspace/rename",
        json={"path": "x.txt", "new_path": "y.txt"},
    )
    assert r.status_code == 200
    assert r.json()["path"] == "y.txt"
    assert client.get("/api/workspace/file", params={"path": "y.txt"}).status_code == 200
    r = client.delete("/api/workspace/path", params={"path": "sub"})
    assert r.status_code == 200
    assert r.json()["type"] == "dir"
    r = client.delete("/api/workspace/path", params={"path": "y.txt"})
    assert r.status_code == 200
    assert client.get("/api/workspace/tree").json()["entries"] == []


def test_workspace_tree_errors(client: TestClient) -> None:
    assert client.get("/api/workspace/tree", params={"path": "../up"}).status_code == 403
    assert client.get("/api/workspace/tree", params={"path": "missing-dir"}).status_code == 404


def test_preview_routes(client: TestClient) -> None:
    client.put("/api/workspace/file", json={"path": "page.html", "content": "<html>hi</html>"})
    r = client.get("/preview/page.html")
    assert r.status_code == 200
    assert "hi" in r.text
    assert client.get("/preview/missing.html").status_code == 404
    assert client.get("/preview/../escape.html").status_code in (403, 404)


def test_proxy_run_not_found(client: TestClient) -> None:
    r = client.get("/proxy/no-such-run/index.html")
    assert r.status_code == 404


def test_websocket_proxy_without_backend(client: TestClient) -> None:
    with client.websocket_connect("/proxy/no-such-run/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "run not found" in msg["message"]


def test_sandbox_websocket_without_backend(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "backend" in msg["message"]


def test_projects_run_validation(client: TestClient) -> None:
    assert client.post("/api/projects/run", json={}).status_code == 400
    assert client.post("/api/projects/run", json={"project_id": "nope"}).status_code == 404
    assert client.post("/api/projects/stop", json={}).status_code == 400
    r = client.post("/api/projects/stop", json={"run_id": "missing"})
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_pending_approvals_listed_and_recoverable(client: TestClient) -> None:
    """并发 L3 授权：pending 列表可查询（前端找回被覆盖的卡片），决策后出列。"""
    import asyncio

    from auc.ports.approval import ApprovalRequest
    from auc.web import server as web_server

    port = web_server._state["approval"]

    async def _setup() -> None:
        for i in (1, 2):
            await port.request_approval(
                ApprovalRequest(
                    request_id=f"req-{i}",
                    run_id="r1",
                    agent_id="a1",
                    tool_name="fetch_url",
                    arguments={"url": f"https://example.com/{i}"},
                    diff_text="",
                    risk_summary=f"L3 请求 {i}",
                )
            )

    asyncio.run(_setup())
    r = client.get("/api/chat/approvals")
    assert r.status_code == 200
    pending = r.json()["pending"]
    assert {p["request_id"] for p in pending} == {"req-1", "req-2"}

    # 批复其一后：等待方消费决策，pending 中只剩另一个
    assert client.post(
        "/api/chat/approve",
        json={"request_id": "req-1", "approved": True},
    ).status_code == 200

    async def _wait() -> bool:
        decision = await port.wait_decision("req-1", timeout=1.0)
        return decision.approved

    assert asyncio.run(_wait()) is True
    pending = client.get("/api/chat/approvals").json()["pending"]
    assert [p["request_id"] for p in pending] == ["req-2"]


def test_websocket_proxy_full_flow_with_echo_backend(client: TestClient) -> None:
    """WebSocket 代理完整流：客户端 ←→ AuC 代理 ←→ 真实 echo 后端。"""
    import asyncio
    import threading

    websockets = pytest.importorskip("websockets")

    from auc.web import server as web_server
    from auc.web.runner import RunInstance, _free_port

    port = _free_port()
    started = threading.Event()
    stop: list = []

    def _serve() -> None:
        async def _main() -> None:
            async def echo(ws):  # noqa: ANN001
                async for msg in ws:
                    await ws.send(f"echo:{msg}" if isinstance(msg, str) else msg)

            async with websockets.serve(echo, "127.0.0.1", port):
                started.set()
                while not stop:
                    await asyncio.sleep(0.05)

        asyncio.run(_main())

    th = threading.Thread(target=_serve, daemon=True)
    th.start()
    assert started.wait(timeout=5.0)

    runner = web_server._state["runner"]
    inst = RunInstance(
        run_id="ws-run-1",
        project_id="echo",
        kind="python",
        port=port,
        status="running",
        url="/proxy/ws-run-1/",
    )
    runner._runs["ws-run-1"] = inst  # noqa: SLF001
    try:
        # 指定 run 的代理
        with client.websocket_connect("/proxy/ws-run-1/ws") as ws:
            ws.send_text("你好")
            assert ws.receive_text() == "echo:你好"
            ws.send_bytes(b"\x01\x02")
            assert ws.receive_bytes() == b"\x01\x02"
        # 沙盒 /ws 走 get_active_backend，同一实例
        with client.websocket_connect("/ws") as ws:
            ws.send_text("ping")
            assert ws.receive_text() == "echo:ping"
    finally:
        stop.append(True)
        runner._runs.pop("ws-run-1", None)  # noqa: SLF001
        th.join(timeout=5.0)


def test_preview_injects_shim_when_backend_running() -> None:
    import asyncio

    from auc.web.preview import inject_preview_shim
    from auc.web.projects import discover_projects
    from auc.web.runner import ProjectRunner

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = Path(tmp) / "backend"
            frontend = Path(tmp) / "frontend"
            backend.mkdir()
            frontend.mkdir()
            (backend / "main.py").write_text(
                "from fastapi import FastAPI\napp = FastAPI()\n",
                encoding="utf-8",
            )
            (frontend / "index.html").write_text(
                "<html><head></head><body><script src='app.js'></script></body></html>",
                encoding="utf-8",
            )
            pytest = __import__("pytest")
            pytest.importorskip("uvicorn")
            runner = ProjectRunner(tmp)
            proj = next(p for p in discover_projects(tmp) if p.id == "backend")
            inst = await runner.start(proj)
            assert inst.status == "running"
            out = inject_preview_shim("<html><head></head><body></body></html>", inst.run_id)
            assert "auc-preview-shim" in out
            assert f"/proxy/{inst.run_id}" in out
            await runner.stop_all()

    asyncio.run(_run())


def test_model_settings_get_and_put(client: TestClient) -> None:
    data = client.get("/api/settings/model").json()
    assert data["provider"] in ("openai", "anthropic", "deepseek")
    assert "model" in data
    assert "api_key_masked" in data
    assert data.get("api_key") == "x"
    assert "base_url" in data
    assert "layers" in data
    assert "active_scope" in data

    updated = client.put(
        "/api/settings/model",
        json={
            "provider": "openai",
            "model": "deepseek-v4-pro",
            "base_url": "http://ailab.example/api",
            "api_key": "sk-test-key-12345",
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["ok"] is True
    assert body["model"] == "deepseek-v4-pro"
    assert body["base_url"] == "http://ailab.example/api"
    assert body["api_key_masked"].startswith("sk-t")

    # 留空 api_key 应保持不变
    kept = client.put(
        "/api/settings/model",
        json={"provider": "openai", "model": "deepseek-v4-flash", "base_url": "http://ailab.example/api"},
    )
    assert kept.status_code == 200
    assert kept.json()["model"] == "deepseek-v4-flash"
    assert kept.json()["api_key_masked"].startswith("sk-t")


def test_model_settings_normalizes_deepseek_base_url(client: TestClient) -> None:
    resp = client.put(
        "/api/settings/model",
        json={
            "provider": "openai",
            "model": "deepseek-chat",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-test-key-12345",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["base_url"] == "https://api.deepseek.com/v1"
