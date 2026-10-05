"""Read-only owner-machine preflight for resuming one existing objective lineage."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from jarvis.autonomy.existing_objective import (
    ExistingObjectiveLineageError,
    ExistingObjectiveLineageV1,
    ExistingObjectiveResumeController,
)
from jarvis.autonomy.mode import AutonomyMode
from jarvis.autonomy.supervisor_cutover import SupervisorCutoverController
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.store import ChangeStore
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.workspace import ObjectiveWorkspaceProjector
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path


class _NoMutationBackend:
    def submit(self, work_id, *, priority):
        del work_id, priority
        raise RuntimeError("read-only preflight may not submit durable work")


def inspect_existing_objective(
    *,
    store_path: pathlib.Path,
    lineage: ExistingObjectiveLineageV1,
    expected_target: str | None = None,
    expected_capability_family: str | None = None,
) -> dict[str, object]:
    path = pathlib.Path(store_path).expanduser().resolve()
    if not path.is_file():
        raise ExistingObjectiveLineageError(
            f"canonical Work database does not exist: {path}"
        )
    work = SQLiteWorkStore(
        path,
        payload_codec=build_default_work_payload_codec(path),
    )
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(
            UNKNOWN_INCIDENT_REPAIR_PROCESS,
            OWNER_CAPABILITY_ACQUISITION_PROCESS,
        ),
    )
    projector = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
        work_store=work,
    )
    cutover = SupervisorCutoverController(
        projector=projector,
        change_coordinator=ChangeCoordinator(changes, _NoMutationBackend()),
        mode=AutonomyMode.SHADOW,
    )
    controller = ExistingObjectiveResumeController(
        projector=projector,
        change_store=changes,
        cutover=cutover,
    )
    snapshot = controller.inspect(lineage)

    target = " ".join(str(expected_target or "").split()).strip()
    if target:
        target_key = target.casefold()
        target_matches = any(
            target_key in candidate.casefold()
            or candidate.casefold() in target_key
            for candidate in snapshot.target_names
        )
        if not target_matches:
            raise ExistingObjectiveLineageError(
                f"expected target is not canonical for this objective: {target}"
            )
    family = " ".join(str(expected_capability_family or "").split()).strip()
    if family and family not in snapshot.capability_families:
        raise ExistingObjectiveLineageError(
            "expected capability family is not canonical for this objective: " + family
        )

    return {
        "status": "PASS",
        "mutation_performed": False,
        "store_path": str(path),
        "snapshot": snapshot.canonical_payload() | {"digest": snapshot.digest},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis-global-supervisor-existing-objective-preflight"
    )
    parser.add_argument(
        "--store-path",
        type=pathlib.Path,
        default=default_work_store_path(),
    )
    parser.add_argument("--goal-id", required=True)
    parser.add_argument("--gap-id", required=True)
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--historical-architecture-artifact-id")
    parser.add_argument("--historical-gate-id")
    parser.add_argument("--expected-target")
    parser.add_argument("--expected-capability-family")
    parser.add_argument("--output", type=pathlib.Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    lineage = ExistingObjectiveLineageV1(
        goal_id=args.goal_id,
        gap_id=args.gap_id,
        change_id=args.change_id,
        historical_architecture_artifact_id=(args.historical_architecture_artifact_id),
        historical_gate_id=args.historical_gate_id,
    )
    try:
        report = inspect_existing_objective(
            store_path=args.store_path,
            lineage=lineage,
            expected_target=args.expected_target,
            expected_capability_family=args.expected_capability_family,
        )
    except (ExistingObjectiveLineageError, ValueError, RuntimeError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "mutation_performed": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
