# AuC

**Agents-ufy-Core** — ufy 体系中的单智能体 Python 核心框架。

AuC 基于 asyncio，提供可插拔推理循环（默认 ReAct）、LLM 适配、工具权限分级（L1/L2/L3）与可观测事件流。与 [AuM](https://github.com/ufy2024/AuM) 协同时，吸收 **Claude Code** 式工程纪律：**上下文切片**、**项目军规（`.aurules`）**、**高危操作 IM 二次授权**。

**v0.2.12** — Web 文档预览（PDF/Word/Excel）与中英文界面切换；v0.2.11 版本更新提示与一键升级。

[![CI](https://github.com/ufy2024/AuC/actions/workflows/ci.yml/badge.svg)](https://github.com/ufy2024/AuC/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/ufy-auc)](https://pypi.org/project/ufy-auc/)
[![Python](https://img.shields.io/pypi/pyversions/ufy-auc)](https://pypi.org/project/ufy-auc/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 特性概览

| 能力 | 说明 |
|------|------|
| **ReAct 循环** | 流式推理、并行工具调用、上下文压缩、检查点回滚 |
| **多模型** | OpenAI Chat Completions、Anthropic Messages、DeepSeek 兼容网关 |
| **工具分级** | L1 只读 / L2 沙盒写 / L3 二次授权；危险命令自动升级 |
| **终端 UI** | prompt-toolkit 多行输入、斜杠命令、Plan / 自治模式 |
| **Web UI** | Code + Chat 双模式、工作区、项目预览/代理运行、SSE 流式对话 |
| **IM 授权** | Telegram、QQ（OneBot 11）L3 审批卡片 |
| **进化记忆** | `.auc/evolution.yaml` 经验召回与金块固化 |
| **沙盒** | 文件读写、Shell、grep/glob、URL 抓取（SSRF 防护） |

## 安装

### 从 PyPI（推荐）

```bash
pip install ufy-auc              # 仅核心（无 HTTP / 无 Web）
pip install "ufy-auc[chat]"      # 终端对话（llm + cli，日常推荐）
pip install "ufy-auc[web]"       # 网页 UI
pip install "ufy-auc[all]"       # 全部可选组件
pip install "ufy-auc[dev]"       # 开发/CI（pytest + 全部组件）
```

> PyPI 包名为 **`ufy-auc`**（`import auc` 不变；CLI 仍为 `auc` / `auc-web`）。PyPI 上的 `auc` 已被其他项目占用。

### 从源码

```bash
git clone https://github.com/ufy2024/AuC.git && cd AuC
pip install -e ".[chat]"       # 或 .[all] / .[dev]
```

### 可选组件对照

| 模式 | 命令 | 包含 |
|------|------|------|
| 核心 | `pip install ufy-auc` | 框架 + YAML（无 HTTP / 无 Web） |
| **llm** | `pip install "ufy-auc[llm]"` | httpx，调用 OpenAI / Anthropic / DeepSeek |
| **cli** | `pip install "ufy-auc[cli]"` | prompt-toolkit 终端增强 |
| **chat** | `pip install "ufy-auc[chat]"` | llm + cli（**终端对话推荐**） |
| **web** | `pip install "ufy-auc[web]"` | FastAPI 网页 UI + 工作区 + 项目运行 |
| **telegram** | `pip install "ufy-auc[telegram]"` | Telegram L3 二次授权 |
| **qq** | `pip install "ufy-auc[qq]"` | QQ L3 二次授权（OneBot 11） |
| **all** | `pip install "ufy-auc[all]"` | 上述全部 |
| **dev** | `pip install "ufy-auc[dev]"` | pytest + 全部（CI / 本地开发） |

可组合：`pip install "ufy-auc[chat,web]"`。`openai` 为 `llm` 的兼容别名。运行 `auc extras` 查看完整列表。

## 快速开始

### 1. 配置大模型

```bash
auc config init                              # ~/.Au/AuC/settings.json
auc config init --provider deepseek          # DeepSeek 模板
export DEEPSEEK_API_KEY=sk-...               # 或 OPENAI_API_KEY / ANTHROPIC_API_KEY
auc config show
```

配置格式为 JSON（Claude Code 风格），详见仓库内 `docs/model-config.md`。

### 2. 终端对话

```bash
auc chat "你好"
auc chat "hi" -p anthropic -m claude-sonnet-4-20250514
auc chat                                    # 进入交互 REPL（/help /plan /autonomy …）
auc undo --list                             # 检查点回滚
```

### 3. Web UI

```bash
auc web --sandbox ./my-project              # http://127.0.0.1:8765
# 或
auc-web --sandbox ./my-project
```

侧栏可浏览工作区、运行沙盒内项目（HTML / Node / Python）、在 Chat 模式与智能体对话（含 L3 授权弹窗、图片上传）。

### 4. 程序化调用

```python
import asyncio
from auc import AgentConfig, DefaultAgent, DefaultToolRegistry, InMemoryModelClient, make_echo_tool
from auc.messages import ToolCall
from auc.model import AssistantMessage

async def main():
    reg = DefaultToolRegistry()
    t, p = make_echo_tool()
    reg.register(t, p)
    model = InMemoryModelClient(responses=[
        AssistantMessage(content=None, tool_calls=[
            ToolCall(id="1", name="echo", arguments={"x": 1}),
        ]),
        AssistantMessage(content="done", tool_calls=None),
    ])
    agent = DefaultAgent(AgentConfig(agent_id="demo", model=model, tools=reg))
    print((await agent.run("run echo")).output)

asyncio.run(main())
```

更多示例见 `examples/`。

## CLI 命令

| 命令 | 说明 |
|------|------|
| `auc chat` | 终端对话（推荐 `[chat]`） |
| `auc web` | 启动 Web UI（推荐 `[web]`） |
| `auc config init/show/set/migrate` | 管理 `settings.json` |
| `auc slice` | 语义切片（Au-Context Slicer） |
| `auc undo` | 检查点列表与回滚 |
| `auc run` | 脚本化单次运行（`--reply` 调试） |
| `auc dispatch` | IM 遥控分发 |
| `auc extras` | 打印可选安装模式 |

## 设计亮点（Claude Code 经验）

| 机制 | 实现要点 |
|------|----------|
| **Au-Context Slicer** | `SemanticSlicer` → `ContextPackage` |
| **Au-Rules Matrix** | `FileRulesPort` + `.aurules` |
| **L3 二次授权** | `TelegramApprovalPort`、`QQApprovalPort`、`WebApprovalPort`、`ConsoleApprovalPort` |
| **自治与升级** | `AutonomyPolicy`、危险 Shell 自动升 L3 |
| **检查点** | `write_file` / `delete_path` / `run_command` 快照与 `auc undo` |
| **进化记忆** | `EvolutionMemoryPort`、`.auc/evolution.yaml` |

## 开发与测试

```bash
pip install -e ".[dev]"
pytest -q                                    # 267 项用例
pytest -q --cov=auc --cov-fail-under=75    # CI 同款（当前约 80%）
ruff check auc tests
```

CI：GitHub Actions，Python 3.11 / 3.12，覆盖率门槛 ≥75%。

## 文档

设计文档位于仓库 `docs/` 目录（本地克隆后可见）：

| 文档 | 说明 |
|------|------|
| `docs/design-philosophy.md` | 设计哲学与生态蓝图 |
| `docs/architecture.md` | 总体架构 |
| `docs/model-config.md` | OpenAI / Anthropic / DeepSeek 配置 |
| `docs/tool-privilege.md` | L1/L2/L3 工具权限 |
| `docs/aum-compatibility.md` | AuM 联调与版本 |
| `docs/test-report.md` | 测试报告与覆盖率 |

## 路线图

### 已完成（v0.2.x）

- [x] ReAct 循环、`run_stream`、事件总线
- [x] OpenAI / Anthropic / DeepSeek 流式客户端
- [x] 沙盒文件、Shell、搜索、URL 抓取工具
- [x] 检查点回滚、Plan 模式、自治策略、上下文压缩
- [x] 终端 REPL（斜杠命令、prompt-toolkit）
- [x] Web UI（工作区、项目运行、SSE Chat、L3 授权队列）
- [x] Telegram + QQ（OneBot 11）IM 二次授权
- [x] 进化记忆与金块固化
- [x] 267 项 pytest、CI 覆盖率门槛

### 进行中 / 计划

- [ ] `ConversationStore` 上移共享（M2）
- [ ] Usage 上报与进化层联动
- [ ] 独立 AuM 仓库生产化（持久化、向量索引、Webhook）

## 仓库与发布

- **源码**：https://github.com/ufy2024/AuC
- **PyPI**：https://pypi.org/project/ufy-auc/

```bash
pip install -U "ufy-auc[chat]"
```

## 许可

MIT — 见 [LICENSE](LICENSE)。
