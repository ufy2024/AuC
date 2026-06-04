# ADR 005：L1/L2/L3 工具分级与 L3 IM 二次授权

- **状态**：已接受
- **日期**：2026-06-04

## 背景

生产环境 Agent 7×24 运行，但 `git push`、实盘 API、宿主机越权不可自动化。Claude Code 在终端对高危操作要求人类确认。

## 决策

1. AuC 实现 **`ToolPrivilegeGate`**：`L1`/`L2` 默认放行，`L3` 挂起 Run。
2. 新增 **`RunStatus.pending_approval`** 与 **`ApprovalPort`**（AuM 实现，IM 网关批复）。
3. L3 审批不可被 Loop 跳过；Gate 为唯一强制执行点。
4. L2 写操作限定沙盒路径（`.aurules` 的 `sandbox_root`）。

## 后果

- **正面**：人类始终在回路（HITL）；后台自动化与资金安全兼得。
- **负面**：L3 操作延迟取决于 IM 响应；需 `timeout` 与 `denied` 语义。

## 相关文档

- [tool-privilege.md](../tool-privilege.md)
- [aum-integration.md](../aum-integration.md)
