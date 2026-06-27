from __future__ import annotations

import json
from datetime import timedelta, timezone, datetime

import pytest

from auc.routines import Routine, RoutineStore, fire_due_routines


def _t(offset_s: int = 0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset_s)


# ── Routine ──
def test_routine_roundtrip():
    r = Routine(id="rt-1", message="hi", interval_seconds=60)
    r2 = Routine.from_dict(r.to_dict())
    assert r2 == r


def test_routine_due_logic():
    now = _t(100)
    r = Routine(id="rt", message="m", interval_seconds=10, next_run=_t(50).isoformat())
    assert r.is_due(now) is True
    r.enabled = False
    assert r.is_due(now) is False
    r.enabled = True
    r.next_run = _t(200).isoformat()
    assert r.is_due(now) is False
    # 无 next_run 视为立即到点
    r.next_run = None
    assert r.is_due(now) is True
    # interval<=0 永不触发
    r.interval_seconds = 0
    assert r.is_due(now) is False


# ── RoutineStore ──
def test_store_add_validation(tmp_path):
    s = RoutineStore(str(tmp_path))
    with pytest.raises(ValueError):
        s.add("", 60)
    with pytest.raises(ValueError):
        s.add("ok", 0)


def test_store_add_list_remove(tmp_path):
    s = RoutineStore(str(tmp_path))
    rt = s.add("跑测试", 30, role="qa", now=_t(0))
    assert rt.next_run == _t(0).isoformat()
    assert s.get(rt.id) is not None
    assert [r.id for r in s.list()] == [rt.id]
    assert s.remove(rt.id) is True
    assert s.get(rt.id) is None
    assert s.remove("nope") is False


def test_store_enable_disable(tmp_path):
    s = RoutineStore(str(tmp_path))
    rt = s.add("m", 30)
    assert s.set_enabled(rt.id, False).enabled is False
    assert s.set_enabled(rt.id, True).enabled is True
    assert s.set_enabled("nope", True) is None


def test_store_due_and_mark_fired(tmp_path):
    s = RoutineStore(str(tmp_path))
    rt = s.add("m", 10, now=_t(0))
    # t=5 还没到（next_run=0 → 其实立即到点）
    assert s.due(_t(0)) == [rt] or s.due(_t(0))[0].id == rt.id
    fired = s.mark_fired(rt, _t(0))
    assert fired.last_run == _t(0).isoformat()
    assert fired.next_run == _t(10).isoformat()
    # mark_fired 后，t=5 未到点
    assert s.due(_t(5)) == []
    # t=10 到点
    assert [r.id for r in s.due(_t(10))] == [rt.id]


# ── fire_due_routines ──
def test_fire_due_routines_enqueues(tmp_path):
    s = RoutineStore(str(tmp_path))
    s.add("夜间巡检", 3600, role="ops", now=_t(0))

    calls = []

    class _FakeJob:
        def __init__(self, msg):
            self.id = "job-1"
            self.message = msg

    def _enqueue(message, **kw):
        calls.append((message, kw))
        return _FakeJob(message)

    fired = fire_due_routines(s, object(), now=_t(0), enqueue=_enqueue)
    assert len(fired) == 1
    assert calls[0][0] == "夜间巡检"
    assert calls[0][1]["role"] == "ops"
    # 触发后 next_run 推进，再次同一时刻不重复触发
    fired2 = fire_due_routines(s, object(), now=_t(0), enqueue=_enqueue)
    assert fired2 == []


def test_fire_due_routines_handles_enqueue_error(tmp_path):
    s = RoutineStore(str(tmp_path))
    s.add("m", 10, now=_t(0))

    def _boom(message, **kw):
        raise RuntimeError("queue full")

    fired = fire_due_routines(s, object(), now=_t(0), enqueue=_boom)
    assert fired == []


# ── worker 集成 ──
def test_run_worker_fires_routines(tmp_path):
    from auc.jobs import JobStore, run_worker

    js = JobStore(str(tmp_path))
    rs = RoutineStore(str(tmp_path))
    rs.add("周期任务", 3600, sandbox=str(tmp_path), now=_t(0))

    def _runner(job, store):
        job.status = "done"
        store.save(job)
        return job

    n = run_worker(js, once=True, runner=_runner, routines=rs)
    assert n == 1
    assert js.list()[0].message == "周期任务"


# ── CLI ──
def test_cli_routines_add_list_run_due(tmp_path, capsys):
    from auc.cli import main

    code = main(["routines", "add", "巡检", "--every", "60", "--sandbox", str(tmp_path)])
    assert code == 0
    assert "已新增定时任务" in capsys.readouterr().out

    code = main(["routines", "list", "--sandbox", str(tmp_path), "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data and data[0]["message"] == "巡检"
    rid = data[0]["id"]

    code = main(["routines", "disable", rid, "--sandbox", str(tmp_path)])
    assert code == 0
    assert "已停用" in capsys.readouterr().out

    code = main(["routines", "run-due", "--sandbox", str(tmp_path)])
    assert code == 0
    # 已停用 → 不触发
    assert "已触发 0" in capsys.readouterr().out

    code = main(["routines", "enable", rid, "--sandbox", str(tmp_path)])
    assert code == 0
    capsys.readouterr()
    code = main(["routines", "run-due", "--sandbox", str(tmp_path)])
    assert code == 0
    assert "已触发 1" in capsys.readouterr().out

    code = main(["routines", "remove", rid, "--sandbox", str(tmp_path)])
    assert code == 0
