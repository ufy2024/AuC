"""prompt_input：补全收集、回退输入、能力探测（脚本化 stdin）。"""

from __future__ import annotations

import asyncio
import builtins
from pathlib import Path

import pytest

from auc import prompt_input
from auc.prompt_input import (
    SLASH_COMMANDS,
    _collect_workspace_files,
    _read_fallback,
    _read_plain,
    input_capabilities,
    read_user_input,
)


@pytest.fixture
def sandbox(tmp_path: Path) -> str:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x=1", encoding="utf-8")
    (tmp_path / "readme.md").write_text("hi", encoding="utf-8")
    (tmp_path / ".hidden").write_text("secret", encoding="utf-8")
    return str(tmp_path)


def _patch_history(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(prompt_input, "HISTORY_PATH", tmp_path / "history")


def _script_input(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> None:
    it = iter(lines)

    def fake_input(prompt: str = "") -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr(builtins, "input", fake_input)


def test_collect_workspace_files_basic(sandbox: str) -> None:
    out = _collect_workspace_files(sandbox, "")
    assert "@readme.md" in out
    assert "@src/" in out
    assert all(not o.startswith("@.hidden") for o in out)


def test_collect_workspace_files_prefix_and_subdir(sandbox: str) -> None:
    assert _collect_workspace_files(sandbox, "read") == ["@readme.md"]
    assert _collect_workspace_files(sandbox, "src/") == ["@src/main.py"]
    assert _collect_workspace_files(sandbox, "src/ma") == ["@src/main.py"]


def test_collect_workspace_files_rejects_escape(sandbox: str) -> None:
    assert _collect_workspace_files(sandbox, "../") == []
    assert _collect_workspace_files(sandbox, "/etc") == []
    assert _collect_workspace_files("/no/such/dir", "") == []


def test_collect_workspace_files_limit(tmp_path: Path) -> None:
    for i in range(60):
        (tmp_path / f"f{i:02d}.txt").write_text("x", encoding="utf-8")
    out = _collect_workspace_files(str(tmp_path), "")
    assert len(out) == 40


def test_read_fallback_single_line(
    sandbox: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_history(monkeypatch, tmp_path)
    _script_input(monkeypatch, ["hello world"])
    assert asyncio.run(_read_fallback(sandbox)) == "hello world"


def test_read_fallback_backslash_continuation(
    sandbox: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_history(monkeypatch, tmp_path)
    _script_input(monkeypatch, ["第一行\\", "第二行"])
    assert asyncio.run(_read_fallback(sandbox)) == "第一行\n第二行"


def test_read_fallback_eof_returns_none(
    sandbox: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_history(monkeypatch, tmp_path)
    _script_input(monkeypatch, [])
    assert asyncio.run(_read_fallback(sandbox)) is None


def test_read_plain_mode(
    sandbox: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUC_PLAIN_INPUT", "1")
    _script_input(monkeypatch, ["  plain text  "])
    assert asyncio.run(read_user_input(sandbox)) == "plain text"
    _script_input(monkeypatch, [""])
    assert asyncio.run(_read_plain(sandbox)) is None


def test_slash_commands_and_capabilities() -> None:
    assert "/plan" in SLASH_COMMANDS
    assert "/autonomy" in SLASH_COMMANDS
    assert input_capabilities() in ("prompt_toolkit", "readline", "plain")


# ── prompt-toolkit 真实交互（PipeInput，无需 TTY）────────────────


def test_ptk_prompt_single_line(
    sandbox: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from auc.prompt_input import _make_prompt_toolkit_session

    _patch_history(monkeypatch, tmp_path)
    with create_pipe_input() as pipe:
        session, _ = _make_prompt_toolkit_session(sandbox, input=pipe, output=DummyOutput())
        pipe.send_text("你好世界\n")
        text = asyncio.run(session.prompt_async())
    assert text == "你好世界"


def test_ptk_backslash_enter_continues_line(
    sandbox: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """行尾反斜杠 + Enter 触发自定义键绑定：换行续输而非提交。"""
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from auc.prompt_input import _make_prompt_toolkit_session

    _patch_history(monkeypatch, tmp_path)
    with create_pipe_input() as pipe:
        session, _ = _make_prompt_toolkit_session(sandbox, input=pipe, output=DummyOutput())
        pipe.send_text("第一行\\\n第二行\n")
        text = asyncio.run(session.prompt_async())
    assert text == "第一行\n第二行"


def test_ptk_completer_slash_and_at(
    sandbox: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("prompt_toolkit")
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from auc.prompt_input import _make_prompt_toolkit_session

    _patch_history(monkeypatch, tmp_path)
    with create_pipe_input() as pipe:
        session, _ = _make_prompt_toolkit_session(sandbox, input=pipe, output=DummyOutput())
        completer = session.completer

        def _complete(text: str) -> list[str]:
            doc = Document(text, cursor_position=len(text))
            return [c.text for c in completer.get_completions(doc, CompleteEvent())]

        assert "/plan" in _complete("/")
        assert _complete("/he") == ["/help"]
        at = _complete("看 @read")
        assert "@readme.md" in at
        assert all(not c.startswith("@.") for c in _complete("@"))
