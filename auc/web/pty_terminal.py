"""沙盒工作区 PTY 终端（WebSocket 桥接）。"""

from __future__ import annotations

import asyncio
import json
import os
import pty
import struct
import termios
import fcntl
from pathlib import Path
from typing import Any

from auc.sandbox import resolve_under_sandbox


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


async def bridge_pty_terminal(websocket: Any, sandbox_root: str) -> None:
    """在沙盒根目录启动交互式 shell，与 WebSocket 双向转发。"""
    cwd = str(resolve_under_sandbox(sandbox_root, "."))
    master_fd, slave_fd = pty.openpty()
    shell = os.environ.get("SHELL") or "/bin/bash"
    env = {
        **os.environ,
        "TERM": "xterm-256color",
        "COLORTERM": "truecolor",
        "PWD": cwd,
    }
    proc = await asyncio.create_subprocess_exec(
        shell,
        "-l",
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=cwd,
        env=env,
        preexec_fn=os.setsid,
        close_fds=True,
    )
    os.close(slave_fd)

    loop = asyncio.get_running_loop()
    closed = asyncio.Event()

    def _on_master_readable() -> None:
        if closed.is_set():
            return
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            closed.set()
            return
        if not data:
            closed.set()
            return
        asyncio.create_task(_send_bytes(websocket, data))

    async def _send_bytes(ws: Any, data: bytes) -> None:
        try:
            await ws.send_bytes(data)
        except Exception:  # noqa: BLE001
            closed.set()

    loop.add_reader(master_fd, _on_master_readable)

    async def _watch_proc() -> None:
        await proc.wait()
        closed.set()

    watch_task = asyncio.create_task(_watch_proc())

    try:
        while not closed.is_set():
            try:
                msg = await websocket.receive()
            except Exception:  # noqa: BLE001
                break
            if msg.get("type") == "websocket.disconnect":
                break
            raw = msg.get("bytes")
            if raw is not None:
                try:
                    os.write(master_fd, bytes(raw))
                except OSError:
                    break
                continue
            text = msg.get("text")
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                try:
                    os.write(master_fd, text.encode("utf-8"))
                except OSError:
                    break
                continue
            if payload.get("type") == "resize":
                cols = int(payload.get("cols") or 80)
                rows = int(payload.get("rows") or 24)
                _set_winsize(master_fd, max(rows, 1), max(cols, 1))
    finally:
        closed.set()
        loop.remove_reader(master_fd)
        watch_task.cancel()
        try:
            os.close(master_fd)
        except OSError:
            pass
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()


def terminal_available() -> bool:
    return hasattr(pty, "openpty") and Path("/bin/bash").exists()
