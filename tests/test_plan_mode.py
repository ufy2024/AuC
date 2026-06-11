import asyncio

from auc import (
    AgentConfig,
    DefaultAgent,
    DefaultToolRegistry,
    InMemoryModelClient,
)
from auc.messages import RunRequest
from auc.model import AssistantMessage
from auc.plan import READONLY_TOOL_NAMES, parse_plan_block, render_plan_context
from auc.tools.files import make_file_tools
from auc.work_mode import WORK_MODES, get_mode_spec

PLAN_TEXT = """\
我研究了代码，计划如下：

```json auc-plan
{
  "goal": "加搜索工具",
  "steps": [{"n": 1, "title": "写 search.py", "detail": "实现 grep", "files": ["auc/tools/search.py"]}],
  "files": ["auc/tools/search.py"],
  "risks": ["正则性能"],
  "estimate": "约 3 步"
}
```
"""


def test_parse_plan_block() -> None:
    plan = parse_plan_block(PLAN_TEXT)
    assert plan is not None
    assert plan["goal"] == "加搜索工具"
    assert plan["steps"][0]["n"] == 1


def test_parse_failure_degrades() -> None:
    assert parse_plan_block("没有计划块的普通回复") is None
    assert parse_plan_block("```json auc-plan\n{broken json}\n```") is None
    assert parse_plan_block('```json auc-plan\n{"goal": "缺 steps"}\n```') is None
    assert parse_plan_block(None) is None


def test_render_plan_context() -> None:
    plan = parse_plan_block(PLAN_TEXT)
    text = render_plan_context(plan)
    assert "[已批准计划]" in text
    assert "加搜索工具" in text
    assert "auc/tools/search.py" in text


def test_plan_mode_spec_readonly() -> None:
    spec = get_mode_spec("plan")
    assert spec.readonly_tools
    assert "plan" in WORK_MODES
    # 其他模式不收窄
    assert not get_mode_spec("implement").readonly_tools


def test_plan_mode_filters_write_tools(tmp_path) -> None:
    asyncio.run(_test_plan_mode_filters_write_tools(tmp_path))


async def _test_plan_mode_filters_write_tools(tmp_path) -> None:
    registry = DefaultToolRegistry()
    for tool, pol in make_file_tools(str(tmp_path)):
        registry.register(tool, pol)
    assert registry.get("write_file") is not None

    view = registry.filtered_view(READONLY_TOOL_NAMES)
    assert view.get("write_file") is None
    assert view.get("read_file") is not None
    names = {s.name for s in view.list_schemas()}
    assert names <= READONLY_TOOL_NAMES


def test_plan_ready_event_emitted(tmp_path) -> None:
    asyncio.run(_test_plan_ready_event(tmp_path))


async def _test_plan_ready_event(tmp_path) -> None:
    model = InMemoryModelClient(
        responses=[AssistantMessage(content=PLAN_TEXT, tool_calls=None)]
    )
    registry = DefaultToolRegistry()
    for tool, pol in make_file_tools(str(tmp_path)):
        registry.register(tool, pol)
    agent = DefaultAgent(
        AgentConfig(
            agent_id="a",
            model=model,
            tools=registry,
            sandbox_root=str(tmp_path),
        )
    )
    events = []
    async for ev in agent.run_stream(
        RunRequest(input="出个计划", metadata={"work_mode": "plan"})
    ):
        events.append(ev)
    plan_events = [e for e in events if e.type == "plan_ready"]
    assert plan_events
    assert plan_events[0].payload["plan"]["goal"] == "加搜索工具"


def test_approved_plan_injected(tmp_path) -> None:
    asyncio.run(_test_approved_plan_injected(tmp_path))


async def _test_approved_plan_injected(tmp_path) -> None:
    plan = parse_plan_block(PLAN_TEXT)
    model = InMemoryModelClient(
        responses=[AssistantMessage(content="开始执行", tool_calls=None)]
    )
    agent = DefaultAgent(
        AgentConfig(
            agent_id="a",
            model=model,
            tools=DefaultToolRegistry(),
            sandbox_root=str(tmp_path),
        )
    )
    result = await agent.run(
        RunRequest(input="按计划执行", metadata={"approved_plan": plan})
    )
    assert result.status == "completed"
    assert any(
        m.role == "system" and "[已批准计划]" in m.content for m in result.messages
    )
