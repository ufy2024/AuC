from __future__ import annotations

import asyncio
import os
import socket
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from auc.sandbox import resolve_under_sandbox
from auc.web.projects import ProjectInfo

RunStatus = Literal["running", "stopped", "error"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_open(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


async def _read_process_error(proc: asyncio.subprocess.Process) -> str:
    if proc.stderr is None:
        return ""
    try:
        data = await asyncio.wait_for(proc.stderr.read(8192), timeout=0.5)
    except TimeoutError:
        return ""
    return data.decode(errors="replace").strip()


async def _wait_for_ready(
    proc: asyncio.subprocess.Process,
    port: int,
    *,
    timeout: float = 20.0,
) -> str | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if proc.returncode is not None:
            err = await _read_process_error(proc)
            return err or f"进程已退出 (code {proc.returncode})"
        if _port_open(port):
            await asyncio.sleep(0.15)
            return None
        await asyncio.sleep(0.25)
    return "服务启动超时，请检查项目依赖与日志"


@dataclass
class RunInstance:
    run_id: str
    project_id: str
    kind: str
    port: int | None
    status: RunStatus
    url: str | None
    error: str | None = None
    process: asyncio.subprocess.Process | None = field(default=None, repr=False)


class ProjectRunner:
    """在沙盒内启动项目（静态服务 / npm / python）。"""

    def __init__(self, sandbox_root: str) -> None:
        self._sandbox = str(Path(sandbox_root).resolve())
        self._runs: dict[str, RunInstance] = {}
        self._by_project: dict[str, str] = {}

    def list_runs(self) -> list[RunInstance]:
        return list(self._runs.values())

    def get(self, run_id: str) -> RunInstance | None:
        return self._runs.get(run_id)

    def get_by_project(self, project_id: str) -> RunInstance | None:
        rid = self._by_project.get(project_id)
        return self._runs.get(rid) if rid else None

    def get_active_backend(self) -> RunInstance | None:
        """返回当前运行中的 API 服务（python/node），供沙盒 API 转发使用。"""
        candidates = [
            inst
            for inst in self._runs.values()
            if inst.status == "running"
            and inst.port is not None
            and inst.kind in ("python", "node")
        ]
        if not candidates:
            return None
        return candidates[-1]

    async def start(self, project: ProjectInfo) -> RunInstance:
        existing = self.get_by_project(project.id)
        if existing and existing.status == "running":
            return existing

        if project.kind == "html" or project.entry.endswith(".html"):
            run_id = str(uuid.uuid4())
            url = f"/preview/{project.entry}"
            inst = RunInstance(
                run_id=run_id,
                project_id=project.id,
                kind="preview",
                port=None,
                status="running",
                url=url,
            )
            self._runs[run_id] = inst
            self._by_project[project.id] = run_id
            return inst

        workdir = resolve_under_sandbox(self._sandbox, project.path)
        if not workdir.is_dir():
            workdir = resolve_under_sandbox(self._sandbox, project.path).parent

        port = _free_port()
        env = {
            **os.environ,
            "PORT": str(port),
            "HOST": "127.0.0.1",
            "HOSTNAME": "127.0.0.1",
        }

        if project.kind == "node" and project.run_command:
            script = project.entry
            cmd = [
                "npm",
                "run",
                script,
                "--",
                "--port",
                str(port),
                "--host",
                "127.0.0.1",
            ]
        elif project.kind == "python" and project.entry.endswith(".py"):
            entry_path = Path(project.entry)
            module = entry_path.stem
            if entry_path.parent and str(entry_path.parent) not in ("", "."):
                workdir = resolve_under_sandbox(self._sandbox, str(entry_path.parent))
            cmd = [
                "python",
                "-m",
                "uvicorn",
                f"{module}:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
        elif project.kind == "python" and project.run_command:
            cmd = project.run_command.split()
        else:
            cmd = ["python", "-m", "http.server", str(port), "--bind", "127.0.0.1"]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(workdir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            run_id = str(uuid.uuid4())
            inst = RunInstance(
                run_id=run_id,
                project_id=project.id,
                kind=project.kind,
                port=port,
                status="error",
                url=None,
                error=str(exc),
            )
            self._runs[run_id] = inst
            return inst

        ready_err = await _wait_for_ready(proc, port)
        if ready_err:
            run_id = str(uuid.uuid4())
            inst = RunInstance(
                run_id=run_id,
                project_id=project.id,
                kind=project.kind,
                port=port,
                status="error",
                url=None,
                error=ready_err,
                process=proc,
            )
            self._runs[run_id] = inst
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
            return inst

        run_id = str(uuid.uuid4())
        url = f"/proxy/{run_id}/"
        inst = RunInstance(
            run_id=run_id,
            project_id=project.id,
            kind=project.kind,
            port=port,
            status="running",
            url=url,
            process=proc,
        )
        self._runs[run_id] = inst
        self._by_project[project.id] = run_id
        return inst

    async def stop(self, run_id: str) -> bool:
        inst = self._runs.get(run_id)
        if inst is None:
            return False
        if inst.process is not None and inst.process.returncode is None:
            try:
                inst.process.terminate()
            except (ProcessLookupError, PermissionError):
                pass
            else:
                try:
                    await asyncio.wait_for(inst.process.wait(), timeout=3.0)
                except TimeoutError:
                    try:
                        inst.process.kill()
                    except (ProcessLookupError, PermissionError):
                        pass
                    else:
                        await inst.process.wait()
        inst.status = "stopped"
        self._by_project.pop(inst.project_id, None)
        return True

    async def stop_all(self) -> None:
        for run_id in list(self._runs):
            await self.stop(run_id)

    def run_to_dict(self, inst: RunInstance) -> dict:
        return {
            "run_id": inst.run_id,
            "project_id": inst.project_id,
            "kind": inst.kind,
            "port": inst.port,
            "status": inst.status,
            "url": inst.url,
            "error": inst.error,
        }
