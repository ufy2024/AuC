import asyncio
import json
import os

import pytest

from auc.tools.shell import make_shell_tool, run_shell_command, scrub_env, truncate_output


def test_run_basic(tmp_path) -> None:
    result = asyncio.run(run_shell_command(str(tmp_path), "echo hello"))
    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert not result.timed_out


def test_nonzero_exit_is_error(tmp_path) -> None:
    tool, policy = make_shell_tool(str(tmp_path))
    tr = asyncio.run(tool.invoke({"command": "exit 3"}))
    assert tr.is_error
    payload = json.loads(tr.content)
    assert payload["exit_code"] == 3


def test_timeout_kill(tmp_path) -> None:
    result = asyncio.run(
        run_shell_command(str(tmp_path), "sleep 30", timeout=1.0)
    )
    assert result.timed_out
    assert result.duration_ms < 10_000


def test_output_truncation(tmp_path) -> None:
    text, truncated = truncate_output(b"x" * 100, 10, 10)
    assert truncated
    assert "truncated 80 bytes" in text
    text2, t2 = truncate_output(b"short", 10, 10)
    assert not t2 and text2 == "short"


def test_cwd_escape_rejected(tmp_path) -> None:
    tool, _ = make_shell_tool(str(tmp_path))
    tr = asyncio.run(tool.invoke({"command": "ls", "cwd": "../.."}))
    assert tr.is_error


def test_env_scrubbed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MY_API_KEY", "secret123")
    env = scrub_env()
    assert "MY_API_KEY" not in env
    assert "PATH" in env
    result = asyncio.run(run_shell_command(str(tmp_path), "env"))
    assert "secret123" not in result.stdout


def test_empty_command(tmp_path) -> None:
    tool, _ = make_shell_tool(str(tmp_path))
    tr = asyncio.run(tool.invoke({"command": "  "}))
    assert tr.is_error


def test_policy_flags(tmp_path) -> None:
    _, policy = make_shell_tool(str(tmp_path))
    assert policy.privilege == "L2"
    assert policy.sandbox_only
    assert policy.mutates_state
    assert not policy.mutates_files


def test_cwd_subdir(tmp_path) -> None:
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "marker.txt").write_text("m", encoding="utf-8")
    result = asyncio.run(run_shell_command(str(tmp_path), "ls", cwd="pkg"))
    assert "marker.txt" in result.stdout
