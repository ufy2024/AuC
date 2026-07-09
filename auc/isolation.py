"""云端/容器隔离后端（R17/R18 增量）：把后台作业放进容器执行。

三强的「云端隔离」本质是「在独立环境跑 Run」。AuC 不绑定某云厂商，提供**本地 Docker 隔离**
作为可移植落点（与 Claude Code 的可选 Docker 镜像同思路），云端 runner 可在此抽象上替换：

- `mode="none"`（默认）：原样在本机子进程跑（现有 R17 行为）。
- `mode="docker"`：`docker run --rm -v <sandbox>:/work -w /work <image> <cmd>`，沙盒挂载进容器。

安全模型（fail-closed）：
  用户显式选择 `docker` 隔离即代表**不信任在本机直接执行**。因此当 docker CLI 缺失或
  缺 sandbox 路径时，**默认拒绝执行并报错**（`IsolationUnavailableError`），而非静默降级到
  本机——静默降级会让用户误以为已隔离却在裸机跑不受信代码。如确需「尽力隔离、失败回退本机」
  的旧行为，显式设 `fail_closed=False`。
  容器默认加固：`--network none`（禁网）、`--security-opt no-new-privileges`、
  `--cap-drop ALL`；可选 `read_only=True` 以只读挂载沙盒（防容器内篡改 `.git`/`.auc`）。

纯命令构造可测（不实际起容器）；零新增 Python 依赖。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

DEFAULT_IMAGE = "python:3.12-slim"


class IsolationUnavailableError(RuntimeError):
    """请求 docker 隔离但环境不满足（fail-closed 时抛出，绝不静默降级到本机）。"""


@dataclass
class IsolationConfig:
    mode: str = "none"  # none | docker
    image: str = DEFAULT_IMAGE
    network: str = "none"  # docker --network 值（默认禁网，更安全）
    extra_args: tuple[str, ...] = ()
    fail_closed: bool = True  # docker 不可用时拒绝执行（默认），而非降级本机
    read_only: bool = False  # 只读挂载沙盒（防容器内改 .git/.auc）；默认读写以便写产物
    harden: bool = True  # no-new-privileges + cap-drop ALL


def docker_available() -> bool:
    return shutil.which("docker") is not None


def wrap_command(
    cmd: list[str],
    sandbox: str,
    config: IsolationConfig,
) -> tuple[list[str], str]:
    """按隔离配置包装命令。返回 (最终命令, 说明/告警)。

    - `mode != "docker"`：原样返回。
    - docker 不可用 / 缺 sandbox：`fail_closed=True`（默认）抛
      `IsolationUnavailableError`；`fail_closed=False` 时原样返回并在说明里标注降级原因。
    """
    if config.mode != "docker":
        return cmd, ""
    if not sandbox:
        if config.fail_closed:
            raise IsolationUnavailableError(
                "isolation: 请求 docker 隔离但缺少 sandbox 路径，已拒绝执行"
                "（设 fail_closed=False 可降级本机）"
            )
        return cmd, "isolation: 缺少 sandbox 路径，降级为本机执行"
    if not docker_available():
        if config.fail_closed:
            raise IsolationUnavailableError(
                "isolation: 请求 docker 隔离但未检测到 docker CLI，已拒绝执行"
                "（安装 docker，或设 fail_closed=False 降级本机）"
            )
        return cmd, "isolation: 未检测到 docker，降级为本机执行"
    mount = f"{sandbox}:/work:ro" if config.read_only else f"{sandbox}:/work"
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        mount,
        "-w",
        "/work",
    ]
    if config.harden:
        docker_cmd += ["--security-opt", "no-new-privileges", "--cap-drop", "ALL"]
    if config.network:
        docker_cmd += ["--network", config.network]
    docker_cmd += list(config.extra_args)
    docker_cmd.append(config.image)
    docker_cmd += cmd
    ro = "、只读挂载" if config.read_only else ""
    return docker_cmd, f"isolation: docker（{config.image}{ro}）"
