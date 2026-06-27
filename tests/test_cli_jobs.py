from __future__ import annotations

import json

from auc.cli import main
from auc.jobs import JobStore


def test_chat_background_enqueues(tmp_path, capsys):
    code = main(["chat", "--background", "--sandbox", str(tmp_path), "build feature"])
    assert code == 0
    out = capsys.readouterr().out
    assert "已入队后台作业" in out
    jobs = JobStore(str(tmp_path)).list()
    assert len(jobs) == 1
    assert jobs[0].message == "build feature"
    assert jobs[0].status == "queued"


def test_chat_background_needs_message(tmp_path, capsys, monkeypatch):
    # 无消息且 stdin 为 tty → 报错退出 2
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    code = main(["chat", "--background", "--sandbox", str(tmp_path)])
    assert code == 2


def test_jobs_list_and_show_and_cancel(tmp_path, capsys):
    store = JobStore(str(tmp_path))
    job = store.enqueue("task one", sandbox=str(tmp_path))

    code = main(["jobs", "list", "--sandbox", str(tmp_path)])
    assert code == 0
    assert job.id in capsys.readouterr().out

    code = main(["jobs", "show", job.id, "--sandbox", str(tmp_path), "--json"])
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["message"] == "task one"

    code = main(["jobs", "cancel", job.id, "--sandbox", str(tmp_path)])
    assert code == 0
    assert store.get(job.id).status == "cancelled"


def test_jobs_show_missing(tmp_path, capsys):
    code = main(["jobs", "show", "nope", "--sandbox", str(tmp_path)])
    assert code == 1


def test_jobs_worker_once(tmp_path, capsys, monkeypatch):
    store = JobStore(str(tmp_path))
    store.enqueue("a", sandbox=str(tmp_path))

    # 用假 popen 让 worker 子进程「成功」，避免真起进程
    class FakeProc:
        pid = 1
        def wait(self):
            return 0

    monkeypatch.setattr("auc.jobs.subprocess.Popen", lambda *a, **k: FakeProc())
    code = main(["jobs", "worker", "--sandbox", str(tmp_path), "--once"])
    assert code == 0
    assert store.list()[0].status == "done"
