import tempfile
from pathlib import Path

from auc.cli_ui import (
    ClaudeCodeStreamPrinter,
    expand_file_refs,
    format_tool_label,
    parse_slash_command,
    pop_last_turn,
)
from auc.messages import ChatMessage


def test_format_tool_label() -> None:
    assert format_tool_label("write_file", {"path": "a.py"}) == "Write(a.py)"
    assert format_tool_label("delete_path", {"path": "snake-game"}) == "Delete(snake-game)"


def test_slash_commands() -> None:
    assert parse_slash_command("/help") == ("help", "")
    assert parse_slash_command("/clear") == ("clear", "")
    assert parse_slash_command("/status") == ("status", "")
    assert parse_slash_command("/exit") == ("exit", "")
    assert parse_slash_command("/files src") == ("files", "src")
    assert parse_slash_command("/retry") == ("retry", "")
    assert parse_slash_command("hello") == (None, "")


def test_expand_file_refs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "hello.txt"
        p.write_text("hi\n", encoding="utf-8")
        expanded, notes = expand_file_refs("see @hello.txt", tmp)
        assert "--- file: hello.txt ---" in expanded
        assert "hi" in expanded
        assert len(notes) == 1


def test_pop_last_turn() -> None:
    history = [
        ChatMessage(role="user", content="a"),
        ChatMessage(role="assistant", content="b"),
        ChatMessage(role="user", content="c"),
        ChatMessage(role="assistant", content="d"),
    ]
    assert len(pop_last_turn(history)) == 2


def test_stream_printer_run_start() -> None:
    from auc.events.bus import RunEvent

    p = ClaudeCodeStreamPrinter()
    p.feed(RunEvent(type="run_start", run_id="r", agent_id="a", payload={}))
    p.finish_reply()
