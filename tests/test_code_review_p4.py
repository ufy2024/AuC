"""回归测试：2026-07 P1 批次（git 沙盒/ref 白名单 / MCP sandbox_only / 发现禁重定向）。"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest


# --- git 工具：path 沙盒校验 + ref 白名单 --------------------------------------

pytestmark_git = pytest.mark.skipif(shutil.which("git") is None, reason="git 不可用")


def _git_tool(tools, name):
    for t, _ in tools:
        if t.name == name:
            return t
    raise AssertionError(f"missing tool: {name}")


def _init_repo(path: Path) -> None:
    for args in (
        ["init"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "T"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


@pytestmark_git
def test_git_diff_rejects_path_traversal(tmp_path: Path) -> None:
    from auc.tools.git import make_git_tools

    _init_repo(tmp_path)
    tools = make_git_tools(str(tmp_path))
    res = asyncio.run(_git_tool(tools, "git_diff").invoke({"path": "../../etc/passwd"}))
    assert res.is_error
    assert "escapes sandbox" in res.content or "越界" in res.content or "sandbox" in res.content


@pytestmark_git
def test_git_add_rejects_path_traversal(tmp_path: Path) -> None:
    from auc.tools.git import make_git_tools

    _init_repo(tmp_path)
    tools = make_git_tools(str(tmp_path))
    res = asyncio.run(_git_tool(tools, "git_add").invoke({"paths": "../evil"}))
    assert res.is_error


@pytestmark_git
def test_git_push_rejects_option_like_remote(tmp_path: Path) -> None:
    from auc.tools.git import make_git_tools

    _init_repo(tmp_path)
    tools = make_git_tools(str(tmp_path))
    res = asyncio.run(_git_tool(tools, "git_push").invoke({"remote": "--exec=sh"}))
    assert res.is_error
    assert "非法 remote" in res.content or "remote" in res.content


def test_validate_ref_and_path_helpers() -> None:
    from auc.tools.git import _validate_git_path, _validate_ref

    assert _validate_ref("origin", what="remote") == "origin"
    assert _validate_ref("feature/x-1", what="branch") == "feature/x-1"
    with pytest.raises(ValueError):
        _validate_ref("--force", what="remote")
    with pytest.raises(ValueError):
        _validate_ref("a b", what="branch")  # 空格非法
    assert _validate_git_path("/sb", ".", "src/a.py") == "src/a.py"
    with pytest.raises(Exception):
        _validate_git_path("/sb", ".", "../escape")
    with pytest.raises(ValueError):
        _validate_git_path("/sb", ".", "-rf")


# --- MCP：工具默认 sandbox_only=True（即便 L1）--------------------------------

def test_mcp_config_sandbox_only_default_true() -> None:
    from auc.integration.mcp import parse_mcp_configs

    cfgs = parse_mcp_configs(
        {"mcpServers": {"srv": {"command": "echo", "privilege": "L1"}}}
    )
    assert len(cfgs) == 1
    assert cfgs[0].sandbox_only is True


def test_mcp_config_sandbox_only_opt_out() -> None:
    from auc.integration.mcp import parse_mcp_configs

    cfgs = parse_mcp_configs(
        {"mcpServers": {"srv": {"command": "echo", "sandbox_only": False}}}
    )
    assert cfgs[0].sandbox_only is False


# --- 模型发现：禁重定向，3xx 不携密钥跟随 -------------------------------------

def test_discover_models_does_not_follow_redirect() -> None:
    httpx = pytest.importorskip("httpx")

    from auc.model.discovery import ModelDiscoveryError, discover_models

    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        # 恶意/异常网关：始终 302 指向内网，尝试骗取带密钥的跟随请求
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/meta-data"})

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def _factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real(*args, **kwargs)

    import auc.model.discovery as disc

    orig = disc.httpx.AsyncClient
    disc.httpx.AsyncClient = _factory  # type: ignore[assignment]
    try:
        with pytest.raises(ModelDiscoveryError) as exc:
            asyncio.run(discover_models(base_url="http://relay/api", api_key="sk-secret"))
    finally:
        disc.httpx.AsyncClient = orig  # type: ignore[assignment]
    # 绝不请求重定向目标（元数据服务），只打到用户配置的候选端点
    assert all("169.254.169.254" not in h for h in hits)
    assert "302" in str(exc.value)
