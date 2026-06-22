"""AuC Web 访问控制：非本机绑定须携带 token。"""

from __future__ import annotations

import os
import secrets
from typing import Any

_PUBLIC_BIND_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})


def is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "[::1]")


def is_public_bind(host: str) -> bool:
    return not is_loopback_host(host) or host.strip() in _PUBLIC_BIND_HOSTS


def resolve_web_token(cli_token: str | None = None) -> str | None:
    raw = (cli_token or os.environ.get("AUC_WEB_TOKEN") or "").strip()
    return raw or None


def require_web_token(host: str, cli_token: str | None = None) -> str | None:
    """本机绑定可无 token；监听非本机或 0.0.0.0 时必须提供 token。"""
    token = resolve_web_token(cli_token)
    if is_public_bind(host) and not token:
        raise SystemExit(
            "绑定非本机地址（如 0.0.0.0）时必须设置 --token 或环境变量 AUC_WEB_TOKEN"
        )
    return token


def extract_request_token(headers: Any) -> str | None:
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    for key in ("x-auc-token", "X-AuC-Token"):
        val = headers.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def token_ok(expected: str | None, provided: str | None) -> bool:
    if not expected:
        return True
    if not provided:
        return False
    return secrets.compare_digest(expected, provided)
