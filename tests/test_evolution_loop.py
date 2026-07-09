from __future__ import annotations

import json
import random
from datetime import timedelta

from auc.evolution_loop import (
    EntryStat,
    EvolutionMetrics,
    Retrospector,
    build_retro_entry,
    build_run_text,
    run_evolution_cycle,
)
from auc.messages import ChatMessage, ToolCall


def _msgs(goal="修复 mermaid gantt 语法", final="已完成", cmd="python3 -m pytest"):
    return [
        ChatMessage(role="user", content=goal),
        ChatMessage(
            role="assistant",
            content=None,
            tool_calls=[ToolCall(id="t1", name="run_command", arguments={"command": cmd})],
        ),
        ChatMessage(role="tool", name="run_command", content="ok", tool_call_id="t1"),
        ChatMessage(role="assistant", content=final),
    ]


# ── R20 复盘 ──
def test_build_retro_success():
    entry = build_retro_entry(status="completed", messages=_msgs(), run_id="r1")
    assert entry.outcome == "success"
    assert entry.confidence == 0.7
    assert "python3 -m pytest" in entry.commands
    assert "成功路径" in entry.summary
    assert entry.run_id == "r1"


def test_build_retro_failure_attribution():
    entry = build_retro_entry(
        status="error", messages=_msgs(final=""), run_id="r2", error="ImportError x"
    )
    assert entry.outcome == "failure"
    assert "失败归因" in entry.summary
    assert "ImportError x" in entry.summary


def test_build_retro_cancelled():
    entry = build_retro_entry(status="cancelled", messages=_msgs())
    assert entry.outcome == "cancelled"
    assert entry.confidence == 0.3


def test_build_retro_no_goal_returns_none():
    msgs = [ChatMessage(role="assistant", content="hi")]
    assert build_retro_entry(status="completed", messages=msgs) is None


class FakeMemory:
    def __init__(self):
        self.saved = []
        self._episodes = []

    def save_lesson(self, tags, lesson, *, agent_id=None):
        self.saved.append((tags, lesson, agent_id))
        return "ok"

    def snapshot_episodes(self, agent_id=None):
        return self._episodes


def test_retrospector_records_via_memory():
    mem = FakeMemory()
    retro = Retrospector(sample_rate=1.0)
    entry = retro.retrospect(
        status="completed", messages=_msgs(), run_id="r3", memory=mem, agent_id="chat:default"
    )
    assert entry is not None
    assert len(mem.saved) == 1
    tags, lesson, aid = mem.saved[0]
    assert "outcome:success" in tags
    assert aid == "chat:default"


def test_retrospector_sampling_zero():
    retro = Retrospector(sample_rate=0.0, rng=random.Random(1))
    assert retro.should_run() is False
    assert retro.retrospect(status="completed", messages=_msgs()) is None


# ── R23 度量 ──
def test_metrics_record_and_weight(tmp_path):
    m = EvolutionMetrics(str(tmp_path))
    m.record_recall("ep-1")
    m.record_adoption("ep-1")
    m.record_adoption("ep-1")
    m.record_link("ep-1", success=True)
    assert m.stats["ep-1"].recall_count == 1
    assert m.stats["ep-1"].adopted_count == 2
    assert m.weight("ep-1") > 1.0
    assert m.weight("missing") == 1.0


def test_metrics_persistence(tmp_path):
    m = EvolutionMetrics(str(tmp_path))
    m.record_adoption("ep-9")
    m.save()
    assert m.path.is_file()
    m2 = EvolutionMetrics(str(tmp_path))
    assert m2.stats["ep-9"].adopted_count == 1


def test_metrics_update_from_run(tmp_path):
    m = EvolutionMetrics(str(tmp_path))
    entries = [
        ("ep-1", ["mermaid", "gantt"]),
        ("ep-2", ["kubernetes", "helm"]),
    ]
    run_text = build_run_text(_msgs(goal="修复 mermaid gantt 语法"))
    adopted = m.update_from_run(entries, run_text, success=True)
    assert "ep-1" in adopted
    assert "ep-2" not in adopted
    assert m.stats["ep-1"].success == 1


