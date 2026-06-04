from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

Provider = Literal["openai", "anthropic"]

_ENV_REF = re.compile(r"^\$\{([^}]+)\}$")


@dataclass
class ModelConfig:
    """LLM provider configuration (file + env + CLI)."""

    provider: Provider = "openai"
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    timeout: float = 120.0
    max_tokens: int = 4096
    config_path: str | None = None

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


def _default_base_url(provider: Provider) -> str:
    if provider == "anthropic":
        return "https://api.anthropic.com"
    return "https://api.openai.com/v1"


def _default_api_key_env(provider: Provider) -> str:
    return "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"


def _default_model(provider: Provider) -> str:
    if provider == "anthropic":
        return "claude-sonnet-4-20250514"
    return "gpt-4o-mini"


def discover_config_path(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    candidates = [
        Path.cwd() / ".auc.yaml",
        Path.cwd() / "auc.yaml",
        Path.cwd() / ".auc.yml",
        Path.home() / ".config" / "auc" / "config.yaml",
        Path.home() / ".auc.yaml",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def load_config_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in data.items():
        out[k] = _resolve_value(v)
    return out


def load_model_config(
    *,
    config_path: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    timeout: float | None = None,
    max_tokens: int | None = None,
) -> ModelConfig:
    """Merge config: defaults < file < env < CLI arguments."""
    path = discover_config_path(config_path)
    file_data: dict[str, Any] = load_config_file(path) if path else {}

    prov_raw = (
        provider
        or os.environ.get("AUC_PROVIDER")
        or file_data.get("provider")
        or "openai"
    )
    prov: Provider = "anthropic" if str(prov_raw).lower() == "anthropic" else "openai"

    cfg = ModelConfig(
        provider=prov,
        model=str(
            model
            or os.environ.get("AUC_MODEL")
            or file_data.get("model")
            or _default_model(prov)
        ),
        api_key=None,
        base_url=None,
        timeout=float(
            timeout
            or os.environ.get("AUC_TIMEOUT")
            or file_data.get("timeout")
            or 120.0
        ),
        max_tokens=int(
            max_tokens
            or os.environ.get("AUC_MAX_TOKENS")
            or file_data.get("max_tokens")
            or 4096
        ),
        config_path=str(path) if path else None,
    )

    cfg.api_key = (
        api_key
        or os.environ.get("AUC_API_KEY")
        or file_data.get("api_key")
        or os.environ.get(_default_api_key_env(prov))
    )
    if cfg.api_key == "":
        cfg.api_key = None

    cfg.base_url = (
        base_url
        or os.environ.get("AUC_BASE_URL")
        or file_data.get("base_url")
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
    data = {
        "provider": cfg.provider,
        "model": cfg.model,
        "api_key": f"${_default_api_key_env(cfg.provider)}",
        "base_url": cfg.base_url,
        "timeout": cfg.timeout,
        "max_tokens": cfg.max_tokens,
    }
    header = "# AuC model config — api_key can use ${ENV_VAR}\n"
    path.write_text(header + yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


DEFAULT_CONFIG_TEMPLATE = """# AuC model configuration
# Search order: --config > ./.auc.yaml > ~/.config/auc/config.yaml

provider: openai   # openai | anthropic
model: gpt-4o-mini
api_key: ${OPENAI_API_KEY}
base_url: https://api.openai.com/v1
timeout: 120
max_tokens: 4096

# --- Anthropic example ---
# provider: anthropic
# model: claude-sonnet-4-20250514
# api_key: ${ANTHROPIC_API_KEY}
# base_url: https://api.anthropic.com
"""
