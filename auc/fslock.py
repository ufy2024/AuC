"""跨进程文件锁与原子写工具（纯标准库，零新增依赖）。

用于多 worker / 并发写同一 `.auc/` 文件的临界区保护：
  - `file_lock(path)`：基于 `fcntl.flock` 的建议锁（POSIX）；无 fcntl 的平台
    退化为无锁上下文（不阻断功能，仅失去跨进程互斥）。
  - `atomic_write_text(path, text)`：写临时文件后 `os.replace` 原子替换，
    避免并发/崩溃读到半截内容。
"""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl  # type: ignore[import]
except ImportError:  # pragma: no cover - 非 POSIX 平台
    fcntl = None  # type: ignore[assignment]


@contextmanager
def file_lock(lock_path: str | Path) -> Iterator[None]:
    """获取以 `lock_path` 为对象的独占建议锁；退出时释放。

    锁文件独立于数据文件（`<path>.lock`），避免与 `os.replace` 原子替换冲突
    （替换会更换 inode，持有数据文件 fd 的锁会失效）。
    """
    p = Path(lock_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if fcntl is None:  # pragma: no cover
        yield
        return
    fd = os.open(str(p), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def atomic_write_text(path: str | Path, text: str) -> None:
    """写临时文件后 os.replace 原子替换，避免并发/崩溃损坏文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, p)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
