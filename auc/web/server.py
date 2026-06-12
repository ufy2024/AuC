from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from auc.chat_agent import ChatAgentOptions, build_chat_agent, resolve_sandbox_root
from auc.config import load_model_config
from auc.integration.evolution import evolution_paths
from auc.roles import load_role_catalog, role_evolution_paths
from auc.web.approval import WebApprovalPort
from auc.web.conversations import ConversationStore, messages_for_ui
from auc.web.session import WebSession
from auc.multimodal import is_image_path, strip_images_for_memory
from auc.web.preview import inject_preview_shim, is_html_path, media_type_for, resolve_preview_file
from auc.web.projects import discover_projects, project_to_dict
from auc.web.runner import ProjectRunner
from auc.web.workspace import (
    SandboxViolationError,
    list_tree,
    read_image_file,
    read_text_file,
    short_display_path,
    tree_to_dict,
    write_text_file,
)

try:
    from starlette.requests import Request
    from starlette.websockets import WebSocket
except ImportError:  # pragma: no cover - fastapi installs starlette
    Request = object  # type: ignore[misc, assignment]
    WebSocket = object  # type: ignore[misc, assignment]

_STATIC = Path(__file__).parent / "static"

_state: dict[str, Any] = {}


def _roles_payload(sandbox: str) -> list[dict[str, object]]:
    from auc.config import load_merged_settings
    from auc.roles import load_role_catalog, roles_payload

    settings: dict = {}
    try:
        settings, _ = load_merged_settings(None, None)
    except Exception:  # noqa: BLE001
        pass
    catalog = load_role_catalog(sandbox=sandbox, settings=settings)
    return roles_payload(catalog=catalog)


def _work_modes_payload() -> list[dict[str, str]]:
    from auc.work_mode import list_work_modes

    return [
        {
            "id": "auto",
            "label": "自动识别",
            "description": "根据消息内容智能选择最合适的工作模式",
            "phases": "自动",
        },
        *list_work_modes(),
    ]


def _get_approval() -> WebApprovalPort:
    port = _state.get("approval")
    if port is None:
        raise RuntimeError("web approval not initialized")
    return port


def _get_session() -> WebSession:
    session = _state.get("session")
    if session is None:
        raise RuntimeError("web session not initialized")
    return session


