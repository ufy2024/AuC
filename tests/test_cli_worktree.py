from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from auc.cli import main


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _has_git() -> bool:
    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _has_git(), reason="git unavailable")


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-b", "main"], path)
    _git(["config", "user.email", "t@t.t"], path)
    _git(["config", "user.name", "tester"], path)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(["add", "."], path)
    _git(["commit", "-m", "init"], path)


def test_worktree_add_list_remove(tmp_path, capsys):
    repo = tmp_path / "repo"
    _init_repo(repo)

    assert main(["worktree", "add", "feat", "--repo", str(repo)]) == 0
    assert "auc/feat" in capsys.readouterr().out

    assert main(["worktree", "list", "--repo", str(repo)]) == 0
    assert "auc/feat" in capsys.readouterr().out

    assert main(["worktree", "remove", "feat", "--repo", str(repo)]) == 0


def test_worktree_run_rejects_bad_task(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    assert main(["worktree", "run", "noequals", "--repo", str(repo)]) == 2
