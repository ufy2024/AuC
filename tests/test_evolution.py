import asyncio
from pathlib import Path

from auc.integration.evolution import EvolutionMemoryPort, NuggetsStore
from auc.messages import ChatMessage


def test_evolution_recall_and_remember(tmp_path) -> None:
    sb = tmp_path / "ws"
    sb.mkdir()
    mem = EvolutionMemoryPort(sandbox_root=str(sb))

    async def _go() -> list[ChatMessage]:
        await mem.remember(
            [
                ChatMessage(role="user", content="删除 snake-game 目录"),
                ChatMessage(role="assistant", content="已用 delete_path 删除"),
            ]
        )
        return await mem.recall("删除 snake-game", limit=5)

    recalled = asyncio.run(_go())
    assert any("进化·经验" in m.content for m in recalled)


def test_promote_nugget(tmp_path) -> None:
    sb = tmp_path / "ws"
    sb.mkdir()
    nug_path = sb / ".auc" / "au-nuggets.yaml"
    mem = EvolutionMemoryPort(sandbox_root=str(sb))
    msg = mem.promote_nugget(
        "del-dir",
        "delete,snake",
        "删除目录一律用 delete_path，不要 write 覆盖",
    )
    assert "promoted" in msg
    assert nug_path.is_file()
    store = NuggetsStore.from_yaml(nug_path)
    assert any(n.id == "del-dir" for n in store.nuggets)
