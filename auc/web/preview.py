from __future__ import annotations

import mimetypes
from pathlib import Path

from auc.sandbox import resolve_under_sandbox

_HTML_EXTS = {".html", ".htm"}
_PREVIEWABLE = _HTML_EXTS | {
    ".js", ".css", ".json", ".svg", ".woff", ".woff2", ".ttf", ".map", ".ico", ".wasm",
    ".pdf",
}


def is_html_path(path: str) -> bool:
    return Path(path).suffix.lower() in _HTML_EXTS


def is_previewable(path: str) -> bool:
    ext = Path(path).suffix.lower()
    if ext in _PREVIEWABLE:
        return True
    return ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp3", ".mp4", ".wav", ".ogg"}


def resolve_preview_file(sandbox_root: str, rel_path: str) -> Path:
    resolved = resolve_under_sandbox(sandbox_root, rel_path)
    if resolved.is_dir():
        index = resolved / "index.html"
        if index.is_file():
            return index
        raise FileNotFoundError(f"no index.html in {rel_path}")
    if not resolved.is_file():
        raise FileNotFoundError(rel_path)
    return resolved


def media_type_for(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def preview_security_headers() -> dict[str, str]:
    """预览响应安全头：限制框架来源、禁用嗅探，收敛预览页的外联能力。

    预览页仅在主应用同源 iframe 内展示，故 frame-ancestors 限定 'self'；
    default-src 收敛到 self 以减小 stored XSS 横向触达 /api/* 的面。
    """
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https:; "
        "connect-src 'self' https: wss: ws:; "
        "frame-ancestors 'self'"
    )
    return {
        "Cache-Control": "no-cache",
        "Content-Security-Policy": csp,
        "X-Frame-Options": "SAMEORIGIN",
        "X-Content-Type-Options": "nosniff",
    }


def inject_preview_shim(html: str, run_id: str) -> str:
    """静态 /preview/ 页面注入 API/WS 转发，使绝对路径 /api、/ws 连到运行中的 backend。"""
    prefix = f"/proxy/{run_id}"
    shim = f"""<script id="auc-preview-shim">
(function() {{
  var P = "{prefix}";
  var f = window.fetch;
  window.fetch = function(input, init) {{
    if (typeof input === "string" && input.indexOf("/api") === 0) {{
      input = P + input;
    }}
    return f.call(this, input, init);
  }};
  var W = window.WebSocket;
  window.WebSocket = function(url, protocols) {{
    if (typeof url === "string") {{
      var ws = (location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host;
      if (url.indexOf("/ws") === 0 || url.indexOf("/ws") > 0) {{
        url = ws + P + "/ws";
      }}
    }}
    return protocols !== undefined ? new W(url, protocols) : new W(url);
  }};
}})();
</script>"""
    lower = html.lower()
    if "</head>" in lower:
        idx = lower.index("</head>")
        return html[:idx] + shim + html[idx:]
    return shim + html
