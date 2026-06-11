from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from auc.web.preview import is_html_path

ProjectKind = Literal["html", "static", "node", "python"]


@dataclass
class ProjectInfo:
    id: str
    name: str
    path: str
    kind: ProjectKind
    entry: str
    run_command: str | None = None
    description: str = ""


def _read_package_scripts(pkg_path: Path) -> dict[str, str]:
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    scripts = data.get("scripts") or {}
    return {k: str(v) for k, v in scripts.items() if isinstance(v, str)}


def _pick_npm_script(scripts: dict[str, str]) -> str | None:
    for name in ("dev", "start", "preview", "serve"):
        if name in scripts:
            return name
    return None


def discover_projects(sandbox_root: str, *, max_depth: int = 3) -> list[ProjectInfo]:
    root = Path(sandbox_root).resolve()
    found: list[ProjectInfo] = []
    seen: set[str] = set()

    def _add(proj: ProjectInfo) -> None:
        if proj.id in seen:
            return
        seen.add(proj.id)
        found.append(proj)

    def _scan_dir(directory: Path, rel: str, depth: int) -> None:
        if depth > max_depth:
            return
        pkg = directory / "package.json"
        if pkg.is_file():
            scripts = _read_package_scripts(pkg)
            script = _pick_npm_script(scripts)
            if script:
                _add(
                    ProjectInfo(
                        id=rel or ".",
                        name=directory.name if rel else root.name,
                        path=rel or ".",
                        kind="node",
                        entry=script,
                        run_command=f"npm run {script}",
                        description=f"npm scripts: {', '.join(sorted(scripts.keys())[:5])}",
                    )
                )
                return
        index = directory / "index.html"
        if index.is_file():
            entry = f"{rel}/index.html".lstrip("./") if rel else "index.html"
            _add(
                ProjectInfo(
                    id=rel or ".",
                    name=directory.name if rel else root.name,
                    path=rel or ".",
                    kind="html",
                    entry=entry,
                    description="静态 HTML · 可直接预览",
                )
            )
            return
        for py_name in ("main.py", "app.py", "run.py", "server.py"):
            py = directory / py_name
            if py.is_file():
                entry = f"{rel}/{py_name}".lstrip("./") if rel else py_name
                _add(
                    ProjectInfo(
                        id=rel or ".",
                        name=directory.name if rel else root.name,
                        path=rel or ".",
                        kind="python",
                        entry=entry,
                        run_command=f"uvicorn {py_name[:-3]}:app --host 127.0.0.1",
                        description="Python / FastAPI 项目",
                    )
                )
                return
        if depth < max_depth:
            try:
                children = sorted(
                    [p for p in directory.iterdir() if p.is_dir() and not p.name.startswith(".")],
                    key=lambda p: p.name.lower(),
                )
            except OSError:
                return
            for child in children[:40]:
                child_rel = f"{rel}/{child.name}".lstrip("./") if rel else child.name
                _scan_dir(child, child_rel, depth + 1)

    _scan_dir(root, "", 0)

    # 独立 HTML 文件（如 game.html）
    try:
        for item in sorted(root.rglob("*.html")):
            if item.name == "index.html":
                continue
            rel = str(item.relative_to(root))
            if rel.count("/") > max_depth:
                continue
            pid = f"file:{rel}"
            if pid in seen:
                continue
            _add(
                ProjectInfo(
                    id=pid,
                    name=item.stem,
                    path=str(item.parent.relative_to(root)) or ".",
                    kind="html",
                    entry=rel,
                    description="HTML 页面",
                )
            )
    except OSError:
        pass

    return found


def project_to_dict(p: ProjectInfo, *, running: bool = False, run_url: str | None = None) -> dict:
    preview_url = f"/preview/{p.entry}"
    return {
        "id": p.id,
        "name": p.name,
        "path": p.path,
        "kind": p.kind,
        "entry": p.entry,
        "run_command": p.run_command,
        "description": p.description,
        "preview_url": preview_url if p.kind == "html" or is_html_path(p.entry) else None,
        "running": running,
        "run_url": run_url,
    }
