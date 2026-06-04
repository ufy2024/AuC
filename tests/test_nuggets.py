import asyncio
from pathlib import Path

from auc.integration import NuggetsMemoryPort, NuggetsStore


def test_nuggets_recall() -> None:
    path = Path(__file__).parent / "fixtures" / "au-nuggets.yaml"
    store = NuggetsStore.from_yaml(path)
    mem = NuggetsMemoryPort(store=store)

    async def _go():
        return await mem.recall("edit stop_loss threshold")

    msgs = asyncio.run(_go())
    assert msgs
    assert "AU-NUGGET" in msgs[0].content
    assert "pytest" in msgs[0].content
