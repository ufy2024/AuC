"""回归测试：2026-07 P2 批次（子 Run 生命周期 / jobs & metrics 并发锁 / 索引原子写）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from auc.events.bus import EventBus
from auc.run_context import current_loop_context


# --- subagent：超时 + 父取消联动 -----------------------------------------------

class _SleepyChild:
    """模拟一个永远跑不完的子智能体：run 挂起直到被取消。"""

    def __init__(self) -> None:
        self.cancelled_with: str | None = None

    def cancel(self, run_id: str) -> None:
        self.cancelled_with = run_id

    async def run(self, request):  # noqa: ANN001
        # 若被 cancel，尽快优雅返回（模拟 step 边界检测 cancelled）
        for _ in range(100):
            await asyncio.sleep(0.05)
            if self.cancelled_with is not None:
                return SimpleNamespace(status="cancelled", error=None, output="")
        return SimpleNamespace(status="completed", error=None, output="done")


def _parent_ctx(events: EventBus):
    return SimpleNamespace(
        run_id="parent-1",
        agent_id="chat:default",
        events=events,
        parent_run_id=None,
        autonomy_policy=None,
        cancelled=False,
    )


def test_subagent_timeout_terminates_child(tmp_path: Path) -> None:
    from auc.tools.subagent import make_subagent_tool

    child = _SleepyChild()
    tool, _ = make_subagent_tool(
        build_agent=lambda kind: child,
        sandbox=str(tmp_path),
        allowed_kinds=["default"],
        default_kind="default",
        timeout=0.3,
    )
    token = current_loop_context.set(_parent_ctx(EventBus()))
    try:
        res = asyncio.run(tool.invoke({"task": "loop forever", "kind": "default"}))
    finally:
        current_loop_context.reset(token)
    # 子 Run 因超时被要求取消，最终优雅返回 cancelled 回执
    assert child.cancelled_with is not None
    assert not res.is_error or "超时" in res.content


def test_subagent_parent_cancel_stops_child(tmp_path: Path) -> None:
    from auc.tools.subagent import make_subagent_tool

    child = _SleepyChild()
    ctx = _parent_ctx(EventBus())
    tool, _ = make_subagent_tool(
        build_agent=lambda kind: child,
        sandbox=str(tmp_path),
        allowed_kinds=["default"],
        default_kind="default",
        timeout=0,  # 无硬超时，仅靠父取消联动
    )

    async def _run() -> None:
        token = current_loop_context.set(ctx)
        try:
            invoke_task = asyncio.create_task(
                tool.invoke({"task": "x", "kind": "default"})
            )
            await asyncio.sleep(0.15)
            ctx.cancelled = True  # 父 Run 被取消
            await asyncio.wait_for(invoke_task, timeout=5)
        finally:
            current_loop_context.reset(token)

    asyncio.run(_run())
    assert child.cancelled_with is not None


# --- jobs：claim_next 并发锁不重复领取 -----------------------------------------

def test_job_claim_next_single_claim(tmp_path: Path) -> None:
    from auc.jobs import STATUS_RUNNING, JobStore

    store = JobStore(str(tmp_path))
    store.enqueue("do it", sandbox=str(tmp_path))
    first = store.claim_next()
    assert first is not None and first.status == STATUS_RUNNING
    # 同一 queued 作业不会被二次领取
    second = store.claim_next()
    assert second is None


def test_job_save_atomic_no_tmp(tmp_path: Path) -> None:
    from auc.jobs import JobStore

    store = JobStore(str(tmp_path))
    store.enqueue("m", sandbox=str(tmp_path))
    assert not list(store.base.glob("*.tmp"))


# --- EvolutionMetrics：并发写不丢计数（增量合并）-------------------------------

def test_evolution_metrics_merge_no_lost_update(tmp_path: Path) -> None:
    from auc.evolution_loop import EvolutionMetrics

    # 两个实例从同一空基线加载，各自对不同条目 +1，分别 save
    a = EvolutionMetrics(str(tmp_path))
    b = EvolutionMetrics(str(tmp_path))
    a.record_recall("e1")
    b.record_recall("e2")
    a.save()
    b.save()  # 若无合并会覆盖 a 的 e1
    merged = EvolutionMetrics(str(tmp_path))
    assert "e1" in merged.stats
    assert "e2" in merged.stats
    assert merged.stats["e1"].recall_count == 1
    assert merged.stats["e2"].recall_count == 1


def test_evolution_metrics_same_entry_increments_accumulate(tmp_path: Path) -> None:
    from auc.evolution_loop import EvolutionMetrics

    a = EvolutionMetrics(str(tmp_path))
    b = EvolutionMetrics(str(tmp_path))
    a.record_recall("shared")
    b.record_recall("shared")
    a.save()
    b.save()
    merged = EvolutionMetrics(str(tmp_path))
    # 两个会话各 +1，合并后应为 2（而非最后写入者的 1）
    assert merged.stats["shared"].recall_count == 2


# --- 向量索引：原子写不遗留 .tmp -----------------------------------------------

def test_vector_index_save_atomic(tmp_path: Path) -> None:
    from auc.index_vector import VectorIndex

    idx = VectorIndex(str(tmp_path), embed_fn=lambda texts: [[0.1, 0.2] for _ in texts])
    idx.items = [{"name": "foo", "path": "a.py"}]
    idx.vectors = [[0.1, 0.2]]
    idx.save()
    assert idx._path.is_file()
    assert not list(idx._path.parent.glob("*.tmp"))
