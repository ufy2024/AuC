"""run_interactive_repl 脚本化 stdin 多轮对话测试。"""

from __future__ import annotations

import argparse
import asyncio
import builtins
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from auc import cli_ui
from auc.cli_ui import run_interactive_repl
from auc.config import ModelConfig
from auc.messages import ChatMessage


@dataclass
class _FakeResult:
    output: str = "好的"
    status: str = "completed"


@dataclass
class _FakeAgent:
    last_run_result: _FakeResult | None = field(default_factory=_FakeResult)


def _make_args(**extra: Any) -> argparse.Namespace:
    return argparse.Namespace(no_evolve=True, autonomy=None, _work_mode=None, **extra)


def _cfg() -> ModelConfig:
    return ModelConfig(provider="openai", model="test", api_key="x")


def _script_reader(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    it = iter(lines)

    async def fake_read(sandbox: str) -> str | None:
        del sandbox
        return next(it, None)

    monkeypatch.setattr(cli_ui, "read_user_input", fake_read)


def _run_repl(
    agent: _FakeAgent,
    args: argparse.Namespace,
    sandbox: str,
    run_turn: Any,
) -> int:
    return asyncio.run(
        run_interactive_repl(
            agent=agent, cfg=_cfg(), args=args, sandbox=sandbox, run_turn=run_turn
        )
    )


def test_repl_multi_turn_and_slash_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    async def run_turn(agent, cfg, args, user_msg, history):  # noqa: ANN001, ANN202
        calls.append(user_msg.content)
        new_history = [*history, user_msg, ChatMessage(role="assistant", content="好的")]
        return 0, new_history, 0

    _script_reader(
        monkeypatch,
        ["你好", "/help", "/status", "再来一轮", "/exit"],
    )
    code = _run_repl(_FakeAgent(), _make_args(), str(tmp_path), run_turn)
    assert code == 0
    assert len(calls) == 2  # 两次真实对话，斜杠命令不进模型
    out = capsys.readouterr().out
    assert "斜杠命令" in out or "/help" in out  # help 输出
    assert "turn 2" in out  # 回合统计


def test_repl_clear_undo_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    histories: list[int] = []

    async def run_turn(agent, cfg, args, user_msg, history):  # noqa: ANN001, ANN202
        histories.append(len(history))
        new_history = [*history, user_msg, ChatMessage(role="assistant", content="ok")]
        return 0, new_history, 0

    _script_reader(
        monkeypatch,
        ["第一句", "/undo", "/retry", "/clear", "/undo", "/retry", "/exit"],
    )
    code = _run_repl(_FakeAgent(), _make_args(), str(tmp_path), run_turn)
    assert code == 0
    # 三次 run：首轮、/undo 后 /retry 重发、/clear 后 /retry 重发（last_raw_input 保留）
    # 每次进入 run_turn 时 history 均为空（undo/clear 都已清掉上一轮）
    assert histories == [0, 0, 0]


def test_repl_autonomy_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run_turn(agent, cfg, args, user_msg, history):  # noqa: ANN001, ANN202
        return 0, history, 0

    args = _make_args()
    _script_reader(
        monkeypatch,
        ["/autonomy", "/autonomy full-auto", "/autonomy bogus", "/exit"],
    )
    code = _run_repl(_FakeAgent(), args, str(tmp_path), run_turn)
    assert code == 0
    assert args.autonomy == "full-auto"
    out = capsys.readouterr().out
    assert "full-auto" in out
    assert "未知级别" in out


def test_repl_run_turn_exception_keeps_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    attempts: list[str] = []

    async def run_turn(agent, cfg, args, user_msg, history):  # noqa: ANN001, ANN202
        attempts.append(user_msg.content)
        if len(attempts) == 1:
            raise RuntimeError("模型连接失败")
        return 0, [*history, user_msg], 0

    _script_reader(monkeypatch, ["第一次会失败", "第二次成功", "/exit"])
    code = _run_repl(_FakeAgent(), _make_args(), str(tmp_path), run_turn)
    assert code == 0
    assert len(attempts) == 2
    assert "模型连接失败" in capsys.readouterr().out


def test_repl_plan_mode_not_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan_output = (
        "计划如下\n```json auc-plan\n"
        '{"goal": "重构", "steps": [{"n": 1, "title": "a", "detail": "b"}], '
        '"files": ["x.py"], "risks": []}'
        "\n```"
    )
    agent = _FakeAgent(last_run_result=_FakeResult(output=plan_output))
    executed: list[str] = []

    async def run_turn(agent_, cfg, args, user_msg, history):  # noqa: ANN001, ANN202
        executed.append(user_msg.content)
        return 0, [*history, user_msg], 0

    monkeypatch.setattr(builtins, "input", lambda *a: "n")
    args = _make_args()
    _script_reader(monkeypatch, ["/plan 重构模块", "/exit"])
    code = _run_repl(agent, args, str(tmp_path), run_turn)
    assert code == 0
    assert len(executed) == 1  # 仅计划探索一轮，未批准不执行
    assert getattr(args, "_approved_plan", None) is None
    out = capsys.readouterr().out
    assert "计划未批准" in out


def test_repl_plan_without_arg_shows_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run_turn(agent, cfg, args, user_msg, history):  # noqa: ANN001, ANN202
        raise AssertionError("不应触发模型调用")

    _script_reader(monkeypatch, ["/plan", "/exit"])
    code = _run_repl(_FakeAgent(), _make_args(), str(tmp_path), run_turn)
    assert code == 0
    assert "用法: /plan" in capsys.readouterr().out
