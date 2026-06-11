from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from auc.config import ModelConfig
from auc.events.bus import RunEvent
from auc.integration.evolution import evolution_paths
from auc.messages import ChatMessage
from auc.multimodal import PreparedUserInput, build_user_message, prepare_user_input
from auc.prompt_input import SLASH_COMMANDS, input_capabilities, read_user_input
from auc.terminal import (
    blue,
    bold,
    cyan,
    dim,
    display_width,
    draw_panel,
    green,
    magenta,
    pad_to,
    red,
    truncate_to,
    white,
    yellow,
)

_KEY_W = 11


def _short_path(path: str, *, max_len: int = 44) -> str:
    home = str(Path.home())
    if path.startswith(home):
        path = "~" + path[len(home) :]
    if display_width(path) > max_len:
        return truncate_to(path, max_len)
    return path


def _kv(key: str, value: str) -> str:
    k = dim(pad_to(key, _KEY_W))
    return f"{k}{value}"


def _chip(text: str) -> str:
    return dim("· ") + cyan(text)


def format_tool_label(name: str, arguments: dict[str, Any] | None = None) -> str:
    args = arguments or {}
    if name == "write_file":
        return f"Write({args.get('path', '?')})"
    if name == "read_file":
        return f"Read({args.get('path', '?')})"
    if name == "delete_path":
        return f"Delete({args.get('path', '?')})"
    if name == "list_dir":
        p = args.get("path", ".")
        return f"List({p})"
    if name == "save_lesson":
        return "SaveLesson()"
    if name == "promote_nugget":
        return f"PromoteNugget({args.get('nugget_id', '?')})"
    if args:
        brief = json.dumps(args, ensure_ascii=False)
        if len(brief) > 48:
            brief = brief[:45] + "..."
        return f"{name}({brief})"
    return name


class StreamSpinner:
    """首 token 前显示等待动画。"""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if not sys.stdout.isatty():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._spin())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _spin(self) -> None:
        frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        while not self._stop.is_set():
            sys.stdout.write(f"\r{magenta('◆')} {dim(frames[i % len(frames)] + ' 思考中')}")
            sys.stdout.flush()
            i += 1
            await asyncio.sleep(0.08)
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


class ClaudeCodeStreamPrinter:
    """流式回复 ◆ · 工具 ● · 结果 ⎿。"""

    def __init__(self, *, show_tools: bool = True) -> None:
        self._show_tools = show_tools
        self._in_reply = False
        self._marker_printed = False
        self._pending_tools: set[str] = set()
        self._tool_started: dict[str, float] = {}
        self._tool_count = 0
        self._cancelled = False

    def feed(self, ev: RunEvent) -> None:
        if ev.type == "run_start":
            self._begin_assistant()
            return
        if ev.type == "model_delta":
            delta = ev.payload.get("delta")
            if delta:
                self._begin_assistant()
                sys.stdout.write(delta)
                sys.stdout.flush()
            elif self._show_tools and ev.payload.get("tool_calls"):
                self.finish_reply()
                for tc in ev.payload["tool_calls"]:
                    label = format_tool_label(tc.get("name", "tool"), {})
                    self._print_tool_line(label)
        elif ev.type == "tool_start" and self._show_tools:
            self.finish_reply()
            tool = ev.payload.get("tool", "tool")
            args = ev.payload.get("arguments") or {}
            label = format_tool_label(tool, args)
            key = f"{tool}:{label}"
            self._tool_started[key] = time.monotonic()
            if key not in self._pending_tools:
                self._pending_tools.add(key)
                self._print_tool_line(label)
        elif ev.type == "tool_end" and self._show_tools:
            self._tool_count += 1
            tool = ev.payload.get("tool", "tool")
            summary = ev.payload.get("summary", "")
            is_error = ev.payload.get("is_error", False)
            elapsed = ""
            for key, started in list(self._tool_started.items()):
                if key.startswith(f"{tool}:"):
                    ms = int((time.monotonic() - started) * 1000)
                    elapsed = dim(f" {ms}ms")
                    del self._tool_started[key]
                    break
            self._print_tool_result(summary, is_error=is_error, suffix=elapsed)
        elif ev.type == "run_end":
            self.finish_reply()
            status = ev.payload.get("status", "")
            if status == "cancelled":
                self._cancelled = True
                print(dim("  ⊘ ") + yellow("已取消"))
            err = ev.payload.get("error")
            if err and status == "error":
                print(red(f"  ✗ {err}"))

    @property
    def tool_count(self) -> int:
        return self._tool_count

    @property
    def was_cancelled(self) -> bool:
        return self._cancelled

    def _begin_assistant(self) -> None:
        if not self._marker_printed:
            sys.stdout.write(f"\n{magenta('◆')} {dim(' ')}")
            sys.stdout.flush()
            self._marker_printed = True
            self._in_reply = True

    def _print_tool_line(self, label: str) -> None:
        print(f"  {yellow('●')} {white(label)}")

    def _print_tool_result(
        self, summary: str, *, is_error: bool, suffix: str = ""
    ) -> None:
        if not summary:
            return
        line = summary.replace("\n", " ")
        if len(line) > 88:
            line = line[:85] + "…"
        body = red(line) if is_error else dim(line)
        print(f"    {dim('⎿')} {body}{suffix}")

    def finish_reply(self) -> None:
        if self._in_reply:
            sys.stdout.write("\n")
            sys.stdout.flush()
        self._in_reply = False
        self._marker_printed = False
        self._pending_tools.clear()


