"""并发与竞态：多 run 并发、授权超时竞态。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from auc import (
    AgentConfig,
    DefaultAgent,
    DefaultToolRegistry,
    InMemoryModelClient,
)
from auc.loop.base import LoopConfig
from auc.messages import ChatMessage, RunRequest
from auc.model import AssistantMessage
from auc.ports.approval import ApprovalRequest
from auc.web.approval import WebApprovalPort


@dataclass
class _SlowModel(InMemoryModelClient):
    """每次补全前 sleep，强制两个 run 时间窗重叠。"""

    delay: float = 0.05

    async def complete(self, messages, tools=None):  # noqa: ANN001, ANN201
        await asyncio.sleep(self.delay)
        return await super().complete(messages, tools)


def test_two_runs_concurrently_on_same_agent() -> None:
    async def _run() -> None:
        model = _SlowModel(
            responses=[
                AssistantMessage(content="回复甲", tool_calls=None),
                AssistantMessage(content="回复乙", tool_calls=None),
            ]
        )
        agent = DefaultAgent(
            AgentConfig(
                agent_id="conc",
                model=model,
                tools=DefaultToolRegistry(),
                loop_config=LoopConfig(max_steps=3),
            )
        )
        r1, r2 = await asyncio.gather(
            agent.run(RunRequest(input=[ChatMessage(role="user", content="一")])),
            agent.run(RunRequest(input=[ChatMessage(role="user", content="二")])),
        )
        assert r1.status == "completed"
        assert r2.status == "completed"
        assert r1.run_id != r2.run_id
        assert {r1.output, r2.output} == {"回复甲", "回复乙"}
        # 运行态上下文已清理
        assert agent._active_ctx == {}  # noqa: SLF001

    asyncio.run(_run())


def _req(rid: str) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=rid,
        run_id="run-1",
        agent_id="agent",
        tool_name="fetch_url",
        arguments={"url": "https://example.com"},
        diff_text="",
        risk_summary="test",
    )


def test_approval_wait_timeout_returns_denied() -> None:
    async def _run() -> None:
        port = WebApprovalPort()
        await port.request_approval(_req("slow-1"))
        decision = await port.wait_decision("slow-1", timeout=0.05)
        assert decision.approved is False
        assert decision.reason == "授权超时"

    asyncio.run(_run())


def test_approval_decide_racing_with_timeout() -> None:
    """决策恰好在等待超时边界附近到达：要么放行要么超时拒绝，绝不抛错或挂起。"""

    async def _run() -> None:
        port = WebApprovalPort()
        await port.request_approval(_req("race-1"))

        async def _decide_soon() -> None:
            await asyncio.sleep(0.04)
            port.decide("race-1", approved=True)

        decision, _ = await asyncio.gather(
            port.wait_decision("race-1", timeout=0.05),
            _decide_soon(),
        )
        if decision.approved:
            assert decision.decided_by == "web"
        else:
            assert decision.reason == "授权超时"

    asyncio.run(_run())


def test_approval_late_decide_after_timeout_is_recorded() -> None:
    """超时后迟到的决策仍被登记；后续 wait 直接命中缓存（不会无限挂起）。"""

    async def _run() -> None:
        port = WebApprovalPort()
        await port.request_approval(_req("late-1"))
        timed_out = await port.wait_decision("late-1", timeout=0.02)
        assert timed_out.approved is False
        assert port.decide("late-1", approved=True) is True
        cached = await port.wait_decision("late-1", timeout=0.02)
        assert cached.approved is True

    asyncio.run(_run())


def test_concurrent_approvals_independent() -> None:
    """两个并发审批请求互不串扰。"""

    async def _run() -> None:
        port = WebApprovalPort()
        await port.request_approval(_req("p1"))
        await port.request_approval(_req("p2"))

        async def _decide() -> None:
            await asyncio.sleep(0.02)
            port.decide("p1", approved=True)
            port.decide("p2", approved=False, reason="拒绝乙")

        (d1, d2), _ = await asyncio.gather(
            asyncio.gather(
                port.wait_decision("p1", timeout=1.0),
                port.wait_decision("p2", timeout=1.0),
            ),
            _decide(),
        )
        assert d1.approved is True
        assert d2.approved is False
        assert d2.reason == "拒绝乙"

    asyncio.run(_run())
