"""R18 并行 worktree：基于 git worktree 的多智能体隔离。

多个任务各自在独立 worktree（独立分支、独立工作目录）执行，互不冲突；完成后可
人工或自动合并回主分支。依赖 R8（git）+ R13/R17（每个 worktree 跑一个后台作业）。

设计：`WorktreeManager` 封装 `git worktree add/list/remove` 与合并/冲突检测（git 调用
可注入，纯解析可测）；`run_parallel` 为每个任务建 worktree 并**并发**执行（线程池跑各自
子进程作业），返回逐任务结果，支持可选自动合并与清理。零新增依赖。
"""

from __future__ import annotations

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_NAME_RE = re.compile(r"[^a-zA-Z0-9_.-]+")

GitRunner = Callable[[list[str], str], "GitResult"]


@dataclass
class GitResult:
    code: int
    out: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


@dataclass
class Worktree:
    name: str
    path: str
    branch: str
    base: str = ""


@dataclass
class MergeResult:
    ok: bool
    branch: str
    conflicted_files: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class ParallelTaskResult:
    name: str
    worktree: Worktree | None = None
    status: str = "pending"  # done | failed | error
    exit_code: int | None = None
    changed_files: list[str] = field(default_factory=list)
    merge: MergeResult | None = None
    error: str | None = None
    cleaned: bool = False


def sanitize_name(name: str) -> str:
    s = _NAME_RE.sub("-", name).strip("-")
    return s or "task"


def _default_git(args: list[str], cwd: str) -> GitResult:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return GitResult(proc.returncode, (proc.stdout or "") + (proc.stderr or ""))
    except subprocess.TimeoutExpired:
        return GitResult(124, "(git timeout)")
    except Exception as exc:  # noqa: BLE001
        return GitResult(1, str(exc))


class WorktreeManager:
    """管理 `<repo>/.auc/worktrees/<name>`（分支 `auc/<name>`）。"""

    def __init__(self, repo_root: str, *, git: GitRunner | None = None) -> None:
        self._root = Path(repo_root).resolve()
        self._git_fn = git or _default_git

    @property
    def base_dir(self) -> Path:
        return self._root / ".auc" / "worktrees"

    def _git(self, args: list[str], cwd: str | None = None) -> GitResult:
        return self._git_fn(args, cwd or str(self._root))

    def branch_for(self, name: str) -> str:
        return f"auc/{sanitize_name(name)}"

    def path_for(self, name: str) -> Path:
        return self.base_dir / sanitize_name(name)

    def create(self, name: str, *, base: str = "HEAD") -> Worktree:
        safe = sanitize_name(name)
        branch = self.branch_for(safe)
        path = self.path_for(safe)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        res = self._git(["worktree", "add", "-b", branch, str(path), base])
        if not res.ok:
            # 分支可能已存在：退一步用现有分支
            res2 = self._git(["worktree", "add", str(path), branch])
            if not res2.ok:
                raise RuntimeError(f"创建 worktree 失败：{res.out.strip()}")
        return Worktree(name=safe, path=str(path), branch=branch, base=base)

    def list(self) -> list[Worktree]:
        res = self._git(["worktree", "list", "--porcelain"])
        if not res.ok:
            return []
        return _parse_worktree_list(res.out)

    def remove(self, name: str, *, force: bool = True) -> bool:
        path = self.path_for(name)
        args = ["worktree", "remove", str(path)]
        if force:
            args.append("--force")
        return self._git(args).ok

    def changed_files(self, name: str) -> list[str]:
        path = self.path_for(name)
        res = self._git(["status", "--porcelain"], cwd=str(path))
        if not res.ok:
            return []
        files = []
        for line in res.out.splitlines():
            if len(line) > 3:
                files.append(line[3:].strip())
        return files

    def merge(self, name: str, *, into: str | None = None) -> MergeResult:
        """把 worktree 分支合并回当前（或指定）分支，检测冲突。"""
        branch = self.branch_for(name)
        if into:
            co = self._git(["checkout", into])
            if not co.ok:
                return MergeResult(False, branch, message=f"checkout {into} 失败：{co.out.strip()}")
        res = self._git(["merge", "--no-edit", branch])
        if res.ok:
            return MergeResult(True, branch, message=res.out.strip())
        conflicts = self._git(["diff", "--name-only", "--diff-filter=U"])
        files = [ln.strip() for ln in conflicts.out.splitlines() if ln.strip()]
        # 中止合并，保持主分支干净
        self._git(["merge", "--abort"])
        return MergeResult(False, branch, conflicted_files=files, message="合并冲突，已 abort")


