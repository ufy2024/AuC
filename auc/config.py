from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

Provider = Literal["openai", "anthropic", "deepseek"]

_ENV_REF = re.compile(r"^\$\{([^}]+)\}$")

# 用户级配置目录（类比 ~/.claude/）
AUC_USER_DIR_NAME = ".Au"
AUC_APP_DIR_NAME = "AuC"
DEFAULT_SETTINGS_FILENAME = "settings.json"
LEGACY_CONFIG_YAML = "config.yaml"
PROJECT_AUC_DIR = ".auc"
SCHEMA_URL = "https://github.com/ufy2024/AuC/blob/main/docs/schema/settings.schema.json"


@dataclass
class ModelConfig:
    """大模型提供商配置（文件 + 环境变量 + CLI）。"""

    provider: Provider = "openai"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 120.0
    max_tokens: int = 8192
    config_path: str | None = None
    config_name: str | None = None
    config_id: str | None = None
    description: str | None = None

    def masked_api_key(self) -> str:
        if not self.api_key:
            return "(not set)"
        if len(self.api_key) <= 8:
            return "***"
        return self.api_key[:4] + "..." + self.api_key[-4:]


def _resolve_value(val: Any) -> Any:
    if isinstance(val, str):
        m = _ENV_REF.match(val.strip())
        if m:
            return os.environ.get(m.group(1), "")
    return val


