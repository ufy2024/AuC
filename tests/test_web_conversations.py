"""Web 对话记录与续聊。"""

import tempfile
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from auc.config import ModelConfig
from auc.messages import ChatMessage, RunResult
from auc.web.conversations import ConversationStore, messages_for_ui, title_from_messages
from auc.web.server import create_app, init_web_state
from auc.web.session import WebSession


def test_title_from_messages() -> None:
    msgs = [
        ChatMessage(
            role="user",
            content="[工作模式：实现模式 · implement · 自动识别]\n规则\n\n帮我改 API",
        )
    ]
    assert title_from_messages(msgs) == "帮我改 API"


def test_conversation_store_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(tmp)
        conv_id = store.create()
        msgs = [
            ChatMessage(role="user", content="你好"),
            ChatMessage(role="assistant", content="你好，有什么可以帮你？"),
        ]
        store.save_messages(conv_id, msgs)
        loaded = store.load_messages(conv_id)
        assert len(loaded) == 2
        assert loaded[1].content.startswith("你好")
        ui = messages_for_ui(loaded)
        assert len(ui) == 2
        assert ui[0]["role"] == "user"


@pytest.fixture
def client() -> TestClient:
    with tempfile.TemporaryDirectory() as tmp:
        cfg = ModelConfig(provider="openai", model="test", api_key="x")
        init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
        yield TestClient(create_app())


def test_list_and_new_conversation(client: TestClient) -> None:
    listed = client.get("/api/chat/conversations")
    assert listed.status_code == 200
    data = listed.json()
    assert "conversations" in data
    assert data.get("active_id")

    created = client.post("/api/chat/conversations")
    assert created.status_code == 200
    body = created.json()
    assert body["ok"] is True
    assert body["conversation_id"]
    assert body["messages"] == []


def test_info_includes_conversation(client: TestClient) -> None:
    info = client.get("/api/info").json()
    assert "conversation" in info
    assert "active_id" in info["conversation"]
    assert "messages" in info["conversation"]


def test_switch_persists_previous_conversation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(tmp)
        conv_a = store.create()
        conv_b = store.create()
        agent = MagicMock()
        agent.last_run_result = None
        session = WebSession(
            agent=agent,
            cfg=ModelConfig(provider="openai", model="test", api_key="x"),
            sandbox=tmp,
            store=store,
            history=[ChatMessage(role="user", content="对话A的问题")],
            active_conversation_id=conv_a,
        )
        session.switch_conversation(conv_b)
        loaded_a = store.load_messages(conv_a)
        assert len(loaded_a) == 1
        assert loaded_a[0].content == "对话A的问题"
        assert session.active_conversation_id == conv_b


def test_apply_result_saves_to_run_conversation_not_active() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(tmp)
        conv_a = store.create()
        conv_b = store.create()
        store.save_messages(conv_b, [ChatMessage(role="user", content="B")])

        result_msgs = [
            ChatMessage(role="user", content="A的问题"),
            ChatMessage(role="assistant", content="A的回答"),
        ]
        agent = MagicMock()
        agent.last_run_result = RunResult(
            output="A的回答",
            messages=result_msgs,
            status="completed",
            run_id="run-1",
        )
        session = WebSession(
            agent=agent,
            cfg=ModelConfig(provider="openai", model="test", api_key="x"),
            sandbox=tmp,
            store=store,
            history=[ChatMessage(role="user", content="B")],
            active_conversation_id=conv_b,
        )
        session.apply_result(conv_a)

        loaded_a = store.load_messages(conv_a)
        loaded_b = store.load_messages(conv_b)
        assert loaded_a[1].content == "A的回答"
        assert loaded_b[0].content == "B"
        assert session.history[0].content == "B"
        assert store.get_active_id() == conv_b


def _session_with_history(tmp: str, history: list[ChatMessage]) -> WebSession:
    store = ConversationStore(tmp)
    conv = store.create()
    agent = MagicMock()
    agent.last_run_result = None
    session = WebSession(
        agent=agent,
        cfg=ModelConfig(provider="openai", model="test", api_key="x"),
        sandbox=tmp,
        store=store,
        history=list(history),
        active_conversation_id=conv,
    )
    return session


def test_truncate_to_user_turn_truncates_and_persists() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = _session_with_history(
            tmp,
            [
                ChatMessage(role="user", content="Q1"),
                ChatMessage(role="assistant", content="A1"),
                ChatMessage(role="user", content="Q2"),
                ChatMessage(role="assistant", content="A2"),
            ],
        )
        ui = session.truncate_to_user_turn(1)
        assert [m.content for m in session.history] == ["Q1", "A1"]
        assert [it["role"] for it in ui] == ["user", "assistant"]
        # 已落盘
        loaded = session.store.load_messages(session.active_conversation_id)
        assert [m.content for m in loaded] == ["Q1", "A1"]


def test_truncate_to_user_turn_zero_clears_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = _session_with_history(
            tmp,
            [
                ChatMessage(role="user", content="Q1"),
                ChatMessage(role="assistant", content="A1"),
            ],
        )
        ui = session.truncate_to_user_turn(0)
        assert session.history == []
        assert ui == []


def test_truncate_to_user_turn_invalid_index_raises() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = _session_with_history(
            tmp, [ChatMessage(role="user", content="Q1")]
        )
        with pytest.raises(ValueError):
            session.truncate_to_user_turn(3)


def test_truncate_to_user_turn_blocked_during_run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        session = _session_with_history(
            tmp, [ChatMessage(role="user", content="Q1")]
        )
        session.active_run_id = "run-x"
        with pytest.raises(RuntimeError):
            session.truncate_to_user_turn(0)


def test_truncate_endpoint_happy_path(client: TestClient) -> None:
    from auc.web.server import _get_session

    session = _get_session()
    conv = session.active_conversation_id
    session.history = [
        ChatMessage(role="user", content="Q1"),
        ChatMessage(role="assistant", content="A1"),
        ChatMessage(role="user", content="Q2"),
        ChatMessage(role="assistant", content="A2"),
    ]
    session.persist()
    res = client.post(
        f"/api/chat/conversations/{conv}/truncate", json={"user_index": 1}
    )
    assert res.status_code == 200
    msgs = res.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "Q1"


def test_truncate_endpoint_rejects_bad_index(client: TestClient) -> None:
    from auc.web.server import _get_session

    conv = _get_session().active_conversation_id
    assert (
        client.post(
            f"/api/chat/conversations/{conv}/truncate", json={"user_index": -1}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/chat/conversations/{conv}/truncate", json={"user_index": "x"}
        ).status_code
        == 400
    )
    # bool 不是合法 index
    assert (
        client.post(
            f"/api/chat/conversations/{conv}/truncate", json={"user_index": True}
        ).status_code
        == 400
    )


def test_truncate_endpoint_conversation_mismatch(client: TestClient) -> None:
    res = client.post(
        "/api/chat/conversations/not-the-active-one/truncate",
        json={"user_index": 0},
    )
    assert res.status_code == 409


def test_save_messages_without_set_active() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = ConversationStore(tmp)
        conv_a = store.create()
        conv_b = store.create()
        store.set_active_id(conv_a)
        store.save_messages(
            conv_b,
            [ChatMessage(role="user", content="后台保存")],
            set_active=False,
        )
        assert store.get_active_id() == conv_a