def _parse_worktree_list(text: str) -> list[Worktree]:
    trees: list[Worktree] = []
    cur: dict[str, str] = {}

    def flush() -> None:
        if cur.get("worktree"):
            branch = cur.get("branch", "")
            branch = branch.replace("refs/heads/", "")
            trees.append(
                Worktree(
                    name=Path(cur["worktree"]).name,
                    path=cur["worktree"],
                    branch=branch,
                )
            )

    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            flush()
            cur = {}
            continue
        if line.startswith("worktree "):
            cur["worktree"] = line[len("worktree "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):]
        elif line == "detached":
            cur["branch"] = "(detached)"
    flush()
    return trees


# ── 并行编排 ──
TaskExecutor = Callable[[Worktree, str], int]


def _default_executor(worktree: Worktree, message: str) -> int:
    """默认执行器：在 worktree 内跑一个 R17 后台作业并等待。"""
    from auc.jobs import JobStore, run_job

    store = JobStore(worktree.path)
    job = store.enqueue(message, sandbox=worktree.path)
    job = store.claim_next()
    if job is None:
        return 1
    done = run_job(job, store)
    return done.exit_code if done.exit_code is not None else (0 if done.status == "done" else 1)


def run_parallel(
    repo_root: str,
    tasks: list[tuple[str, str]],
    *,
    base: str = "HEAD",
    merge: bool = False,
    cleanup: bool = False,
    max_workers: int = 4,
    executor: TaskExecutor | None = None,
    manager: WorktreeManager | None = None,
) -> list[ParallelTaskResult]:
    """为每个 (name, message) 任务建独立 worktree 并并发执行。

    merge=True 时执行完按顺序合并回当前分支（串行，避免交叉冲突）；cleanup=True
    时合并后移除 worktree。返回逐任务结果（含改动文件与合并状态）。
    """
    mgr = manager or WorktreeManager(repo_root)
    exec_fn = executor or _default_executor

    # 1) 建 worktree（串行，git 索引非并发安全）
    results: list[ParallelTaskResult] = []
    prepared: list[tuple[ParallelTaskResult, str]] = []
    for name, message in tasks:
        r = ParallelTaskResult(name=sanitize_name(name))
        try:
            r.worktree = mgr.create(name, base=base)
            prepared.append((r, message))
        except Exception as exc:  # noqa: BLE001
            r.status = "error"
            r.error = str(exc)
        results.append(r)

    # 2) 并发执行各 worktree 的任务
    def _work(item: tuple[ParallelTaskResult, str]) -> None:
        r, message = item
        try:
            code = exec_fn(r.worktree, message)  # type: ignore[arg-type]
            r.exit_code = code
            r.status = "done" if code == 0 else "failed"
            r.changed_files = mgr.changed_files(r.name)
        except Exception as exc:  # noqa: BLE001
            r.status = "error"
            r.error = str(exc)

    if prepared:
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
            list(pool.map(_work, prepared))

    # 3) 可选合并（串行）+ 清理
    for r, _ in prepared:
        if merge and r.status == "done":
            r.merge = mgr.merge(r.name)
        # 仅在安全时清理：任务失败/出错，或合并失败（冲突已 abort）时保留
        # worktree，避免丢失未合并的工作，供人工排查/解决冲突。
        if cleanup and _safe_to_cleanup(r, merge=merge):
            r.cleaned = mgr.remove(r.name)
    return results


def _safe_to_cleanup(r: ParallelTaskResult, *, merge: bool) -> bool:
    """判断某任务的 worktree 是否可安全清理。

    - 任务未成功（failed/error）→ 保留，便于排查；
    - 请求了合并但合并未成功（冲突/checkout 失败）→ 保留，防止丢失未合并改动。
    """
    if r.status != "done":
        return False
    if merge and (r.merge is None or not r.merge.ok):
        return False
    return True
