from __future__ import annotations

from jarvis.engineering_change.acceptance import inspect_change
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.store import SQLiteWorkStore


def test_inspection_never_claims_external_acceptance_or_emits_goal(tmp_path) -> None:
    changes = ChangeStore(SQLiteWorkStore(tmp_path / "work.sqlite3"))
    item = changes.create(
        request="Private owner goal",
        process_key="engineering.change",
        process_version=1,
        source_session_id="owner",
        source_turn_id="one",
    )
    result = inspect_change(changes, item.change_id)
    assert result["result"] == "FAIL"
    assert set(result["external_gates"].values()) == {"PENDING"}
    assert "Private owner goal" not in str(result)
