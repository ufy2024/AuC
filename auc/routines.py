"""定时 Routines（R17 增量）：按周期把预设指令投递为后台作业。

在 R17 `JobStore` 之上加一层「调度」：`Routine` 描述「每隔 N 秒跑一次某指令」，落盘
`.auc/routines/<id>.json`；`auc jobs worker` 主循环每轮先 `fire_due_routines` —— 到点的
routine 入队成 `Job`（沿用其 sandbox/role/model/autonomy/approval 上下文）并更新下次触发时间。

设计：纯逻辑可测（`now`/`enqueue` 可注入），零新增依赖，进程级隔离与取消复用 R17。
不引入 cron 解析器（避免新依赖）：调度以「固定间隔秒」表达，足够覆盖周期任务场景。
"""

from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _new_id() -> str:
    return f"rt-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


@dataclass
class Routine:
    id: str
    message: str
    interval_seconds: int = 0
    enabled: bool = True
    sandbox: str = ""
    repo: str = ""
    role: str | None = None
    model: str | None = None
    autonomy: str = "full-auto"
    approval: str = "none"
    created_at: str = field(default_factory=lambda: _iso(_now()))
    last_run: str | None = None
    next_run: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Routine":
        fields = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in fields})

    def is_due(self, now: datetime) -> bool:
        if not self.enabled or self.interval_seconds <= 0:
            return False
        nxt = _parse(self.next_run)
        return nxt is None or nxt <= now


class RoutineStore:
    """定时任务持久化到 `<sandbox>/.auc/routines/`。"""

    def __init__(self, sandbox_root: str) -> None:
        self._root = Path(sandbox_root).resolve()
        self._base = self._root / ".auc" / "routines"

    @property
    def base(self) -> Path:
        return self._base

    def _path(self, routine_id: str) -> Path:
        return self._base / f"{routine_id}.json"

    def save(self, routine: Routine) -> None:
        self._base.mkdir(parents=True, exist_ok=True)
        self._path(routine.id).write_text(
            json.dumps(routine.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(
        self,
        message: str,
        interval_seconds: int,
        *,
        sandbox: str = "",
        repo: str = "",
        role: str | None = None,
        model: str | None = None,
        autonomy: str = "full-auto",
        approval: str = "none",
        now: datetime | None = None,
    ) -> Routine:
        if not message or not message.strip():
            raise ValueError("routine 指令不能为空")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds 必须为正")
        now = now or _now()
        routine = Routine(
            id=_new_id(),
            message=message,
            interval_seconds=interval_seconds,
            sandbox=sandbox or str(self._root),
            repo=repo,
            role=role,
            model=model,
            autonomy=autonomy,
            approval=approval,
            next_run=_iso(now),
        )
        self.save(routine)
        return routine

    def get(self, routine_id: str) -> Routine | None:
        path = self._path(routine_id)
        if not path.is_file():
            return None
        try:
            return Routine.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def list(self) -> list[Routine]:
        if not self._base.exists():
            return []
        out: list[Routine] = []
        for p in self._base.glob("*.json"):
            try:
                out.append(Routine.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, OSError, TypeError):
                continue
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out

    def remove(self, routine_id: str) -> bool:
        path = self._path(routine_id)
        if not path.is_file():
            return False
        path.unlink()
        return True

    def set_enabled(self, routine_id: str, enabled: bool) -> Routine | None:
        routine = self.get(routine_id)
        if routine is None:
            return None
        routine.enabled = enabled
        self.save(routine)
        return routine

    def due(self, now: datetime | None = None) -> list[Routine]:
        now = now or _now()
        return [r for r in self.list() if r.is_due(now)]

    def mark_fired(self, routine: Routine, now: datetime | None = None) -> Routine:
        now = now or _now()
        routine.last_run = _iso(now)
        from datetime import timedelta

        routine.next_run = _iso(now + timedelta(seconds=routine.interval_seconds))
        self.save(routine)
        return routine


def fire_due_routines(
    routines: RoutineStore,
    jobs: Any,
    *,
    now: datetime | None = None,
    enqueue: Callable[..., Any] | None = None,
) -> list[Any]:
    """把到点的 routine 入队成后台作业，并更新其下次触发时间。返回入队的作业列表。"""
    now = now or _now()
    fired: list[Any] = []
    enqueue_fn = enqueue or jobs.enqueue
    for routine in routines.due(now):
        try:
            job = enqueue_fn(
                routine.message,
                sandbox=routine.sandbox,
                repo=routine.repo,
                role=routine.role,
                model=routine.model,
                autonomy=routine.autonomy,
                approval=routine.approval,
            )
            fired.append(job)
            routines.mark_fired(routine, now)
        except Exception:  # noqa: BLE001 单条 routine 失败不影响其余
            continue
    return fired