def print_turn_footer(
    *,
    elapsed: float,
    turn: int,
    tool_count: int,
    status: str,
) -> None:
    icon = green("✓") if status == "completed" else yellow("○")
    parts = [dim(f"{elapsed:.1f}s"), dim(f"turn {turn}")]
    if tool_count:
        parts.append(dim(f"{tool_count} tools"))
    print(f"  {icon} {dim('│')} {' '.join(parts)}")


def print_user_echo(text: str, *, image_count: int = 0) -> None:
    lines = text.split("\n") if text else ["（仅图片）"]
    inner = min(52, max(12, max(display_width(ln) for ln in lines) + 2))
    bar = dim("─" * inner)
    print()
    print(f"  {blue('╭')}{bar}{blue('╮')}")
    print(f"  {blue('│')} {bold(white(lines[0]))}")
    for line in lines[1:]:
        print(f"  {blue('│')} {white(line)}")
    if image_count:
        print(f"  {blue('│')} {dim(f'🖼 {image_count} 张图片')}")
    print(f"  {blue('╰')}{bar}{blue('╯')}")


def print_note(text: str) -> None:
    print(f"  {dim('›')} {text}")


def expand_file_refs(text: str, sandbox: str) -> tuple[str, list[str]]:
    prepared = prepare_user_input(text, sandbox)
    return prepared.text, prepared.notes


def pop_last_turn(history: list[ChatMessage]) -> list[ChatMessage]:
    for i in range(len(history) - 1, -1, -1):
        if history[i].role == "user":
            return history[:i]
    return []


def last_user_text(history: list[ChatMessage]) -> str | None:
    for msg in reversed(history):
        if msg.role == "user":
            return msg.content
    return None


def print_welcome(
    cfg: ModelConfig,
    sandbox: str,
    *,
    evolve: bool,
    version: str = "0.2.4",
) -> None:
    model = cfg.model
    ws = _short_path(sandbox)
    cap = input_capabilities()
    title = (
        f"{magenta('◆')} {bold(white('AuC'))} {dim(version)}"
    )
    badge = green("ready")
    rows = [
        _kv("model", bold(cyan(model))),
        _kv("workspace", cyan(ws)),
        _kv("input", dim(cap)),
    ]
    if evolve:
        _, evo = evolution_paths(sandbox)
        rows.append(_kv("evolve", dim(_short_path(str(evo), max_len=40))))
    hints = (
        _chip("Enter 发送")
        + _chip("\\ 续行")
        + _chip("Tab 补全")
        + _chip("@ 文件/图片")
    )
    hints2 = _chip("/help 命令") + _chip("Ctrl+C 取消") + _chip("多模态")
    draw_panel(title=title, rows=rows, footer=[hints, hints2], badge=badge)
    print()


