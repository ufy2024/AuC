# AuC 接口草案

本文档描述 AuC 核心 **Protocol** 与 **数据类** 草案，为 Python 伪代码，**非可运行实现**。实现时应保持签名与语义一致，并补充 `py.typed` 与单元测试。

## 公共类型

```python
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal, Protocol

AgentId = str
RunId = str

RunStatus = Literal["completed", "max_steps", "cancelled", "error"]
MessageRole = Literal["system", "user", "assistant", "tool"]
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

class ToolRegistry(Protocol):
    def register(self, tool: Tool) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def list_schemas(self) -> list[ToolSchema]: ...
```

实现阶段可提供 `@tool` 装饰器，从函数签名生成 `ToolSchema`。

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

`truncate` 在 token 超限等场景由 Loop 或 Agent 触发；智能摘要实现可由 AuM 提供并注入自定义 `TruncatePolicy` 处理器（见 [aum-integration.md](aum-integration.md)）。

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

## 相关文档

- [architecture.md](architecture.md)
- [loops.md](loops.md)
- [aum-integration.md](aum-integration.md)
