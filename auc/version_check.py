"""查询 PyPI 最新版本，用于 CLI / Web 更新提示。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from auc import __version__

PYPI_PACKAGE = "ufy-auc"
PYPI_JSON_URL = f"https://pypi.org/pypi/{PYPI_PACKAGE}/json"
_CACHE_TTL_SEC = 3600.0

_cache_at = 0.0
_cache_latest: str | None = None


def parse_version(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.strip().lstrip("v").split("."):
        head = piece.split("-", 1)[0]
        try:
            parts.append(int(head))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def fetch_latest_version(*, timeout: float = 3.0, force: bool = False) -> str | None:
    global _cache_at, _cache_latest
    now = time.monotonic()
    if not force and _cache_latest and now - _cache_at < _CACHE_TTL_SEC:
        return _cache_latest
    try:
        req = urllib.request.Request(
            PYPI_JSON_URL,
            headers={
                "Accept": "application/json",
                "User-Agent": f"{PYPI_PACKAGE}/{__version__} version-check",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest = data.get("info", {}).get("version")
        if isinstance(latest, str) and latest.strip():
            _cache_latest = latest.strip()
            _cache_at = now
            return _cache_latest
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
        pass
    return _cache_latest


def release_info(*, timeout: float = 3.0) -> dict[str, object]:
    current = __version__
    latest = fetch_latest_version(timeout=timeout)
    available = bool(latest and is_newer(latest, current))
    return {
        "package": PYPI_PACKAGE,
        "current_version": current,
        "latest_version": latest,
        "update_available": available,
        "pypi_url": f"https://pypi.org/project/{PYPI_PACKAGE}/",
        "install_cmd": f"pip install -U {PYPI_PACKAGE}",
    }


def print_update_notice(*, timeout: float = 2.0) -> None:
    info = release_info(timeout=timeout)
    if not info.get("update_available"):
        return
    from auc.terminal import yellow

    latest = info.get("latest_version")
    current = info.get("current_version")
    cmd = info.get("install_cmd")
    print(
        yellow(f"新版 {latest} 可用（当前 {current}）· 运行: {cmd}"),
        flush=True,
    )
