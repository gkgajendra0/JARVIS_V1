from pathlib import Path

from tools.research.gicc_phase9_live_status import probe_live_mission


def test_live_mission_probe_reports_missing_goal_without_mutation(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "work.sqlite3"

    result = probe_live_mission(
        goal_id="goal_missing",
        work_ids=("work_missing",),
        change_ids=("change_missing",),
        store_path=store_path,
    )

    assert result == {
        "status": "GOAL_NOT_FOUND",
        "store_path": str(store_path.resolve()),
        "goal_id": "goal_missing",
        "works": [],
        "changes": [],
    }
