import tempfile
from pathlib import Path

import pytest

from auc.web.workspace import (
    create_directory,
    list_tree,
    read_text_file,
    short_display_path,
    tree_to_dict,
    write_text_file,
)
from auc.sandbox import SandboxViolationError


def test_list_tree_and_rw() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_text("print(1)\n", encoding="utf-8")
        (Path(tmp) / "pkg").mkdir()
        tree = list_tree(tmp, ".")
        assert len(tree.entries) == 2
        data = read_text_file(tmp, "a.py")
        assert "print" in data["content"]
        write_text_file(tmp, "b.txt", "hi")
        assert (Path(tmp) / "b.txt").read_text() == "hi"


def test_sandbox_escape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(SandboxViolationError):
            read_text_file(tmp, "/etc/passwd")


def test_tree_to_dict() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = tree_to_dict(list_tree(tmp))
        assert "entries" in d


def test_create_directory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        create_directory(tmp, "nested/pkg")
        assert (Path(tmp) / "nested" / "pkg").is_dir()
        with pytest.raises(FileExistsError):
            create_directory(tmp, "nested/pkg")


def test_short_path() -> None:
    home = str(Path.home())
    assert short_display_path(home + "/x").startswith("~")
