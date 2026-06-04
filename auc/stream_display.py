from __future__ import annotations

import sys

from auc.events.bus import RunEvent


class ChatStreamPrinter:
    """DeepSeek 式流式输出：逐字打印，工具调用单独提示。"""

    def __init__(self, *, show_tools: bool = True) -> None:
        self._in_reply = False
        self._show_tools = show_tools

    def feed(self, ev: RunEvent) -> None:
        if ev.type == "model_delta":
            delta = ev.payload.get("delta")
            if delta:
                if not self._in_reply:
                    sys.stdout.write("\n")
                    self._in_reply = True
                sys.stdout.write(delta)
                sys.stdout.flush()
            elif self._show_tools and ev.payload.get("tool_calls"):
                self.finish_line()
                names = ", ".join(
                    t.get("name", "?") for t in ev.payload["tool_calls"]
                )
                sys.stdout.write(f"\n▸ 调用工具: {names}\n")
                sys.stdout.flush()
        elif ev.type == "tool_start" and self._show_tools:
            self.finish_line()
            tool = ev.payload.get("tool", "tool")
            sys.stdout.write(f"\n▸ {tool} …\n")
            sys.stdout.flush()
        elif ev.type == "run_end":
            self.finish_line()

    def finish_line(self) -> None:
        if self._in_reply:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._in_reply = False