def print_help() -> None:
    rows = [
        _kv("Enter", "发送消息"),
        _kv("\\", "换行续写"),
        _kv("Tab", "补全 / 命令 或 @文件"),
        _kv("Ctrl+C", "取消生成"),
        _kv("Ctrl+D", "退出"),
        _kv("/retry", "重发上一条"),
        _kv("/undo", "撤销上一轮"),
        _kv("/edit", "编辑后重发"),
        _kv("/files", "浏览工作区"),
        _kv("/clear", "清空上下文"),
        _kv("/plan <任务>", "计划模式：只读探索出计划，批准后执行"),
        _kv("/autonomy <级别>", "自治级别 confirm-all/auto-edit/full-auto"),
        _kv("@path", "附加文本或图片"),
        _kv("图片", "png/jpg/gif/webp"),
    ]
    draw_panel(title=bold(white("帮助")), rows=rows)
    print()


def print_status(cfg: ModelConfig, sandbox: str, *, evolve: bool, session: ReplSession) -> None:
    rows = [
        _kv("model", f"{cfg.provider} / {bold(cyan(cfg.model))}"),
        _kv("config", dim(f"{cfg.config_name or '-'} · {cfg.config_id or '-'}")),
        _kv("workspace", cyan(_short_path(sandbox))),
        _kv("evolve", green("on") if evolve else dim("off")),
        _kv("turns", f"{session.turn_count}  {dim(f'({session.total_seconds:.1f}s)')}"),
        _kv("input", dim(input_capabilities())),
    ]
    if cfg.config_path:
        rows.append(_kv("settings", dim(_short_path(cfg.config_path, max_len=36))))
    draw_panel(title=bold(white("状态")), rows=rows)
    print()


def list_workspace_files(sandbox: str, subpath: str = ".") -> None:
    root = Path(sandbox).resolve()
    target = (root / subpath).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        print_note(red("路径越界"))
        return
    if not target.is_dir():
        print_note(red(f"不是目录: {subpath}"))
        return
    try:
        entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        print_note(red(str(exc)))
        return
    rows: list[str] = []
    for entry in entries[:24]:
        if entry.name.startswith("."):
            continue
        rel = str(entry.relative_to(root))
        if entry.is_dir():
            rows.append(f"{cyan('▸')} {rel}/")
        else:
            rows.append(f"{dim('·')} {rel}")
    if not rows:
        rows.append(dim("(空目录)"))
    title = f"{bold(white('文件'))} {dim('·')} {cyan(_short_path(str(target)))}"
    draw_panel(title=title, rows=rows, footer=[dim("输入 @相对路径 引用文件")])
    print()


def parse_slash_command(text: str) -> tuple[str | None, str]:
    t = text.strip()
    low = t.lower()
    if low in ("/help", "/h", "/?"):
        return "help", ""
    if low in ("/exit", "/quit", "/q"):
        return "exit", ""
    if low in ("/clear", "/reset"):
        return "clear", ""
    if low in ("/status", "/info"):
        return "status", ""
    if low.startswith("/retry"):
        return "retry", ""
    if low.startswith("/undo"):
        return "undo", ""
    if low.startswith("/edit"):
        return "edit", ""
    if low.startswith("/files"):
        arg = t[6:].strip() or "."
        return "files", arg
    if low.startswith("/plan"):
        return "plan", t[5:].strip()
    if low.startswith("/autonomy"):
        return "autonomy", t[9:].strip()
    return None, ""


@dataclass
class ReplSession:
    history: list[ChatMessage] = field(default_factory=list)
    last_raw_input: str = ""
    turn_count: int = 0
    total_seconds: float = 0.0


