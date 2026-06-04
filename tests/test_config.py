import os
from pathlib import Path

from auc.config import load_model_config, save_config_file, ModelConfig, discover_config_path
from auc.model.factory import create_model_client
from auc.model.openai import OpenAICompatibleClient
from auc.model.anthropic import AnthropicClient


def test_load_from_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("AUC_PROVIDER", raising=False)
    cfg_file = tmp_path / ".auc.yaml"
    cfg_file.write_text(
        """
provider: anthropic
model: claude-test
api_key: ${MY_KEY}
base_url: https://api.anthropic.com
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_KEY", "secret-key")
    monkeypatch.chdir(tmp_path)
    cfg = load_model_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-test"
    assert cfg.api_key == "secret-key"


def test_cli_overrides_file(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / ".auc.yaml"
    cfg_file.write_text("provider: openai\nmodel: gpt-old\n", encoding="utf-8")
    cfg = load_model_config(
        config_path=str(cfg_file),
        provider="anthropic",
        model="claude-new",
        api_key="k",
    )
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-new"


def test_env_overrides_file(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / ".auc.yaml"
    cfg_file.write_text("provider: openai\nmodel: gpt-old\n", encoding="utf-8")
    monkeypatch.setenv("AUC_MODEL", "from-env")
    cfg = load_model_config(config_path=str(cfg_file))
    assert cfg.model == "from-env"


def test_create_openai_client(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    cfg = load_model_config(provider="openai", api_key="test")
    client = create_model_client(cfg)
    assert isinstance(client, OpenAICompatibleClient)


def test_create_anthropic_client(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    cfg = load_model_config(provider="anthropic", api_key="test")
    client = create_model_client(cfg)
    assert isinstance(client, AnthropicClient)
