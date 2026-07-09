"""回归测试：2026-07 代码审查后的优化项（retry 幂等性 / 子智能体自治继承 / 原子写）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from auc.model.retry import _RETRY_STATUS, with_retry


# --- retry：409 Conflict 不应被重试（非幂等 POST 重复计费风险）-----------------

def test_409_not_in_retry_status() -> None:
    assert 409 not in _RETRY_STATUS
    # 仍保留瞬时/限流/5xx
    for code in (408, 425, 429, 500, 502, 503, 504):
        assert code in _RETRY_STATUS


def test_with_retry_does_not_retry_409() -> None:
    httpx = pytest.importorskip("httpx")
    calls = {"n": 0}

    async def conflict() -> str:
        calls["n"] += 1
        resp = httpx.Response(409, request=httpx.Request("POST", "http://x"))
        raise httpx.HTTPStatusError("409", request=resp.request, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(with_retry(conflict, max_attempts=3))
    assert calls["n"] == 1  # 409 只调用一次，不重试


# --- subagent：子 Run 不得比父 Run 更宽松 ------------------------------------

def _spawn_and_capture(parent_autonomy: str | None):
    from auc.events.bus import EventBus
    from auc.run_context import current_loop_context
    from auc.tools.subagent import make_subagent_tool

    captured: dict[str, object] = {}

    class _FakeChild:
        async def run(self, request):  # noqa: ANN001
            captured["metadata"] = dict(request.metadata)
            return SimpleNamespace(status="completed", error=None, output="done")

    tool, _pol = make_subagent_tool(
        build_agent=lambda kind: _FakeChild(),
        sandbox="/tmp",
        allowed_kinds=["default"],
        default_kind="default",
    )

    policy = (
        SimpleNamespace(level=parent_autonomy) if parent_autonomy is not None else None
    )
    ctx = SimpleNamespace(
        run_id="parent-1",
        agent_id="chat:default",
        events=EventBus(),
        parent_run_id=None,
        autonomy_policy=policy,
    )
    token = current_loop_context.set(ctx)
    try:
        asyncio.run(tool.invoke({"task": "do", "kind": "default"}))
    finally:
        current_loop_context.reset(token)
    return captured["metadata"]


def test_subagent_inherits_parent_autonomy() -> None:
    meta = _spawn_and_capture("auto-edit")
    assert meta["autonomy"] == "auto-edit"  # 继承父级，而非强制 full-auto


def test_subagent_omits_autonomy_when_parent_unknown() -> None:
    meta = _spawn_and_capture(None)
    # 父级未知时不注入 autonomy，让子智能体沿用自身配置默认（不抬升为 full-auto）
    assert "autonomy" not in meta


def test_subagent_never_forces_full_auto_from_confirm_all() -> None:
    meta = _spawn_and_capture("confirm-all")
    assert meta["autonomy"] == "confirm-all"


# --- 进化/金块：原子写不遗留 .tmp 且内容正确 ---------------------------------

def test_evolution_save_atomic(tmp_path: Path) -> None:
    from auc.integration.evolution import Episode, EvolutionStore

    store = EvolutionStore(path=tmp_path / "sub" / "evolution.yaml")
    store.episodes.append(
        Episode(id="e1", tags=["t"], lesson="记住这条", created_at="2026", metadata={})
    )
    store.save()
    assert store.path.exists()
    assert "记住这条" in store.path.read_text(encoding="utf-8")
    # 不遗留临时文件
    assert not list(store.path.parent.glob("*.tmp"))


def test_nuggets_save_atomic(tmp_path: Path) -> None:
    from auc.integration.nuggets import AuNugget, NuggetsStore

    store = NuggetsStore(nuggets=[AuNugget(id="n1", tags=["a"], content="金块内容")])
    dest = tmp_path / "nested" / "nuggets.yaml"
    store.save_yaml(dest)
    assert dest.exists()
    assert "金块内容" in dest.read_text(encoding="utf-8")
    assert not list(dest.parent.glob("*.tmp"))


# --- Web P0：token 模式下 WebSocket / preview / raw 端点鉴权与守卫 -------------

def _web_client(token: str | None = None):
    import tempfile

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from auc.config import ModelConfig
    from auc.web.server import _state, create_app, init_web_state

    tmp = tempfile.mkdtemp()
    cfg = ModelConfig(provider="openai", model="test", api_key="sk-secret-123")
    init_web_state(sandbox=tmp, repo=None, cfg=cfg, evolve=False)
    _state["web_token"] = token
    return TestClient(create_app()), tmp


def test_ws_terminal_rejects_without_token() -> None:
    """token 模式下，未携带 token 的 WebSocket 握手必须被拒绝（防 PTY 裸奔）。"""
    from starlette.websockets import WebSocketDisconnect

    client, _ = _web_client(token="tok-1")
    try:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/terminal/ws") as ws:
                ws.receive_bytes()
    finally:
        from auc.web.server import _state

        _state["web_token"] = None


def test_ws_terminal_accepts_query_token() -> None:
    from auc.web.pty_terminal import terminal_available

    if not terminal_available():
        pytest.skip("PTY not available")
    client, _ = _web_client(token="tok-1")
    try:
        with client.websocket_connect("/api/terminal/ws?token=tok-1") as ws:
            ws.send_text('{"type":"resize","cols":80,"rows":24}')
    finally:
        from auc.web.server import _state

        _state["web_token"] = None


def test_preview_and_proxy_require_token() -> None:
    client, _ = _web_client(token="tok-2")
    try:
        assert client.get("/preview/index.html").status_code == 401
        assert client.get("/proxy/run-x/").status_code == 401
        assert client.get("/api/info").status_code == 401
        ok = client.get("/api/info", headers={"Authorization": "Bearer tok-2"})
        assert ok.status_code == 200
    finally:
        from auc.web.server import _state

        _state["web_token"] = None


def test_model_settings_never_echo_plaintext_key() -> None:
    client, _ = _web_client()
    data = client.get("/api/settings/model").json()
    assert "api_key" not in data
    assert data["api_key_set"] is True
    assert "sk-secret-123" not in str(data)
    assert data["api_key_masked"]  # 掩码仍供 UI 展示


def test_file_raw_blocks_auc_metadata() -> None:
    client, tmp = _web_client()
    auc_dir = Path(tmp) / ".auc"
    auc_dir.mkdir(parents=True, exist_ok=True)
    secret = auc_dir / "settings.local.json"
    secret.write_text('{"env": {"OPENAI_API_KEY": "sk-leak"}}', encoding="utf-8")
    resp = client.get("/api/workspace/file/raw", params={"path": ".auc/settings.local.json"})
    assert resp.status_code == 403
    # 常规文件仍可读取
    (Path(tmp) / "ok.txt").write_text("hello", encoding="utf-8")
    ok = client.get("/api/workspace/file/raw", params={"path": "ok.txt"})
    assert ok.status_code == 200
    assert ok.content == b"hello"


# --- P0：isolation fail-closed + eval 无 shell/路径校验 ------------------------

def test_isolation_fail_closed_when_docker_missing(monkeypatch) -> None:
    from auc import isolation
    from auc.isolation import IsolationConfig, IsolationUnavailableError, wrap_command

    monkeypatch.setattr(isolation, "docker_available", lambda: False)
    with pytest.raises(IsolationUnavailableError):
        wrap_command(["echo", "hi"], "/sb", IsolationConfig(mode="docker"))
    # 显式 opt-out 才降级本机
    out, note = wrap_command(
        ["echo", "hi"], "/sb", IsolationConfig(mode="docker", fail_closed=False)
    )
    assert out == ["echo", "hi"] and "降级" in note


def test_isolation_hardening_flags(monkeypatch) -> None:
    from auc import isolation
    from auc.isolation import IsolationConfig, wrap_command

    monkeypatch.setattr(isolation, "docker_available", lambda: True)
    out, _ = wrap_command(["echo", "hi"], "/sb", IsolationConfig(mode="docker"))
    assert "no-new-privileges" in out
    assert "--cap-drop" in out and "ALL" in out
    assert "--network" in out and "none" in out


def test_job_docker_fail_closed_marks_failed(monkeypatch, tmp_path: Path) -> None:
    """docker 不可用时，docker 隔离作业应落 failed，绝不静默在本机执行。"""
    from auc import isolation
    from auc.jobs import Job, JobStore, run_job

    monkeypatch.setattr(isolation, "docker_available", lambda: False)
    store = JobStore(str(tmp_path))
    job = Job(id="j-iso", message="do", sandbox=str(tmp_path), isolation="docker")
    store.save(job)
    called = {"n": 0}

    def _popen(*a, **k):  # noqa: ANN002, ANN003
        called["n"] += 1
        raise AssertionError("不应在本机启动子进程")

    out = run_job(job, store, popen=_popen)
    assert out.status == "failed"
    assert called["n"] == 0
    assert "docker" in (out.error or "")


def test_eval_run_command_no_shell_injection() -> None:
    """`run:` 校验命令不经 shell，元字符不触发注入。"""
    import tempfile

    from auc.evaluation import _run_command

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "pwned"
        # 若经 shell，`; touch pwned` 会创建文件；无 shell 时整串作为 argv 报错
        code, _out = _run_command(f"echo hi; touch {marker}", tmp)
        assert not marker.exists()
        # 正常参数式命令仍可执行
        code2, out2 = _run_command("echo hello", tmp)
        assert code2 == 0 and "hello" in out2


def test_eval_files_reject_path_traversal() -> None:
    from auc.evaluation import EvalCase, run_case

    case = EvalCase(id="evil", files={"../escape.txt": "x"}, checks=[])
    result = asyncio.run(run_case(case))
    assert result.passed is False
    assert result.status == "error"
    assert "越界" in (result.error or "")
