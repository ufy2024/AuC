# 术语表

AuC 文档与接口中使用的核心术语。

| 术语 | 英文 | 说明 |
|------|------|------|
| **Agent** | Agent | 单智能体对外门面，提供 `run` / `run_stream` / `cancel` |
| **AgentId** | Agent ID | 智能体实例标识，用于记忆作用域与事件关联 |
| **AgentLoop** | Agent Loop | 可插拔的推理—行动策略（如 ReAct） |
| **AgentLoopRunner** | Loop Runner | 循环调用 `step` 直至终止，产出 `RunResult` |
| **AssistantMessage** | — | `ModelClient.complete` 的返回：文本与/或 `tool_calls` |
| **AuC** | Agents-ufy-Core | 本仓库：单智能体 Python 核心框架 |
| **AuM** | Agents-ufy-Memory | 记忆与持久化层（独立仓库），实现 AuC 端口 |
| **ChatMessage** | — | 统一消息结构：system / user / assistant / tool |
| **ContextComposer** | — | 合并 `MemoryPort` 召回与 `ContextWindow` 的协议 |
| **ContextWindow** | — | 当前 Run 的短期消息工作区 |
| **EventBus** | — | Run 生命周期事件分发 |
| **LoopConfig** | — | `max_steps`、并行工具、remember 等循环配置 |
| **LoopContext** | — | 单次 Run 内 Loop 共享的依赖与状态 |
| **LoopStepResult** | — | 单步结果：`done`、`tool_results` 等 |
| **MemoryPort** | — | 长期记忆的 recall / remember 端口（AuM 实现） |
| **ModelClient** | — | LLM 适配层协议 |
| **Observation** | Observation | ReAct 中工具执行结果，通常以 `role=tool` 的 `ChatMessage` 表示 |
| **ReAct** | Reason + Act | 思考（模型）→ 行动（工具）→ 观察 → 循环 |
| **Run** | Run | 一次 `agent.run(request)` 的完整执行 |
| **RunEvent** | — | 流式/可观测事件：model_delta、tool_start 等 |
| **RunId** | Run ID | 单次 Run 的唯一标识 |
| **RunRequest** | — | 运行输入：`str` 或 `list[ChatMessage]` |
| **RunResult** | — | 运行输出：`output`、`messages`、`status` |
| **RunStatus** | — | `completed` / `max_steps` / `cancelled` / `error` |
| **SessionStore** | — | AuM 专有：会话元数据与历史索引，AuC 不定义 |
| **Step** | Step | Loop 的一次 `step()` 调用 |
| **StreamChunk** | — | 流式模型输出的增量片段 |
| **Tool** | Tool | 可被 Agent 调用的能力单元 |
| **ToolCall** | Tool Call | 模型请求的一次工具调用（id、name、arguments） |
| **ToolRegistry** | — | 工具注册表与 schema 列表 |
| **ToolResult** | Tool Result | 工具执行结果，对应 `tool_call_id` |
| **ToolSchema** | — | 暴露给模型的 JSON Schema 描述 |
| **TruncatePolicy** | — | 上下文截断策略（条数、token、策略名） |
