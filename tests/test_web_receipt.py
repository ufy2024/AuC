"""R28 Web 回执端点测试。"""

from __future__ import annotations

import tempfile

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auc.config import ModelConfig  # noqa: E402
from auc.receipt import ReceiptStore, RunReceipt  # noqa: E402
from auc.web.server import create_app, init_web_state  # noqa: E402


def test_receipt_endpoint_returns_markdown() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ReceiptStore(tmp).write(
            RunReceipt(run_id="run-1", agent_id="a", status="completed", goal="目标X")
        )
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        client = TestClient(create_app())
        resp = client.get("/api/receipt")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "run-1"
        assert "目标X" in data["markdown"]
        assert data["runs"] == ["run-1"]


def test_receipt_endpoint_404_when_empty() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        client = TestClient(create_app())
        resp = client.get("/api/receipt")
        assert resp.status_code == 404
