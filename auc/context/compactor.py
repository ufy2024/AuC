"""R3 上下文自动压缩：两级策略。

一级（廉价）：估算 token 超软阈值时，将「距今较远的 tool 消息」内容折叠为
单行占位（只改 content 不删消息，保证 tool_call 配对完整）。

二级（摘要）：仍超硬阈值时，调模型把早期消息压缩为一条 system 摘要，
原消息从窗口移除；首条 user 消息永不压缩。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from auc.context.pairing import group_boundaries
from auc.context.window import ContextWindow
from auc.messages import ChatMessage
from auc.model.client import ModelClient

if TYPE_CHECKING:
    from auc.loop.base import LoopContext

FOLD_MARKER = "[tool 输出已折叠"
SUMMARY_MARKER = "[已压缩历史]"

SUMMARY_PROMPT = """\
请把以下对话压缩为接续工作所需的最小摘要，必须保留：
1) 用户最初任务目标 2) 已完成事项 3) 关键决策与原因
4) 涉及文件清单（路径） 5) 未决事项与下一步
输出纯文本，分五节。"""

_IMAGE_TOKENS = 1100


@dataclass
class CompactionConfig:
    token_limit: int = 96_000
    soft_ratio: float = 0.6
    hard_ratio: float = 0.8
    keep_recent_steps: int = 6  # 二级压缩保留的近期消息条数（按消息组）
    fold_tool_older_than: int = 4  # 一级折叠：距窗口尾部超过 N 条消息的 tool 输出
    min_fold_bytes: int = 256  # 小于该长度的 tool 输出不折叠


def estimate_message_tokens(msg: ChatMessage) -> int:
    tokens = len(msg.content or "") // 3
    if msg.thinking:
        tokens += len(msg.thinking) // 3
    if msg.tool_calls:
        for tc in msg.tool_calls:
            tokens += len(str(tc.arguments)) // 3 + 8
    if msg.images:
        tokens += _IMAGE_TOKENS * len(msg.images)
    return tokens + 4


def estimate_tokens(messages: list[ChatMessage]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


class SummarizingCompactor:
    def __init__(
        self,
        model: ModelClient | None = None,
        config: CompactionConfig | None = None,
    ) -> None:
        self._model = model
        self.config = config or CompactionConfig()
        # usage 在线校准系数（模型返回真实 token 后调整）
        self._calibration = 1.0

    def estimate_tokens(self, messages: list[ChatMessage]) -> int:
        return int(estimate_tokens(messages) * self._calibration)

    def calibrate(self, estimated: int, actual: int) -> None:
        if estimated > 0 and actual > 0:
            ratio = actual / estimated
            # 平滑更新，避免单次抖动
            self._calibration = 0.7 * self._calibration + 0.3 * ratio

    async def maybe_compact(self, window: ContextWindow, ctx: LoopContext) -> bool:
        cfg = self.config
        messages = window.view()
        before = self.estimate_tokens(messages)
        if before <= cfg.token_limit * cfg.soft_ratio:
            return False

        # R14 pre_compact 生命周期钩子（best-effort）
        hooks = getattr(ctx, "hooks", None)
        if hooks is not None and hooks.has("pre_compact"):
            try:
                await hooks.run_lifecycle(
                    "pre_compact",
                    {
                        "event": "pre_compact",
                        "run_id": ctx.run_id,
                        "agent_id": ctx.agent_id,
                        "before_tokens": before,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

        # 一级：折叠较旧的 tool 输出
        folded = self._fold_tools(messages)
        after_fold = self.estimate_tokens(messages)
        compacted = folded > 0
        level = 1

        # 二级：仍超硬阈值则摘要化早期消息
        if after_fold > cfg.token_limit * cfg.hard_ratio and self._model is not None:
            summarized = await self._summarize(messages)
            if summarized is not None:
                messages = summarized
                level = 2
                compacted = True

        if not compacted:
            return False

        window.clear()
        for m in messages:
            window.append(m)
        after = self.estimate_tokens(messages)
        ctx.events.emit_typed(
            "context_compacted",
            ctx.run_id,
            ctx.agent_id,
            {
                "level": level,
                "before_tokens": before,
                "after_tokens": after,
                "folded": folded,
                "schema_version": 2,
            },
        )
        return True

    def _fold_tools(self, messages: list[ChatMessage]) -> int:
        cfg = self.config
        folded = 0
        cutoff = len(messages) - cfg.fold_tool_older_than
        for i, msg in enumerate(messages):
            if i >= cutoff:
                break
            if msg.role != "tool":
                continue
            content = msg.content or ""
            if content.startswith(FOLD_MARKER) or len(content) < cfg.min_fold_bytes:
                continue
            msg.content = (
                f"{FOLD_MARKER}: {msg.name or 'tool'}, {len(content)} bytes]"
            )
            folded += 1
        return folded

    async def _summarize(
        self, messages: list[ChatMessage]
    ) -> list[ChatMessage] | None:
        cfg = self.config
        if len(messages) <= cfg.keep_recent_steps + 2:
            return None

        # 首条 user 消息永不压缩
        head_idx = next(
            (i for i, m in enumerate(messages) if m.role == "user"), None
        )
        if head_idx is None:
            return None

        # 压缩段 = 首条 user 之后到「保留近期消息」之前；边界对齐到工具组末尾
        target_end = len(messages) - cfg.keep_recent_steps
        boundaries = group_boundaries(messages)
        end = max(
            (b for b in boundaries if head_idx < b <= target_end),
            default=None,
        )
        if end is None or end <= head_idx + 1:
            return None

        # 近期段不得以孤立 tool 开头（assistant+tool_use 已被摘要掉会触发 API 400）
        while end < len(messages) and messages[end].role == "tool":
            k = end
            while k > head_idx + 1 and messages[k - 1].role == "tool":
                k -= 1
            if (
                k > head_idx + 1
                and messages[k - 1].role == "assistant"
                and messages[k - 1].tool_calls
            ):
                end = k - 1
                break
            end += 1
        if end >= len(messages) or end <= head_idx + 1:
            return None

        to_summarize = messages[head_idx + 1 : end]
        if not to_summarize:
            return None

        transcript_parts: list[str] = []
        for m in to_summarize:
            content = (m.content or "")[:2000]
            transcript_parts.append(f"[{m.role}] {content}")
        transcript = "\n".join(transcript_parts)

        try:
            assert self._model is not None
            reply = await self._model.complete(
                [
                    ChatMessage(role="system", content=SUMMARY_PROMPT),
                    ChatMessage(role="user", content=transcript),
                ],
                None,
            )
        except Exception:  # noqa: BLE001 摘要失败不致命，下步重试
            return None
        summary = (reply.content or "").strip()
        if not summary:
            return None

        return (
            messages[: head_idx + 1]
            + [
                ChatMessage(
                    role="system",
                    content=f"{SUMMARY_MARKER}\n{summary}",
                )
            ]
            + messages[end:]
        )
