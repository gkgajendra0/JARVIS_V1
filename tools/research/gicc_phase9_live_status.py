"""Read-only live status probe for a GICC -> Phase-9 owner mission.

The probe reads canonical durable state only. It does not advance workflows,
change goals, promote code, activate capabilities, or make provider/API calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jarvis.engineering_change import ChangeStore
from jarvis.goal_intelligence.store import GoalStore
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path

_ARTIFACT_KINDS = (
    "gicc_capability_gap_link",
    "owner_capability_goal",
    "capability_acquisition_admission",
    "research",
    "architecture",
    "capability_candidate",
    "verification",
    "promotion",
    "capability_package_admission",
    "capability_lifecycle_activation",
    "capability_external_acceptance",
)


def _work_summary(store: SQLiteWorkStore, work_id: str) -> dict[str, object]:
    work = store.get(work_id)
    if work is None:
        return {"work_id": work_id, "found": False}

    return {
        "work_id": work.work_id,
        "found": True,
        "state": work.state.value,
        "work_type": work.work_type.value,
        "priority": int(work.priority),
        "status_detail": work.status_detail,
        "current_step_id": work.current_step_id,
        "dependencies": list(work.dependencies),
        "version": work.version,
        "created_at": work.created_at.isoformat(),
        "updated_at": work.updated_at.isoformat(),
        "steps": [
            {
                "step_id": step.step_id,
                "kind": step.kind,
                "summary": step.summary,
                "state": step.state.value,
                "error": step.error,
                "started_at": (
                    None if step.started_at is None else step.started_at.isoformat()
                ),
                "completed_at": (
                    None if step.completed_at is None else step.completed_at.isoformat()
                ),
            }
            for step in store.list_steps(work.work_id)
        ],
    }


def _change_summary(store: ChangeStore, change_id: str) -> dict[str, object]:
    change = store.get(change_id)
    if change is None:
        return {"change_id": change_id, "found": False}

    artifacts = []
    for kind in _ARTIFACT_KINDS:
        artifact = store.latest_artifact(change.change_id, kind)
        if artifact is None:
            continue
        artifacts.append(
            {
                "kind": artifact.kind,
                "artifact_id": artifact.artifact_id,
                "revision": artifact.revision,
                "digest": artifact.digest,
                "created_at": artifact.created_at,
            }
        )

    return {
        "change_id": change.change_id,
        "found": True,
        "state": change.state.value,
        "process_key": change.process_key,
        "process_version": change.process_version,
        "version": change.version,
        "created_at": change.created_at,
        "updated_at": change.updated_at,
        "stages": [
            {
                "stage_key": stage.stage_key,
                "attempt": stage.attempt,
                "work_id": stage.work_id,
                "plan_artifact_id": stage.plan_artifact_id,
            }
            for stage in store.list_stages(change.change_id)
        ],
        "artifacts": artifacts,
    }


def probe_live_mission(
    *,
    goal_id: str,
    work_ids: tuple[str, ...] = (),
    change_ids: tuple[str, ...] = (),
    store_path: Path | None = None,
) -> dict[str, object]:
    path = Path(store_path or default_work_store_path()).expanduser().resolve()
    codec = build_default_work_payload_codec(path)
    work_store = SQLiteWorkStore(path, payload_codec=codec)
    goals = GoalStore(work_store)
    changes = ChangeStore(work_store)

    goal = goals.get_goal(goal_id)
    if goal is None:
        return {
            "status": "GOAL_NOT_FOUND",
            "store_path": str(path),
            "goal_id": goal_id,
            "works": [],
            "changes": [],
        }

    gaps = goals.list_gaps(goal_id=goal.goal_id, limit=100)
    continuations = goals.list_continuations(goal_id=goal.goal_id, limit=100)
    plan = goals.latest_plan_for_goal(goal.goal_id)

    resolved_work_ids = set(work_ids)
    for continuation in continuations:
        resolved_work_ids.update(continuation.work_ids)

    resolved_change_ids = set(change_ids)
    for work_id in tuple(resolved_work_ids):
        stage = changes.stage_for_work(work_id)
        if stage is not None:
            resolved_change_ids.add(stage.change_id)

    result = {
        "status": "OK",
        "store_path": str(path),
        "goal": {
            "goal_id": goal.goal_id,
            "state": goal.state.value,
            "goal_revision": goal.goal_revision,
            "desired_outcome": goal.desired_outcome,
            "exact_owner_request": goal.exact_owner_request,
        },
        "plan": (
            None
            if plan is None
            else {
                "plan_id": plan.plan_id,
                "state": plan.state.value,
                "plan_revision": plan.plan_revision,
                "node_count": len(plan.nodes),
            }
        ),
        "gaps": [
            {
                "gap_id": gap.gap_id,
                "state": gap.state.value,
                "family": gap.reusable_capability_family,
                "operations": list(gap.minimum_required_operations),
                "target_entity_type": gap.target_entity_type,
                "target_entity_id": gap.target_entity_id,
            }
            for gap in gaps
        ],
        "continuations": [
            {
                "continuation_id": continuation.continuation_id,
                "state": continuation.state.value,
                "blocked_by_type": continuation.blocked_by_type.value,
                "blocked_by_id": continuation.blocked_by_id,
                "work_ids": list(continuation.work_ids),
                "goal_revision": continuation.goal_revision,
                "resumed_at": continuation.resumed_at,
            }
            for continuation in continuations
        ],
        "works": [
            _work_summary(work_store, work_id) for work_id in sorted(resolved_work_ids)
        ],
        "changes": [
            _change_summary(changes, change_id)
            for change_id in sorted(resolved_change_ids)
        ],
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read canonical live status for one GICC/Phase-9 mission."
    )
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--work-id", action="append", default=[])
    parser.add_argument("--change-id", action="append", default=[])
    parser.add_argument("--store-path", type=Path)
    args = parser.parse_args()

    result = probe_live_mission(
        goal_id=args.goal_id,
        work_ids=tuple(args.work_id),
        change_ids=tuple(args.change_id),
        store_path=args.store_path,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
