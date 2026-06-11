"""Mermaid / 图表相关（系统提示、本地修复、API）。"""

import tempfile

import pytest

from auc.chat_agent import DEFAULT_CHAT_SYSTEM
from auc.diagrams import (
    extract_mermaid_codeblock,
    try_local_mermaid_fix,
)
from auc.model.client import AssistantMessage, InMemoryModelClient

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auc.config import ModelConfig
from auc.web.server import create_app, init_web_state


def test_chat_system_mentions_mermaid() -> None:
    assert "Mermaid" in DEFAULT_CHAT_SYSTEM
    assert "mermaid" in DEFAULT_CHAT_SYSTEM
    assert "subgraph" in DEFAULT_CHAT_SYSTEM
    assert "sequenceDiagram" in DEFAULT_CHAT_SYSTEM
    assert "mindmap" in DEFAULT_CHAT_SYSTEM


def test_fenced_block_split_convention() -> None:
    text = "intro\n```mermaid\ngraph TD\nA-->B\n```\noutro"
    parts = text.split("```")
    assert len(parts) == 3
    assert "mermaid" in parts[1]


def test_local_fix_quotes_subgraph_with_chinese() -> None:
    code = "flowchart TD\nsubgraph 第一阶段：基础奠基\nA1[数学基础]\nend"
    fixed = try_local_mermaid_fix(code)
    assert 'subgraph "第一阶段：基础奠基"' in fixed
    assert 'A1["数学基础"]' in fixed


def test_local_fix_quotes_node_with_emoji() -> None:
    code = "flowchart TD\nF[🎯 求职 / 研究]"
    fixed = try_local_mermaid_fix(code)
    assert 'F["🎯 求职 / 研究"]' in fixed


GANTT_SAMPLE = """\
gantt
    title AI + 量化交易：1 年学习路线
    dateFormat  YYYY-MM-DD
    axisFormat  %m月

    section Q1 地基
    加密市场微观结构          :a1, 2025-01-01, 3w
    链上数据基础与工具        :a2, after a1, 3w

    section Q2 策略+ML
    ML入门→XGBoost实战       :b3, after a2, 3w
    时序深度学习 LSTM/TFT     :c1, after b3, 4w
"""


def test_local_fix_gantt_special_chars() -> None:
    fixed = try_local_mermaid_fix(GANTT_SAMPLE)
    assert 'title "AI + 量化交易：1 年学习路线"' in fixed
    assert 'section "Q1 地基"' in fixed
    assert 'section "Q2 策略+ML"' in fixed
    assert 'axisFormat "%m月"' in fixed
    assert '"ML入门→XGBoost实战"' in fixed
    assert '"时序深度学习 LSTM/TFT"' in fixed


def test_extract_mermaid_codeblock() -> None:
    text = '说明\n```mermaid\ngraph TD\nA-->B\n```\n'
    assert extract_mermaid_codeblock(text) == "graph TD\nA-->B"


def test_diagram_fix_api_local() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        client = TestClient(create_app())
        code = "flowchart TD\nsubgraph 第一阶段\nA-->B\nend"
        resp = client.post(
            "/api/chat/diagram-fix",
            json={"code": code, "error": "Lexical error"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "local"
        assert data["changed"] is True
        assert '"第一阶段"' in data["code"]


def test_diagram_fix_api_agent_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        from auc.web import server as web_server

        agent = web_server._state["agent"]
        agent._config.model = InMemoryModelClient(  # noqa: SLF001
            responses=[
                AssistantMessage(
                    content='```mermaid\nflowchart TD\nA["修复后"]\n```',
                    tool_calls=None,
                )
            ]
        )
        client = TestClient(create_app())
        resp = client.post(
            "/api/chat/diagram-fix",
            json={
                "code": "flowchart TD\n@@@invalid@@@",
                "error": "parse error",
                "force_agent": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "agent"
        assert 'A["修复后"]' in data["code"]