def create_app():  # noqa: ANN201
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:
        from auc.extras import hint_for

        raise ImportError(hint_for("web", "all")) from exc

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # noqa: ANN001, ARG001
        yield
        runner: ProjectRunner | None = _state.get("runner")
        if runner is not None:
            await runner.stop_all()
        agent = _state.get("agent")
        if agent is not None:
            from auc.model.factory import aclose_model_client

            await aclose_model_client(agent._config.model)  # noqa: SLF001

    app = FastAPI(title="AuC Web", version="0.2.6", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    @app.get("/api/info")
    async def api_info() -> JSONResponse:
        session = _get_session()
        cfg = session.cfg
        evolve = _state.get("evolve", True)
        role_catalog = load_role_catalog(sandbox=session.sandbox)
        active_role = role_catalog.active_role_id or role_catalog.default_role_id
        payload: dict[str, Any] = {
            "version": "0.2.6",
            "workspace": {
                "root": session.sandbox,
                "display": short_display_path(session.sandbox),
            },
            "model": {
                "provider": cfg.provider,
                "model": cfg.model,
                "configName": cfg.config_name,
                "configId": cfg.config_id,
            },
            "evolve": evolve,
            "turns": len([m for m in session.history if m.role == "user"]),
            "conversation": {
                "active_id": session.active_conversation_id,
                "messages": messages_for_ui(session.history),
            },
            "multimodal": True,
            "agent": {
                "id": session.agent.agent_id,
                "work_mode_default": "auto",
                "role_default": role_catalog.default_role_id,
                "active_role": active_role,
            },
            "roles": _roles_payload(session.sandbox),
            "work_modes": _work_modes_payload(),
        }
        if evolve:
            nug, evo = role_evolution_paths(session.sandbox, active_role)
            payload["evolution"] = {
                "evolution": short_display_path(str(evo)),
                "nuggets": short_display_path(str(nug)),
                "role_id": active_role,
                "legacy_global": short_display_path(str(evolution_paths(session.sandbox)[1])),
            }
        return JSONResponse(payload)

    def _runner() -> ProjectRunner:
        runner = _state.get("runner")
        if runner is None:
            raise HTTPException(500, "runner not initialized")
        return runner

    def _refresh_projects() -> None:
        session = _get_session()
        projects = discover_projects(session.sandbox)
        _state["projects"] = {p.id: p for p in projects}

    @app.get("/api/projects")
    async def api_projects() -> JSONResponse:
        _refresh_projects()
        runner = _runner()
        catalog = _state.get("projects", {})
        out = []
        for proj in catalog.values():
            inst = runner.get_by_project(proj.id)
            running = inst is not None and inst.status == "running"
            run_url = inst.url if running else None
            out.append(project_to_dict(proj, running=running, run_url=run_url))
        return JSONResponse({"projects": out})

    @app.post("/api/projects/run")
    async def api_project_run(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"invalid JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "body must be a JSON object")
        project_id = body.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise HTTPException(400, "project_id required")
        _refresh_projects()
        proj = _state.get("projects", {}).get(project_id)
        if proj is None:
            raise HTTPException(404, "project not found")
        inst = await _runner().start(proj)
        return JSONResponse(_runner().run_to_dict(inst))

    @app.post("/api/projects/stop")
    async def api_project_stop(request: Request) -> JSONResponse:
        body = await request.json()
        run_id = body.get("run_id")
        project_id = body.get("project_id")
        runner = _runner()
        if isinstance(run_id, str) and run_id:
            ok = await runner.stop(run_id)
        elif isinstance(project_id, str) and project_id:
            inst = runner.get_by_project(project_id)
            ok = await runner.stop(inst.run_id) if inst else False
        else:
            raise HTTPException(400, "run_id or project_id required")
        return JSONResponse({"ok": ok})

    @app.get("/preview/{file_path:path}")
    async def preview_file(file_path: str):  # noqa: ANN201
        from fastapi.responses import HTMLResponse

        session = _get_session()
        try:
            resolved = resolve_preview_file(session.sandbox, file_path)
        except SandboxViolationError as exc:
            raise HTTPException(403, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

        rel = file_path if not resolved.is_dir() else file_path.rstrip("/") + "/index.html"
        if is_html_path(rel) or resolved.suffix.lower() in {".html", ".htm"}:
            inst = _runner().get_active_backend()
            if inst is not None and inst.run_id:
                html = resolved.read_text(encoding="utf-8", errors="replace")
                body = inject_preview_shim(html, inst.run_id)
                return HTMLResponse(
                    content=body,
                    headers={"Cache-Control": "no-cache"},
                )

        return FileResponse(
            resolved,
            media_type=media_type_for(resolved),
            headers={"Cache-Control": "no-cache"},
        )

    async def _bridge_websocket(websocket, backend_uri: str | None, *, err: str | None) -> None:  # noqa: ANN001
        from fastapi import WebSocketDisconnect

        if err or not backend_uri:
            await websocket.accept()
            try:
                await websocket.send_json({"type": "error", "message": err or "unavailable"})
            except Exception:  # noqa: BLE001
                pass
            await websocket.close(code=1008, reason=err or "unavailable")
            return

        try:
            import websockets  # noqa: F811
        except ImportError:
            await websocket.accept()
            try:
                await websocket.send_json(
                    {"type": "error", "message": "websockets 未安装，请 pip install 'uvicorn[standard]'"}
                )
            except Exception:  # noqa: BLE001
                pass
            await websocket.close(code=1011, reason="websockets not installed")
            return

        await websocket.accept()

    @app.websocket("/proxy/{run_id}/ws")
    async def proxy_run_ws(run_id: str, websocket: WebSocket):  # noqa: ANN201
        from fastapi import WebSocketDisconnect

        inst = _runner().get(run_id)
        if inst is None or inst.port is None or inst.status != "running":
            await _bridge_websocket(websocket, None, err="run not found")
            return

        backend_uri = f"ws://127.0.0.1:{inst.port}/ws"
        await websocket.accept()

        async def client_to_backend(backend) -> None:  # noqa: ANN001
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    if msg.get("text") is not None:
                        await backend.send(msg["text"])
                    elif msg.get("bytes") is not None:
                        await backend.send(msg["bytes"])
            except WebSocketDisconnect:
                pass

        async def backend_to_client(backend) -> None:  # noqa: ANN001
            async for data in backend:
                if isinstance(data, str):
                    await websocket.send_text(data)
                else:
                    await websocket.send_bytes(data)

        try:
            import websockets

            async with websockets.connect(backend_uri) as backend:
                await asyncio.gather(client_to_backend(backend), backend_to_client(backend))
        except Exception:  # noqa: BLE001
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001
                pass

    @app.api_route(
        "/proxy/{run_id}/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
    async def proxy_run(run_id: str, path: str, request: Request):  # noqa: ANN201
        try:
            import httpx
        except ImportError as exc:
            raise HTTPException(500, "httpx required for proxy") from exc
        from fastapi.responses import Response

        inst = _runner().get(run_id)
        if inst is None or inst.port is None or inst.status != "running":
            raise HTTPException(404, "run not found")
        target = f"http://127.0.0.1:{inst.port}/{path}"
        if request.url.query:
            target += f"?{request.url.query}"
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length")
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.request(
                    request.method,
                    target,
                    headers=headers,
                    content=await request.body(),
                )
        except httpx.ConnectError as exc:
            if inst.process is not None and inst.process.returncode is not None:
                inst.status = "error"
                inst.error = inst.error or "项目进程已退出"
            raise HTTPException(
                502,
                f"无法连接项目服务 (127.0.0.1:{inst.port})，请停止后重新运行",
            ) from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "项目服务响应超时") from exc
        skip = {"transfer-encoding", "content-encoding", "content-length"}
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}
        return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)

    @app.get("/api/workspace/tree")
    async def api_tree(path: str = ".") -> JSONResponse:
        session = _get_session()
        try:
            tree = list_tree(session.sandbox, path)
        except SandboxViolationError as exc:
            raise HTTPException(403, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return JSONResponse(tree_to_dict(tree))

    @app.get("/api/workspace/file")
    async def api_read_file(path: str) -> JSONResponse:
        session = _get_session()
        try:
            if is_image_path(path):
                data = read_image_file(session.sandbox, path)
            else:
                data = read_text_file(session.sandbox, path)
        except SandboxViolationError as exc:
            raise HTTPException(403, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return JSONResponse(data)

    @app.put("/api/workspace/file")
    async def api_write_file(request: Request) -> JSONResponse:
        session = _get_session()
        body = await request.json()
        rel = body.get("path")
        content = body.get("content", "")
        if not isinstance(rel, str) or not rel:
            raise HTTPException(400, "path required")
        if not isinstance(content, str):
            raise HTTPException(400, "content must be string")
        try:
            data = write_text_file(session.sandbox, rel, content)
        except SandboxViolationError as exc:
            raise HTTPException(403, str(exc)) from exc
        return JSONResponse(data)

    @app.get("/api/chat/conversations")
    async def api_list_conversations() -> JSONResponse:
        session = _get_session()
        rows = session.store.list_summaries()
        return JSONResponse(
            {
                "active_id": session.active_conversation_id,
                "conversations": [r.to_dict() for r in rows],
            }
        )

    @app.post("/api/chat/conversations")
    async def api_new_conversation() -> JSONResponse:
        session = _get_session()
        if session.active_run_id:
            raise HTTPException(409, "对话生成中，请等待完成或取消后再新建")
        session.clear()
        return JSONResponse(
            {
                "ok": True,
                "conversation_id": session.active_conversation_id,
                "messages": [],
            }
        )

    @app.get("/api/chat/conversations/{conv_id}")
    async def api_get_conversation(conv_id: str) -> JSONResponse:
        session = _get_session()
        messages = session.store.load_messages(conv_id)
        summaries = {s.id: s for s in session.store.list_summaries()}
        meta = summaries.get(conv_id)
        return JSONResponse(
            {
                "id": conv_id,
                "title": meta.title if meta else "新对话",
                "messages": messages_for_ui(messages),
                "active": conv_id == session.active_conversation_id,
            }
        )

    @app.post("/api/chat/conversations/{conv_id}/switch")
    async def api_switch_conversation(conv_id: str) -> JSONResponse:
        session = _get_session()
        if not session.store.exists(conv_id):
            raise HTTPException(404, "对话不存在")
        if session.active_run_id:
            raise HTTPException(409, "对话生成中，请等待完成或取消后再切换")
        try:
            ui_messages = session.switch_conversation(conv_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        summaries = {s.id: s for s in session.store.list_summaries()}
        meta = summaries.get(conv_id)
        return JSONResponse(
            {
                "ok": True,
                "conversation_id": conv_id,
                "title": meta.title if meta else "新对话",
                "messages": ui_messages,
            }
        )

    @app.delete("/api/chat/conversations/{conv_id}")
    async def api_delete_conversation(conv_id: str) -> JSONResponse:
        session = _get_session()
        if not session.store.exists(conv_id):
            raise HTTPException(404, "对话不存在")
        was_active = session.active_conversation_id == conv_id
        session.store.delete(conv_id)
        if was_active:
            active = session.store.get_active_id()
            if active:
                ui_messages = session.switch_conversation(active)
            else:
                session.clear()
                ui_messages = []
                active = session.active_conversation_id
            return JSONResponse(
                {
                    "ok": True,
                    "active_id": active,
                    "messages": ui_messages,
                }
            )
        return JSONResponse({"ok": True})

    @app.post("/api/chat/clear")
    async def api_clear() -> JSONResponse:
        session = _get_session()
        if session.active_run_id:
            raise HTTPException(409, "对话生成中，请等待完成或取消后再清空")
        session.clear()
        return JSONResponse(
            {
                "ok": True,
                "conversation_id": session.active_conversation_id,
                "messages": [],
            }
        )

    @app.post("/api/chat/cancel")
    async def api_cancel() -> JSONResponse:
        session = _get_session()
        if session.active_run_id:
            session.agent.cancel(session.active_run_id)
        return JSONResponse({"ok": True})

    @app.post("/api/chat/approve")
    async def api_chat_approve(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"无效 JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "请求体必须是 JSON 对象")
        request_id = str(body.get("request_id") or "").strip()
        if not request_id:
            raise HTTPException(400, "request_id 不能为空")
        approved = bool(body.get("approved"))
        reason = str(body.get("reason") or ("用户拒绝" if not approved else ""))
        port = _get_approval()
        if not port.decide(request_id, approved=approved, reason=reason or None):
            raise HTTPException(404, "授权请求不存在或已过期")
        return JSONResponse({"ok": True, "approved": approved})

    @app.get("/api/chat/approvals")
    async def api_list_approvals() -> JSONResponse:
        """未决授权列表：前端启动/重连时拉取，找回丢失的授权卡片。"""
        port = _get_approval()
        return JSONResponse({"pending": port.list_pending()})

    @app.post("/api/qq/callback")
    async def api_qq_callback(request: Request) -> JSONResponse:
        """OneBot 11 反向 HTTP 上报入口：提取按钮回调 data 并登记 L3 决策（R24）。"""
        from auc.integration.qq import register_qq_callback

        try:
            body: Any = await request.json()
        except Exception:  # noqa: BLE001
            return JSONResponse({"ok": False, "ignored": True})
        if not isinstance(body, dict):
            return JSONResponse({"ok": False, "ignored": True})
        data = str(body.get("data") or body.get("raw") or "")
        decided_by = str(body.get("user_id") or body.get("decided_by") or "qq")
        decision = register_qq_callback(data, decided_by=decided_by)
        if decision is None:
            # OneBot 会上报心跳/普通消息等无关事件，静默忽略
            return JSONResponse({"ok": False, "ignored": True})
        return JSONResponse({"ok": True, "approved": decision.approved})

    @app.get("/api/chat/checkpoints")
    async def api_checkpoints(request: Request) -> JSONResponse:
        from auc.checkpoint import CheckpointStore

        session = _get_session()
        store = CheckpointStore(session.sandbox)
        run_id = (request.query_params.get("run_id") or "").strip()
        if not run_id:
            runs = store.list_runs()
            if not runs:
                return JSONResponse({"run_id": None, "entries": []})
            run_id = runs[0]
        entries = [
            {
                "step": e.step,
                "tool": e.tool,
                "op": e.op,
                "path": e.path,
                "command": e.command,
                "ts": e.ts,
            }
            for e in store.list_entries(run_id)
        ]
        return JSONResponse({"run_id": run_id, "entries": entries})

    @app.post("/api/chat/checkpoints/revert")
    async def api_checkpoints_revert(request: Request) -> JSONResponse:
        from auc.checkpoint import CheckpointStore

        try:
            body: Any = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"无效 JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "请求体必须是 JSON 对象")
        run_id = str(body.get("run_id") or "").strip()
        if not run_id:
            raise HTTPException(400, "run_id 不能为空")
        step = int(body.get("step") or 0)
        session = _get_session()
        if session.active_run_id:
            raise HTTPException(409, "对话生成中，请等待完成或取消后再回滚")
        store = CheckpointStore(session.sandbox)
        report = store.revert_to(run_id, step)
        return JSONResponse(
            {
                "ok": True,
                "run_id": run_id,
                "step": step,
                "restored": report.restored,
                "deleted": report.deleted,
                "warnings": report.warnings,
            }
        )

    @app.post("/api/chat/diagram-fix")
    async def api_diagram_fix(request: Request) -> JSONResponse:
        try:
            body: Any = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"无效 JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "请求体必须是 JSON 对象")
        code = (body.get("code") or "").strip()
        if not code:
            raise HTTPException(400, "code 不能为空")
        error = str(body.get("error") or "")
        force_agent = bool(body.get("force_agent"))
        session = _get_session()
        model = session.agent._config.model  # noqa: SLF001
        from auc.diagrams import fix_mermaid_diagram

        fixed, method = await fix_mermaid_diagram(
            model, code, error, force_agent=force_agent
        )
        return JSONResponse({"code": fixed, "method": method, "changed": fixed != code})

    def _chat_has_input(body: dict[str, Any]) -> bool:
        message = (body.get("message") or "").strip()
        images = body.get("images") or []
        ctx = body.get("context") if isinstance(body.get("context"), dict) else {}
        if message or images:
            return True
        if ctx.get("selection", "").strip():
            return True
        if ctx.get("auto_attach") and ctx.get("active_file"):
            return True
        return False

    @app.post("/api/chat/stream")
    async def api_chat_stream(request: Request) -> StreamingResponse:
        session = _get_session()
        try:
            body: Any = await request.json()
        except Exception as exc:  # noqa: BLE001
            body = {"__parse_error__": str(exc)}

        def _sse(obj: dict[str, Any]) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

        async def _gen():  # noqa: ANN202
            result = None
            status = "error"
            err: str | None = None
            run_conversation_id: str | None = None
            saved_conv_id: str | None = None
            try:
                if isinstance(body, dict) and "__parse_error__" in body:
                    yield _sse(
                        {
                            "type": "error",
                            "payload": {"message": f"无效 JSON: {body['__parse_error__']}"},
                        }
                    )
                    return
                if not isinstance(body, dict):
                    yield _sse(
                        {"type": "error", "payload": {"message": "请求体必须是 JSON 对象"}}
                    )
                    return
                if not _chat_has_input(body):
                    yield _sse(
                        {
                            "type": "error",
                            "payload": {
                                "message": "请输入消息，或打开文件并开启「附带当前文件」",
                            },
                        }
                    )
                    return

                message = (body.get("message") or "").strip()
                images = body.get("images")
                if images is not None and not isinstance(images, list):
                    yield _sse({"type": "error", "payload": {"message": "images 必须是数组"}})
                    return
                editor_context = body.get("context")
                if editor_context is not None and not isinstance(editor_context, dict):
                    yield _sse({"type": "error", "payload": {"message": "context 必须是对象"}})
                    return

                work_mode = body.get("work_mode") or "auto"
                role_id = body.get("role_id") or body.get("role") or "coder"
                autonomy = body.get("autonomy") or None
                approved_plan = body.get("approved_plan")
                if approved_plan is not None and not isinstance(approved_plan, dict):
                    yield _sse(
                        {"type": "error", "payload": {"message": "approved_plan 必须是对象"}}
                    )
                    return
                client_conv_id = (body.get("conversation_id") or "").strip() or None
                if (
                    client_conv_id
                    and session.active_conversation_id
                    and client_conv_id != session.active_conversation_id
                ):
                    yield _sse(
                        {
                            "type": "error",
                            "payload": {
                                "message": "对话已切换，请刷新后重试",
                                "code": "conversation_mismatch",
                            },
                        }
                    )
                    return
                try:
                    req, notes = session.prepare_request(
                        message,
                        images,
                        editor_context,
                        work_mode=work_mode,
                        autonomy=autonomy,
                        approved_plan=approved_plan,
                        role_id=role_id,
                    )
                except ValueError as exc:
                    yield _sse({"type": "error", "payload": {"message": str(exc)}})
                    return
                run_conversation_id = str(
                    (req.metadata or {}).get("conversation_id") or ""
                ) or session.active_conversation_id

                if notes:
                    yield _sse({"type": "note", "payload": {"notes": notes}})

                session.active_run_id = None
                # 注意：不要在 run_end 上提前 break——生成器收到 run_end 后会自行结束，
                # 其 finally 块负责设置 last_run_result；提前 break 会让结果丢失。
                async for ev in session.agent.run_stream(req):
                    if ev.type == "run_start":
                        session.active_run_id = ev.run_id
                    yield _sse(
                        {
                            "type": ev.type,
                            "run_id": ev.run_id,
                            "agent_id": ev.agent_id,
                            "payload": ev.payload,
                            "timestamp": ev.timestamp,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                yield _sse({"type": "error", "payload": {"message": str(exc)}})
            else:
                try:
                    saved_conv_id = session.apply_result(run_conversation_id)
                except Exception:  # noqa: BLE001
                    pass
                result = session.agent.last_run_result
                if (
                    result is not None
                    and result.status == "completed"
                    and session.agent._config.memory is not None  # noqa: SLF001
                ):
                    try:
                        await session.agent._config.memory.remember(  # noqa: SLF001
                            strip_images_for_memory(result.messages),
                            run_id=result.run_id,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                if result is not None:
                    status = result.status
                    err = result.error
            finally:
                session.active_run_id = None
                yield _sse(
                    {
                        "type": "done",
                        "payload": {
                            "status": status,
                            "error": err,
                            "output": (result.output or "")[:500] if result else "",
                            "conversation_id": saved_conv_id or run_conversation_id,
                        },
                    }
                )
                if status != "completed" and err:
                    yield _sse({"type": "error", "payload": {"message": err}})

        return StreamingResponse(
            _gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # 沙盒项目 API / WebSocket 转发（静态预览 /preview/ 时前端请求同源 /api、/ws）
    _AUC_API_ROOTS = frozenset({"info", "projects", "workspace", "chat"})

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
    async def sandbox_api_proxy(path: str, request: Request):  # noqa: ANN201
        try:
            import httpx
        except ImportError as exc:
            raise HTTPException(500, "httpx required for proxy") from exc
        from fastapi.responses import Response

        root = path.split("/")[0] if path else ""
        if root in _AUC_API_ROOTS:
            raise HTTPException(404, "Not Found")

        inst = _runner().get_active_backend()
        if inst is None or inst.port is None:
            raise HTTPException(
                404,
                "沙盒 API 未运行，请先在左侧项目栏启动 backend",
            )

        target = f"http://127.0.0.1:{inst.port}/api/{path}"
        if request.url.query:
            target += f"?{request.url.query}"
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length")
        }
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.request(
                    request.method,
                    target,
                    headers=headers,
                    content=await request.body(),
                )
        except httpx.ConnectError as exc:
            raise HTTPException(502, "沙盒 backend 未响应") from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "沙盒 backend 响应超时") from exc

        skip = {"transfer-encoding", "content-encoding", "content-length"}
        out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}
        return Response(content=resp.content, status_code=resp.status_code, headers=out_headers)

    @app.websocket("/ws")
    async def sandbox_ws_proxy(websocket: WebSocket):  # noqa: ANN201
        from fastapi import WebSocketDisconnect

        inst = _runner().get_active_backend()
        if inst is None or inst.port is None:
            await _bridge_websocket(websocket, None, err="请先启动 backend 项目")
            return

        backend_uri = f"ws://127.0.0.1:{inst.port}/ws"
        await websocket.accept()

        async def client_to_backend(backend) -> None:  # noqa: ANN001
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    if msg.get("text") is not None:
                        await backend.send(msg["text"])
                    elif msg.get("bytes") is not None:
                        await backend.send(msg["bytes"])
            except WebSocketDisconnect:
                pass

        async def backend_to_client(backend) -> None:  # noqa: ANN001
            async for data in backend:
                if isinstance(data, str):
                    await websocket.send_text(data)
                else:
                    await websocket.send_bytes(data)

        try:
            import websockets

            async with websockets.connect(backend_uri) as backend:
                await asyncio.gather(client_to_backend(backend), backend_to_client(backend))
        except Exception:  # noqa: BLE001
            try:
                await websocket.close()
            except Exception:  # noqa: BLE001
                pass

    return app


def init_web_state(
    *,
    sandbox: str,
    repo: str | None,
    cfg: Any,
    evolve: bool,
) -> None:
    opts = ChatAgentOptions(
        sandbox=sandbox,
        repo=repo,
        evolve=evolve,
    )
    root = resolve_sandbox_root(sandbox=sandbox, repo=repo)
    approval = WebApprovalPort()
    _state["approval"] = approval
    agent = build_chat_agent(cfg, opts, approval=approval)
    store = ConversationStore(root)
    conv_id, history = store.get_or_create_active()
    _state["agent"] = agent
    _state["evolve"] = evolve
    _state["session"] = WebSession(
        agent=agent,
        cfg=cfg,
        sandbox=root,
        store=store,
        history=history,
        active_conversation_id=conv_id,
    )
    _state["runner"] = ProjectRunner(root)
    projects = discover_projects(root)
    _state["projects"] = {p.id: p for p in projects}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="auc-web", description="AuC Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--sandbox", default="", help="Workspace root")
    parser.add_argument("--repo", default="", help="Repo root for .aurules")
    parser.add_argument("--config", "-c", default=None)
    parser.add_argument("--provider", "-p", choices=("openai", "anthropic", "deepseek"))
    parser.add_argument("--model", "-m", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--no-evolve", action="store_true")
    args = parser.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        from auc.extras import hint_for

        print(hint_for("web", "all"), flush=True)
        return 1

    repo = args.repo or None
    cfg = load_model_config(
        config_path=args.config,
        provider=args.provider,
        model=args.model,
        api_key=args.api_key,
        base_url=args.base_url,
        repo_root=repo,
    )
    sandbox = args.sandbox or args.repo or "."
    init_web_state(sandbox=sandbox, repo=repo, cfg=cfg, evolve=not args.no_evolve)

    app = create_app()
    print(
        f"AuC Web → http://{args.host}:{args.port}  "
        f"workspace: {short_display_path(_state['session'].sandbox)}",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
