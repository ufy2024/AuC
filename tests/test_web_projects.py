import asyncio
import tempfile
from pathlib import Path

from auc.web.preview import is_html_path, resolve_preview_file
from auc.web.projects import discover_projects, project_to_dict
from auc.web.runner import ProjectRunner


def test_discover_html_game() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        game = Path(tmp) / "snake-game"
        game.mkdir()
        (game / "index.html").write_text("<html><body>game</body></html>", encoding="utf-8")
        projects = discover_projects(tmp)
        assert any(p.entry.endswith("index.html") for p in projects)
        html = next(p for p in projects if "snake" in p.name or "snake" in p.entry)
        d = project_to_dict(html)
        assert d["preview_url"].startswith("/preview/")


def test_preview_resolve() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "a.html"
        p.write_text("<h1>hi</h1>", encoding="utf-8")
        assert is_html_path("a.html")
        resolved = resolve_preview_file(tmp, "a.html")
        assert resolved.name == "a.html"


def test_runner_html_preview() -> None:
    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("ok", encoding="utf-8")
            from auc.web.projects import discover_projects

            proj = discover_projects(tmp)[0]
            runner = ProjectRunner(tmp)
            inst = await runner.start(proj)
            assert inst.status == "running"
            assert inst.url == f"/preview/{proj.entry}"
            await runner.stop_all()

    asyncio.run(_run())


def test_runner_python_uvicorn() -> None:
    pytest = __import__("pytest")
    pytest.importorskip("uvicorn")
    pytest.importorskip("fastapi")

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                '@app.get("/")\n'
                "def root():\n"
                '    return {"ok": True}\n',
                encoding="utf-8",
            )
            proj = discover_projects(tmp)[0]
            runner = ProjectRunner(tmp)
            inst = await runner.start(proj)
            try:
                assert inst.status == "running", inst.error
                assert inst.port is not None
                assert inst.url == f"/proxy/{inst.run_id}/"
                from auc.web.runner import _port_open

                assert _port_open(inst.port)
            finally:
                await runner.stop_all()

    asyncio.run(_run())


def test_runner_python_nested_backend() -> None:
    pytest = __import__("pytest")
    pytest.importorskip("uvicorn")
    pytest.importorskip("fastapi")

    async def _run() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = Path(tmp) / "backend"
            backend.mkdir()
            (backend / "main.py").write_text(
                "from fastapi import FastAPI\n"
                "app = FastAPI()\n"
                '@app.get("/")\n'
                "def root():\n"
                '    return {"ok": True}\n',
                encoding="utf-8",
            )
            proj = next(p for p in discover_projects(tmp) if p.id == "backend")
            assert proj.entry == "backend/main.py"
            runner = ProjectRunner(tmp)
            inst = await runner.start(proj)
            try:
                assert inst.status == "running", inst.error
                assert inst.port is not None
                from auc.web.runner import _port_open

                assert _port_open(inst.port)
            finally:
                await runner.stop_all()

    asyncio.run(_run())