def _resolve_tree(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _resolve_tree(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_resolve_tree(v) for v in data]
    return _resolve_value(data)


def normalize_provider(raw: str) -> Provider:
    p = str(raw).lower().strip()
    if p == "anthropic":
        return "anthropic"
    if p == "deepseek":
        return "deepseek"
    return "openai"


def _default_base_url(provider: Provider) -> str:
    if provider == "anthropic":
        return "https://api.anthropic.com"
    if provider == "deepseek":
        return "https://api.deepseek.com/v1"
    return "https://api.openai.com/v1"


def normalize_openai_compatible_base_url(base_url: str) -> str:
    """DeepSeek 官方 OpenAI 兼容接口在 /v1 下，避免请求落到 /chat/completions。"""
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return base
    lower = base.lower()
    if "api.deepseek.com" in lower and "/anthropic" not in lower and not lower.endswith("/v1"):
        return f"{base}/v1"
    return base


def _default_api_key_env(provider: Provider) -> str:
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider == "deepseek":
        return "DEEPSEEK_API_KEY"
    return "OPENAI_API_KEY"


def _default_model(provider: Provider) -> str:
    if provider == "anthropic":
        return "claude-sonnet-4-20250514"
    if provider == "deepseek":
        return "deepseek-chat"
    return "gpt-4o-mini"


def user_config_dir() -> Path:
    return Path.home() / AUC_USER_DIR_NAME / AUC_APP_DIR_NAME


def default_config_path() -> Path:
    """默认路径：~/.Au/AuC/settings.json（Claude 对应 ~/.claude/settings.json）。"""
    return user_config_dir() / DEFAULT_SETTINGS_FILENAME


def project_auc_dir(repo_root: Path | None = None) -> Path:
    return (repo_root or Path.cwd()) / PROJECT_AUC_DIR


def global_settings_path() -> Path:
    return default_config_path()


def project_settings_path(repo_root: Path | str | None = None) -> Path:
    return project_auc_dir(Path(repo_root) if repo_root else None) / "settings.json"


def project_local_settings_path(repo_root: Path | str | None = None) -> Path:
    return project_auc_dir(Path(repo_root) if repo_root else None) / "settings.local.json"


ConfigScope = Literal["global", "project", "project_local"]


def resolve_config_repo_root(
    *,
    repo_root: str | Path | None = None,
    sandbox: str | Path | None = None,
) -> Path | None:
    """项目级配置根目录：显式 repo > sandbox > 当前工作目录。"""
    if repo_root:
        return Path(repo_root)
    if sandbox:
        return Path(sandbox)
    return None


def global_config_layers() -> list[Path]:
    """用户级配置层（低优先级）。"""
    env_path = os.environ.get("AUC_CONFIG")
    if env_path:
        p = Path(env_path).expanduser()
        return [p] if p.is_file() else []

    layers: list[Path] = []
    udir = user_config_dir()
    for name in (
        LEGACY_CONFIG_YAML,
        "config.json",
        DEFAULT_SETTINGS_FILENAME,
    ):
        p = udir / name
        if p.is_file():
            layers.append(p)
    return layers


def project_config_layers(repo_root: Path | None = None) -> list[Path]:
    """项目级配置层（覆盖全局，后者优先）。"""
    layers: list[Path] = []
    proj = project_auc_dir(repo_root)
    for name in ("settings.json", "settings.local.json"):
        p = proj / name
        if p.is_file():
            layers.append(p)

    root = repo_root or Path.cwd()
    for name in (".auc.yaml", "auc.yaml"):
        p = root / name
        if p.is_file() and p not in layers:
            layers.append(p)
    return layers


def config_scope_for_path(path: Path | str | None, *, repo_root: Path | str | None = None) -> ConfigScope | None:
    if not path:
        return None
    p = Path(path).expanduser().resolve()
    if p == global_settings_path().resolve():
        return "global"
    proj = project_auc_dir(Path(repo_root) if repo_root else None).resolve()
    if p == (proj / "settings.json").resolve():
        return "project"
    if p == (proj / "settings.local.json").resolve():
        return "project_local"
    return None


def describe_config_layers(
    *,
    explicit: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """返回全局/项目配置层说明，供 CLI 与 Web 展示。"""
    root = Path(repo_root) if repo_root else None
    if explicit:
        p = Path(explicit).expanduser()
        layers = [p] if p.is_file() else []
        return {
            "global_dir": str(user_config_dir()),
            "project_dir": str(project_auc_dir(root)),
            "layers": [str(x) for x in layers],
            "effective_path": str(layers[-1]) if layers else None,
            "effective_scope": config_scope_for_path(layers[-1], repo_root=root) if layers else None,
            "priority_note": "显式 --config 仅使用该文件",
        }

    global_layers = global_config_layers()
    project_layers = project_config_layers(root)
    merged = global_layers + project_layers

    def _file_row(path: Path) -> dict[str, Any]:
        return {
            "path": str(path),
            "exists": path.is_file(),
            "scope": config_scope_for_path(path, repo_root=root),
        }

    return {
        "global_dir": str(user_config_dir()),
        "project_dir": str(project_auc_dir(root)),
        "global_files": [
            _file_row(user_config_dir() / name)
            for name in (LEGACY_CONFIG_YAML, "config.json", DEFAULT_SETTINGS_FILENAME)
        ],
        "project_files": [
            _file_row(project_auc_dir(root) / name)
            for name in ("settings.json", "settings.local.json")
        ],
        "layers": [str(p) for p in merged],
        "effective_path": str(merged[-1]) if merged else None,
        "effective_scope": config_scope_for_path(merged[-1], repo_root=root) if merged else None,
        "priority_note": "项目级覆盖全局：settings.json < settings.local.json",
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """浅层-深层合并，类似 Claude 配置分层。"""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def discover_config_layers(
    explicit: str | None = None,
    repo_root: Path | None = None,
) -> list[Path]:
    """返回配置文件列表，低 → 高优先级（后者覆盖前者）。"""
    if explicit:
        p = Path(explicit).expanduser()
        return [p] if p.is_file() else []

    return global_config_layers() + project_config_layers(repo_root)


def discover_config_path(explicit: str | None = None) -> Path | None:
    layers = discover_config_layers(explicit)
    return layers[-1] if layers else None


def load_raw_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        return {}
    return _resolve_tree(data)


def load_merged_settings(
    explicit: str | None = None,
    repo_root: Path | None = None,
) -> tuple[dict[str, Any], Path | None]:
    layers = discover_config_layers(explicit, repo_root)
    merged: dict[str, Any] = {}
    last: Path | None = None
    for p in layers:
        merged = _deep_merge(merged, load_raw_config_file(p))
        last = p
    return merged, last


def _settings_env_dict(data: dict[str, Any]) -> dict[str, str]:
    block = data.get("env")
    if not isinstance(block, dict):
        return {}
    return {str(k): str(v) for k, v in block.items() if v is not None and v != ""}


def _extract_naming_fields(data: dict[str, Any]) -> dict[str, str | None]:
    return {
        "config_name": data.get("configName") or data.get("config_name") or data.get("name"),
        "config_id": data.get("configId") or data.get("config_id"),
        "description": data.get("description"),
    }


def _env_lookup(env: dict[str, str], key: str) -> str | None:
    val = env.get(key)
    if val is None or val == "":
        val = os.environ.get(key)
    return val if val else None


def _timeout_from_env(env: dict[str, str]) -> float | None:
    ms = _env_lookup(env, "API_TIMEOUT_MS")
    if ms:
        try:
            return float(ms) / 1000.0
        except ValueError:
            pass
    sec = _env_lookup(env, "AUC_TIMEOUT")
    if sec:
        try:
            return float(sec)
        except ValueError:
            pass
    return None


def _infer_provider_from_env(env: dict[str, str]) -> Provider | None:
    raw = _env_lookup(env, "AUC_PROVIDER")
    if raw:
        return normalize_provider(raw)
    if _env_lookup(env, "ANTHROPIC_MODEL") or _env_lookup(env, "ANTHROPIC_AUTH_TOKEN"):
        return "anthropic"
    if _env_lookup(env, "DEEPSEEK_API_KEY"):
        return "deepseek"
    if _env_lookup(env, "OPENAI_API_KEY"):
        return "openai"
    return None


def _extract_model_fields(data: dict[str, Any]) -> dict[str, Any]:
    """Claude settings.json：顶层 env + 可选的旧版 model 块。"""
    env = _settings_env_dict(data)
    block = data.get("model")
    from_model: dict[str, Any] = {}
    if isinstance(block, dict):
        from_model = {
            "provider": block.get("provider") or block.get("providerId"),
            "model": block.get("id") or block.get("name") or block.get("model"),
            "api_key": block.get("apiKey") or block.get("api_key"),
            "base_url": block.get("baseUrl") or block.get("base_url"),
            "timeout": block.get("timeoutSeconds")
            or block.get("timeout")
            or block.get("timeout_seconds"),
            "max_tokens": block.get("maxTokens") or block.get("max_tokens"),
        }
    else:
        from_model = {
            "provider": data.get("provider"),
            "model": data.get("model") if isinstance(data.get("model"), str) else None,
            "api_key": data.get("apiKey") or data.get("api_key"),
            "base_url": data.get("baseUrl") or data.get("base_url"),
            "timeout": data.get("timeoutSeconds") or data.get("timeout"),
            "max_tokens": data.get("maxTokens") or data.get("max_tokens"),
        }

    prov = _infer_provider_from_env(env) or (
        normalize_provider(str(from_model["provider"]))
        if from_model.get("provider")
        else None
    )

    api_key = (
        _env_lookup(env, "ANTHROPIC_AUTH_TOKEN")
        or _env_lookup(env, "ANTHROPIC_API_KEY")
        or _env_lookup(env, "OPENAI_API_KEY")
        or _env_lookup(env, "DEEPSEEK_API_KEY")
        or _env_lookup(env, "AUC_API_KEY")
        or from_model.get("api_key")
    )

    model_id = (
        _env_lookup(env, "ANTHROPIC_MODEL")
        or _env_lookup(env, "AUC_MODEL")
        or _env_lookup(env, "OPENAI_MODEL")
        or from_model.get("model")
    )

    base_url = (
        _env_lookup(env, "ANTHROPIC_BASE_URL")
        or _env_lookup(env, "OPENAI_BASE_URL")
        or _env_lookup(env, "AUC_BASE_URL")
        or from_model.get("base_url")
    )

    max_tokens = _env_lookup(env, "AUC_MAX_TOKENS") or from_model.get("max_tokens")
    timeout = _timeout_from_env(env) or from_model.get("timeout")

    return {
        "provider": prov,
        "model": model_id,
        "api_key": api_key,
        "base_url": base_url,
        "timeout": timeout,
        "max_tokens": int(max_tokens) if max_tokens is not None else None,
        **_extract_naming_fields(data),
    }


def _model_config_to_env(cfg: ModelConfig) -> dict[str, str]:
    """将 ModelConfig 映射为 Claude 风格的 env 块。"""
    if cfg.provider == "anthropic":
        base = cfg.base_url or _default_base_url("anthropic")
        env: dict[str, str] = {
            "AUC_PROVIDER": "anthropic",
            "ANTHROPIC_AUTH_TOKEN": f"${_default_api_key_env('anthropic')}",
            "ANTHROPIC_BASE_URL": base,
            "ANTHROPIC_MODEL": cfg.model,
            "API_TIMEOUT_MS": str(int(cfg.timeout * 1000)),
            "AUC_MAX_TOKENS": str(cfg.max_tokens),
        }
        if "deepseek.com" in base:
            env["ANTHROPIC_AUTH_TOKEN"] = "${DEEPSEEK_API_KEY}"
            env["ANTHROPIC_SMALL_FAST_MODEL"] = cfg.model
            env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = cfg.model
            env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = cfg.model
        return env
    if cfg.provider == "deepseek":
        return {
            "AUC_PROVIDER": "deepseek",
            "DEEPSEEK_API_KEY": "${DEEPSEEK_API_KEY}",
            "OPENAI_API_KEY": "${DEEPSEEK_API_KEY}",
            "OPENAI_BASE_URL": cfg.base_url or _default_base_url("deepseek"),
            "AUC_MODEL": cfg.model,
            "API_TIMEOUT_MS": str(int(cfg.timeout * 1000)),
            "AUC_MAX_TOKENS": str(cfg.max_tokens),
        }
    return {
        "AUC_PROVIDER": "openai",
        "OPENAI_API_KEY": "${OPENAI_API_KEY}",
        "OPENAI_BASE_URL": cfg.base_url or _default_base_url("openai"),
        "AUC_MODEL": cfg.model,
        "API_TIMEOUT_MS": str(int(cfg.timeout * 1000)),
        "AUC_MAX_TOKENS": str(cfg.max_tokens),
    }


def model_config_to_settings_dict(cfg: ModelConfig) -> dict[str, Any]:
    out: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "configName": cfg.config_name or _default_config_name(cfg.provider),
        "configId": cfg.config_id or _default_config_id(cfg.provider),
        "description": cfg.description or _default_config_description(cfg.provider),
        "env": _model_config_to_env(cfg),
    }
    return out


def _default_config_name(provider: Provider) -> str:
    if provider == "deepseek":
        return "DeepSeek 对话"
    if provider == "anthropic":
        return "Anthropic"
    return "OpenAI"


def _default_config_id(provider: Provider) -> str:
    if provider == "deepseek":
        return "deepseek-v4-anthropic"
    return f"{provider}-default"


def _default_config_description(provider: Provider) -> str:
    if provider == "deepseek":
        return "经 DeepSeek Anthropic 兼容网关（与 Claude Code settings.json 同结构）"
    if provider == "anthropic":
        return "Anthropic Messages API"
    return "OpenAI 兼容 API"


def config_template_dict(provider: str) -> dict[str, Any]:
    p = normalize_provider(provider)
    if p == "deepseek":
        return model_config_to_settings_dict(
            ModelConfig(
                provider="anthropic",
                model="deepseek-chat",
                base_url="https://api.deepseek.com/anthropic",
                timeout=300.0,
                config_name="DeepSeek V4",
                config_id="deepseek-v4-anthropic",
                description=_default_config_description("deepseek"),
            )
        )
    return model_config_to_settings_dict(
        ModelConfig(
            provider=p,
            model=_default_model(p),
            base_url=_default_base_url(p),
            config_name=_default_config_name(p),
            config_id=_default_config_id(p),
            description=_default_config_description(p),
        )
    )


def mask_settings_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """返回副本，敏感 env 值已脱敏。"""
    out = json.loads(json.dumps(data, ensure_ascii=False))

    def _mask_key(key: str, val: str) -> str:
        if _ENV_REF.match(val.strip()):
            return val
        upper = key.upper()
        if any(s in upper for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "AUTH")):
            if len(val) <= 8:
                return "***"
            return val[:4] + "..." + val[-4:]
        return val

    env = out.get("env")
    if isinstance(env, dict):
        out["env"] = {k: _mask_key(k, str(v)) for k, v in env.items()}
    return out


def config_template_for_provider(provider: str) -> str:
    """供 CLI init 使用的 JSON 字符串（格式化输出）。"""
    return json.dumps(config_template_dict(provider), indent=2, ensure_ascii=False) + "\n"


def load_config_file(path: Path) -> dict[str, Any]:
    return _extract_model_fields(load_raw_config_file(path))


def load_model_config(
    *,
    config_path: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
    repo_root: str | None = None,
) -> ModelConfig:
    """合并顺序：用户 settings < 项目 settings < 项目 local < 环境变量 < CLI。"""
    root = Path(repo_root) if repo_root else None
    merged, path = load_merged_settings(config_path, root)
    file_data = _extract_model_fields(merged)

    prov = normalize_provider(
        str(
            provider
            or os.environ.get("AUC_PROVIDER")
            or file_data.get("provider")
            or "openai"
        )
    )
    file_prov = (
        normalize_provider(str(file_data["provider"]))
        if file_data.get("provider")
        else None
    )
    provider_switched = bool(
        (provider is not None or os.environ.get("AUC_PROVIDER"))
        and file_prov is not None
        and file_prov != prov
    )
    use_file_llm = bool(file_data) and not provider_switched

    def _from_file(key: str) -> Any:
        return file_data.get(key) if use_file_llm else None

    naming = _extract_naming_fields(merged)

    cfg = ModelConfig(
        provider=prov,
        model=str(
            model
            or os.environ.get("AUC_MODEL")
            or _from_file("model")
            or _default_model(prov)
        ),
        api_key=None,
        base_url=None,
        timeout=float(
            timeout
            or os.environ.get("AUC_TIMEOUT")
            or _from_file("timeout")
            or 120.0
        ),
        max_tokens=int(
            max_tokens
            or os.environ.get("AUC_MAX_TOKENS")
            or _from_file("max_tokens")
            or 8192
        ),
        config_path=str(path) if path else None,
        config_name=naming.get("config_name"),
        config_id=naming.get("config_id"),
        description=naming.get("description"),
    )

    cfg.api_key = (
        api_key
        or os.environ.get("AUC_API_KEY")
        or _from_file("api_key")
        or os.environ.get(_default_api_key_env(prov))
    )
    if cfg.api_key == "":
        cfg.api_key = None

    cfg.base_url = normalize_openai_compatible_base_url(
        base_url
        or os.environ.get("AUC_BASE_URL")
        or _from_file("base_url")
        or _default_base_url(prov)
    )

    return cfg


def save_config_file(
    path: Path,
    cfg: ModelConfig,
    *,
    overwrite: bool = False,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"config already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = model_config_to_settings_dict(cfg)
    if path.suffix.lower() in (".yaml", ".yml"):
        path.write_text(
            "# AuC settings (legacy YAML)\n" + yaml.safe_dump(data, allow_unicode=True),
            encoding="utf-8",
        )
    else:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def migrate_yaml_to_json(*, remove_yaml: bool = False) -> Path | None:
    """将 ~/.Au/AuC/config.yaml 迁移为 settings.json；仅当 yaml 存在时返回路径。"""
    udir = user_config_dir()
    yaml_path = udir / LEGACY_CONFIG_YAML
    json_path = udir / DEFAULT_SETTINGS_FILENAME
    if not yaml_path.is_file():
        return None
    raw = load_raw_config_file(yaml_path)
    fields = _extract_model_fields(raw)
    prov = normalize_provider(str(fields.get("provider") or "openai"))
    cfg = ModelConfig(
        provider=prov,
        model=str(fields.get("model") or _default_model(prov)),
        api_key=fields.get("api_key"),
        base_url=fields.get("base_url") or _default_base_url(prov),
        timeout=float(fields.get("timeout") or 120),
        max_tokens=int(fields.get("max_tokens") or 8192),
        config_name=fields.get("config_name"),
        config_id=fields.get("config_id"),
        description=fields.get("description"),
    )
    save_config_file(json_path, cfg, overwrite=True)
    if remove_yaml:
        yaml_path.unlink()
    return json_path
