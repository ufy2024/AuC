"""模型 HTTP 调用的有限次指数退避重试。

仅对可重试的瞬时错误（429 / 5xx / 连接超时）重试，并尊重 Retry-After。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger("auc.model.retry")

T = TypeVar("T")

# 仅重试瞬时/幂等安全的状态：连接超时(408)、Too Early(425)、限流(429)、5xx。
# 刻意排除 409 Conflict——它不是瞬时错误，对非幂等的 POST /chat/completions
# 重试会导致重复补全与重复计费。
_RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
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


_HTTP_STATUS_HINTS: dict[int, str] = {
    401: "鉴权失败，请检查 API Key",
    403: "访问被拒绝",
    404: "接口不存在，请检查 Base URL",
    408: "请求超时",
    429: "请求过于频繁，请稍后重试",
    500: "服务端内部错误",
    502: "网关错误",
    503: "服务不可用，请稍后重试或更换网关",
    504: "网关超时",
}


def format_model_http_error(exc: BaseException) -> str:
    """把 httpx / HTTP 异常转为用户可读短句（避免整段 URL + MDN 链接）。"""
    status = _status_of(exc)
    if status is None:
        return str(exc)
    hint = _HTTP_STATUS_HINTS.get(status, "")
    try:
        import httpx
    except ImportError:  # pragma: no cover
        return f"HTTP {status}" + (f"（{hint}）" if hint else "")
    if isinstance(exc, httpx.HTTPStatusError):
        detail = ""
        try:
            detail = (exc.response.text or "").strip()
            if detail:
                data = json.loads(detail)
                if isinstance(data, dict):
                    err = data.get("error")
                    if isinstance(err, dict) and err.get("message"):
                        detail = str(err["message"])
                    elif data.get("message"):
                        detail = str(data["message"])
        except Exception:  # noqa: BLE001
            detail = detail[:200] if detail else ""
        path = str(getattr(exc.request.url, "path", "") or exc.request.url)
        msg = f"HTTP {status}"
        if hint:
            msg += f"（{hint}）"
        if path:
            msg += f"：{path}"
        if detail and detail not in msg:
            msg += f" — {detail[:300]}"
        return msg
    return f"HTTP {status}" + (f"（{hint}）" if hint else "")


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
