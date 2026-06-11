from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from auc.terminal import blue, cyan, dim

HISTORY_PATH = Path.home() / ".Au" / "AuC" / "history"

SLASH_COMMANDS = (
    "/help",
    "/clear",
    "/status",
    "/exit",
    "/retry",
    "/undo",
    "/files",
    "/edit",
    "/plan",
    "/autonomy",
)

def _prompt_hint() -> str:
    return (
        dim(" ")
        + cyan("Enter")
        + dim(" 发送  ")
        + cyan("\\")
        + dim(" 续行  ")
        + cyan("Tab")
        + dim(" 补全  ")
        + cyan("@")
        + dim(" 文件")
    )


def _ensure_history_dir() -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _collect_workspace_files(sandbox: str, prefix: str) -> list[str]:
    root = Path(sandbox).resolve()
    if not root.is_dir():
        return []
    rel = prefix
    while rel.startswith("./"):
        rel = rel[2:]
    if rel.startswith("/") or ".." in rel.split("/"):
        return []
    rel = rel.rstrip("/")
    search_dir = root / rel if rel else root
    if not search_dir.exists():
        parent = search_dir.parent
        stem = search_dir.name
        if not parent.is_dir() or not str(parent).startswith(str(root)):
            return []
        search_dir = parent
        rel = str(search_dir.relative_to(root))
        if rel == ".":
            rel = ""
        stem_filter = stem
    else:
        stem_filter = ""

    out: list[str] = []
    if search_dir.is_dir():
        try:
            entries = sorted(search_dir.iterdir(), key=lambda p: p.name)
        except OSError:
            return []
        for entry in entries:
            name = entry.name
            if name.startswith("."):
                continue
            if stem_filter and not name.startswith(stem_filter):
                continue
            rel_path = f"{rel}/{name}".lstrip("/") if rel else name
            if entry.is_dir():
                out.append(f"@{rel_path}/")
            else:
                out.append(f"@{rel_path}")
    return out[:40]


def _setup_readline(sandbox: str) -> None:
    try:
        import readline
    except ImportError:
        return

    _ensure_history_dir()
    try:
        readline.read_history_file(str(HISTORY_PATH))
    except OSError:
        pass
    readline.set_history_length(2000)

    def _completer(text: str, state: int) -> str | None:
        options: list[str] = []
        if text.startswith("/"):
            options = [c for c in SLASH_COMMANDS if c.startswith(text)]
        elif text.startswith("@"):
            options = _collect_workspace_files(sandbox, text[1:])
        if state < len(options):
            return options[state]
        return None

    readline.set_completer(_completer)
    readline.parse_and_bind("tab: complete")


def _save_readline_history() -> None:
    try:
        import readline
    except ImportError:
        return
    _ensure_history_dir()
    try:
        readline.write_history_file(str(HISTORY_PATH))
    except OSError:
        pass


async def _read_fallback(sandbox: str) -> str | None:
    _setup_readline(sandbox)
    lines: list[str] = []
    try:
        while True:
            prompt = blue("❯ ") if not lines else dim("  … ")
            line = await asyncio.to_thread(input, prompt)
            if line.endswith("\\"):
                lines.append(line[:-1])
                continue
            lines.append(line)
            break
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    text = "\n".join(lines).strip()
    if text:
        _save_readline_history()
    return text or None


def _make_prompt_toolkit_session(
    sandbox: str,
    *,
    input: Any = None,  # noqa: A002 - prompt_toolkit 同名约定
    output: Any = None,
) -> tuple[Any, Any]:
    """构造交互会话；input/output 可注入 PipeInput/DummyOutput 供无 TTY 测试。"""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings

    _ensure_history_dir()

    class AuCCompleter(Completer):
        def get_completions(self, document, complete_event):  # noqa: ANN001
            text = document.text_before_cursor
            if text.startswith("/") and " " not in text:
                # 仍在输入首个斜杠命令：按前缀过滤（如 "/he" → "/help"）
                for cmd in SLASH_COMMANDS:
                    if cmd.startswith(text):
                        yield Completion(cmd, start_position=-len(text))
            elif "@" in text:
                at = text.rfind("@")
                frag = text[at:]
                for item in _collect_workspace_files(sandbox, frag[1:]):
                    yield Completion(item, start_position=-len(frag))

    bindings = KeyBindings()

    @bindings.add("enter")
    def _submit(event) -> None:  # noqa: ANN001
        buf = event.current_buffer
        if buf.document.text.endswith("\\"):
            buf.delete_before_cursor(count=1)
            buf.insert_text("\n")
        else:
            buf.validate_and_handle()

    extra: dict[str, Any] = {}
    if input is not None:
        extra["input"] = input
    if output is not None:
        extra["output"] = output
    session = PromptSession(
        history=FileHistory(str(HISTORY_PATH)),
        completer=AuCCompleter(),
        key_bindings=bindings,
        multiline=True,
        **extra,
    )
    return session, bindings


async def _read_prompt_toolkit(sandbox: str) -> str | None:
    try:
        session, _ = _make_prompt_toolkit_session(sandbox)
    except Exception:
        return await _read_fallback(sandbox)
    try:
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.styles import Style

        text = await session.prompt_async(
            HTML('<style fg="#5B9BD5" bold="true">❯ </style>'),
            style=Style.from_dict({"": "#E8E8E8"}),
            bottom_toolbar=lambda: _prompt_hint(),
        )
        return text.strip() or None
    except (EOFError, KeyboardInterrupt):
        print()
        return None


async def read_user_input(sandbox: str) -> str | None:
    """读取用户输入：优先 prompt_toolkit，否则 readline 回退。"""
    if os.environ.get("AUC_PLAIN_INPUT"):
        return await _read_plain(sandbox)
    if sys.stdin.isatty():
        try:
            import prompt_toolkit  # noqa: F401

            return await _read_prompt_toolkit(sandbox)
        except ImportError:
            pass
    return await _read_fallback(sandbox)


async def _read_plain(sandbox: str) -> str | None:
    try:
        line = await asyncio.to_thread(input, "> ")
        return line.strip() or None
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def input_capabilities() -> str:
    try:
        import prompt_toolkit  # noqa: F401

        return "prompt_toolkit"
    except ImportError:
        try:
            import readline  # noqa: F401

            return "readline"
        except ImportError:
            return "plain"
