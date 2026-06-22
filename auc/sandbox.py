from __future__ import annotations

from pathlib import Path

# 单文件读取/嵌入的默认上限（字节），防止上下文爆炸 / DoS
DEFAULT_MAX_READ_BYTES = 2_000_000


class SandboxViolationError(ValueError):
    pass


def assert_not_hardlink_escape(path: Path, sandbox_root: str) -> None:
    """拒绝多硬链接的常规文件，避免经沙盒内硬链接读到沙盒外同 inode 内容。

    符号链接已由 resolve() 处理；此处针对硬链接：常规文件 st_nlink>1 时，
    无法廉价地证明所有链接都在沙盒内，故保守拒绝。
    """
    try:
        st = path.lstat()
    except OSError:
        return
    if not path.is_file():
        return
    if getattr(st, "st_nlink", 1) > 1:
        raise SandboxViolationError(
            f"path {str(path)!r} is a multi-link file (potential hardlink escape)"
        )


def assert_within_size_limit(path: Path, max_bytes: int = DEFAULT_MAX_READ_BYTES) -> None:
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > max_bytes:
        raise SandboxViolationError(
            f"file too large: {size} bytes exceeds limit {max_bytes}"
        )


def resolve_under_sandbox(sandbox_root: str, user_path: str) -> Path:
    """Resolve user_path to an absolute path that must stay under sandbox_root."""
    root = Path(sandbox_root).resolve()
    target = (root / user_path).resolve() if not Path(user_path).is_absolute() else Path(user_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SandboxViolationError(
            f"path {user_path!r} escapes sandbox {sandbox_root!r}"
        ) from exc
    return target


def validate_path_argument(
    sandbox_root: str | None,
    arguments: dict[str, object],
    *,
    path_keys: tuple[str, ...] = ("path", "file", "filepath"),
) -> None:
    if not sandbox_root:
        return
    for key in path_keys:
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            resolve_under_sandbox(sandbox_root, val)
