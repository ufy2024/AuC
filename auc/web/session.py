from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auc import DefaultAgent
from auc.config import ModelConfig, load_merged_settings
from auc.messages import ChatMessage, RunRequest
from auc.multimodal import (
    PreparedUserInput,
    build_user_message,
    image_from_payload,
    prepare_user_input,
)
from auc.vision_proxy import model_supports_vision, prepare_images_for_model
from auc.web.conversations import ConversationStore, messages_for_ui
from auc.web.editor_context import merge_message_with_context
from auc.roles import format_role_note, load_role_catalog, set_active_role
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

    def truncate_to_user_turn(self, user_index: int) -> list[dict[str, Any]]:
        """截断历史到第 ``user_index`` 个用户消息之前（不含），用于重试 / 编辑重答。

        随后由 stream 接口重新追加用户消息并运行，从而在同一对话里
        「就地重试」或「改完再答」，无需新开对话或重复提问。
        """
        if self.active_run_id:
            raise RuntimeError("对话生成中，请等待完成或取消后再操作")
        seen = -1
        cut: int | None = None
        for i, msg in enumerate(self.history):
            if msg.role == "user":
                seen += 1
                if seen == user_index:
                    cut = i
                    break
        if cut is None:
            raise ValueError("指定的消息不存在或已变更，请刷新后重试")
        self.history = self.history[:cut]
        self.persist()
        return messages_for_ui(self.history)

    async def prepare_request(
        self,
        message: str,
        images_payload: list[dict[str, Any]] | None = None,
        editor_context: dict[str, Any] | None = None,
        work_mode: str | None = AUTO_MODE,
        autonomy: str | None = None,
        approved_plan: dict[str, Any] | None = None,
        role_id: str | None = None,
        role_locale: str | None = None,
    ) -> tuple[RunRequest, list[str]]:
        if not self.active_conversation_id:
            self.active_conversation_id = self.store.create()
        merged, ctx_notes = merge_message_with_context(message, editor_context)
        merged, mode_id, mode_src = enrich_user_turn(merged, selected=work_mode)
        extra = []
        for item in images_payload or []:
            extra.append(image_from_payload(item))
        prepared = prepare_user_input(merged, self.sandbox, extra_images=extra)
        settings, _ = load_merged_settings(None, Path(self.sandbox))
        text, images, vision_notes = await prepare_images_for_model(
            prepared.text,
            prepared.images,
            self.cfg,
            settings,
        )
        prepared = PreparedUserInput(
            text=text,
            notes=[*prepared.notes, *vision_notes],
            images=images,
        )
        catalog = load_role_catalog(sandbox=self.sandbox, locale=role_locale)
        from auc.roles.routing import format_auto_role_note, is_auto_role, route_role

        if is_auto_role(role_id):
            rid = route_role(message, catalog)
            role_note = format_auto_role_note(rid, catalog=catalog)
        else:
            rid = catalog.resolve(role_id)
            role_note = format_role_note(rid, catalog=catalog)
            if role_id and catalog.try_resolve(role_id):
                set_active_role(self.sandbox, rid)
                catalog.active_role_id = rid
        notes = [
            *ctx_notes,
            format_mode_note(mode_id, mode_src),
            role_note,
            *prepared.notes,
        ]
        user_msg = build_user_message(prepared)
        self.history = [*self.history, user_msg]
        self.pending_run_conversation_id = self.active_conversation_id
        self.persist()
        meta: dict[str, Any] = {
            "editor_context": editor_context or {},
            "work_mode": mode_id,
            "work_mode_source": mode_src,
            "role_id": rid,
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
