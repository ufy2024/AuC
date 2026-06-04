import asyncio

from auc.ports.memory import DefaultComposer
from auc.ports.rules import parse_aurules_markdown
from auc.context import ListContextWindow
from auc.messages import ChatMessage
from auc.ports.package import CodeSnippet, ContextPackage


SAMPLE = """---
version: 1
---

## Build Commands
- `npm run dev`

## Test Commands
- `pytest tests/test_app.py`

## Code Style
- Use type hints.
"""


def test_parse_aurules() -> None:
    rules = parse_aurules_markdown(SAMPLE)
    assert rules.version == 1
    assert any("npm" in c for c in rules.build_commands)
    assert any("pytest" in c for c in rules.test_commands)


def test_compose_with_rules_and_package() -> None:
    asyncio.run(_test_compose_with_rules_and_package())


async def _test_compose_with_rules_and_package() -> None:
    from auc.ports.rules import ProjectRules

    window = ListContextWindow()
    window.append(ChatMessage(role="user", content="fix stop_loss"))
    rules = ProjectRules(
        build_commands=["npm run dev"],
        test_commands=["pytest tests/test_risk.py"],
    )
    pkg = ContextPackage(
        package_id="p1",
        intent_summary="stop_loss",
        snippets=[CodeSnippet(path="risk.py", content="def stop_loss(): pass")],
        token_estimate=50,
    )
    composer = DefaultComposer()
    msgs = await composer.compose(
        window, [], system_prompt="You are helpful.", rules=rules, package=pkg
    )
    assert msgs[0].role == "system"
    assert "helpful" in msgs[0].content
    assert "[AU-RULES" in msgs[1].content
    assert "[CONTEXT-PACKAGE" in msgs[2].content
    assert msgs[-1].role == "user"
