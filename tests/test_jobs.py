from __future__ import annotations

import json

import pytest

from auc.jobs import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    Job,
    JobStore,
    build_job_command,
    run_job,
    run_worker,
)


class FakeProc:
    def __init__(self, pid: int = 4242, code: int = 0):
        self.pid = pid
        self._code = code

    def wait(self):
        return self._code


def test_enqueue_and_get(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.enqueue("do thing", role="architect", model="m1")
    assert job.status == STATUS_QUEUED
    assert job.message == "do thing"
    loaded = store.get(job.id)
    assert loaded is not None
    assert loaded.role == "architect"
    assert loaded.sandbox == str(tmp_path.resolve())


def test_enqueue_rejects_empty(tmp_path):
    store = JobStore(str(tmp_path))
    with pytest.raises(ValueError):
        store.enqueue("   ")


def test_list_sorted_desc(tmp_path):
    store = JobStore(str(tmp_path))
    a = store.enqueue("a")
    a.created_at = "2020-01-01T00:00:00+00:00"
    store.save(a)
    b = store.enqueue("b")
    b.created_at = "2021-01-01T00:00:00+00:00"
    store.save(b)
    ids = [j.id for j in store.list()]
    assert ids[0] == b.id


def test_claim_next_oldest_first(tmp_path):
    store = JobStore(str(tmp_path))
    j1 = store.enqueue("first")
    j1.created_at = "2020-01-01T00:00:00+00:00"
    store.save(j1)
    j2 = store.enqueue("second")
    j2.created_at = "2021-01-01T00:00:00+00:00"
    store.save(j2)

    claimed = store.claim_next()
    assert claimed.id == j1.id
    assert claimed.status == STATUS_RUNNING
    assert claimed.started_at is not None
    # 再领取拿到第二个
    assert store.claim_next().id == j2.id
    # 队列空
    assert store.claim_next() is None


def test_build_job_command_includes_flags(tmp_path):
    job = Job(
        id="x",
        message="hello",
        sandbox="/sb",
        repo="/repo",
        role="architect",
        model="m1",
        autonomy="full-auto",
        approval="none",
    )
    cmd = build_job_command(job)
    assert "chat" in cmd
    assert "--sandbox" in cmd and "/sb" in cmd
    assert "--repo" in cmd and "/repo" in cmd
    assert "--role" in cmd and "architect" in cmd
    assert "--autonomy" in cmd and "full-auto" in cmd
    assert cmd[-1] == "hello"


def test_run_job_success(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.enqueue("go")
    job = store.claim_next()

    captured = {}

    def fake_popen(cmd, stdout=None, stderr=None):
        captured["cmd"] = cmd
        return FakeProc(pid=999, code=0)

    done = run_job(job, store, popen=fake_popen)
    assert done.status == STATUS_DONE
    assert done.exit_code == 0
    assert done.pid == 999
    assert store.log_path(job.id).is_file()
    assert captured["cmd"][0:1]  # 命令非空


def test_run_job_failure_exit_code(tmp_path):
    store = JobStore(str(tmp_path))
    store.enqueue("go")
    job = store.claim_next()

    done = run_job(job, store, popen=lambda *a, **k: FakeProc(code=3))
    assert done.status == STATUS_FAILED
    assert done.exit_code == 3
    assert "3" in (done.error or "")


def test_run_job_spawn_error(tmp_path):
    store = JobStore(str(tmp_path))
    store.enqueue("go")
    job = store.claim_next()

    def boom(*a, **k):
        raise OSError("cannot spawn")

    done = run_job(job, store, popen=boom)
    assert done.status == STATUS_FAILED
    assert "cannot spawn" in done.error


def test_run_job_respects_cancellation(tmp_path):
    store = JobStore(str(tmp_path))
    store.enqueue("go")
    job = store.claim_next()

    class CancellingProc:
        pid = 555

        def wait(self_inner):  # noqa: N805 模拟等待期间外部取消
            cur = store.get(job.id)
            cur.status = STATUS_CANCELLED
            cur.finished_at = "now"
            store.save(cur)
            return 0

    done = run_job(job, store, popen=lambda *a, **k: CancellingProc())
    assert done.status == STATUS_CANCELLED


def test_cancel_queued(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.enqueue("go")
    ok, _ = store.cancel(job.id)
    assert ok
    assert store.get(job.id).status == STATUS_CANCELLED


def test_cancel_running_kills_pid(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.enqueue("go")
    job = store.claim_next()
    job.pid = 2_000_000_000  # 不存在的 pid，os.kill 抛错被吞
    store.save(job)
    ok, _ = store.cancel(job.id)
    assert ok
    assert store.get(job.id).status == STATUS_CANCELLED


def test_cancel_terminal_rejected(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.enqueue("go")
    store.cancel(job.id)
    ok, msg = store.cancel(job.id)
    assert not ok
    assert "终态" in msg


def test_cancel_missing(tmp_path):
    store = JobStore(str(tmp_path))
    ok, msg = store.cancel("nope")
    assert not ok


def test_run_worker_once_processes_queue(tmp_path):
    store = JobStore(str(tmp_path))
    store.enqueue("a")
    store.enqueue("b")
    seen = []

    def fake_runner(job, st):
        job.status = STATUS_DONE
        st.save(job)
        seen.append(job.id)
        return job

    n = run_worker(store, once=True, runner=fake_runner)
    assert n == 2
    assert len(seen) == 2
    assert all(j.status == STATUS_DONE for j in store.list())


def test_run_worker_max_jobs(tmp_path):
    store = JobStore(str(tmp_path))
    for i in range(5):
        store.enqueue(f"j{i}")

    def fake_runner(job, st):
        job.status = STATUS_DONE
        st.save(job)
        return job

    n = run_worker(store, runner=fake_runner, max_jobs=2, interval=0)
    assert n == 2


def test_job_roundtrip_json(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.enqueue("hi")
    raw = json.loads((store.base / f"{job.id}.json").read_text())
    again = Job.from_dict(raw)
    assert again.id == job.id
    assert again.message == "hi"
