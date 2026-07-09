"""R8 Git 专用工具：在沙盒内包装常用 git 子命令。

权限分层（沿用 ADR-006 裁决链）：
  - 只读类（status/diff/log）→ L1
  - 改本地仓库状态（add/commit）→ L2 + mutates_state
  - 推送远端（push）→ L3，必过审批

所有参数经 `shlex.quote` 转义后拼接，避免命令注入；执行复用 `run_shell_command`
（环境变量白名单、超时杀进程组、输出截断）。
"""

from __future__ import annotations

import re
import shlex
from typing import Any

from auc.sandbox import SandboxViolationError, resolve_under_sandbox
from auc.tools.base import ToolPolicy, tool_from_function
from auc.tools.shell import run_shell_command

_GIT_TIMEOUT = 60.0
_GIT_MAX_TIMEOUT = 180.0

# 远端名/分支/ref 的保守白名单：字母数字与 . _ / - @ +，不得以 '-' 开头
#（否则会被 git 当成选项，如 remote="--exec=..." 造成参数注入）。
_REF_RE = re.compile(r"^[A-Za-z0-9._/@+][A-Za-z0-9._/@+-]*$")


def _validate_ref(value: str, *, what: str) -> str:
    v = value.strip()
    if not v:
        raise ValueError(f"{what} 不能为空")
    if v.startswith("-") or not _REF_RE.match(v):
        raise ValueError(f"非法 {what}: {value!r}（禁止以 '-' 开头或含特殊字符）")
    return v


def _validate_git_path(sandbox_root: str, cwd: str, path: str) -> str:
    """校验 git 路径参数在沙盒内。路径相对 cwd（已在沙盒内）解析。"""
    p = path.strip()
    if not p:
        raise ValueError("path 不能为空")
    if p.startswith("-"):
        raise ValueError(f"非法 path: {path!r}（禁止以 '-' 开头）")
    base = (cwd or ".").rstrip("/") or "."
    rel = p if base == "." else f"{base}/{p}"
    # 越界（含 `..`/绝对路径）时 resolve_under_sandbox 抛 SandboxViolationError
    resolve_under_sandbox(sandbox_root, rel)
    return p


async def _run_git(
    sandbox_root: str,
    args: list[str],
    *,
    cwd: str = ".",
    timeout: float = _GIT_TIMEOUT,
) -> str:
    command = "git " + " ".join(shlex.quote(a) for a in args)
    result = await run_shell_command(
        sandbox_root,
        command,
        cwd=cwd or ".",
        timeout=timeout,
        max_timeout=_GIT_MAX_TIMEOUT,
    )
    body = result.stdout.strip()
    err = result.stderr.strip()
    if result.timed_out:
        raise ValueError(f"git {args[0]} 超时")
    if result.exit_code != 0:
        detail = "\n".join(p for p in (body, err) if p) or f"exit {result.exit_code}"
        raise ValueError(f"git {args[0]} 失败 (exit {result.exit_code}):\n{detail}")
    out = "\n".join(p for p in (body, err) if p)
    return out or f"(git {args[0]} 无输出)"


def make_git_tools(sandbox: str) -> list[tuple[Any, ToolPolicy]]:
    async def git_status(cwd: str = ".") -> str:
        """显示工作区状态（精简格式 + 分支信息）。"""
        return await _run_git(sandbox, ["status", "--short", "--branch"], cwd=cwd)

    async def git_diff(path: str = "", staged: bool = False, cwd: str = ".") -> str:
        """显示改动 diff；staged=true 看已暂存改动，path 可限定文件/目录。"""
        args = ["--no-pager", "diff"]
        if staged:
            args.append("--cached")
        if path.strip():
            safe = _validate_git_path(sandbox, cwd, path)
            args.extend(["--", safe])
        return await _run_git(sandbox, args, cwd=cwd)

    async def git_log(max_count: int = 10, cwd: str = ".") -> str:
        """显示最近提交历史（单行格式）。"""
        n = max(1, min(int(max_count or 10), 100))
        return await _run_git(
            sandbox,
            ["--no-pager", "log", f"-{n}", "--oneline", "--decorate"],
            cwd=cwd,
        )

    async def git_add(paths: str = ".", cwd: str = ".") -> str:
        """暂存改动；paths 为空格分隔的路径列表，默认暂存全部（'.')。"""
        raw = shlex.split(paths) if paths.strip() else ["."]
        targets = [_validate_git_path(sandbox, cwd, t) for t in raw]
        await _run_git(sandbox, ["add", "--", *targets], cwd=cwd)
        return await _run_git(sandbox, ["status", "--short"], cwd=cwd)

    async def git_commit(message: str, add_all: bool = False, cwd: str = ".") -> str:
        """提交已暂存改动；add_all=true 先暂存全部已跟踪文件的改动。"""
        if not message.strip():
            raise ValueError("commit message 不能为空")
        args = ["commit", "-m", message]
        if add_all:
            args.insert(1, "-a")
        return await _run_git(sandbox, args, cwd=cwd)

    async def git_push(remote: str = "origin", branch: str = "", cwd: str = ".") -> str:
        """推送到远端（L3，需授权）。branch 留空则推当前分支。"""
        args = ["push", _validate_ref(remote, what="remote")]
        if branch.strip():
            args.append(_validate_ref(branch, what="branch"))
        return await _run_git(sandbox, args, cwd=cwd, timeout=_GIT_MAX_TIMEOUT)

    return [
        tool_from_function(
            git_status,
            name="git_status",
            description="显示 git 工作区状态（git status -sb）。",
            privilege="L1",
        ),
        tool_from_function(
            git_diff,
            name="git_diff",
            description=(
                "显示 git 改动 diff。staged=true 查看已暂存改动；"
                "path 可限定到某文件/目录。"
            ),
            privilege="L1",
        ),
        tool_from_function(
            git_log,
            name="git_log",
            description="显示最近提交历史（oneline，max_count 默认 10、上限 100）。",
            privilege="L1",
        ),
        tool_from_function(
            git_add,
            name="git_add",
            description="暂存改动（git add）；paths 空格分隔，默认 '.' 暂存全部。",
            privilege="L2",
            mutates_state=True,
        ),
        tool_from_function(
            git_commit,
            name="git_commit",
            description=(
                "提交已暂存改动（git commit -m）。add_all=true 时先 -a 暂存"
                "已跟踪文件的改动。"
            ),
            privilege="L2",
            mutates_state=True,
        ),
        tool_from_function(
            git_push,
            name="git_push",
            description="推送到远端（git push，L3 需用户授权）。",
            privilege="L3",
            mutates_state=True,
        ),
    ]
