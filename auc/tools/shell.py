"""R1 Shell 执行工具：沙盒内执行命令，输出截断、超时杀进程组、环境变量白名单。"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import time
from dataclasses import asdict, dataclass

from auc.messages import ToolResult
from auc.sandbox import resolve_under_sandbox
from auc.tools.base import FunctionTool, ToolPolicy

ENV_WHITELIST = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "PYTHONPATH", "VIRTUAL_ENV")


@dataclass
class ShellResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool
    timed_out: bool


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """先杀进程组（防孤儿），失败则直接杀子进程。"""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except (ProcessLookupError, PermissionError, OSError):
        # 受限环境（如 seccomp 沙盒）可能禁止发信号；
        # 调用方对二次 communicate 设置了宽限超时，不会无限等待。
        pass


def scrub_env() -> dict[str, str]:
    """仅透传白名单环境变量，剥除 *_API_KEY / TOKEN / SECRET 等敏感项。"""
    return {k: v for k, v in os.environ.items() if k in ENV_WHITELIST}


def truncate_output(data: bytes, head_bytes: int, tail_bytes: int) -> tuple[str, bool]:
    if len(data) <= head_bytes + tail_bytes:
        return data.decode("utf-8", errors="replace"), False
    omitted = len(data) - head_bytes - tail_bytes
    head = data[:head_bytes].decode("utf-8", errors="replace")
    tail = data[-tail_bytes:].decode("utf-8", errors="replace")
    return f"{head}\n…(truncated {omitted} bytes)…\n{tail}", True


async def run_shell_command(
    sandbox_root: str,
    command: str,
    *,
    cwd: str = ".",
    timeout: float = 120.0,
    max_timeout: float = 600.0,
    head_bytes: int = 8192,
    tail_bytes: int = 8192,
) -> ShellResult:
    resolved_cwd = resolve_under_sandbox(sandbox_root, cwd or ".")
    if not resolved_cwd.is_dir():
        raise ValueError(f"cwd 不是目录: {cwd}")
    timeout = min(max(float(timeout), 1.0), max_timeout)

    start = time.monotonic()
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(resolved_cwd),
        env=scrub_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        timed_out = True
        _kill_process_tree(proc)
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), 5.0)
        except asyncio.TimeoutError:
            stdout_b, stderr_b = b"", b""
    duration_ms = int((time.monotonic() - start) * 1000)

    stdout, t1 = truncate_output(stdout_b or b"", head_bytes, tail_bytes)
    stderr, t2 = truncate_output(stderr_b or b"", head_bytes, tail_bytes)
    exit_code = proc.returncode if proc.returncode is not None else -1
    return ShellResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        truncated=t1 or t2,
        timed_out=timed_out,
    )


def make_shell_tool(
    sandbox_root: str,
    *,
    default_timeout: float = 120.0,
    max_timeout: float = 600.0,
    head_bytes: int = 8192,
    tail_bytes: int = 8192,
) -> tuple[FunctionTool, ToolPolicy]:
    """注册名 run_command；L2 + mutates_state（不设 mutates_files，检查点仅记命令文本）。"""

    class _ShellTool(FunctionTool):
        async def invoke(self, arguments: dict) -> ToolResult:  # type: ignore[override]
            command = arguments.get("command", "")
            if not isinstance(command, str) or not command.strip():
                return ToolResult(
                    tool_call_id="", name=self._name,
                    content="command 不能为空", is_error=True,
                )
            try:
                result = await run_shell_command(
                    sandbox_root,
                    command,
                    cwd=str(arguments.get("cwd") or "."),
                    timeout=float(arguments.get("timeout") or default_timeout),
                    max_timeout=max_timeout,
                    head_bytes=head_bytes,
                    tail_bytes=tail_bytes,
                )
            except Exception as exc:  # noqa: BLE001
                return ToolResult(
                    tool_call_id="", name=self._name,
                    content=str(exc), is_error=True,
                )
            return ToolResult(
                tool_call_id="",
                name=self._name,
                content=json.dumps(asdict(result), ensure_ascii=False),
                is_error=result.exit_code != 0 or result.timed_out,
            )

    tool = _ShellTool(
        _name="run_command",
        _description=(
            "Run a shell command inside the sandbox (tests/build/git etc). "
            "No state persists across calls; chain with `cd dir && cmd` when needed. "
            f"Default timeout {int(default_timeout)}s, max {int(max_timeout)}s."
        ),
        _fn=lambda: None,
        _parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 shell 命令"},
                "cwd": {
                    "type": "string",
                    "description": "相对沙盒根的工作目录，默认 '.'",
                },
                "timeout": {
                    "type": "number",
                    "description": "秒，默认 120，上限 600",
                },
            },
            "required": ["command"],
        },
    )
    policy = ToolPolicy(
        name="run_command",
        privilege="L2",
        sandbox_only=True,
        mutates_state=True,
    )
    return tool, policy
