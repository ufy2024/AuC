from auc.checkpoint import CheckpointStore


def test_write_snapshot_and_revert(tmp_path) -> None:
    target = tmp_path / "a.txt"
    target.write_text("v1", encoding="utf-8")
    store = CheckpointStore(str(tmp_path))

    store.snapshot(run_id="r1", step=0, tool="write_file", arguments={"path": "a.txt"})
    target.write_text("v2", encoding="utf-8")

    report = store.revert_to("r1", 0)
    assert target.read_text(encoding="utf-8") == "v1"
    assert "a.txt" in report.restored


def test_new_file_revert_deletes(tmp_path) -> None:
    store = CheckpointStore(str(tmp_path))
    store.snapshot(run_id="r1", step=0, tool="write_file", arguments={"path": "new.txt"})
    (tmp_path / "new.txt").write_text("created", encoding="utf-8")

    report = store.revert_to("r1", 0)
    assert not (tmp_path / "new.txt").exists()
    assert "new.txt" in report.deleted


def test_delete_snapshot_and_revert(tmp_path) -> None:
    target = tmp_path / "b.txt"
    target.write_text("keep me", encoding="utf-8")
    store = CheckpointStore(str(tmp_path))

    entries = store.snapshot(
        run_id="r1", step=2, tool="delete_path", arguments={"path": "b.txt"}
    )
    assert entries and entries[0].op == "delete"
    target.unlink()

    report = store.revert_to("r1", 0)
    assert target.read_text(encoding="utf-8") == "keep me"
    assert "b.txt" in report.restored


def test_shell_step_warns_on_revert(tmp_path) -> None:
    store = CheckpointStore(str(tmp_path))
    entries = store.snapshot(
        run_id="r1", step=1, tool="run_command", arguments={"command": "make build"}
    )
    assert entries[0].op == "shell" and entries[0].command == "make build"

    report = store.revert_to("r1", 0)
    assert any("shell" in w for w in report.warnings)


def test_revert_only_from_target_step(tmp_path) -> None:
    target = tmp_path / "c.txt"
    target.write_text("v1", encoding="utf-8")
    store = CheckpointStore(str(tmp_path))
    store.snapshot(run_id="r1", step=0, tool="write_file", arguments={"path": "c.txt"})
    target.write_text("v2", encoding="utf-8")
    store.snapshot(run_id="r1", step=1, tool="write_file", arguments={"path": "c.txt"})
    target.write_text("v3", encoding="utf-8")

    store.revert_to("r1", 1)  # 只回滚 step>=1，应恢复到 v2
    assert target.read_text(encoding="utf-8") == "v2"


def test_blob_dedup(tmp_path) -> None:
    target = tmp_path / "d.txt"
    target.write_text("same content", encoding="utf-8")
    store = CheckpointStore(str(tmp_path))
    e1 = store.snapshot(run_id="r1", step=0, tool="write_file", arguments={"path": "d.txt"})
    e2 = store.snapshot(run_id="r1", step=1, tool="write_file", arguments={"path": "d.txt"})
    assert e1[0].blob == e2[0].blob
    blobs = list((tmp_path / ".auc" / "checkpoints" / "r1" / "blobs").iterdir())
    assert len(blobs) == 1


def test_gc_keeps_recent_steps(tmp_path) -> None:
    target = tmp_path / "e.txt"
    store = CheckpointStore(str(tmp_path))
    for step in range(10):
        target.write_text(f"v{step}", encoding="utf-8")
        store.snapshot(
            run_id="r1", step=step, tool="write_file", arguments={"path": "e.txt"}
        )
    removed = store.gc(keep_steps=3)
    assert removed == 7
    entries = store.list_entries("r1")
    assert sorted({e.step for e in entries}) == [7, 8, 9]


def test_sandbox_escape_ignored(tmp_path) -> None:
    store = CheckpointStore(str(tmp_path))
    entries = store.snapshot(
        run_id="r1", step=0, tool="write_file", arguments={"path": "../outside.txt"}
    )
    assert entries == []
