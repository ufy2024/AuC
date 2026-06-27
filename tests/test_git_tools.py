"""R8 Git 工具测试（在临时 git 仓库内验证）。"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from auc.tools.git import make_git_tools

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git 不可用"
)


def _tool(tools, name):
    for t, _ in tools:
        if t.name == name:
            return t
    raise AssertionError(f"missing tool: {name}")


def _init_repo(path: Path) -> None:
    def run(*args: str) -> None:
        subprocess.run(
            ["git", *args], cwd=path, check=True, capture_output=True
        )

    run("init")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "Tester")
    run("config", "commit.gpgsign", "false")


def test_git_status_add_commit_log(tmp_path) -> None:
    _init_repo(tmp_path)
    sandbox = str(tmp_path)
    tools = make_git_tools(sandbox)
    (tmp_path / "a.txt").write_text("hello\n", encoding="utf-8")

    status = asyncio.run(_tool(tools, "git_status").invoke({}))
    assert not status.is_error
    assert "a.txt" in status.content

    added = asyncio.run(_tool(tools, "git_add").invoke({"paths": "a.txt"}))
    assert not added.is_error

    committed = asyncio.run(
        _tool(tools, "git_commit").invoke({"message": "init commit"})
    )
    assert not committed.is_error

    log = asyncio.run(_tool(tools, "git_log").invoke({}))
    assert not log.is_error
    assert "init commit" in log.content


def test_git_diff_shows_changes(tmp_path) -> None:
    _init_repo(tmp_path)
    sandbox = str(tmp_path)
    tools = make_git_tools(sandbox)
    f = tmp_path / "a.txt"
    f.write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "c1"], cwd=tmp_path, check=True, capture_output=True
    )
    f.write_text("one\ntwo\n", encoding="utf-8")

    diff = asyncio.run(_tool(tools, "git_diff").invoke({}))
    assert not diff.is_error
    assert "two" in diff.content


def test_git_commit_requires_message(tmp_path) -> None:
    _init_repo(tmp_path)
    tools = make_git_tools(str(tmp_path))
    res = asyncio.run(_tool(tools, "git_commit").invoke({"message": "   "}))
    assert res.is_error
    assert "message" in res.content


def test_git_push_is_l3(tmp_path) -> None:
    tools = make_git_tools(str(tmp_path))
    for t, pol in tools:
        if t.name == "git_push":
            assert pol.privilege == "L3"
        if t.name in ("git_status", "git_diff", "git_log"):
            assert pol.privilege == "L1"
        if t.name in ("git_add", "git_commit"):
            assert pol.privilege == "L2"