async def run_interactive_repl(
    *,
    agent: Any,
    cfg: ModelConfig,
    args: argparse.Namespace,
    sandbox: str,
    run_turn: Any,
) -> int:
    evolve = not getattr(args, "no_evolve", False)
    print_welcome(cfg, sandbox, evolve=evolve)
    session = ReplSession()

    while True:
        raw = await read_user_input(sandbox)
        if raw is None:
            break
        text = raw.strip()
        if not text:
            continue
        cmd, arg = parse_slash_command(text)
        if cmd == "exit":
            break
        if cmd == "help":
            print_help()
            continue
        if cmd == "clear":
            session.history = []
            session.turn_count = 0
            session.total_seconds = 0.0
            print_note(dim("对话上下文已清空"))
            continue
        if cmd == "status":
            print_status(cfg, sandbox, evolve=evolve, session=session)
            continue
        if cmd == "files":
            list_workspace_files(sandbox, arg)
            continue
        if cmd == "autonomy":
            from auc.policy.autonomy import AUTONOMY_LEVELS

            if not arg:
                cur = getattr(args, "autonomy", None) or "auto-edit"
                print_note(dim(f"当前自治级别: {cur}（可选: {', '.join(AUTONOMY_LEVELS)}）"))
                continue
            if arg not in AUTONOMY_LEVELS:
                print_note(red(f"未知级别: {arg}（可选: {', '.join(AUTONOMY_LEVELS)}）"))
                continue
            args.autonomy = arg
            if arg == "full-auto":
                print_note(yellow("full-auto：沙盒内写文件与 shell 全自动，仅 L3 仍需授权"))
            else:
                print_note(dim(f"自治级别已切换为 {arg}"))
            continue
        if cmd == "plan":
            if not arg:
                print_note(dim("用法: /plan <任务描述>"))
                continue
            text = arg
            args._work_mode = "plan"
            print_note(dim("计划模式：只读探索，产出计划后等待批准"))
        if cmd == "undo":
            if not session.history:
                print_note(dim("无可撤销内容"))
                continue
            session.history = pop_last_turn(session.history)
            print_note(dim("已撤销上一轮"))
            continue
        if cmd == "retry":
            if not session.last_raw_input:
                print_note(dim("无上一条消息"))
                continue
            text = session.last_raw_input
            session.history = pop_last_turn(session.history)
        elif cmd == "edit":
            prev = session.last_raw_input or last_user_text(session.history)
            if not prev:
                print_note(dim("无上一条消息可编辑"))
                continue
            print_note(dim("编辑上一条 · \\ 续行 · Enter 发送"))
            print_user_echo(prev)
            edited = await read_user_input(sandbox)
            if not edited or not edited.strip():
                continue
            text = edited.strip()
            session.history = pop_last_turn(session.history)
        if text.lower() in ("exit", "quit", "q"):
            break

        prepared = prepare_user_input(text, sandbox)
        from auc.work_mode import enrich_user_turn

        enriched, _, _ = enrich_user_turn(prepared.text)
        if enriched != prepared.text:
            prepared = PreparedUserInput(
                text=enriched, notes=prepared.notes, images=prepared.images
            )
        for note in prepared.notes:
            print_note(note)
        print_user_echo(prepared.text or text, image_count=len(prepared.images))
        session.last_raw_input = text
        t0 = time.monotonic()
        try:
            code, session.history, tool_n = await run_turn(
                agent,
                cfg,
                args,
                build_user_message(prepared),
                session.history,
            )
        except Exception as exc:  # noqa: BLE001
            print_note(red(str(exc)))
            continue
        elapsed = time.monotonic() - t0
        session.turn_count += 1
        session.total_seconds += elapsed
        if code == 0:
            result = getattr(agent, "last_run_result", None)
            status = result.status if result else "completed"
            print_turn_footer(
                elapsed=elapsed,
                turn=session.turn_count,
                tool_count=tool_n,
                status=status,
            )

        # R5 计划模式：检测计划块并询问批准执行
        if getattr(args, "_work_mode", None) == "plan":
            args._work_mode = None
            from auc.plan import parse_plan_block

            result = getattr(agent, "last_run_result", None)
            plan = parse_plan_block(result.output if result else None)
            if plan is None:
                print_note(dim("未检测到结构化计划块，可直接继续对话"))
                continue
            try:
                ans = await asyncio.to_thread(input, "  批准并执行该计划? [y/N]: ")
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans.strip().lower() not in ("y", "yes"):
                print_note(dim("计划未批准，未做任何修改"))
                continue
            args._approved_plan = plan
            t1 = time.monotonic()
            try:
                code, session.history, tool_n = await run_turn(
                    agent, cfg, args, "计划已批准，请按计划开始执行。", session.history
                )
            except Exception as exc:  # noqa: BLE001
                print_note(red(str(exc)))
                continue
            finally:
                args._approved_plan = None
            session.turn_count += 1
            session.total_seconds += time.monotonic() - t1
            if code == 0:
                result = getattr(agent, "last_run_result", None)
                print_turn_footer(
                    elapsed=time.monotonic() - t1,
                    turn=session.turn_count,
                    tool_count=tool_n,
                    status=result.status if result else "completed",
                )
    print()
    print(dim("  AuC · bye"))
    return 0
