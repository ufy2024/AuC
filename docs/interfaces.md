# AuC 接口参考

本文档描述 AuC 核心 **Protocol** 与 **数据类**：**已实现**部分与 `auc/` 源码对齐；**目标扩展**（R1–R23）标注为「规划中」，详见 [详细设计.md](详细设计.md)。

## 公共类型

```python
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol

AgentId = str
RunId = str

RunStatus = Literal[
    "completed", "max_steps", "cancelled", "error",
    "pending_approval", "denied",
]
MessageRole = Literal["system", "user", "assistant", "tool"]
ToolPrivilege = Literal["L1", "L2", "L3"]
```

## 消息与运行

### ChatMessage

与常见 Chat Completions API 对齐，并支持 tool 回合。

```python
@dataclass
class ChatMessage:
    role: MessageRole
    content: str
    tool_call_id: str | None = None   # role=tool 时必填
    name: str | None = None           # role=tool 时为工具名
    tool_calls: list["ToolCall"] | None = None  # role=assistant 时可选
```

### ToolCall / ToolResult

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]  # JSON 解析后的参数

@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
```

### RunRequest / RunResult

```python
@dataclass
class RunRequest:
    input: str | list[ChatMessage]
    run_id: RunId | None = None
    context_package: "ContextPackage | None" = None  # AuM Slicer 交付
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class RunResult:
    output: str
    messages: list[ChatMessage]
    status: RunStatus
    run_id: RunId
    error: str | None = None
```

`input` 为 `str` 时视为单条 `user` 消息；为 `list[ChatMessage]` 时用于多轮续聊或带 system 前缀。

## Agent

对外唯一门面（具体类名实现阶段可为 `DefaultAgent`）。

```python
class Agent(Protocol):
    @property
    def agent_id(self) -> AgentId: ...

    async def run(self, request: RunRequest) -> RunResult: ...

    async def run_stream(
        self, request: RunRequest
    ) -> AsyncIterator["RunEvent"]: ...

    def cancel(self, run_id: RunId) -> None: ...
```

### AgentConfig（构建用）

```python
@dataclass
class AgentConfig:
    agent_id: AgentId
    model: "ModelClient"
    tools: "ToolRegistry"
    loop: "AgentLoop" | None = None          # 默认 ReActLoop
    memory: "MemoryPort | None" = None
    composer: "ContextComposer | None" = None
    rules: "ProjectRulesPort | None" = None
    approval: "ApprovalPort | None" = None
    privilege_gate: "ToolPrivilegeGate | None" = None
    slicer_policy: "SlicerPolicy | None" = None
    loop_config: "LoopConfig" = field(default_factory=lambda: LoopConfig())
    system_prompt: str | None = None
```

## ModelClient（LLM 适配层）

不绑定 OpenAI、Anthropic 等具体厂商；通过适配器实现本协议。

```python
@dataclass
class AssistantMessage:
    content: str | None
    tool_calls: list[ToolCall] | None
    raw: dict[str, Any] | None = None  # 可选：保留厂商原始响应

@dataclass
class StreamChunk:
    delta_content: str | None = None
    delta_tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None

class ModelClient(Protocol):
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list["ToolSchema"] | None = None,
    ) -> AssistantMessage: ...

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        tools: list["ToolSchema"] | None = None,
    ) -> AsyncIterator[StreamChunk]: ...
```

### 计划中的适配器（实现阶段）

| 适配器 | 说明 |
|--------|------|
| `OpenAICompatibleClient` | OpenAI 及兼容 API |
| `AnthropicClient` | Anthropic Messages API |
| `InMemoryModelClient` | 测试用固定响应 |

## Tool 与 ToolRegistry

```python
@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object

