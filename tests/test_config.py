import os
from pathlib import Path

from auc.config import (
    default_config_path,
    discover_config_path,
    load_model_config,
    user_config_dir,
)
from auc.model.anthropic import AnthropicClient
from auc.model.factory import create_model_client
from auc.model.openai import OpenAICompatibleClient


def test_user_config_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert user_config_dir() == tmp_path / ".Au" / "AuC"
    assert default_config_path() == tmp_path / ".Au" / "AuC" / "config.yaml"


def test_load_from_user_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_dir = user_config_dir()
    cfg_dir.mkdir(parents=True)
    cfg_file = cfg_dir / "config.yaml"
    cfg_file.write_text(
        """
provider: anthropic
model: claude-test
api_key: ${MY_KEY}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("MY_KEY", "secret-key")
    cfg = load_model_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-test"
    assert cfg.api_key == "secret-key"
    assert cfg.config_path == str(cfg_file)


def test_cli_overrides_file(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / "custom.yaml"
    cfg_file.write_text("provider: openai\nmodel: gpt-old\n", encoding="utf-8")
    cfg = load_model_config(
        config_path=str(cfg_file),
        provider="anthropic",
        model="claude-new",
        api_key="k",
    )
    assert cfg.provider == "anthropic"
    assert cfg.model == "claude-new"


def test_env_auc_config(monkeypatch, tmp_path) -> None:
    f = tmp_path / "via-env.yaml"
    f.write_text("provider: openai\nmodel: from-env-file\n", encoding="utf-8")
    monkeypatch.setenv("AUC_CONFIG", str(f))
    cfg = load_model_config()
    assert cfg.model == "from-env-file"


def test_env_model_overrides_file(tmp_path, monkeypatch) -> None:
    cfg_file = tmp_path / ".auc.yaml"
    cfg_file.write_text("provider: openai\nmodel: gpt-old\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
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


def test_deepseek_defaults(monkeypatch) -> None:
    from auc.config import normalize_provider, _default_base_url, _default_model

    assert normalize_provider("deepseek") == "deepseek"
    assert _default_base_url("deepseek") == "https://api.deepseek.com"
    assert _default_model("deepseek") == "deepseek-chat"


def test_create_deepseek_client(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    cfg = load_model_config(provider="deepseek", api_key="test")
    client = create_model_client(cfg)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == "https://api.deepseek.com"
    assert cfg.model == "deepseek-chat"


def test_config_init_deepseek_template() -> None:
    from auc.config import config_template_for_provider

    text = config_template_for_provider("deepseek")
    assert "provider: deepseek" in text
    assert "DEEPSEEK_API_KEY" in text
    assert "api.deepseek.com" in text
