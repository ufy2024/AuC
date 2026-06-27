"""R17 后台作业：把 Run 投递为后台作业，串行 worker 子进程隔离执行。

状态机：`queued → running → done | failed | cancelled`。作业落盘 `.auc/jobs/<id>.json`，
日志落 `.auc/jobs/<id>.log`。`auc chat --background` 入队即返 job_id；独立进程
`auc jobs worker` 串行领取并执行（子进程跑 `auc chat`，进程级隔离，可按 pid 取消）。
完成后尽力关联该沙盒最新回执（R28）。零新增依赖。
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
TERMINAL_STATUSES = frozenset({STATUS_DONE, STATUS_FAILED, STATUS_CANCELLED})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


@dataclass
class Job:
    id: str
    message: str
    status: str = STATUS_QUEUED
    sandbox: str = ""
    repo: str = ""
    role: str | None = None
    model: str | None = None
    autonomy: str = "full-auto"
    approval: str = "none"
    isolation: str = "none"
    image: str = ""
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    run_id: str | None = None
    receipt_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in fields})


class JobStore:
    """作业持久化到 `<sandbox>/.auc/jobs/`。单 worker 串行，无需跨进程锁。"""

    def __init__(self, sandbox_root: str) -> None:
        self._root = Path(sandbox_root).resolve()
        self._base = self._root / ".auc" / "jobs"

    @property
    def base(self) -> Path:
        return self._base

    def _path(self, job_id: str) -> Path:
        return self._base / f"{job_id}.json"

    def log_path(self, job_id: str) -> Path:
        return self._base / f"{job_id}.log"

    def save(self, job: Job) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        self._path(job.id).write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def enqueue(
        self,
        message: str,
        *,
        sandbox: str = "",
        repo: str = "",
        role: str | None = None,
        model: str | None = None,
        autonomy: str = "full-auto",
        approval: str = "none",
        isolation: str = "none",
        image: str = "",
    ) -> Job:
        if not message or not message.strip():
            raise ValueError("作业消息不能为空")
        job = Job(
            id=_new_id(),
            message=message,
            sandbox=sandbox or str(self._root),
            repo=repo,
            role=role,
            model=model,
            autonomy=autonomy,
            approval=approval,
            isolation=isolation,
            image=image,
        )
        self.save(job)
        return job

    def get(self, job_id: str) -> Job | None:
        path = self._path(job_id)
        if not path.is_file():
            return None
        try:
            return Job.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def list(self) -> list[Job]:
        if not self._base.exists():
            return []
        jobs = []
        for p in self._base.glob("*.json"):
            try:
                jobs.append(Job.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError, TypeError):
                continue
        jobs.sort(key=lambda j: j.created_at, reverse=True)
        return jobs

    def claim_next(self) -> Job | None:
        """领取最早的 queued 作业并置 running（单 worker 串行，先到先得）。"""
        queued = [j for j in self.list() if j.status == STATUS_QUEUED]
        if not queued:
            return None
        queued.sort(key=lambda j: j.created_at)
        job = queued[0]
        job.status = STATUS_RUNNING
        job.started_at = _now()
        self.save(job)
        return job

    def cancel(self, job_id: str) -> tuple[bool, str]:
        """取消作业：queued 直接置 cancelled；running 杀进程后置 cancelled。"""
        job = self.get(job_id)
        if job is None:
            return False, "作业不存在"
        if job.status in TERMINAL_STATUSES:
            return False, f"作业已处于终态：{job.status}"
        if job.status == STATUS_RUNNING and job.pid:
            try:
                os.kill(job.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        job.status = STATUS_CANCELLED
        job.finished_at = _now()
        self.save(job)
        return True, "已取消"


def build_job_command(job: Job) -> list[str]:
    """构造后台执行的子进程命令（无头跑 `auc chat`）。"""
    cmd = [sys.executable, "-m", "auc.cli", "chat", "--no-stream"]
    if job.sandbox:
        cmd += ["--sandbox", job.sandbox]
    if job.repo:
        cmd += ["--repo", job.repo]
    if job.approval:
        cmd += ["--approval", job.approval]
    if job.autonomy:
        cmd += ["--autonomy", job.autonomy]
    if job.role:
        cmd += ["--role", job.role]
    if job.model:
        cmd += ["--model", job.model]
    cmd.append(job.message)
    if getattr(job, "isolation", "none") == "docker":
        from auc.isolation import IsolationConfig, wrap_command

        config = IsolationConfig(
            mode="docker", image=job.image or IsolationConfig().image
        )
        wrapped, _note = wrap_command(cmd, job.sandbox, config)
        return wrapped
    return cmd


PopenFn = Callable[..., Any]


def run_job(
    job: Job,
    store: JobStore,
    *,
    popen: PopenFn | None = None,
) -> Job:
    """执行单个 running 作业：子进程跑命令、收集退出码、关联回执。"""
    popen = popen or subprocess.Popen
    log_path = store.log_path(job.id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_job_command(job)
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            log.write(f"$ {' '.join(cmd)}\n\n")
            log.flush()
            proc = popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            job.pid = getattr(proc, "pid", None)
            store.save(job)
            exit_code = proc.wait()
    except Exception as exc:  # noqa: BLE001 子进程启动失败也要落终态
        job.status = STATUS_FAILED
        job.error = str(exc)
        job.finished_at = _now()
        store.save(job)
        return job

    # 取消可能在等待期间发生：尊重已写入的终态
    latest = store.get(job.id)
    if latest is not None and latest.status == STATUS_CANCELLED:
        return latest

    job.exit_code = exit_code
    job.finished_at = _now()
    job.status = STATUS_DONE if exit_code == 0 else STATUS_FAILED
    if exit_code != 0:
        job.error = f"子进程退出码 {exit_code}"
    _attach_receipt(job)
    store.save(job)
    return job


def _attach_receipt(job: Job) -> None:
    """尽力关联该沙盒最新回执（R28）。"""
    try:
        from auc.receipt import ReceiptStore

        rs = ReceiptStore(job.sandbox or ".")
        runs = rs.list_runs()
        if runs:
            job.run_id = runs[0]
            job.receipt_path = str(rs.path_for(runs[0]))
    except Exception:  # noqa: BLE001 关联失败不影响作业终态
        pass


def run_worker(
    store: JobStore,
    *,
    once: bool = False,
    interval: float = 2.0,
    runner: Callable[[Job, JobStore], Job] = run_job,
    on_event: Callable[[str, Job], None] | None = None,
    max_jobs: int | None = None,
    routines: Any = None,
) -> int:
    """串行 worker 主循环：领取→执行→落终态。`once` 跑空一次队列后退出。

    若传入 `routines`（RoutineStore），每轮先触发到点的定时任务入队（R17 增量）。
    """
    processed = 0
    while True:
        if routines is not None:
            try:
                from auc.routines import fire_due_routines

                fire_due_routines(routines, store)
            except Exception:  # noqa: BLE001 调度失败不影响作业执行
                pass
        job = store.claim_next()
        if job is None:
            if once:
                break
            if max_jobs is not None and processed >= max_jobs:
                break
            time.sleep(interval)
            continue
        if on_event:
            on_event("start", job)
        done = runner(job, store)
        processed += 1
        if on_event:
            on_event("end", done)
        if max_jobs is not None and processed >= max_jobs:
            break
    return processed
