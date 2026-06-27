"""R27 Web 审查端点测试。"""

from __future__ import annotations

import json
import tempfile
from unittest.mock import AsyncMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auc.config import ModelConfig  # noqa: E402
from auc.messages import RunResult  # noqa: E402
from auc.web.server import _get_session, create_app, init_web_state  # noqa: E402

_REVIEW_OUTPUT = """评审完成。

```json auc-review
{"findings": [
  {"severity": "high", "location": "a.py:3", "issue": "未校验输入", "suggestion": "加校验"}
]}
```
"""


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_review_endpoint_path_scope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        session = _get_session()
        session.agent.run = AsyncMock(
            return_value=RunResult(
                output=_REVIEW_OUTPUT, messages=[], status="completed", run_id="r"
            )
        )
        client = TestClient(create_app())
        resp = client.post(
            "/api/chat/review", json={"path": "a.py", "passes": "correctness"}
        )
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        types = [e["type"] for e in events]
        assert "review_start" in types
        assert "review_pass" in types
        assert "review_report" in types

        report = next(e for e in events if e["type"] == "review_report")
        assert report["payload"]["findings"][0]["severity"] == "high"
        assert report["payload"]["todos"]
        assert "代码审查报告" in report["payload"]["markdown"]


def test_review_endpoint_requires_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        client = TestClient(create_app())
        resp = client.post("/api/chat/review", json={})
        events = _parse_sse(resp.text)
        assert any(e["type"] == "error" for e in events)
