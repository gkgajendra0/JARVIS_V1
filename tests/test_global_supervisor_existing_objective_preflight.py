from __future__ import annotations

import importlib.util
from pathlib import Path

from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore


def _preflight_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "research"
        / "global_supervisor_existing_objective_preflight.py"
    )
    spec = importlib.util.spec_from_file_location(
        "global_supervisor_existing_objective_preflight",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preflight_snapshot_does_not_mutate_source_database(tmp_path: Path) -> None:
    source_path = tmp_path / "canonical.sqlite3"
    source = SQLiteWorkStore(source_path)
    original = source.create(
        WorkItem(
            request="Preserve this canonical record.",
            work_type=WorkType.RESEARCH,
            source_session_id="source-session",
            source_turn_id="source-turn",
        )
    )

    before_bytes = source_path.read_bytes()
    before_mtime = source_path.stat().st_mtime_ns
    before_directory = {
        item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()
    }

    module = _preflight_module()
    guard, snapshot = module._snapshot_work_store(source_path)
    try:
        copied = snapshot.require(original.work_id)
        assert copied.request == original.request
        assert snapshot.path != source_path
        assert snapshot.path.parent != source_path.parent
    finally:
        guard.cleanup()

    assert source_path.read_bytes() == before_bytes
    assert source_path.stat().st_mtime_ns == before_mtime
    assert {
        item.name: item.read_bytes() for item in tmp_path.iterdir() if item.is_file()
    } == before_directory
