"""R7：CLI 会话恢复（--continue/--resume）解析逻辑。"""

from __future__ import annotations

import argparse
import tempfile

from auc.cli import _resolve_chat_resume
from auc.messages import ChatMessage
from auc.web.conversations import ConversationStore


def _args(**kw) -> argparse.Namespace:
    ns = argparse.Namespace(continue_session=False, resume=None)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def test_resume_disabled_returns_none() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store, conv_id = _resolve_chat_resume(tmp, _args())
        assert store is None
        assert conv_id is None


def test_resume_specific_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        seed = ConversationStore(tmp)
        cid = seed.create()
        seed.save_messages(cid, [ChatMessage(role="user", content="hi")])

        store, conv_id = _resolve_chat_resume(tmp, _args(resume=cid))
        assert store is not None
        assert conv_id == cid
        assert store.load_messages(conv_id)[0].content == "hi"


def test_resume_missing_id_falls_back_to_new() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store, conv_id = _resolve_chat_resume(tmp, _args(resume="does-not-exist"))
        assert store is not None
        assert conv_id is None


def test_continue_picks_active() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        seed = ConversationStore(tmp)
        cid = seed.create()
        seed.save_messages(cid, [ChatMessage(role="user", content="prev")])

        store, conv_id = _resolve_chat_resume(tmp, _args(continue_session=True))
        assert conv_id == cid
