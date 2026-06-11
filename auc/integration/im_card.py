"""IM 二次授权卡片格式（Telegram / QQ 共用）。"""

from __future__ import annotations

import json

from auc.ports.approval import ApprovalRequest


def format_approval_card(req: ApprovalRequest, *, diff_limit: int = 1500) -> str:
    diff = req.diff_text or "(no diff)"
    if len(diff) > diff_limit:
        diff = diff[: diff_limit - 10] + "\n..."
    return (
        "⚠️ AuM 风险提示\n"
        f"Agent `{req.agent_id}` 请求 L3 工具: `{req.tool_name}`\n"
        f"Run: `{req.run_id}`\n"
        f"参数: `{json.dumps(req.arguments, ensure_ascii=False)[:500]}`\n"
        f"--- Diff ---\n{diff}"
    )
