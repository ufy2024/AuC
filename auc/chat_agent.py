from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from typing import TYPE_CHECKING

from auc import AgentConfig, DefaultAgent, DefaultToolRegistry
from auc.config import ModelConfig, load_merged_settings
from auc.integration.evolution import EvolutionMemoryPort, make_evolution_tools
from auc.loop.base import LoopConfig
from auc.model.factory import create_model_client
from auc.policy.autonomy import normalize_autonomy
from auc.policy.escalation import merge_escalation_settings
from auc.policy.privilege import ToolPrivilegeGate
from auc.ports import FileRulesPort, SlicerPolicy
from auc.ports.memory import DefaultComposer
from auc.tools.fetch import make_fetch_tool
from auc.tools.files import make_file_tools
from auc.tools.search import make_search_tools
from auc.tools.shell import make_shell_tool

if TYPE_CHECKING:
    from auc.ports.approval import ApprovalPort
from auc.work_mode import WORK_MODE_OVERVIEW, build_full_system_prompt

DEFAULT_CHAT_BASE = """\
你是编程助手。工作区根目录（沙盒）为：{sandbox}
在沙盒内你拥有完整文件系统权限（不可访问沙盒外路径）。

可用工具：
- read_file(path): 读取 UTF-8 文本
- write_file(path, content): 写入或创建文件
- list_dir(path): 列出目录（path 默认 .）
- delete_path(path): 删除文件或整个目录
- run_command(command, cwd?, timeout?): 沙盒内执行 shell 命令（跑测试/构建/git 等）；危险命令需用户授权
- grep_search(pattern, glob?): 按正则搜索文件内容，返回 path:line: text
- glob_files(pattern): 按名称模式找文件（按修改时间排序）
- save_lesson(tags, lesson): 固化可复用经验到进化库（跨会话）
- promote_nugget(nugget_id, tags, content): 将成功经验提升为金块技能

定位代码请优先 grep_search / glob_files，不要逐层 list_dir 遍历。
改完代码后用 run_command 跑测试验证（如 pytest），失败则修复后复跑。

进化能力（默认开启）：
- 每轮成功对话会自动写入 .auc/evolution.yaml
- 启动时会召回 .auc/au-nuggets.yaml 与历史经验

用户要求删除目录/文件时，必须使用 delete_path。
当用户需要代码或文件时，必须用 write_file 写入工作区。

外部链接：需要网页/文章正文时，使用 fetch_url(url, save_path?)。
该工具为 L3 高危操作，**必须经用户授权后才会发起网络请求**；未授权时不得声称已访问链接。
可将结果保存到沙盒文件（save_path）再用 read_file 分析。
write_file 参数必须是合法 JSON，且同时包含 path 与 content。
路径使用相对于沙盒的相对路径。

多模态：用户可通过 @图片路径 附加 png/jpg/gif/webp，请结合图片内容回答。

Web 编辑器：用户消息可能附带「当前文件」或「选中代码」。修改需求时：
1. 优先用 write_file 直接写入工作区，不要只贴代码不保存
2. 小范围改动保持原文件风格；大范围可拆分多文件
3. 改完后简要说明改了哪些文件

图表：说明架构、流程、状态时，用 Mermaid（```mermaid ... ```），Web 端会自动渲染。
支持 flowchart、sequenceDiagram、classDiagram、stateDiagram、erDiagram、gantt、pie、journey、gitGraph、mindmap、timeline、quadrantChart、C4、kanban、sankey、xychart 等全部类型。
Mermaid 语法要求：
- subgraph 标题含中文或标点时必须加双引号：subgraph "第一阶段：基础"
- 节点标签含 emoji、中文、/、空格时用双引号：A["求职 / 研究"]
- gantt 的 title/section/任务名含冒号、+、/、→ 或中文时用双引号："任务名" :id, after x, 3w
- 渲染失败时系统会自动尝试修复；若仍失败请输出修正后的完整 ```mermaid``` 块
"""

# 兼容测试与外部引用：含 {sandbox} 占位符的完整模板
DEFAULT_CHAT_SYSTEM = (
    DEFAULT_CHAT_BASE + "\n\n" + WORK_MODE_OVERVIEW
)


def build_chat_system_prompt(
    sandbox: str,
    *,
    extra: str | None = None,
    include_work_mode: bool = True,
) -> str:
    return build_full_system_prompt(
        sandbox,
        base=DEFAULT_CHAT_BASE,
        include_work_mode=include_work_mode,
        extra=extra,
    )


@dataclass
class ChatAgentOptions:
    sandbox: str
    repo: str | None = None
    system_prompt: str | None = None
    evolve: bool = True
    no_tools: bool = False
    max_steps: int = 40
    include_work_mode: bool = True


def resolve_sandbox_root(*, sandbox: str | None = None, repo: str | None = None) -> str:
    if sandbox:
        return str(Path(sandbox).expanduser().resolve())
    if repo:
        return str(Path(repo).expanduser().resolve())
    return str(Path.cwd().resolve())


def build_chat_agent(
    cfg: ModelConfig,
    opts: ChatAgentOptions,
    *,
    approval: ApprovalPort | None = None,
) -> DefaultAgent:
    sandbox = resolve_sandbox_root(sandbox=opts.sandbox, repo=opts.repo)
    try:
        settings, _ = load_merged_settings(
            None, Path(opts.repo) if opts.repo else None
        )
    except Exception:  # noqa: BLE001
        settings = {}
    memory = (
        EvolutionMemoryPort(sandbox_root=sandbox) if opts.evolve and not opts.no_tools else None
    )
    shell_settings = settings.get("shell") or {}
    registry = DefaultToolRegistry()
    if not opts.no_tools:
        for tool, pol in make_file_tools(sandbox):
            registry.register(tool, pol)
        shell_tool, shell_pol = make_shell_tool(
            sandbox,
            default_timeout=float(shell_settings.get("default_timeout") or 120),
            max_timeout=float(shell_settings.get("max_timeout") or 600),
        )
        registry.register(shell_tool, shell_pol)
        for tool, pol in make_search_tools(sandbox):
            registry.register(tool, pol)
        if memory is not None:
            for tool, pol in make_evolution_tools(memory):
                registry.register(tool, pol)
        for tool, pol in make_fetch_tool(sandbox):
            registry.register(tool, pol)

    gate = ToolPrivilegeGate(
        approval=approval,
        escalation_rules=merge_escalation_settings(settings.get("escalations")),
    )
    system = opts.system_prompt or build_chat_system_prompt(
        sandbox, include_work_mode=opts.include_work_mode
    )
    model = create_model_client(cfg)
    compaction = settings.get("compaction") or {}
    loop_config = LoopConfig(
        max_steps=opts.max_steps,
        context_token_limit=int(compaction.get("token_limit") or 96_000),
    )
    return DefaultAgent(
        AgentConfig(
            agent_id="chat",
            model=model,
            tools=registry,
            memory=memory,
            composer=DefaultComposer(),
            rules=FileRulesPort() if opts.repo else None,
            slicer_policy=SlicerPolicy(require_package=False),
            system_prompt=system,
            sandbox_root=sandbox,
            approval=approval,
            privilege_gate=gate,
            loop_config=loop_config,
            autonomy=normalize_autonomy(str(settings.get("autonomy") or "")),
        )
    )
