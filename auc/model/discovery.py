"""按 base_url + API Key 自动检索可用模型（OpenAI / Anthropic 兼容）。

许多 OpenAI 兼容网关（含「中转」）实现 ``GET {base}/models``；Anthropic 官方为
``GET {base}/v1/models``。当目标端点未实现（404/网关不支持）时抛出
``ModelDiscoveryError``，调用方据此回退到「手动填写模型 ID」。
"""

from __future__ import annotations

from typing import Any

from auc.config import normalize_openai_compatible_base_url
from auc.model.factory import _is_anthropic_style_base

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

ANTHROPIC_VERSION = "2023-06-01"


class ModelDiscoveryError(RuntimeError):
    """无法从网关检索模型列表（端点缺失、鉴权失败或网络错误）。"""


def _require_httpx() -> Any:
    if httpx is None:
        from auc.extras import hint_for

        raise ImportError(hint_for("llm", "all"))
    return httpx


def _anthropic_models_url(base: str) -> str:
    b = base.rstrip("/")
    if b.endswith("/v1"):
        return f"{b}/models"
    return f"{b}/v1/models"


def _candidate_model_urls(base: str, *, anthropic_style: bool) -> list[str]:
    """按常见网关布局推导候选「模型列表」端点（去重保序）。

    很多中转对未实现/未知路径直接返回 401/404，因此多试几个常见位置：
    ``{base}/models``、``{base}/v1/models``，以及 base 以 ``/api`` 结尾时的
    ``{root}/v1/models``。
    """
    b = base.rstrip("/")
    urls: list[str] = []
    if anthropic_style:
        urls.append(_anthropic_models_url(b))
    urls.append(f"{b}/models")
    if not b.endswith("/v1"):
        urls.append(f"{b}/v1/models")
    if b.endswith("/api"):
        urls.append(f"{b[:-4]}/v1/models")
        urls.append(f"{b[:-4]}/models")
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _auth_header_variants(key: str, *, anthropic_style: bool) -> list[dict[str, str]]:
    """常见鉴权头：OpenAI 用 Bearer；Anthropic 用 x-api-key。两者都试以兼容各类中转。"""
    bearer = {"Authorization": f"Bearer {key}"}
    xapi = {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION}
    return [xapi, bearer] if anthropic_style else [bearer, xapi]


def _short_url(url: str) -> str:
    """诊断信息里只保留路径，避免泄露主机噪声。"""
    marker = "://"
    idx = url.find(marker)
    if idx == -1:
        return url
    rest = url[idx + len(marker):]
    slash = rest.find("/")
    return rest[slash:] if slash != -1 else "/"


def parse_models_payload(data: Any) -> list[str]:
    """从 OpenAI / Anthropic 风格响应中提取模型 id 列表（去重、保序）。"""
    items: list[Any]
    if isinstance(data, dict):
        raw = data.get("data")
        if raw is None and isinstance(data.get("models"), list):
            raw = data.get("models")
        items = raw if isinstance(raw, list) else []
    elif isinstance(data, list):
        items = data
    else:
        items = []

    ids: list[str] = []
    seen: set[str] = set()
    for item in items:
        mid: str | None = None
        if isinstance(item, str):
            mid = item
        elif isinstance(item, dict):
            val = item.get("id") or item.get("name") or item.get("model")
            mid = str(val) if val else None
        if mid and mid not in seen:
            seen.add(mid)
            ids.append(mid)
    return ids


async def discover_models(
    *,
    base_url: str | None,
    api_key: str | None,
    provider: str = "openai",
    timeout: float = 15.0,
) -> list[str]:
    """检索网关可用模型；失败抛 ``ModelDiscoveryError``。"""
    httpx_mod = _require_httpx()
    base = normalize_openai_compatible_base_url((base_url or "").strip().rstrip("/"))
    if not base:
        raise ModelDiscoveryError("base_url 为空")
    if not (api_key or "").strip():
        raise ModelDiscoveryError("api_key 为空")
    key = api_key.strip()

    anthropic_style = provider == "anthropic" or _is_anthropic_style_base(base)
    candidate_urls = _candidate_model_urls(base, anthropic_style=anthropic_style)
    header_variants = _auth_header_variants(key, anthropic_style=anthropic_style)

    errors: list[str] = []
    saw_empty = False

    async with httpx_mod.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for url in candidate_urls:
            path = _short_url(url)
            for headers in header_variants:
                try:
                    resp = await client.get(url, headers=headers)
                except Exception as exc:  # noqa: BLE001 网络层异常统一归类
                    errors.append(f"{path}: 请求失败（{exc}）")
                    break  # 同一 URL 换鉴权头无意义
                if resp.is_error:
                    errors.append(f"{path}: HTTP {resp.status_code}")
                    # 端点不存在/方法不允许：换鉴权头无意义，直接试下一个 URL
                    if resp.status_code in (404, 405):
                        break
                    continue  # 401/403/5xx：可能是鉴权头不对，换一种再试
                try:
                    models = parse_models_payload(resp.json())
                except (ValueError, TypeError) as exc:
                    errors.append(f"{path}: 响应解析失败（{exc}）")
                    break
                if models:
                    return models
                saw_empty = True
                break  # 端点可用但空列表，换 URL/鉴权头无意义

    if saw_empty and not errors:
        raise ModelDiscoveryError("网关返回空模型列表")
    # 去重并汇总，便于定位是「路径不对」还是「鉴权不过」
    seen: set[str] = set()
    distinct = [e for e in errors if not (e in seen or seen.add(e))]
    tried = "、".join(_short_url_only(e) for e in distinct[:4])
    if errors and all("HTTP 401" in e for e in errors):
        raise ModelDiscoveryError(
            f"HTTP 401：鉴权未通过或网关未开放模型列表（已试 {tried}）；"
            f"请检查 API Key，或手动填写模型 ID"
        )
    if errors and all(("HTTP 401" in e or "HTTP 403" in e) for e in errors):
        raise ModelDiscoveryError(
            f"鉴权未通过或网关未开放模型列表（已试 {tried}）；"
            f"请检查 API Key，或手动填写模型 ID"
        )
    detail = "；".join(distinct[:4]) or "未知错误"
    raise ModelDiscoveryError(detail)


def _short_url_only(error_line: str) -> str:
    """从 "<path>: HTTP 401" 取出 path 部分用于汇总。"""
    return error_line.split(":", 1)[0]