def test_metrics_recall_decoupled_from_adoption_on_failure(tmp_path):
    """失败 Run：命中经验记召回 + 失败链接，但不计采纳（召回≠采纳）。"""
    m = EvolutionMetrics(str(tmp_path))
    entries = [("ep-1", ["mermaid", "gantt"])]
    run_text = build_run_text(_msgs(goal="修复 mermaid gantt 语法"))
    adopted = m.update_from_run(entries, run_text, success=False)
    assert adopted == []
    s = m.stats["ep-1"]
    assert s.recall_count == 1
    assert s.adopted_count == 0
    assert s.fail == 1 and s.success == 0
    # 失败 Run 的召回/链接也须落盘
    reloaded = EvolutionMetrics(str(tmp_path))
    assert reloaded.stats["ep-1"].recall_count == 1
    assert reloaded.stats["ep-1"].adopted_count == 0


def test_metrics_adoption_rate_below_one_with_mixed_outcomes(tmp_path):
    """混合成败：召回后成功率 = adopted/recall，可低于 1，使晋升阈值有实义。"""
    m = EvolutionMetrics(str(tmp_path))
    entries = [("ep-1", ["mermaid"])]
    run_text = build_run_text(_msgs(goal="修复 mermaid 图"))
    m.update_from_run(entries, run_text, success=True)
    m.update_from_run(entries, run_text, success=False)
    m.update_from_run(entries, run_text, success=False)
    s = m.stats["ep-1"]
    assert s.recall_count == 3
    assert s.adopted_count == 1  # 仅 1 次成功
    assert s.adopted_count / s.recall_count < 0.5


def test_metrics_archive_candidates(tmp_path):
    m = EvolutionMetrics(str(tmp_path))
    for _ in range(3):
        m.record_link("bad", success=False)
    m.record_link("bad", success=True)
    assert "bad" in m.archive_candidates()


def test_metrics_is_stale(tmp_path):
    from datetime import datetime, timezone

    m = EvolutionMetrics(str(tmp_path))
    s = EntryStat(id="old", last_recall=(datetime.now(timezone.utc) - timedelta(days=200)).isoformat())
    m.stats["old"] = s
    assert m.is_stale("old") is True
    assert m.is_stale("missing") is False


# ── 闭环入口 ──
def test_run_evolution_cycle_full(tmp_path):
    mem = FakeMemory()

    class Ep:
        def __init__(self, id, tags, lesson):
            self.id = id
            self.tags = tags
            self.lesson = lesson

    mem._episodes = [Ep("ep-1", ["mermaid", "gantt"], "修 mermaid gantt 的方法")]

    summary = run_evolution_cycle(
        mem,
        sandbox_root=str(tmp_path),
        status="completed",
        messages=_msgs(goal="再次修复 mermaid gantt 语法"),
        run_id="r5",
        agent_id="chat:default",
    )
    # 既有经验被采纳记账
    assert "ep-1" in summary["adopted"]
    # 新复盘已写入
    assert summary["retro"] == "success"
    assert len(mem.saved) == 1
    # 度量已落盘
    metrics = EvolutionMetrics(str(tmp_path))
    assert metrics.stats["ep-1"].adopted_count == 1


def test_cli_evolve_stats_empty(tmp_path, capsys):
    from auc.cli import main

    code = main(["evolve", "stats", "--sandbox", str(tmp_path)])
    assert code == 0
    assert "暂无数据" in capsys.readouterr().out


def test_cli_evolve_stats_json(tmp_path, capsys):
    from auc.cli import main

    m = EvolutionMetrics(str(tmp_path))
    m.record_adoption("ep-1")
    m.save()
    code = main(["evolve", "stats", "--sandbox", str(tmp_path), "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["entries"][0]["id"] == "ep-1"
