"""ClaudeCodeStreamPrinter（stream_display 兼容别名）基础渲染。"""

from __future__ import annotations

import pytest

from auc.events.bus import RunEvent
from auc.stream_display import ChatStreamPrinter


def _ev(ev_type: str, payload: dict, *, ts: float = 1_704_067_200.0) -> RunEvent:
    return RunEvent(
        type=ev_type, run_id="r1", agent_id="a1", payload=payload, timestamp=ts
    )


def test_alias_points_to_printer() -> None:
    from auc.cli_ui import ClaudeCodeStreamPrinter

    assert ChatStreamPrinter is ClaudeCodeStreamPrinter


def test_model_delta_and_finish(capsys: pytest.CaptureFixture[str]) -> None:
    printer = ChatStreamPrinter()
    printer.feed(_ev("run_start", {}))
    printer.feed(_ev("model_delta", {"delta": "你好"}))
    printer.feed(_ev("model_delta", {"delta": "，世界"}))
    printer.finish_reply()
    out = capsys.readouterr().out
    assert "◆" in out
    assert "你好，世界" in out


def test_run_model_shown_and_switch_highlighted(capsys: pytest.CaptureFixture[str]) -> None:
    printer = ChatStreamPrinter()
    printer.feed(_ev("run_start", {"model": "deepseek-chat"}))
    printer.finish_reply()
    out1 = capsys.readouterr().out
    assert "⬡" in out1
    assert "deepseek-chat" in out1

    # 第二次 Run 切换到另一模型 → 高亮「切换」
    printer.feed(_ev("run_start", {"model": "gpt-4o-mini"}))
    printer.finish_reply()
    out2 = capsys.readouterr().out
    assert "⇄" in out2
    assert "deepseek-chat" in out2
    assert "gpt-4o-mini" in out2


def test_run_start_without_model_prints_no_model_line(capsys: pytest.CaptureFixture[str]) -> None:
    printer = ChatStreamPrinter()
    printer.feed(_ev("run_start", {}))
    out = capsys.readouterr().out
    assert "⬡" not in out
    assert "⇄" not in out


def test_tool_lifecycle_rendering(capsys: pytest.CaptureFixture[str]) -> None:
    printer = ChatStreamPrinter()
    printer.feed(_ev("tool_start", {"tool": "read_file", "arguments": {"path": "a.py"}}))
    printer.feed(
        _ev("tool_end", {"tool": "read_file", "summary": "读取 12 行", "is_error": False})
    )
    out = capsys.readouterr().out
    assert "●" in out
    assert "Read(a.py)" in out
    assert "⎿" in out
    assert "读取 12 行" in out
    assert "[" in out  # 时间戳
    assert printer.tool_count == 1


def test_tool_error_and_long_summary_truncated(capsys: pytest.CaptureFixture[str]) -> None:
    printer = ChatStreamPrinter()
    printer.feed(_ev("tool_start", {"tool": "run_command", "arguments": {"command": "x"}}))
    printer.feed(
        _ev("tool_end", {"tool": "run_command", "summary": "e" * 200, "is_error": True})
    )
    out = capsys.readouterr().out
    assert "…" in out
    assert "e" * 200 not in out


def test_run_end_cancelled_and_error(capsys: pytest.CaptureFixture[str]) -> None:
    printer = ChatStreamPrinter()
    printer.feed(_ev("run_end", {"status": "cancelled"}))
    assert printer.was_cancelled is True
    assert "已取消" in capsys.readouterr().out

    printer2 = ChatStreamPrinter()
    printer2.feed(_ev("run_end", {"status": "error", "error": "boom"}))
    assert "boom" in capsys.readouterr().out


def test_show_tools_false_suppresses_tool_lines(capsys: pytest.CaptureFixture[str]) -> None:
    printer = ChatStreamPrinter(show_tools=False)
    printer.feed(_ev("tool_start", {"tool": "read_file", "arguments": {}}))
    printer.feed(_ev("tool_end", {"tool": "read_file", "summary": "done", "is_error": False}))
    out = capsys.readouterr().out
    assert "read_file" not in out
    assert printer.tool_count == 0
