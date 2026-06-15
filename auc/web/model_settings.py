"""Web UI 模型配置（全局 / 项目级分层读写）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from auc.config import (
    SCHEMA_URL,
    ConfigScope,
    ModelConfig,
    _deep_merge,
    _default_base_url,
    _default_model,
    config_scope_for_path,
    describe_config_layers,
    global_settings_path,
    load_model_config,
    load_raw_config_file,
    normalize_openai_compatible_base_url,
    normalize_provider,
    project_local_settings_path,
    project_settings_path,
)

Scope = Literal["global", "project", "project_local"]


def settings_path_for_scope(scope: Scope, sandbox_root: str) -> Path:
    if scope == "global":
        return global_settings_path()
    if scope == "project":
        return project_settings_path(sandbox_root)
    return project_local_settings_path(sandbox_root)


def config_layers_payload(sandbox_root: str, cfg: ModelConfig) -> dict[str, Any]:
    layers = describe_config_layers(repo_root=sandbox_root)
    scope = config_scope_for_path(cfg.config_path, repo_root=sandbox_root)
    return {
        **layers,
        "active_scope": scope,
        "save_scopes": [
            {
                "id": "project_local",
                "label": "项目本地",
                "path": str(project_local_settings_path(sandbox_root)),
                "hint": "推荐：仅本机密钥，通常加入 .gitignore",
            },
            {
                "id": "project",
                "label": "项目共享",
                "path": str(project_settings_path(sandbox_root)),
                "hint": "可提交仓库，团队共用模型与网关（密钥建议用环境变量）",
            },
            {
                "id": "global",
                "label": "全局",
                "path": str(global_settings_path()),
                "hint": "所有工作区默认配置（~/.Au/AuC/settings.json）",
            },
        ],
    }


def model_settings_payload(
    cfg: ModelConfig,
    *,
    sandbox_root: str,
    save_path: Path | None = None,
) -> dict[str, Any]:
    scope = config_scope_for_path(cfg.config_path, repo_root=sandbox_root)
    payload = {
        "provider": cfg.provider,
        "model": cfg.model,
        "base_url": cfg.base_url or _default_base_url(cfg.provider),
        "api_key_masked": cfg.masked_api_key(),
        "api_key": cfg.api_key or "",
        "api_key_set": bool(cfg.api_key),
        "config_name": cfg.config_name,
        "config_id": cfg.config_id,
        "timeout_sec": cfg.timeout,
        "max_tokens": cfg.max_tokens,
        "settings_path": str(save_path or cfg.config_path) if (save_path or cfg.config_path) else None,
        "active_scope": scope,
        "layers": config_layers_payload(sandbox_root, cfg),
    }
    return payload


def _env_for_provider(
    provider: str,
    *,
    model: str,
    base_url: str,
    api_key: str,
    max_tokens: int,
    timeout_sec: float,
) -> dict[str, str]:
    prov = normalize_provider(provider)
    ms = str(int(timeout_sec * 1000))
    common = {"API_TIMEOUT_MS": ms, "AUC_MAX_TOKENS": str(max_tokens)}
    if prov == "anthropic":
        return {
            "AUC_PROVIDER": "anthropic",
            "ANTHROPIC_AUTH_TOKEN": api_key,
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_MODEL": model,
            **common,
        }
    if prov == "deepseek":
        return {
            "AUC_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": api_key,
            "OPENAI_API_KEY": api_key,
            "OPENAI_BASE_URL": base_url or _default_base_url("deepseek"),
            "AUC_MODEL": model,
            **common,
        }
    return {
        "AUC_PROVIDER": "openai",
        "OPENAI_API_KEY": api_key,
        "OPENAI_BASE_URL": base_url or _default_base_url("openai"),
        "AUC_MODEL": model,
        **common,
    }


def save_model_settings(
    sandbox_root: str,
    *,
    provider: str,
    model: str,
    base_url: str | None,
    api_key: str | None = None,
    scope: Scope = "project_local",
    repo_root: str | None = None,
) -> tuple[ModelConfig, Path]:
    """写入指定作用域的配置文件并返回合并后的 ModelConfig。"""
    root = repo_root or sandbox_root
    current = load_model_config(repo_root=root)
    key = (api_key or "").strip() or (current.api_key or "")
    if not key:
        raise ValueError("api_key 不能为空")

    prov = normalize_provider(provider)
    model_id = (model or "").strip() or current.model or _default_model(prov)
    base = normalize_openai_compatible_base_url(
        (base_url or "").strip() or current.base_url or _default_base_url(prov)
    )

    env = _env_for_provider(
        prov,
        model=model_id,
        base_url=base,
        api_key=key,
        max_tokens=current.max_tokens,
        timeout_sec=current.timeout,
    )

    path = settings_path_for_scope(scope, sandbox_root if scope != "global" else sandbox_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        data = load_raw_config_file(path)
    else:
        data = {}
    scope_labels: dict[ConfigScope, str] = {
        "global": "AuC 全局配置",
        "project": "项目配置",
        "project_local": "项目本地配置",
    }
    merged = _deep_merge(
        data,
        {
            "$schema": data.get("$schema") or SCHEMA_URL,
            "configName": data.get("configName") or current.config_name or scope_labels[scope],
            "configId": data.get("configId") or current.config_id or f"web-{scope}",
            "description": data.get("description") or f"由 AuC Web 界面保存（{scope_labels[scope]}）",
            "env": env,
        },
    )
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cfg = load_model_config(repo_root=root)
    return cfg, path


# 兼容旧引用
def settings_local_path(sandbox_root: str) -> Path:
    return project_local_settings_path(sandbox_root)