class Tool(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...
    @property
    def parameters(self) -> dict[str, Any]: ...

    async def invoke(self, arguments: dict[str, Any]) -> ToolResult: ...

@dataclass
class ToolPolicy:
    name: str
    privilege: ToolPrivilege
    sandbox_only: bool = False
    mutates_files: bool = False    # 规划中 R4：写类工具，触发检查点
    mutates_state: bool = False    # 规划中 R6：受自治级别管控（shell/git 等）

class ToolRegistry(Protocol):
    def register(self, tool: Tool, policy: ToolPolicy | None = None) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def get_policy(self, name: str) -> ToolPolicy: ...
    def list_schemas(self) -> list[ToolSchema]: ...

class ToolPrivilegeGate(Protocol):
    async def check_and_invoke(
        self,
        tool: Tool,
        policy: ToolPolicy,
        arguments: dict[str, Any],
        *,
        ctx: "LoopContext",
    ) -> ToolResult | "PendingApproval": ...

@dataclass
class PendingApproval:
    request_id: str
    tool_call: ToolCall
    run_id: RunId
```

实现阶段可提供 `@tool` 装饰器，从函数签名生成 `ToolSchema`；`privilege` 可由 `@tool(privilege="L2")` 指定。

### Tool 扩展说明（文档级）

| 扩展类型 | 实现方式 |
|----------|----------|
| 本地函数 | 实现 `Tool` 或装饰器注册 |
| HTTP 远程工具 | `Tool` 包装层，AuC 不内置 HTTP 客户端配置 |
| MCP | 独立适配包将 MCP tool 转为 `Tool` 实例后 `register` |

AuC 核心只依赖 `Tool` 协议，不耦合 MCP 或 HTTP 细节。

## ContextWindow（短期上下文）

```python
@dataclass
class TruncatePolicy:
    max_messages: int | None = None
    max_tokens: int | None = None
    strategy: Literal["drop_oldest", "drop_middle", "summarize"] = "drop_oldest"

class ContextWindow(Protocol):
    def append(self, message: ChatMessage) -> None: ...
    def view(self) -> list[ChatMessage]: ...
    def truncate(self, policy: TruncatePolicy) -> None: ...
    def clear(self) -> None: ...
```

**现状**：`ListContextWindow.truncate` 实现 `drop_oldest`、`drop_middle`；`summarize` 枚举已声明但未实现。

**规划（R3）**：`SummarizingCompactor` 在 compose 前对 window 做两级压缩（tool 折叠 → 模型摘要），见 [详细设计.md](详细设计.md) §3。AuM 亦可提供替换实现（见 [aum-integration.md](aum-integration.md)）。

## MemoryPort 与 ContextComposer（AuM 实现）

```python
class MemoryPort(Protocol):
    """由 AuM 实现；AuC 在 Loop 每步前后可选调用。"""

    async def recall(
        self,
        query: str,
        limit: int = 10,
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> list[ChatMessage]: ...

    async def remember(
        self,
        items: list[ChatMessage],
        *,
        run_id: RunId | None = None,
        agent_id: AgentId | None = None,
    ) -> None: ...

class ContextComposer(Protocol):
    """合并 Memory 召回与 ContextWindow，得到送入 ModelClient 的消息列表。"""

    async def compose(
        self,
        window: ContextWindow,
        recall: list[ChatMessage],
        *,
        system_prompt: str | None = None,
    ) -> list[ChatMessage]: ...
```

AuC **不**定义 embedding、chunking、存储后端；这些属于 AuM。

## ContextPackage（AuM Slicer 产出）

```python
@dataclass
class CodeSnippet:
    path: str
    content: str
    line_range: tuple[int, int] | None = None
    relevance_score: float | None = None

@dataclass
class ContextPackage:
    package_id: str
    intent_summary: str
    snippets: list[CodeSnippet]
    token_estimate: int
    provenance: dict[str, Any] = field(default_factory=dict)

@dataclass
class SlicerPolicy:
    require_package: bool = True
    max_ad_hoc_read_bytes: int = 8192
    allow_full_repo_grep: bool = False
```

详见 [context-slicer.md](context-slicer.md)。

## ProjectRulesPort（AuM 解析 .aurules）

```python
@dataclass
class ProjectRules:
    version: int
    build_commands: list[str]
    test_commands: list[str]
    style_notes: list[str]
    tool_policy: dict[str, ToolPrivilege]  # 工具名 -> L1/L2/L3
    sandbox_root: str | None = None
    raw_markdown: str | None = None

class ProjectRulesPort(Protocol):
    async def load_rules(self, repo_root: str) -> ProjectRules: ...
```

`ContextComposer.compose` 增加可选参数：`rules: ProjectRules | None`、`package: ContextPackage | None`。详见 [aurules.md](aurules.md)。

## ApprovalPort（AuM IM 2FA）

```python
@dataclass
class ApprovalRequest:
    request_id: str
    run_id: RunId
    agent_id: AgentId
    tool_name: str
    arguments: dict[str, Any]
    diff_text: str
    risk_summary: str

@dataclass
class ApprovalDecision:
    approved: bool
    decided_by: str | None = None  # user_id / telegram chat id / qq user id
    reason: str | None = None

class ApprovalPort(Protocol):
    async def request_approval(self, req: ApprovalRequest) -> str: ...
    async def wait_decision(
        self, request_id: str, timeout: float = 3600.0
    ) -> ApprovalDecision: ...
```

详见 [tool-privilege.md](tool-privilege.md)。

## AgentLoop

```python
@dataclass
class LoopConfig:
    max_steps: int = 20
    stop_sequences: list[str] = field(default_factory=list)
    parallel_tool_calls: bool = True
    remember_each_step: bool = False  # 为 True 时每步结束调用 memory.remember

@dataclass
class LoopContext:
    agent_id: AgentId
    run_id: RunId
    window: ContextWindow
    tools: ToolRegistry
    model: ModelClient
    events: "EventBus"
    config: LoopConfig
    memory: MemoryPort | None = None
    composer: ContextComposer | None = None
    context_package: ContextPackage | None = None
    project_rules: ProjectRules | None = None
    privilege_gate: ToolPrivilegeGate | None = None
    approval: ApprovalPort | None = None
    system_prompt: str | None = None
    cancelled: bool = False

@dataclass
class LoopStepResult:
    assistant_message: AssistantMessage | None
    tool_results: list[ToolResult]
    step_index: int
    done: bool  # 本步后是否应结束 Run（如无 tool_calls 且已有最终答案）

class AgentLoop(Protocol):
    async def step(self, ctx: LoopContext) -> LoopStepResult: ...

    def should_continue(
        self, ctx: LoopContext, last: LoopStepResult
    ) -> bool: ...

class AgentLoopRunner(Protocol):
    async def run_until_done(
        self, loop: AgentLoop, ctx: LoopContext
    ) -> RunResult: ...
```

默认 `should_continue` 逻辑（可由具体 Loop 覆盖）：

- `ctx.cancelled` → 停止
- `step_index >= config.max_steps` → 停止
- `last.done` → 停止
- 否则继续

## 事件

```python
RunEventType = Literal[
    "run_start",
    "step_start",
    "model_delta",
    "tool_start",
    "tool_end",
    "approval_required",
    "approval_granted",
    "approval_denied",
    "step_end",
    "run_end",
]

@dataclass
class RunEvent:
    type: RunEventType
    run_id: RunId
    agent_id: AgentId
    payload: dict[str, Any]
    timestamp: float | None = None

class EventBus(Protocol):
    def emit(self, event: RunEvent) -> None: ...
    def subscribe(
        self, handler: "Callable[[RunEvent], None]"
    ) -> "Unsubscribe": ...
```

`run_stream` 将 Run 期间事件以 `AsyncIterator[RunEvent]` 形式产出；订阅者与流式消费可并存。

## 测试替身（实现阶段）

| 替身 | 用途 |
|------|------|
| `InMemoryModelClient` | 返回预设 `AssistantMessage` 或 `tool_calls` |
| `EchoTool` | `invoke` 回显 arguments |
| `ListContextWindow` | 内存列表实现 `ContextWindow` |
| `NoOpMemoryPort` | 空 recall / remember |

## 角色（R25，已实现）

```python
@dataclass(frozen=True)
class RoleSpec:
    id: RoleId          # coder | reviewer | architect | tutor | ops
    label: str
    title: str
    description: str
    capabilities: tuple[str, ...]
    persona: str        # 含 {sandbox} 占位符
    default_work_mode: str

def build_role_system_prompt(
    sandbox: str,
    role_id: str | None = None,
    *,
    include_work_mode: bool = True,
    extra: str | None = None,
) -> str: ...

def roles_payload() -> list[dict[str, object]]: ...  # Web /api/info
```

- **Run 元数据**：`metadata.role_id` 选择角色；`apply_role_prompt=False` 时仅影响进化分片、不覆盖自定义 `system_prompt`。
- **agent_id**：对话场景为 `chat:{role_id}`，供 `MemoryPort.recall/remember` 过滤。
- **进化标签**：episode/nugget 自动附加 `role:{id}`；`metadata.role_id` 冗余存储；无 `role:` 前缀的遗留条目对所有角色召回。

**目录布局**（每角色一个子文件夹）：

```
auc/roles/coder/              # 系统推荐（随包发布）
  role.yaml                   # 元数据
  prompt.md                   # 提示词（{sandbox}）
  evolution.yaml / nuggets.yaml

{sandbox}/.auc/roles/
  active                      # 当前角色 id（单行）
  stock-analyst/              # 沙盒自定义角色（结构同上）
    role.yaml
    prompt.md
    evolution.yaml
    nuggets.yaml
```

`role id` = 文件夹名（小写字母开头，`a-z0-9_-`）。遗留 `.auc/roles.yaml` 与 `settings.json` 的 `"roles"` 对象仍可读。

CLI：`auc chat --role stock-analyst`；REPL `/role translator`。Web：请求体 `role_id`，`/api/info.roles`。

## 目标扩展（规划中）

以下类型随 [架构设计.md](架构设计.md) M1–M3 落地；完整签名见 [详细设计.md](详细设计.md)。

```python
AutonomyLevel = Literal["confirm-all", "auto-edit", "full-auto"]  # R6

# RunEventType 增量（R3–R23，只增不改）
# context_compacted, checkpoint_created, plan_ready, todos_updated,
# usage_updated, subagent_start, subagent_end, evolution_lesson, skill_promoted

@dataclass
class Usage:  # R11
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    estimated: bool = False

@dataclass
class TodoItem:  # R10
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "cancelled"]
```

`LoopContext` 规划字段：`autonomy`、`todos`、`usage`、`parent_run_id`、`checkpoints`、`compactor`、`hooks`（详见 [详细设计.md](详细设计.md) §2–4）。

工具裁决链顺序见 [adr/006-tool-decision-chain.md](adr/006-tool-decision-chain.md)。

IM 二次授权端口（已实现 / 规划中）：

| 类 | 说明 |
|----|------|
| `ConsoleApprovalPort` | 终端 y/n |
| `TelegramApprovalPort` | 继承 `HttpImApprovalPort` |
| `QQApprovalPort` | 继承 `HttpImApprovalPort`（R24） |
| `WebApprovalPort` | Web 弹窗 |

详见 [详细设计.md](详细设计.md) §12。

## 相关文档

- [design-philosophy.md](design-philosophy.md)
- [context-slicer.md](context-slicer.md)
- [aurules.md](aurules.md)
- [tool-privilege.md](tool-privilege.md)
- [architecture.md](architecture.md) — 现状 As-Is
- [架构设计.md](架构设计.md) — 目标 To-Be
- [详细设计.md](详细设计.md)
- [loops.md](loops.md)
- [aum-integration.md](aum-integration.md)
