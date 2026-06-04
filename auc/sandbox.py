from __future__ import annotations

from pathlib import Path


class SandboxViolationError(ValueError):
    pass


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
