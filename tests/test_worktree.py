from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auc.worktree import (
    GitResult,
    WorktreeManager,
    _parse_worktree_list,
    run_parallel,
    sanitize_name,
)


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], path)
    _git(["config", "user.email", "t@t.t"], path)
    _git(["config", "user.name", "tester"], path)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", "init"], path)


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _has_git(), reason="git unavailable")


def test_sanitize_name():
    assert sanitize_name("feat/login bug!") == "feat-login-bug"
    assert sanitize_name("") == "task"


def test_parse_worktree_list():
    text = (
        "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n"
        "worktree /repo/.auc/worktrees/a\nHEAD def\nbranch refs/heads/auc/a\n\n"
        "worktree /repo/d\nHEAD ghi\ndetached\n"
    )
    trees = _parse_worktree_list(text)
    assert len(trees) == 3
    assert trees[0].branch == "main"
    assert trees[1].branch == "auc/a"
    assert trees[2].branch == "(detached)"


def test_create_and_list_and_remove(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    mgr = WorktreeManager(str(repo))

    wt = mgr.create("feature-x")
    assert Path(wt.path).is_dir()
    assert wt.branch == "auc/feature-x"
    assert (Path(wt.path) / "README.md").is_file()

    branches = {w.branch for w in mgr.list()}
    assert "auc/feature-x" in branches

    assert mgr.remove("feature-x") is True
    assert not Path(wt.path).exists()


def test_changed_files(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    mgr = WorktreeManager(str(repo))
    wt = mgr.create("edit")
    (Path(wt.path) / "new.txt").write_text("hi", encoding="utf-8")
    changed = mgr.changed_files("edit")
    assert "new.txt" in changed


def test_merge_success(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    mgr = WorktreeManager(str(repo))
    wt = mgr.create("addfile")
    p = Path(wt.path)
    (p / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(["add", "."], p)
    _git(["commit", "-m", "add feature"], p)

    res = mgr.merge("addfile")
    assert res.ok is True
    assert (repo / "feature.txt").is_file()


def test_merge_conflict_aborts(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    # 主分支也改 README
    (repo / "README.md").write_text("# main change\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "main edit"], repo)

    mgr = WorktreeManager(str(repo))
    wt = mgr.create("conflict", base="HEAD~1")
    p = Path(wt.path)
    (p / "README.md").write_text("# branch change\n", encoding="utf-8")
    _git(["add", "."], p)
    _git(["commit", "-m", "branch edit"], p)

    res = mgr.merge("conflict")
    assert res.ok is False
    assert "README.md" in res.conflicted_files
    # 主分支被 abort 还原：无冲突标记，README 恢复为主分支内容
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    )
    assert "UU" not in status.stdout
    assert (repo / "README.md").read_text(encoding="utf-8") == "# main change\n"


def test_create_failure_raises_with_fake_git(tmp_path):
    def fail_git(args, cwd):
        return GitResult(1, "boom")

    mgr = WorktreeManager(str(tmp_path), git=fail_git)
    with pytest.raises(RuntimeError):
        mgr.create("x")


def test_run_parallel_with_injected_executor(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    def fake_exec(worktree, message):
        # 模拟智能体在各自 worktree 写文件
        (Path(worktree.path) / f"{worktree.name}.txt").write_text(message, encoding="utf-8")
        return 0

    results = run_parallel(
        str(repo),
        [("alpha", "do A"), ("beta", "do B")],
        executor=fake_exec,
    )
    assert len(results) == 2
    assert all(r.status == "done" for r in results)
    by_name = {r.name: r for r in results}
    assert "alpha.txt" in by_name["alpha"].changed_files
    assert "beta.txt" in by_name["beta"].changed_files


def test_run_parallel_merge_and_cleanup(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    def fake_exec(worktree, message):
        p = Path(worktree.path)
        (p / f"{worktree.name}.txt").write_text(message, encoding="utf-8")
        _git(["add", "."], p)
        _git(["commit", "-m", message], p)
        return 0

    results = run_parallel(
        str(repo),
        [("m1", "module one"), ("m2", "module two")],
        executor=fake_exec,
        merge=True,
        cleanup=True,
    )
    assert all(r.merge and r.merge.ok for r in results)
    assert (repo / "m1.txt").is_file()
    assert (repo / "m2.txt").is_file()
    # cleanup 后 worktree 目录移除
    assert not (repo / ".auc" / "worktrees" / "m1").exists()


def test_run_parallel_cleanup_preserves_conflicted_worktree(tmp_path):
    """合并冲突时即使 cleanup=True 也应保留 worktree，避免丢失未合并改动。"""
    repo = tmp_path / "repo"
    _init_repo(repo)
    # 主分支改 README，制造与子分支的冲突
    (repo / "README.md").write_text("# main change\n", encoding="utf-8")
    _git(["add", "."], repo)
    _git(["commit", "-m", "main edit"], repo)

    def conflicting_exec(worktree, message):
        p = Path(worktree.path)
        (p / "README.md").write_text("# branch change\n", encoding="utf-8")
        _git(["add", "."], p)
        _git(["commit", "-m", message], p)
        return 0

    results = run_parallel(
        str(repo),
        [("conf", "edit readme")],
        base="HEAD~1",
        executor=conflicting_exec,
        merge=True,
        cleanup=True,
    )
    r = results[0]
    assert r.merge is not None and r.merge.ok is False
    assert r.cleaned is False
    # worktree 目录仍在，供人工解决冲突
    assert (repo / ".auc" / "worktrees" / "conf").exists()


def test_run_parallel_cleanup_skips_failed_task(tmp_path):
    """任务失败（非 0 退出）时保留 worktree 便于排查。"""
    repo = tmp_path / "repo"
    _init_repo(repo)

    def failing_exec(worktree, message):
        return 1

    results = run_parallel(
        str(repo),
        [("bad", "task")],
        executor=failing_exec,
        cleanup=True,
    )
    r = results[0]
    assert r.status == "failed"
    assert r.cleaned is False
    assert (repo / ".auc" / "worktrees" / "bad").exists()


def test_run_parallel_executor_failure(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)

    def boom(worktree, message):
        raise RuntimeError("exec failed")

    results = run_parallel(str(repo), [("x", "task")], executor=boom)
    assert results[0].status == "error"
    assert "exec failed" in results[0].error
