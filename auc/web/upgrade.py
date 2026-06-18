"""Web 一键升级：在当前 Python 环境中 pip install -U。"""

from __future__ import annotations

import asyncio
import importlib.metadata
import importlib.util
import re
import sys
from typing import Any

from auc import __version__
from auc.version_check import (
    PYPI_PACKAGE,
    PYPI_SIMPLE_INDEX,
    fetch_latest_version,
    is_newer,
    release_info,
)

_PIP_OK = re.compile(r"Successfully installed", re.I)


def infer_pip_install_spec() -> str:
    """根据已安装的可选组件推断 pip 升级 spec。"""
    extras: list[str] = []
    for mod, tag in (
        ("fastapi", "web"),
        ("httpx", "llm"),
        ("prompt_toolkit", "cli"),
    ):
        if importlib.util.find_spec(mod) and tag not in extras:
            extras.append(tag)
    if "web" in extras:
        return f"{PYPI_PACKAGE}[web]"
    if "llm" in extras and "cli" in extras:
        return f"{PYPI_PACKAGE}[chat]"
    if extras:
        return f'{PYPI_PACKAGE}[{",".join(extras)}]'
    return PYPI_PACKAGE


def _installed_distribution_version() -> str | None:
    try:
        return importlib.metadata.version(PYPI_PACKAGE)
    except importlib.metadata.PackageNotFoundError:
        return None


def _upgrade_achieved(
    before: str | None,
    after: str | None,
    latest: str | None,
) -> bool:
    if not after:
        return False
    if before and is_newer(after, before):
        return True
    if latest and not is_newer(latest, after):
        return True
    return False


def _mirror_stale_output(output: str) -> bool:
    low = output.lower()
    pkg = PYPI_PACKAGE.lower()
    return (
        "requirement already satisfied" in low
        and pkg in low
        and not _PIP_OK.search(output)
    )


def _pip_install(
    spec: str,
    *,
    index_url: str | None = None,
    timeout: float,
) -> tuple[int, str]:
    import subprocess

    cmd = [sys.executable, "-m", "pip", "install", "-U", spec]
    if index_url:
        cmd.extend(["--index-url", index_url])
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, output


def run_pip_upgrade(*, timeout: float = 180.0) -> dict[str, Any]:
    """同步执行 pip upgrade，返回结果摘要。"""
    import subprocess

    spec = infer_pip_install_spec()
    before = _installed_distribution_version()

    import auc.version_check as vc

    vc._cache_latest = None
    vc._cache_at = 0.0
    latest = fetch_latest_version(force=True)

    outputs: list[str] = []
    ok = False
    used_official_index = False

    try:
        for index_url in (None, PYPI_SIMPLE_INDEX):
            if index_url is not None:
                if before and latest and not is_newer(latest, before):
                    break
                used_official_index = True
            returncode, chunk = _pip_install(spec, index_url=index_url, timeout=timeout)
            outputs.append(chunk)
            after = _installed_distribution_version()
            if _upgrade_achieved(before, after, latest):
                ok = True
                break
            if index_url is None and not _mirror_stale_output(chunk):
                if returncode != 0 or not _PIP_OK.search(chunk):
                    break
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") + (exc.stderr or "")
        return {
            "ok": False,
            "spec": spec,
            "pip_output": out[-4000:],
            "message": "升级超时，请稍后在终端手动执行 pip install",
        }

    output = "\n---\n".join(outputs)
    installed = _installed_distribution_version()

    if not ok and installed and before and is_newer(installed, before):
        ok = True

    manual_cmd = f"pip install -U {spec} -i {PYPI_SIMPLE_INDEX}"
    if ok:
        message = (
            f"已升级到 v{installed}，请重启 auc web 使新版本生效"
            if installed
            else "升级完成，请重启 auc web"
        )
    elif used_official_index:
        message = f"升级失败，请手动执行：{manual_cmd}"
    elif before and latest and is_newer(latest, before):
        message = (
            f"镜像源可能未同步最新版，请手动执行：{manual_cmd}"
        )
    else:
        message = "升级失败，请查看输出或在终端手动执行"

    return {
        "ok": ok,
        "spec": spec,
        "pip_output": output[-8000:],
        "runtime_version": __version__,
        "installed_version": installed,
        "latest_version": latest,
        "restart_required": ok,
        "message": message,
        "manual_cmd": manual_cmd,
    }


async def upgrade_package(*, timeout: float = 180.0) -> dict[str, Any]:
    before = release_info(force=True)
    if not before.get("update_available"):
        return {
            "ok": True,
            "skipped": True,
            "message": "当前已是最新版本，无需升级",
            "release": before,
        }
    result = await asyncio.to_thread(run_pip_upgrade, timeout=timeout)
    result["release"] = release_info(force=True)
    if result.get("ok"):
        inst = result.get("installed_version")
        runtime = result.get("runtime_version")
        latest = result.get("latest_version")
        if inst and runtime and is_newer(inst, runtime):
            result["message"] = f"已升级到 v{inst}，请重启 auc web 使新版本生效"
        elif latest and inst and not is_newer(latest, inst):
            result["message"] = f"已升级到 v{inst}（PyPI 最新 v{latest}），请重启 auc web"
    return result
