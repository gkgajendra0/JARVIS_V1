from pathlib import Path

from tools.research.gicc_phase9_live_status import probe_live_mission

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change import ChangeStore
from jarvis.goal_intelligence.models import GoalKind, OwnerGoalV2
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore

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


def test_live_mission_probe_reads_phase9_engineering_change(tmp_path: Path) -> None:
    store_path = tmp_path / "work.sqlite3"
    codec = build_default_work_payload_codec(store_path)
    work = SQLiteWorkStore(store_path, payload_codec=codec)
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="session-live-probe",
            source_turn_id="turn-live-probe",
            exact_owner_request="Play Interstellar on my TV.",
            goal_kind=GoalKind.ACTION,
            desired_outcome="Interstellar is playing on the intended TV.",
            completion_predicates=("movie_playing_verified",),
        )
    )
    change = changes.create(
        request="Acquire reusable TV media control capability.",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id="session-phase9",
        source_turn_id="turn-phase9",
    )

    result = probe_live_mission(
        goal_id=goal.goal_id,
        change_ids=(change.change_id,),
        store_path=store_path,
    )

    assert result["status"] == "OK"
    assert result["changes"] == [
        {
            "change_id": change.change_id,
            "found": True,
            "state": change.state.value,
            "process_key": OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            "process_version": OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
            "version": change.version,
            "created_at": change.created_at,
            "updated_at": change.updated_at,
            "stages": [],
            "artifacts": [],
        }
    ]
