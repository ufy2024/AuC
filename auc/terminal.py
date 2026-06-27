from __future__ import annotations

import os
import re
import sys
import unicodedata
from datetime import datetime

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def _wrap(code: str, text: str) -> str:
    if not _color_enabled():
        return text
    return f"\033[{code}m{text}\033[0m"


def dim(text: str) -> str:
    return _wrap("2", text)


def bold(text: str) -> str:
    return _wrap("1", text)


def cyan(text: str) -> str:
    return _wrap("36", text)


def yellow(text: str) -> str:
    return _wrap("33", text)


def red(text: str) -> str:
    return _wrap("31", text)


def green(text: str) -> str:
    return _wrap("32", text)


def magenta(text: str) -> str:
    return _wrap("35", text)


def blue(text: str) -> str:
    return _wrap("34", text)


def white(text: str) -> str:
    return _wrap("97", text)


def log_time_prefix(ts: float | None = None) -> str:
    """运行日志时间前缀，如 ``[14:32:05.123] ``（已 dim）。"""
    when = datetime.fromtimestamp(ts) if ts is not None else datetime.now()
    ms = when.microsecond // 1000
    stamp = when.strftime("[%H:%M:%S.") + f"{ms:03d}] "
    return dim(stamp)


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def display_width(text: str) -> int:
    """终端可见宽度（CJK 双宽）。"""
    plain = strip_ansi(text)
    width = 0
    for ch in plain:
        if unicodedata.combining(ch):
            continue
        east = unicodedata.east_asian_width(ch)
        if east in ("F", "W"):
            width += 2
        else:
            width += 1
    return width


def pad_to(text: str, width: int, *, align: str = "left") -> str:
    gap = max(0, width - display_width(text))
    if align == "right":
        return " " * gap + text
    return text + " " * gap


def truncate_to(text: str, max_width: int, *, suffix: str = "…") -> str:
    plain = strip_ansi(text)
    if display_width(plain) <= max_width:
        return text
    out: list[str] = []
    w = 0
    budget = max_width - display_width(suffix)
    for ch in plain:
        cw = 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
        if w + cw > budget:
            break
        out.append(ch)
        w += cw
    return "".join(out) + suffix


def hr(width: int, *, char: str = "─") -> str:
    return dim(char * width)


def box_row(content: str, inner_width: int) -> str:
    gap = max(0, inner_width - display_width(content))
    return dim("│ ") + content + " " * gap + dim(" │")


def draw_panel(
    *,
    title: str,
    rows: list[str],
    footer: list[str] | None = None,
    badge: str | None = None,
    min_width: int = 52,
    max_width: int = 72,
) -> None:
    """绘制对齐面板（支持 ANSI 与 CJK）。"""
    all_rows = [title, *rows]
    if footer:
        all_rows.extend(footer)
    content_w = max(display_width(strip_ansi(r)) for r in all_rows)
    if badge:
        content_w = max(content_w, display_width(title) + 2 + display_width(badge))
    inner = min(max_width, max(min_width, content_w + 2))
    top = dim("╭" + "─" * (inner + 2) + "╮")
    sep = dim("├" + "─" * (inner + 2) + "┤")
    bot = dim("╰" + "─" * (inner + 2) + "╯")
    print(top)
    if badge:
        title_line = title + " " * max(1, inner - display_width(title) - display_width(badge)) + badge
    else:
        title_line = pad_to(title, inner)
    print(box_row(title_line, inner))
    if rows:
        print(sep)
        for row in rows:
            print(box_row(pad_to(row, inner), inner))
    if footer:
        print(sep)
        for row in footer:
            print(box_row(pad_to(row, inner), inner))
    print(bot)
