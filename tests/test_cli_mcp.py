from __future__ import annotations

import json
from pathlib import Path

from auc.cli import main


def _write_settings(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    auc = repo / ".auc"
    auc.mkdir(parents=True)
    (auc / "settings.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "fs": {"command": "mcp-fs", "owner": "team", "deny": ["rm*"]},
                }
            }
        ),
        encoding="utf-8",
    )
    return repo


def test_mcp_list_text(tmp_path, capsys):
    repo = _write_settings(tmp_path)
    code = main(["mcp", "list", "--repo", str(repo)])
    assert code == 0
    out = capsys.readouterr().out
    assert "fs" in out
    assert "stdio" in out
    assert "team" in out


def test_mcp_list_json(tmp_path, capsys):
    repo = _write_settings(tmp_path)
    code = main(["mcp", "list", "--repo", str(repo), "--json"])
    assert code == 0
    cards = json.loads(capsys.readouterr().out)
    assert cards[0]["name"] == "fs"
    assert cards[0]["forbidden_tools"] == ["rm*"]


def test_mcp_list_empty(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / ".auc").mkdir(parents=True)
    (repo / ".auc" / "settings.json").write_text("{}", encoding="utf-8")
    code = main(["mcp", "list", "--repo", str(repo)])
    assert code == 1
