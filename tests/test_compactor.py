import asyncio

from auc.context.compactor import (
    FOLD_MARKER,
    SUMMARY_MARKER,
    CompactionConfig,
    SummarizingCompactor,
    estimate_tokens,
)
from auc.context.window import ListContextWindow
from auc.events.bus import EventBus
from auc.loop.base import LoopConfig, LoopContext
from auc.messages import ChatMessage, ToolCall
from auc.model.client import AssistantMessage, InMemoryModelClient
from auc.tools.registry import DefaultToolRegistry


def _ctx(window: ListContextWindow, model) -> LoopContext:
    return LoopContext(
        agent_id="a",
        run_id="r",
        window=window,
        tools=DefaultToolRegistry(),
        model=model,
        events=EventBus(),
        config=LoopConfig(),
    )


def _tool_turn(i: int, payload: str) -> list[ChatMessage]:
    return [
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id=f"c{i}", name="read_file", arguments={"path": "x"})],
        ),
        ChatMessage(role="tool", content=payload, tool_call_id=f"c{i}", name="read_file"),
    ]


def _fill_window(turns: int, payload_chars: int = 3000) -> ListContextWindow:
    window = ListContextWindow()
    window.append(ChatMessage(role="user", content="重构项目并跑通测试"))
    for i in range(turns):
        for m in _tool_turn(i, "x" * payload_chars):
            window.append(m)
    return window


def test_below_threshold_no_compaction() -> None:
    window = _fill_window(2)
    model = InMemoryModelClient()
    compactor = SummarizingCompactor(model, CompactionConfig(token_limit=1_000_000))
    changed = asyncio.run(compactor.maybe_compact(window, _ctx(window, model)))
    assert not changed


def test_level1_folds_old_tool_output_keeps_pairing() -> None:
    window = _fill_window(8)
    model = InMemoryModelClient(
        responses=[AssistantMessage(content="摘要", tool_calls=None)]
    )
    # 软阈值低，硬阈值极高 → 只触发一级
    cfg = CompactionConfig(token_limit=10_000, soft_ratio=0.1, hard_ratio=100.0)
    compactor = SummarizingCompactor(model, cfg)
    before = window.view()
    changed = asyncio.run(compactor.maybe_compact(window, _ctx(window, model)))
    assert changed
    after = window.view()
    # 消息数量不变（只改 content 不删消息），tool_call 配对完整
    assert len(after) == len(before)
    folded = [m for m in after if m.role == "tool" and m.content.startswith(FOLD_MARKER)]
    assert folded
    # 最近的 tool 输出不折叠
    assert not after[-1].content.startswith(FOLD_MARKER)
    for m in after:
        if m.role == "tool":
            assert m.tool_call_id  # 配对 id 保留


def test_level2_summary_keeps_first_user() -> None:
    window = _fill_window(10)
    model = InMemoryModelClient(
        responses=[AssistantMessage(content="目标:重构;已完成:...", tool_calls=None)]
    )
    cfg = CompactionConfig(
        token_limit=100, soft_ratio=0.1, hard_ratio=0.2, keep_recent_steps=4
    )
    compactor = SummarizingCompactor(model, cfg)
    events: list = []
    ctx = _ctx(window, model)
    ctx.events.subscribe(events.append)
    changed = asyncio.run(compactor.maybe_compact(window, ctx))
    assert changed
    after = window.view()
    assert after[0].role == "user"
    assert after[0].content == "重构项目并跑通测试"
    assert any(m.role == "system" and SUMMARY_MARKER in m.content for m in after)
    assert len(after) < 21
    compacted = [e for e in events if e.type == "context_compacted"]
    assert compacted and compacted[0].payload["level"] == 2
    # 摘要边界不切断 assistant(tool_calls)+tool 配对
    for i, m in enumerate(after):
        if m.role == "assistant" and m.tool_calls:
            assert i + 1 < len(after) and after[i + 1].role == "tool"


def test_summary_model_failure_not_fatal() -> None:
    class BoomModel:
        async def complete(self, messages, tools=None):
            raise RuntimeError("boom")

        async def complete_stream(self, messages, tools=None):
            raise RuntimeError("boom")

    window = _fill_window(10)
    cfg = CompactionConfig(token_limit=100, soft_ratio=0.1, hard_ratio=0.2)
    compactor = SummarizingCompactor(BoomModel(), cfg)
    # 一级折叠仍生效，二级失败被吞掉
    changed = asyncio.run(compactor.maybe_compact(window, _ctx(window, None)))
    assert changed
    assert any(m.content.startswith(FOLD_MARKER) for m in window.view() if m.role == "tool")


def test_estimate_and_calibration() -> None:
    msgs = [ChatMessage(role="user", content="x" * 300)]
    assert estimate_tokens(msgs) > 100
    compactor = SummarizingCompactor(None, CompactionConfig())
    est = compactor.estimate_tokens(msgs)
    compactor.calibrate(est, est * 2)  # 实际比估算大 → 系数上调
    assert compactor.estimate_tokens(msgs) > est
