import json
import tempfile
from pathlib import Path

import pytest

from auc.integration.evolution import EvolutionMemoryPort
from auc.roles import load_role_catalog, read_active_role, sandbox_role_dir
from auc.roles.writer import update_role_definition, write_role_definition
from auc.run_context import current_agent_id
from auc.tools.roles import make_role_tools


def test_write_role_definition_creates_files() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = write_role_definition(
            tmp,
            role_id="stock-analyst",
            label="股票分析师",
            persona="你是专业股票分析师。\n工作区：{sandbox}",
            description="基本面与技术面分析",
            capabilities="研报,估值",
            activate=True,
        )
        assert out["role_id"] == "stock-analyst"
        role_dir = sandbox_role_dir(tmp, "stock-analyst")
        assert (role_dir / "role.yaml").is_file()
        assert (role_dir / "prompt.md").is_file()
        assert (role_dir / "evolution.yaml").is_file()
        assert (role_dir / "nuggets.yaml").is_file()
        assert read_active_role(tmp) == "stock-analyst"
        cat = load_role_catalog(sandbox=tmp)
        assert "stock-analyst" in cat.roles


def test_update_role_definition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        write_role_definition(
            tmp,
            role_id="tutor-cn",
            label="家教",
            persona="你是家教老师。{sandbox}",
            activate=False,
        )
        update_role_definition(
            tmp,
            "tutor-cn",
            persona="你是耐心家教，擅长数学。{sandbox}",
            label="数学家教",
        )
        prompt = (sandbox_role_dir(tmp, "tutor-cn") / "prompt.md").read_text()
        assert "数学" in prompt


@pytest.mark.asyncio
async def test_save_lesson_uses_run_context_agent_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem = EvolutionMemoryPort(sandbox_root=tmp, default_role_id="coder")
        write_role_definition(
            tmp,
            role_id="reviewer",
            label="审查",
            persona="审查员。{sandbox}",
            activate=False,
        )
        token = current_agent_id.set("chat:reviewer")
        try:
            mem.save_lesson("lint", "reviewer lesson from context")
        finally:
            current_agent_id.reset(token)
        rev_evo = sandbox_role_dir(tmp, "reviewer") / "evolution.yaml"
        assert rev_evo.is_file()
        coder_evo = sandbox_role_dir(tmp, "coder") / "evolution.yaml"
        if coder_evo.is_file():
            assert "reviewer lesson" not in coder_evo.read_text()


@pytest.mark.asyncio
async def test_define_role_tool() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tools = {t.name: t for t, _ in make_role_tools(tmp)}
        define = tools["define_role"]
        raw = await define.invoke(
            {
                "role_id": "poet",
                "label": "诗人",
                "persona": "你是诗人助手。{sandbox}",
                "description": "写诗",
                "activate": True,
            }
        )
        data = json.loads(raw.content)
        assert data["role_id"] == "poet"
        assert read_active_role(tmp) == "poet"
