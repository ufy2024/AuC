from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from auc import DefaultAgent
from auc.config import ModelConfig
from auc.messages import ChatMessage, RunRequest
from auc.multimodal import build_user_message, image_from_payload, prepare_user_input
from auc.web.conversations import ConversationStore, messages_for_ui
from auc.web.editor_context import merge_message_with_context
from auc.work_mode import AUTO_MODE, enrich_user_turn, format_mode_note


@dataclass
class WebSession:
    agent: DefaultAgent
    cfg: ModelConfig
    sandbox: str
    store: ConversationStore
    history: list[ChatMessage] = field(default_factory=list)
    active_conversation_id: str | None = None
    active_run_id: str | None = None
    pending_run_conversation_id: str | None = None

    def clear(self) -> None:
        """新建对话并切换为空会话。"""
        self.persist()
        conv_id = self.store.create()
        self.active_conversation_id = conv_id
        self.history = []
        self.active_run_id = None
        self.pending_run_conversation_id = None

    def switch_conversation(self, conv_id: str) -> list[dict[str, Any]]:
        if self.active_run_id:
            raise RuntimeError("对话生成中，请等待完成或取消后再切换")
        self.persist()
        self.active_conversation_id = conv_id
        self.store.set_active_id(conv_id)
        self.history = self.store.load_messages(conv_id)
        self.active_run_id = None
        self.pending_run_conversation_id = None
        return messages_for_ui(self.history)

    def persist(self) -> None:
        if not self.active_conversation_id:
            return
        self.store.save_messages(
            self.active_conversation_id,
            self.history,
            set_active=True,
        )

    def prepare_request(
        self,
        message: str,
        images_payload: list[dict[str, Any]] | None = None,
        editor_context: dict[str, Any] | None = None,
        work_mode: str | None = AUTO_MODE,
        autonomy: str | None = None,
        approved_plan: dict[str, Any] | None = None,
    ) -> tuple[RunRequest, list[str]]:
        if not self.active_conversation_id:
            self.active_conversation_id = self.store.create()
        merged, ctx_notes = merge_message_with_context(message, editor_context)
        merged, mode_id, mode_src = enrich_user_turn(merged, selected=work_mode)
        extra = []
        for item in images_payload or []:
            extra.append(image_from_payload(item))
        prepared = prepare_user_input(merged, self.sandbox, extra_images=extra)
        notes = [*ctx_notes, format_mode_note(mode_id, mode_src), *prepared.notes]
        user_msg = build_user_message(prepared)
        self.history = [*self.history, user_msg]
        self.pending_run_conversation_id = self.active_conversation_id
        self.persist()
        meta: dict[str, Any] = {
            "editor_context": editor_context or {},
            "work_mode": mode_id,
            "work_mode_source": mode_src,
            "conversation_id": self.active_conversation_id,
        }
        if autonomy:
            meta["autonomy"] = autonomy
        if approved_plan:
            meta["approved_plan"] = approved_plan
        return RunRequest(input=self.history, metadata=meta), notes

    def apply_result(self, conversation_id: str | None = None) -> str | None:
        """将运行结果写入对应对话；仅当仍为当前对话时更新内存 history。"""
        result = self.agent.last_run_result
        conv_id = (
            conversation_id
            or self.pending_run_conversation_id
            or self.active_conversation_id
        )
        self.pending_run_conversation_id = None
        if result is None or not conv_id:
            return conv_id
        messages = list(result.messages)
        self.store.save_messages(
            conv_id,
            messages,
            set_active=conv_id == self.active_conversation_id,
        )
        if conv_id == self.active_conversation_id:
            self.history = messages
        return conv_id

    @staticmethod
    def event_json(ev: Any) -> str:
        return json.dumps(
            {
                "type": ev.type,
                "run_id": ev.run_id,
                "agent_id": ev.agent_id,
                "payload": ev.payload,
                "timestamp": ev.timestamp,
            },
            ensure_ascii=False,
        )
