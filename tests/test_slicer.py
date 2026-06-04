import asyncio
from pathlib import Path

from auc.integration import SemanticSlicer


def test_slicer_finds_stop_loss() -> None:
    repo = Path(__file__).parent / "fixtures" / "sample_repo"
    pkg = asyncio.run(SemanticSlicer().slice("modify stop_loss logic", str(repo)))
    assert pkg.snippets
    assert any("stop_loss" in s.path or "stop_loss" in s.content for s in pkg.snippets)
