# AuC 架构总览

AuC（**Agents-ufy-Core**）是 ufy 智能体体系中的**单智能体核心框架**：用 Python 与 asyncio 实现可终止的「推理—行动」循环，不内置长期记忆与多智能体编排。AuM 在 AuC 定义的端口之上提供记忆与持久化能力。

## 设计原则

1. **最小核心** — AuC 只保证一个 Agent 能完成一轮可终止的推理—行动循环；不内置 RAG、向量检索或跨会话记忆。
2. **端口隔离** — 通过 `MemoryPort`、`ContextComposer` 将「记什么、怎么检索」交给 AuM；AuC 仅持有当前 Run 的 `ContextWindow`（短期工作区）。
3. **可观测** — `EventBus` 与结构化 `RunEvent`（`step_start`、`tool_call`、`model_chunk`、`run_end` 等），便于日志、调试与 UI。
4. **可测试** — Loop、Tool、`ModelClient` 均面向接口；实现阶段提供 `InMemoryModelClient`、`EchoTool` 等测试替身。
5. **类型优先** — 接口以 `typing.Protocol` 与 `@dataclass` 描述，为后续 `py.typed` 包铺路。

## 系统上下文

```mermaid
flowchart TB
  subgraph auc [AuC Core]
    Agent[Agent]
    Loop[AgentLoop]
    Tools[ToolRegistry]
    LLM[ModelClient]
    Ctx[ContextWindow]
    Events[EventBus]
  end
  subgraph aum [AuM 未来层]
    MemPort[MemoryPort]
    Store[SessionStore]
  end
  User --> Agent
  Agent --> Loop
  Loop --> LLM
  Loop --> Tools
  Loop --> Ctx
  Agent --> Events
  Ctx -.->|可选扩展| MemPort
  MemPort -.-> Store
```

| 组件 | 职责 |
|------|------|
| **Agent** | 对外入口：`run` / `run_stream` / `cancel` |
| **AgentLoop** | 可插拔推理策略（默认 `ReActLoop`） |
| **AgentLoopRunner** | 驱动 Loop 直至终止条件 |
| **ModelClient** | LLM 适配（不绑定单一厂商） |
| **ToolRegistry** | 工具注册与 schema 暴露 |
| **ContextWindow** | 当前 Run 的消息工作区 |
| **EventBus** | Run 生命周期事件分发 |
| **MemoryPort**（端口） | 由 AuM 实现；AuC 仅调用 |

多智能体编排不在 AuC 范围内；若未来需要，可另立独立仓库（例如 AuO）。

## 建议包结构

实现阶段采用如下布局（当前仓库仅文档，尚未创建源码目录）：

```
auc/
├── agent.py          # Agent, AgentConfig, Agent.run()
├── loop/
│   ├── base.py       # AgentLoop Protocol, LoopContext, LoopResult
│   └── react.py      # ReActLoop（默认）
├── model/
│   └── client.py     # ModelClient, ChatMessage, StreamChunk
├── tools/
│   ├── base.py       # Tool, ToolResult, ToolSchema
│   └── registry.py   # ToolRegistry
├── context/
│   └── window.py     # ContextWindow（短期）
├── ports/
│   └── memory.py     # MemoryPort, ContextComposer（AuM 实现）
├── events/
│   └── bus.py        # EventBus, RunEvent
└── types.py          # RunId, AgentId, 公共枚举
```

依赖管理（`pyproject.toml`）、CI 与示例 CLI 见 [README](../README.md) 实现路线图。

## 一次 Run 的数据流

用户通过 `RunRequest` 发起一次运行；Agent 构造 `LoopContext` 并交给 `AgentLoopRunner`。

```mermaid
sequenceDiagram
  participant U as User
  participant A as Agent
  participant R as LoopRunner
  participant L as ReActLoop
  participant C as ContextComposer
  participant M as ModelClient
  participant T as Tools

  U->>A: RunRequest
  A->>R: run_until_done
  loop per step
    R->>L: step
    L->>C: compose
    L->>M: complete
    alt tool_calls
      L->>T: invoke parallel
    end
    L-->>R: LoopStepResult
  end
  R-->>A: RunResult
  A-->>U: output
```

### 阶段说明

| 阶段 | 行为 |
|------|------|
| **初始化** | 生成 `run_id`；将用户输入写入 `ContextWindow`；若配置 `MemoryPort`，可选做一次 `recall` |
| **每步（step）** | Loop 调用 `compose` → `ModelClient.complete`（带 tool schemas）→ 若有 `tool_calls` 则并发 `invoke` → 将 assistant / tool 消息追加到 window |
| **记忆写回** | 若挂载 `MemoryPort`，每步结束可 `remember` 选定消息（策略由 AuM 或配置决定） |
| **终止** | 见下文「终止条件」 |
| **收尾** | 组装 `RunResult`（`output`、`messages`、`status`）；发出 `run_end` 事件 |

更细的 ReAct 状态机见 [loops.md](loops.md)。接口定义见 [interfaces.md](interfaces.md)。

## 终止条件

统一由 `LoopConfig` 与 `AgentLoop.should_continue` 判定：

| 条件 | `RunResult.status` |
|------|-------------------|
| 模型返回无 `tool_calls` 且产生最终文本 | `completed` |
| 达到 `max_steps` | `max_steps` |
| 用户调用 `agent.cancel(run_id)` | `cancelled` |
| 不可恢复错误（模型、工具、配置） | `error` |

## 与 AuM 的边界（摘要）

| 责任 | AuC | AuM |
|------|-----|-----|
| 单轮推理循环 | 是 | 否 |
| 工具注册与执行 | 是 | 可选包装 |
| 跨 Run / 长期记忆 | 端口定义 | 实现 `MemoryPort` |
| 上下文压缩 | `TruncatePolicy` 接口 | 可提供智能实现 |
| 会话持久化 | 不定义 | `SessionStore`（AuM 专有） |

`memory=None` 时 AuC 退化为仅 `ContextWindow` 的纯对话 Agent，**无需 AuM 即可运行**。详情见 [aum-integration.md](aum-integration.md)。

## 相关文档

- [interfaces.md](interfaces.md) — Protocol 与数据类草案
- [loops.md](loops.md) — 可插拔 Loop 与 ReAct
- [aum-integration.md](aum-integration.md) — AuM 挂载与扩展点
- [glossary.md](glossary.md) — 术语表
- [examples/minimal-react.md](examples/minimal-react.md) — 最小 ReAct 时序示例
- [adr/001-async-pluggable-loop.md](adr/001-async-pluggable-loop.md)
- [adr/002-memory-boundary.md](adr/002-memory-boundary.md)
