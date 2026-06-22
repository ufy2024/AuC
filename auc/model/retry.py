"""模型 HTTP 调用的有限次指数退避重试。

仅对可重试的瞬时错误（429 / 5xx / 连接超时）重试，并尊重 Retry-After。
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger("auc.model.retry")

T = TypeVar("T")

_RETRY_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 0.5
DEFAULT_MAX_DELAY = 8.0


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _is_retryable_exception(exc: BaseException) -> bool:
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return False
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            httpx.PoolTimeout,
            httpx.RemoteProtocolError,
        ),
    )


def _status_of(exc: BaseException) -> int | None:
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return None
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    return None


def _retry_after_of(exc: BaseException) -> float | None:
    status = _status_of(exc)
    if status is None:
        return None
    try:
        import httpx  # noqa: F401
    except ImportError:  # pragma: no cover
        return None
    resp = getattr(exc, "response", None)
    if resp is None:
        return None
    return _parse_retry_after(resp.headers.get("retry-after"))


def _backoff_delay(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        return min(retry_after, DEFAULT_MAX_DELAY)
    base = DEFAULT_BASE_DELAY * (2 ** (attempt - 1))
    return min(base, DEFAULT_MAX_DELAY) + random.uniform(0, 0.25)


async def with_retry(
    func: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    label: str = "model",
) -> T:
    """执行 async func，对瞬时网络/服务端错误做有限次退避重试。"""
    last_exc: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await func()
        except Exception as exc:  # noqa: BLE001
            status = _status_of(exc)
            retryable = _is_retryable_exception(exc) or (
                status is not None and status in _RETRY_STATUS
            )
            if not retryable or attempt >= max_attempts:
                raise
            last_exc = exc
            delay = _backoff_delay(attempt, _retry_after_of(exc))
            logger.warning(
                "%s request failed (attempt %d/%d, status=%s): %s; retrying in %.2fs",
                label,
                attempt,
                max_attempts,
                status,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    if last_exc is not None:  # pragma: no cover - defensive
        raise last_exc
    raise RuntimeError("with_retry exhausted without result")


def make_timeout(timeout: float) -> Any:
    """细分连接/读/写/连接池超时，避免单一 float 把慢响应卡死。"""
    import httpx

    return httpx.Timeout(
        timeout,
        connect=min(10.0, timeout),
        read=timeout,
        write=min(30.0, timeout),
        pool=min(10.0, timeout),
    )
