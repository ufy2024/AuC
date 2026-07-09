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
        # 预校验阶段 DNS 不可用时仅依赖主机名规则；真正的 fail-closed 与 IP 绑定
        # 在连接阶段由 _GuardedBackend 强制执行（见 make_fetch_tool），从而既不误
        # 拦公网域名，又能堵住 DNS-rebinding TOCTOU。
        return False
    for ip in ips:
        try:
            if _ip_blocked(ipaddress.ip_address(ip)):
                return True
        except ValueError:
            return True
    return False


def _validated_connect_ip(host: str) -> str:
    """连接期解析并校验主机，返回可安全连接的 IP（fail-closed）。

    - DNS 解析失败 → 抛错（拒绝，而非放行）；
    - 任一解析 IP 命中内网/环回/保留段 → 拒绝（防混合应答 rebinding）；
    - 字面 IP 直接校验。
    返回首个（已确保全部通过校验的）IP，供 socket 连接**绑定**，杜绝校验后重解析
    到内网的 TOCTOU。
    """
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        raise ValueError("无效的主机")
    # 字面 IP
    try:
        addr = ipaddress.ip_address(h)
    except ValueError:
        addr = None
    if addr is not None:
        if _ip_blocked(addr):
            raise ValueError(f"禁止连接内网/本机地址: {host}")
        return h
    if _hostname_blocked(h):
        raise ValueError(f"禁止连接内网/本机地址: {host}")
    ips = _resolve_host_ips(h)  # DNS 失败在此抛错 → fail-closed
    for ip in ips:
        try:
            blocked = _ip_blocked(ipaddress.ip_address(ip))
        except ValueError:
            blocked = True  # 无法解析的地址一律拒绝
        if blocked:
            raise ValueError(f"禁止连接内网/本机地址: {host} → {ip}")
    return ips[0]


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


def _make_guarded_transport(httpx: Any) -> Any:
    """构造在**连接期**做 SSRF 绑定的 httpx 传输层。

    复用 httpx 默认传输的 TLS/连接池配置，仅替换其底层网络后端：连接前解析并校验
    目标主机、把 socket **钉定**到已校验 IP（origin 主机名保持不变，故 Host 头 /
    SNI / 证书校验 / 重定向语义均不受影响）。
    """
    import httpcore

    inner_transport = httpx.AsyncHTTPTransport()
    pool = inner_transport._pool
    real_backend = pool._network_backend

    class _GuardedBackend(httpcore.AsyncNetworkBackend):
        async def connect_tcp(
            self,
            host: str,
            port: int,
            timeout: float | None = None,
            local_address: str | None = None,
            socket_options: Any = None,
        ) -> Any:
            # host 为 origin 主机名/字面 IP；解析+校验后连接到已校验 IP。
            pinned = _validated_connect_ip(host)
            return await real_backend.connect_tcp(
                pinned,
                port,
                timeout=timeout,
                local_address=local_address,
                socket_options=socket_options,
            )

        async def connect_unix_socket(
            self, path: str, timeout: float | None = None, socket_options: Any = None
        ) -> Any:
            raise ValueError("禁止连接 unix socket")

        async def sleep(self, seconds: float) -> None:
            await real_backend.sleep(seconds)

    pool._network_backend = _GuardedBackend()
    return inner_transport


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
            transport=_make_guarded_transport(httpx),
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
