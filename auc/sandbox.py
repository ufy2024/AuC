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
    """将 user_path 解析为必须位于 sandbox_root 下的绝对路径。"""
    root = Path(sandbox_root).resolve()
    target = (root / user_path).resolve() if not Path(user_path).is_absolute() else Path(user_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise SandboxViolationError(
            f"path {user_path!r} escapes sandbox {sandbox_root!r}"
        ) from exc
    return target


_AUC_META_MSG = "路径 .auc/ 为框架元数据，禁止通过 workspace API 访问"


def _norm_user_path(user_path: str) -> str:
    norm = Path(user_path).as_posix().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _is_auc_metadata(norm: str) -> bool:
    return norm == ".auc" or norm.startswith(".auc/")


def resolve_workspace_safe(sandbox_root: str, user_path: str) -> Path:
    """沙盒解析并拒绝 `.auc/` 框架元数据。

    对**用户原始路径**与 `.resolve()` 后的**真实路径**双重检查，
    防止经沙盒内符号链接（如 `evil -> .auc/settings.local.json`）绕过
    `.auc/` 保护，读写/删除框架密钥与元数据。
    """
    if _is_auc_metadata(_norm_user_path(user_path)):
        raise SandboxViolationError(_AUC_META_MSG)
    resolved = resolve_under_sandbox(sandbox_root, user_path)
    root = Path(sandbox_root).resolve()
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved
    if _is_auc_metadata(rel):
        raise SandboxViolationError(_AUC_META_MSG)
    return resolved


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
