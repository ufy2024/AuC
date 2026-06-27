"""云端/容器隔离后端（R17/R18 增量）：把后台作业放进容器执行。

三强的「云端隔离」本质是「在独立环境跑 Run」。AuC 不绑定某云厂商，提供**本地 Docker 隔离**
作为可移植落点（与 Claude Code 的可选 Docker 镜像同思路），云端 runner 可在此抽象上替换：

- `mode="none"`（默认）：原样在本机子进程跑（现有 R17 行为）。
- `mode="docker"`：`docker run --rm -v <sandbox>:/work -w /work <image> <cmd>`，沙盒挂载进容器。
  `docker_available()` 探测 CLI；**缺失时安全降级**为本机执行并附告警，绝不阻断作业。

纯命令构造可测（不实际起容器）；零新增 Python 依赖。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

DEFAULT_IMAGE = "python:3.12-slim"


@dataclass
class IsolationConfig:
    mode: str = "none"  # none | docker
    image: str = DEFAULT_IMAGE
    network: str = "none"  # docker --network 值（默认禁网，更安全）
    extra_args: tuple[str, ...] = ()


def docker_available() -> bool:
    return shutil.which("docker") is not None


def wrap_command(
    cmd: list[str],
    sandbox: str,
    config: IsolationConfig,
) -> tuple[list[str], str]:
    """按隔离配置包装命令。返回 (最终命令, 说明/告警)。

    docker 不可用或 mode=none 时原样返回，说明里标注降级原因。
    """
    if config.mode != "docker":
        return cmd, ""
    if not sandbox:
        return cmd, "isolation: 缺少 sandbox 路径，降级为本机执行"
    if not docker_available():
        return cmd, "isolation: 未检测到 docker，降级为本机执行"
    docker_cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{sandbox}:/work",
        "-w",
        "/work",
    ]
    if config.network:
        docker_cmd += ["--network", config.network]
    docker_cmd += list(config.extra_args)
    docker_cmd.append(config.image)
    docker_cmd += cmd
    return docker_cmd, f"isolation: docker（{config.image}）"
