"""R4 检查点与回滚：写类工具执行前对受影响文件做内容寻址影子快照。

存储布局（沙盒内，框架特权 IO，不经工具面）：

    .auc/checkpoints/<run_id>/manifest.jsonl   # 每行一个 CheckpointEntry
    .auc/checkpoints/<run_id>/blobs/<sha1>     # zlib 压缩的文件内容
"""

from __future__ import annotations

import hashlib
import json
import shutil
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from auc.sandbox import resolve_under_sandbox

CheckpointOp = Literal["write", "delete", "shell"]


@dataclass
class CheckpointEntry:
    run_id: str
    step: int
    tool: str
    op: CheckpointOp
    path: str | None  # 相对沙盒根；shell 为 None
    blob: str | None  # sha1；新建文件（写前不存在）为 None
    command: str | None  # shell 命令文本
    ts: str


@dataclass
class RevertReport:
    run_id: str
    target_step: int
    restored: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class CheckpointStore:
    def __init__(self, sandbox_root: str) -> None:
        self._root = Path(sandbox_root).resolve()
        self._base = self._root / ".auc" / "checkpoints"

    def _run_dir(self, run_id: str) -> Path:
        return self._base / run_id

    def _manifest(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "manifest.jsonl"

    def _blob_path(self, run_id: str, sha1: str) -> Path:
        return self._run_dir(run_id) / "blobs" / sha1

    def _save_blob(self, run_id: str, data: bytes) -> str:
        sha1 = hashlib.sha1(data).hexdigest()
        path = self._blob_path(run_id, sha1)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(zlib.compress(data))
        return sha1

    def _load_blob(self, run_id: str, sha1: str) -> bytes | None:
        path = self._blob_path(run_id, sha1)
        if not path.exists():
            return None
        try:
            return zlib.decompress(path.read_bytes())
        except zlib.error:
            return None

    def _append(self, entry: CheckpointEntry) -> None:
        manifest = self._manifest(entry.run_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def snapshot(
        self,
        *,
        run_id: str,
        step: int,
        tool: str,
        arguments: dict[str, Any],
    ) -> list[CheckpointEntry]:
        """写类工具放行后、invoke 前调用。返回新增的 manifest 条目。"""
        ts = datetime.now(timezone.utc).isoformat()
        entries: list[CheckpointEntry] = []

        if tool == "run_command":
            entry = CheckpointEntry(
                run_id=run_id, step=step, tool=tool, op="shell",
                path=None, blob=None,
                command=str(arguments.get("command") or ""), ts=ts,
            )
            self._append(entry)
            return [entry]

        raw_path = arguments.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return []
        try:
            resolved = resolve_under_sandbox(str(self._root), raw_path)
        except ValueError:
            return []
        rel = resolved.relative_to(self._root).as_posix()
        op: CheckpointOp = "delete" if tool in ("delete_path", "delete_file") else "write"

        targets: list[Path] = []
        if resolved.is_dir():
            targets = [p for p in resolved.rglob("*") if p.is_file()]
        elif resolved.exists():
            targets = [resolved]

        if not targets:
            # 新建文件：记 blob=None，回滚 = 删除
            entry = CheckpointEntry(
                run_id=run_id, step=step, tool=tool, op=op,
                path=rel, blob=None, command=None, ts=ts,
            )
            self._append(entry)
            return [entry]

        for target in targets:
            try:
                data = target.read_bytes()
            except OSError:
                continue
            sha1 = self._save_blob(run_id, data)
            entry = CheckpointEntry(
                run_id=run_id, step=step, tool=tool, op=op,
                path=target.relative_to(self._root).as_posix(),
                blob=sha1, command=None, ts=ts,
            )
            self._append(entry)
            entries.append(entry)
        return entries

    def list_entries(self, run_id: str) -> list[CheckpointEntry]:
        manifest = self._manifest(run_id)
        if not manifest.exists():
            return []
        out: list[CheckpointEntry] = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(CheckpointEntry(**json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                continue
        return out

    def list_runs(self) -> list[str]:
        if not self._base.exists():
            return []
        runs = [p for p in self._base.iterdir() if p.is_dir()]
        runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.name for p in runs]

    def revert_to(self, run_id: str, step: int) -> RevertReport:
        """回滚到 `step` 之前的状态：逆序回放 manifest 中 step >= 目标 的条目。"""
        report = RevertReport(run_id=run_id, target_step=step)
        entries = [e for e in self.list_entries(run_id) if e.step >= step]
        for entry in reversed(entries):
            if entry.op == "shell":
                report.warnings.append(
                    f"step {entry.step} 含 shell 命令（{(entry.command or '')[:80]}），"
                    "文件级回滚可能不完整"
                )
                continue
            if not entry.path:
                continue
            target = self._root / entry.path
            if entry.blob is None:
                # 写前不存在 → 回滚 = 删除
                if target.exists():
                    if target.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                    report.deleted.append(entry.path)
                continue
            data = self._load_blob(run_id, entry.blob)
            if data is None:
                report.warnings.append(f"blob 损坏或缺失，跳过 {entry.path}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            report.restored.append(entry.path)
        return report

    def gc(self, keep_steps: int = 200) -> int:
        """每 run 仅保留最近 keep_steps 步；返回清理的条目数。"""
        removed = 0
        for run_id in self.list_runs():
            entries = self.list_entries(run_id)
            steps = sorted({e.step for e in entries})
            if len(steps) <= keep_steps:
                continue
            cutoff = steps[-keep_steps]
            kept = [e for e in entries if e.step >= cutoff]
            removed += len(entries) - len(kept)
            manifest = self._manifest(run_id)
            with manifest.open("w", encoding="utf-8") as f:
                for e in kept:
                    f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
            live = {e.blob for e in kept if e.blob}
            blob_dir = self._run_dir(run_id) / "blobs"
            if blob_dir.exists():
                for blob in blob_dir.iterdir():
                    if blob.name not in live:
                        blob.unlink(missing_ok=True)
        return removed
