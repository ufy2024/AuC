# 工具权限分级与 L3 二次授权

借鉴 Claude Code 对 `git push`、高额 API、系统级改动的**终端确认**，AuC 在框架层实现 **Tool Privilege Levels** 与 **挂起—审批—恢复** 状态机；经 **IM 网关（Telegram / QQ）** 完成人机二次授权（2FA for AI）。

## 权限分级

| 级别 | 名称 | 典型操作 | 默认策略 |
|------|------|----------|----------|
| **L1** | Read-Only | 读文件、查状态、`git status` | **自动放行** |
| **L2** | Write-Isolated | 沙盒内写代码、编译、单元测试 | **自动放行**（需沙盒路径策略） |
| **L3** | High-Risk / Host Impact | `git push`、实盘资金 API、突破沙盒写宿主机 | **挂起 + 人工批准** |

```python
ToolPrivilege = Literal["L1", "L2", "L3"]

@dataclass
class ToolPolicy:
    name: str
    privilege: ToolPrivilege
    sandbox_only: bool = False  # L2 常为 True
```

工具注册时声明；`.aurules` 可覆盖（见 [aurules.md](aurules.md)）。

## AuC：ToolPrivilegeGate

在 `ToolRegistry.invoke` 与 Loop 之间插入门控：

```mermaid
flowchart TB
  TC[ToolCall] --> Gate[ToolPrivilegeGate]
  Gate -->|L1 L2| Exec[invoke]
  Gate -->|L3| Suspend[挂起Session]
  Suspend --> AuM[AuM封装Diff与上下文]
  AuM --> IM[Telegram / QQ 等 IM]
  IM -->|批准| Resume[恢复Run]
  IM -->|拒绝| Abort[RunStatus cancelled]
  Resume --> Exec
```

### 挂起语义

| 状态 | 说明 |
|------|------|
| `RunStatus.pending_approval` | 新增状态：等待 L3 批复 |
| `ApprovalRequest` | 含 `run_id`、`tool_call`、`diff`、`risk_summary` |
| `ApprovalDecision` | `approved` / `denied` / `timeout` |

Loop **不**丢弃 `LoopContext`；将当前 step 冻结在内存或 AuM `SessionStore` 快照，直至 `ApprovalPort.resolve(request_id)` 返回。

## AuM：IM 2FA 网关

AuC 定义 **`ApprovalPort`**（AuM 实现）：

```python
class ApprovalPort(Protocol):
    async def request_approval(self, req: ApprovalRequest) -> str: ...  # request_id
    async def wait_decision(
        self, request_id: str, timeout: float = 3600
    ) -> ApprovalDecision: ...
```

AuM 职责：

1. 从挂起的 Run 提取 **代码 Diff**、分支名、工具参数。
2. 格式化为 IM 卡片（Telegram Inline Keyboard 或 QQ 消息按钮：`允许并继续` / `拒绝并中断`；共用 `format_approval_card`）。
3. 将用户点击结果回写 `ApprovalPort`。

### IM 卡片示意

```text
⚠️ AuM 风险提示
Agent 正在尝试向 main 分支推送代码。
─── 代码 Diff ───
+ def stop_loss():
...
[ 允许并继续 ]  [ 拒绝并中断 ]
```

用户睡觉期间：L1/L2 后台自动化可继续；**L3 永远无法自作主张**。

## 事件扩展

新增 `RunEvent` 类型（见 [interfaces.md](interfaces.md)）：

- `approval_required`
- `approval_granted`
- `approval_denied`

便于 CLI / IM 与 `run_stream` 订阅同一套可观测性。

## HumanInTheLoopLoop

可在 [loops.md](loops.md) 使用专用 Loop：在每次 L3 调用前主动 `request_approval`，与 Gate 双保险。

生产推荐：**Gate 强制拦截**（不可被 Loop 绕过）；Loop 仅作显式提示。

## 沙盒与 L2

L2 工具必须满足：

- 写路径 ⊆ `.aurules` 声明的 `sandbox_root`（如 `/workspace`）
- 禁止挂载宿主机 `/etc`、`~/.ssh`

越界尝试升级为 **L3** 或硬拒绝。

## IM 实现（Telegram / QQ）

| 端口 | 基类 | 回调语义 | 安装 |
|------|------|----------|------|
| `TelegramApprovalPort` | `HttpImApprovalPort` | `auc:approve\|deny:<id>`，Bot API 轮询 | `pip install -e '.[telegram]'` |
| `QQApprovalPort` | `HttpImApprovalPort` | 同上，OneBot Webhook 写入 | `pip install -e '.[qq]'` |

详见 [详细设计.md](详细设计.md) §12、[需求.md](需求.md) R24。

## 会话自治级别（规划中 R6）

在静态 L1/L2/L3 之上，规划三级会话开关：`confirm-all` / `auto-edit`（默认）/ `full-auto`。`full-auto` 仅放宽 L2，**L3 永不自动放行**。`confirm-all` 下写文件挂起并携带 unified diff，与 R9 Diff 审阅共用 `ApprovalPort`。

完整裁决链（Hooks → Escalation → Autonomy → Gate → Checkpoint → invoke）见 [adr/006-tool-decision-chain.md](adr/006-tool-decision-chain.md) 与 [架构设计.md](架构设计.md) §4.4。

## 相关文档

- [interfaces.md](interfaces.md) — `ApprovalPort`、`ToolPolicy`
- [aum-integration.md](aum-integration.md) — IM 网关
- [adr/005-tool-privilege-2fa.md](adr/005-tool-privilege-2fa.md)
- [adr/006-tool-decision-chain.md](adr/006-tool-decision-chain.md) — 裁决链（R1/R6/R9/R14）
