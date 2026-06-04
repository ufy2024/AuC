# ADR 002：记忆能力外置至 AuM

- **状态**：已接受
- **日期**：2026-06-04
- **决策者**：AuC 架构设计

## 背景

智能体系统通常需要短期对话上下文与长期记忆（跨 Run、检索、持久化）。若在 AuC 核心内置向量库、embedding 与会话存储，会导致核心膨胀、依赖过重，且与「单智能体最小核心」定位冲突。AuM 将作为 AuC 之上的独立仓库。

## 决策

1. **AuC 不实现长期记忆**，仅定义 `MemoryPort` 与 `ContextComposer` Protocol。
2. **AuC 持有 `ContextWindow`**，范围限定为**当前 Run** 的消息工作区。
3. **`SessionStore`、embedding、chunking、向量后端** 均属 AuM，不在 AuC 类型系统中出现。
4. **`memory=None` 时必须可完整运行**（无 recall/remember，仅 window）。

## 理由

- **单一职责**：AuC = 推理循环 + 工具 + LLM 适配；AuM = 记什么、存哪、怎么搜。
- **可选依赖**：用户可不安装 AuM，降低试用与嵌入成本。
- **演进独立**：记忆方案（SQL、向量、图）变更不牵动 AuC 发版节奏。
- **AuM 作为 AuC 基石的实现层**：接口稳定后，AuM 专注质量与存储，而非重复实现 Loop。

## 后果

### 正面

- AuC 包体积小、依赖少，易于审计与安全扫描。
- 第三方可自带 `MemoryPort` 实现，不限于官方 AuM。
- 联调边界清晰：Protocol 即契约。

### 负面

- 开箱即用「带记忆的 Agent」需组合 AuC + AuM 两个包。
- `recall`/`remember` 语义由 AuM 文档补充，AuC 仅规定调用时机。

## 调用约定（摘要）

- 每步（可选）：`recall` → `compose` → model → tools →（可选）`remember`。
- `remember_each_step` 默认 `False`，避免无意写满存储。

## 备选方案（未采纳）

- **AuC 内置简单内存列表**：无法满足跨 Run，且与 AuM 重复，不采用。
- **AuC 内置向量 RAG**：耦合重、依赖多，不采用。

## 相关文档

- [aum-integration.md](../aum-integration.md)
- [interfaces.md](../interfaces.md)
- [architecture.md](../architecture.md)
