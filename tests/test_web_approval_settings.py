"""授权模式解析与 Web 设置 API。"""

from __future__ import annotations

import tempfile

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auc.config import ModelConfig  # noqa: E402
from auc.policy.autonomy import (  # noqa: E402
    AutonomyPolicy,
    resolve_approval_prefs,
)
from auc.tools.base import ToolPolicy  # noqa: E402
from auc.web.approval_settings import save_approval_settings  # noqa: E402
from auc.web.server import create_app, init_web_state  # noqa: E402

L3 = ToolPolicy(name="fetch_url", privilege="L3")


def test_auto_approve_skips_l3() -> None:
    pol = AutonomyPolicy(level="full-auto", auto_approve=True)
    assert pol.skips_all_approval()
    assert not pol.requires_approval(L3)


def test_resolve_prefs_downgrades_auto_approve_on_remote_bind() -> None:
    prefs = resolve_approval_prefs(
        {"approval": {"mode": "auto-approve", "auto_approve": True}},
        bind_host="0.0.0.0",
    )
    assert prefs.mode_id == "ask-on-danger"
    assert prefs.auto_approve is False


@pytest.fixture
def client() -> TestClient:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False, bind_host="127.0.0.1")
        app = create_app()
        yield TestClient(app)


def test_api_approval_settings_roundtrip(client: TestClient) -> None:
    data = client.get("/api/settings/approval").json()
    assert data["mode"] == "ask-on-state"
    assert data["auto_approve_available"] is True
    assert len(data["modes"]) == 4

    put = client.put(
        "/api/settings/approval",
        json={"mode": "ask-every-write", "scope": "project_local"},
    )
    assert put.status_code == 200
    body = put.json()
    assert body["mode"] == "ask-every-write"
    assert body["autonomy"] == "confirm-all"

    again = client.get("/api/settings/approval").json()
    assert again["mode"] == "ask-every-write"


def test_api_auto_approve_requires_local_bind(client: TestClient) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False, bind_host="0.0.0.0")
        app = create_app()
        remote = TestClient(app)
        res = remote.put(
            "/api/settings/approval",
            json={"mode": "auto-approve", "scope": "project_local"},
        )
        assert res.status_code == 400


def test_save_approval_settings_writes_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prefs, path = save_approval_settings(
            tmp, mode_id="ask-on-danger", scope="project_local", bind_host="127.0.0.1"
        )
        assert path.is_file()
        assert prefs.autonomy == "full-auto"
        assert prefs.auto_approve is False
