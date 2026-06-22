"""受控外链抓取（L3 授权）。"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse

from auc.sandbox import resolve_under_sandbox
from auc.tools.base import ToolPolicy, tool_from_function

_MAX_BYTES = 512_000
_TIMEOUT_SEC = 20.0
_USER_AGENT = "AuC-agent/1.0 (+local-sandbox)"
_MAX_REDIRECTS = 8

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "metadata.google",
    }
)


def _require_httpx() -> Any:
    try:
        import httpx
    except ImportError as exc:
        from auc.extras import hint_for

        raise ImportError(hint_for("web", "llm", "all")) from exc
    return httpx


def _ip_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _hostname_blocked(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h in _BLOCKED_HOSTNAMES:
        return True
    if h.endswith(".local") or h.endswith(".internal"):
        return True
    try:
        return _ip_blocked(ipaddress.ip_address(h))
    except ValueError:
        return False


def _resolve_host_ips(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"无法解析主机: {host}") from exc
    ips: list[str] = []
    for info in infos:
        ip = info[4][0]
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise ValueError(f"无法解析主机: {host}")
    return ips


def _host_blocked(host: str) -> bool:
    if _hostname_blocked(host):
        return True
    try:
        ips = _resolve_host_ips(host)
    except ValueError:
        # DNS 不可用时仅依赖主机名规则（公网域名由连接阶段再失败）
        return False
    for ip in ips:
        try:
            if _ip_blocked(ipaddress.ip_address(ip)):
                return True
        except ValueError:
            return True
    return False


def validate_fetch_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("url 不能为空")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("仅允许 http/https 链接")
    if not parsed.hostname:
        raise ValueError("无效的 URL")
    if _host_blocked(parsed.hostname):
        raise ValueError(f"禁止访问内网/本机地址: {parsed.hostname}")
    return raw


def _assert_request_url_allowed(url: str) -> None:
    host = urlparse(url).hostname
    if not host or _host_blocked(host):
        raise ValueError(f"禁止访问内网/本机地址: {host or url}")


def _html_to_text(html: str) -> str:
    text = _HTML_TAG_RE.sub(" ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_fetch_tool(sandbox_root: str) -> list[tuple[Any, ToolPolicy]]:
    httpx = _require_httpx()

    async def fetch_url(url: str, save_path: str = "") -> str:
        """
        抓取外部 http(s) 链接内容（需用户授权）。
        url: 目标链接；save_path: 可选，保存到沙盒内相对路径。
        """
        safe_url = validate_fetch_url(url)

        async def _guard_request(request: httpx.Request) -> None:  # type: ignore[name-defined]
            _assert_request_url_allowed(str(request.url))

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=_TIMEOUT_SEC,
            headers={"User-Agent": _USER_AGENT},
            event_hooks={"request": [_guard_request]},
            max_redirects=_MAX_REDIRECTS,
        ) as client:
            resp = await client.get(safe_url)
            final_host = urlparse(str(resp.url)).hostname or ""
            if _host_blocked(final_host):
                raise ValueError(f"重定向目标被禁止: {final_host}")
            if resp.status_code >= 400:
                raise ValueError(f"HTTP {resp.status_code}")
            body = resp.content[:_MAX_BYTES]
            ctype = (resp.headers.get("content-type") or "").lower()
            if "html" in ctype:
                text = _html_to_text(body.decode(resp.encoding or "utf-8", errors="replace"))
            else:
                text = body.decode(resp.encoding or "utf-8", errors="replace")
            if len(resp.content) > _MAX_BYTES:
                text += "\n\n… (内容已截断)"
            header = (
                f"URL: {resp.url}\n"
                f"Status: {resp.status_code}\n"
                f"Content-Type: {ctype or 'unknown'}\n"
                f"Length: {len(body)} bytes\n\n"
            )
            if save_path and save_path.strip():
                dest = resolve_under_sandbox(sandbox_root, save_path.strip())
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                header += f"已保存到沙盒: {save_path.strip()}\n\n"
            return header + text

    tool, pol = tool_from_function(
        fetch_url,
        name="fetch_url",
        description=(
            "抓取外部 http(s) 网页/文本内容（L3：需用户授权后才会请求）。"
            "参数 url 必填；save_path 可选，将正文写入沙盒文件。"
            "无法访问内网/本机地址。"
        ),
        privilege="L3",
    )
    pol.sandbox_only = False
    return [(tool, pol)]
