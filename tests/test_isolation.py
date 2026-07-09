from __future__ import annotations

import pytest

from auc import isolation
from auc.isolation import IsolationConfig, IsolationUnavailableError, wrap_command


def test_mode_none_passthrough():
    cmd = ["auc", "chat", "hi"]
    out, note = wrap_command(cmd, "/work", IsolationConfig(mode="none"))
    assert out == cmd
    assert note == ""


def test_docker_unavailable_fail_closed(monkeypatch):
    """默认 fail-closed：docker 缺失时拒绝执行，绝不静默降级本机。"""
    monkeypatch.setattr(isolation, "docker_available", lambda: False)
    cmd = ["auc", "chat", "hi"]
    with pytest.raises(IsolationUnavailableError):
        wrap_command(cmd, "/work", IsolationConfig(mode="docker"))


def test_docker_unavailable_degrades_when_opted_out(monkeypatch):
    monkeypatch.setattr(isolation, "docker_available", lambda: False)
    cmd = ["auc", "chat", "hi"]
    out, note = wrap_command(cmd, "/work", IsolationConfig(mode="docker", fail_closed=False))
    assert out == cmd
    assert "降级" in note


def test_docker_missing_sandbox_fail_closed(monkeypatch):
    monkeypatch.setattr(isolation, "docker_available", lambda: True)
    cmd = ["auc", "chat", "hi"]
    with pytest.raises(IsolationUnavailableError):
        wrap_command(cmd, "", IsolationConfig(mode="docker"))


def test_docker_missing_sandbox_degrades_when_opted_out(monkeypatch):
    monkeypatch.setattr(isolation, "docker_available", lambda: True)
    cmd = ["auc", "chat", "hi"]
    out, note = wrap_command(cmd, "", IsolationConfig(mode="docker", fail_closed=False))
    assert out == cmd
    assert "sandbox" in note


def test_docker_wrap(monkeypatch):
    monkeypatch.setattr(isolation, "docker_available", lambda: True)
    cmd = ["python", "-m", "auc.cli", "chat", "hi"]
    cfg = IsolationConfig(mode="docker", image="myimg:1", network="none")
    out, note = wrap_command(cmd, "/abs/sandbox", cfg)
    assert out[:3] == ["docker", "run", "--rm"]
    assert "/abs/sandbox:/work" in out
    assert "-w" in out and "/work" in out
    assert "--network" in out and "none" in out
    assert "myimg:1" in out
    # 默认加固：no-new-privileges + cap-drop ALL
    assert "no-new-privileges" in out
    assert "--cap-drop" in out and "ALL" in out
    # 实际命令追加在镜像之后
    assert out[-len(cmd):] == cmd
    assert "docker" in note


def test_docker_read_only_mount(monkeypatch):
    monkeypatch.setattr(isolation, "docker_available", lambda: True)
    cmd = ["echo", "hi"]
    cfg = IsolationConfig(mode="docker", read_only=True)
    out, note = wrap_command(cmd, "/abs/sandbox", cfg)
    assert "/abs/sandbox:/work:ro" in out
    assert "只读" in note


def test_build_job_command_with_docker(monkeypatch):
    monkeypatch.setattr(isolation, "docker_available", lambda: True)
    from auc.jobs import Job, build_job_command

    job = Job(
        id="j1", message="do it", sandbox="/sb", isolation="docker", image="img:2"
    )
    cmd = build_job_command(job)
    assert cmd[0] == "docker"
    assert "img:2" in cmd
    assert cmd[-1] == "do it"


def test_build_job_command_plain():
    from auc.jobs import Job, build_job_command

    job = Job(id="j2", message="do it", sandbox="/sb")
    cmd = build_job_command(job)
    assert cmd[0] != "docker"
    assert cmd[-1] == "do it"
