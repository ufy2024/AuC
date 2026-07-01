import tempfile
from pathlib import Path

import pytest
import yaml

from auc.integration.evolution import EvolutionMemoryPort, resolve_evolution_storage
from auc.roles import (
    BUILTIN_ROLES,
    active_role_path,
    build_role_system_prompt,
    get_role,
    load_role_catalog,
    matches_role,
    normalize_role_id,
    package_roles_root,
    read_active_role,
    role_evolution_paths,
    role_from_folder,
    role_tag,
    roles_yaml_path,
    sandbox_role_dir,
    set_active_role,
)


def test_builtin_roles_from_package_dirs() -> None:
    assert "coder" in BUILTIN_ROLES
    coder_dir = package_roles_root() / "core" / "coder"
    assert (coder_dir / "role.yaml").is_file()
    assert (coder_dir / "prompt.md").is_file()
    assert get_role("unknown").id == "coder"


def test_build_role_system_prompt() -> None:
    prompt = build_role_system_prompt("/tmp/ws", "engineering-code-reviewer")
    assert "/tmp/ws" in prompt
    assert "grep_search" in prompt


def test_matches_role_legacy_global() -> None:
    assert matches_role(role_id="coder", tags=["pytest"], metadata={})
    assert matches_role(role_id="reviewer", tags=["pytest"], metadata={})


def test_matches_role_scoped() -> None:
    assert matches_role(
        role_id="coder",
        tags=[role_tag("coder"), "test"],
        metadata={},
    )
    assert not matches_role(
        role_id="reviewer",
        tags=[role_tag("coder"), "test"],
        metadata={},
    )


@pytest.mark.asyncio
async def test_evolution_per_role_directories() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        mem_coder = EvolutionMemoryPort(sandbox_root=tmp, default_role_id="coder")
        mem_coder.save_lesson("pytest", "coder-only lesson")
        mem_rev = EvolutionMemoryPort(sandbox_root=tmp, default_role_id="reviewer")
        rev_msgs = await mem_rev.recall("pytest coder lesson")
        assert not any("coder-only lesson" in m.content for m in rev_msgs)
        coder_msgs = await mem_coder.recall("pytest coder lesson")
        assert any("coder-only lesson" in m.content for m in coder_msgs)
        coder_evo = sandbox_role_dir(tmp, "coder") / "evolution.yaml"
        assert coder_evo.is_file()


@pytest.mark.asyncio
async def test_evolution_remember_in_role_dir() -> None:
    from auc.messages import ChatMessage

    with tempfile.TemporaryDirectory() as tmp:
        mem = EvolutionMemoryPort(sandbox_root=tmp, default_role_id="architect")
        await mem.remember(
            [
                ChatMessage(role="user", content="设计模块边界"),
                ChatMessage(role="assistant", content="建议分层"),
            ],
            agent_id="chat:architect",
        )
        store = mem.evolution_store
        assert store.episodes
        ep = store.episodes[-1]
        assert ep.metadata.get("role_id") == "architect"
        assert store.path == sandbox_role_dir(tmp, "architect") / "evolution.yaml"


def test_normalize_role_id() -> None:
    catalog = load_role_catalog()
    assert normalize_role_id("CODER", catalog=catalog) == "coder"
    assert normalize_role_id("engineering-code-reviewer", catalog=catalog) == (
        "engineering-code-reviewer"
    )
    assert normalize_role_id(None, catalog=catalog) == "coder"


def test_custom_role_folder_in_sandbox() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        role_dir = sandbox_role_dir(tmp, "stock-analyst")
        role_dir.mkdir(parents=True)
        (role_dir / "role.yaml").write_text(
            yaml.safe_dump(
                {
                    "label": "股票分析师",
                    "title": "行情与基本面",
                    "description": "解读财报与行业逻辑",
                    "capabilities": ["基本面", "技术面"],
                    "default_work_mode": "explain",
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        (role_dir / "prompt.md").write_text(
            "你是股票分析师。工作区：{sandbox}",
            encoding="utf-8",
        )
        catalog = load_role_catalog(sandbox=tmp)
        assert "stock-analyst" in catalog.roles
        assert catalog.get("stock-analyst").label == "股票分析师"
        prompt = build_role_system_prompt(tmp, "stock-analyst", catalog=catalog)
        assert "股票分析师" in prompt


def test_active_role_marker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        set_active_role(tmp, "engineering-code-reviewer")
        assert read_active_role(tmp) == "engineering-code-reviewer"
        assert active_role_path(tmp).is_file()
        catalog = load_role_catalog(sandbox=tmp)
        assert catalog.default_role_id == "engineering-code-reviewer"
        payload_role = next(
            r for r in catalog.list_roles() if r.id == "engineering-code-reviewer"
        )
        assert payload_role.id == "engineering-code-reviewer"


def test_role_from_folder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        role_dir = Path(tmp) / "translator"
        role_dir.mkdir()
        (role_dir / "role.yaml").write_text("label: 翻译专家\n", encoding="utf-8")
        (role_dir / "prompt.md").write_text("你是翻译专家。\n沙盒：{sandbox}", encoding="utf-8")
        spec = role_from_folder(role_dir)
        assert spec is not None
        assert spec.label == "翻译专家"


def test_legacy_roles_yaml_still_works() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = roles_yaml_path(tmp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                {
                    "roles": {
                        "mathematician": {
                            "label": "数学家",
                            "persona": "你是数学家。\n工作区：{sandbox}",
                        }
                    }
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        catalog = load_role_catalog(sandbox=tmp)
        assert catalog.get("mathematician").label == "数学家"


def test_resolve_evolution_storage_prefers_role_dir() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        n, e, legacy = resolve_evolution_storage(tmp, "coder")
        assert not legacy
        assert e.parent == sandbox_role_dir(tmp, "coder")
        n2, e2 = role_evolution_paths(tmp, "coder")
        assert n == n2 and e == e2
