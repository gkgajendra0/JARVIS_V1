"""Read-only owner-machine preflight for resuming one existing objective lineage."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile

from jarvis.autonomy.existing_objective import (
    ExistingObjectiveLineageError,
    ExistingObjectiveLineageV1,
    ExistingObjectiveResumeController,
    ExistingObjectiveResumeDisposition,
)
from jarvis.autonomy.mode import AutonomyMode
from jarvis.autonomy.supervisor_cutover import SupervisorCutoverController
from jarvis.capability_acquisition.hardening import (
    CapabilitySystemInvariantCode,
    blocking_capability_workspace_invariant_codes,
    inspect_capability_workspace_invariants,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.store import ChangeStore
from jarvis.goal_intelligence.phase9 import migrate_legacy_phase9_gap_links
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.workspace import ObjectiveWorkspaceProjector
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.work.privacy import (
    build_default_work_payload_codec,
    default_work_payload_key_path,
)
from jarvis.work.store import SQLiteWorkStore, default_work_store_path


class _NoMutationBackend:
    def submit(self, work_id, *, priority):
        del work_id, priority
        raise RuntimeError("read-only preflight may not submit durable work")


def _database_source_fingerprint(
    source_path: pathlib.Path,
) -> tuple[tuple[str, str], ...]:
    """Hash canonical SQLite data files without opening the database."""

    members = (source_path, pathlib.Path(str(source_path) + "-wal"))
    fingerprint: list[tuple[str, str]] = []
    for member in members:
        if not member.is_file():
            continue
        digest = hashlib.sha256()
        with member.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint.append((member.name, digest.hexdigest()))
    return tuple(fingerprint)


def _snapshot_work_store(
    source_path: pathlib.Path,
) -> tuple[tempfile.TemporaryDirectory[str], SQLiteWorkStore]:
    """Inspect a stable file snapshot without opening canonical SQLite for writes."""

    if os.name == "nt":
        key_path = default_work_payload_key_path(source_path)
        if not key_path.is_file():
            raise ExistingObjectiveLineageError(
                "protected Work payload key is missing; read-only preflight will not "
                f"create it: {key_path}"
            )
    payload_codec = build_default_work_payload_codec(source_path)
    guard = tempfile.TemporaryDirectory(prefix="jarvis-preflight-")
    snapshot_path = pathlib.Path(guard.name) / source_path.name
    source_wal = pathlib.Path(str(source_path) + "-wal")
    snapshot_wal = pathlib.Path(str(snapshot_path) + "-wal")
    before = _database_source_fingerprint(source_path)
    try:
        shutil.copyfile(source_path, snapshot_path)
        if source_wal.is_file():
            shutil.copyfile(source_wal, snapshot_wal)
        after = _database_source_fingerprint(source_path)
        if before != after:
            raise ExistingObjectiveLineageError(
                "canonical Work database changed during read-only snapshot; "
                "stop JARVIS and rerun the preflight"
            )
    except Exception:
        guard.cleanup()
        raise
    return guard, SQLiteWorkStore(snapshot_path, payload_codec=payload_codec)


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
    snapshot_guard, work = _snapshot_work_store(path)
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(
            UNKNOWN_INCIDENT_REPAIR_PROCESS,
            OWNER_CAPABILITY_ACQUISITION_PROCESS,
        ),
    )
    snapshot_lineage_migrations = migrate_legacy_phase9_gap_links(
        goal_store=goals,
        change_store=changes,
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
    workspace = projector.project(lineage.goal_id)
    invariant_report = inspect_capability_workspace_invariants(
        workspace=workspace,
        change_store=changes,
    )
    blocking_invariant_codes = set(
        blocking_capability_workspace_invariant_codes(
            workspace=workspace,
            change_store=changes,
        )
    )
    recoverable_invariant_codes: set[CapabilitySystemInvariantCode] = set()
    if "phase9-authoritative-source-dependency-v1" in snapshot.startup_recovery_kinds:
        recoverable_invariant_codes.update(
            {
                CapabilitySystemInvariantCode.DEVELOPMENT_MISSING_AUTHORITATIVE_SOURCE,
                CapabilitySystemInvariantCode.DEVELOPMENT_DEPENDS_ON_STALE_SOURCE,
            }
        )
    if (
        "phase9-gicc-external-acceptance-contract-v1"
        in snapshot.startup_recovery_kinds
    ):
        recoverable_invariant_codes.update(
            {
                CapabilitySystemInvariantCode.GICC_ARCHITECTURE_MISSING_EXTERNAL_ACCEPTANCE,
                CapabilitySystemInvariantCode.GICC_ARCHITECTURE_SEMANTIC_CONTRACT_DRIFT,
            }
        )
    recoverable_invariant_findings = tuple(
        finding
        for finding in invariant_report.findings
        if finding.code in recoverable_invariant_codes
        and finding.code.value in blocking_invariant_codes
    )
    unsafe_invariant_findings = tuple(
        finding
        for finding in invariant_report.findings
        if finding.code.value in blocking_invariant_codes
        and finding.code not in recoverable_invariant_codes
    )

    target = " ".join(str(expected_target or "").split()).strip()
    if target:
        target_key = target.casefold()
        target_matches = any(
            target_key in candidate.casefold() or candidate.casefold() in target_key
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

    work_by_id = {item.work_id: item for item in workspace.work_items}
    changes_report = []
    for item in workspace.changes:
        exact_gap_link = any(
            artifact.kind == "gicc_capability_gap_link"
            and str(artifact.payload.get("motivating_goal_id") or "").strip()
            == lineage.goal_id
            and str(artifact.payload.get("gap_id") or "").strip() == lineage.gap_id
            for artifact in item.artifacts
        )
        changes_report.append(
            {
                "change_id": item.change_id,
                "process_key": item.process_key,
                "state": item.state,
                "updated_at": item.updated_at,
                "current_architecture_artifact_id": (
                    item.current_architecture_artifact_id
                ),
                "exact_gap_link": exact_gap_link,
            }
        )

    requested_change = next(
        item for item in workspace.changes if item.change_id == lineage.change_id
    )
    stages_report = []
    for stage in requested_change.stages:
        work_item = work_by_id.get(stage.work_id)
        stages_report.append(
            {
                "stage_key": stage.stage_key,
                "attempt": stage.attempt,
                "work_id": stage.work_id,
                "work_state": None if work_item is None else work_item.state,
                "work_outcome": (
                    None if work_item is None else work_item.system_outcome.kind
                ),
                "work_reason": (
                    None if work_item is None else work_item.system_outcome.reason
                ),
                "authoritative": stage.authoritative,
                "status": stage.status,
                "superseded_by_attempt": stage.superseded_by_attempt,
                "plan_artifact_id": stage.plan_artifact_id,
                "produced_artifact_ids": list(stage.produced_artifact_ids),
            }
        )

    milestone_kinds = (
        "gicc_capability_gap_link",
        "architecture",
        "architecture_revision_request",
        "development_engine_outcome",
        "acceptance",
        "capability_candidate",
        "capability_candidate_verification",
        "capability_package_admission",
        "capability_lifecycle_proposal",
        "capability_lifecycle_activation",
        "capability_lifecycle_disable",
        "capability_external_acceptance_binding",
        "capability_external_acceptance",
    )
    milestones = {}
    for kind in milestone_kinds:
        artifact = changes.latest_artifact(lineage.change_id, kind)
        milestones[kind] = (
            None
            if artifact is None
            else {
                "artifact_id": artifact.artifact_id,
                "digest": artifact.digest,
                "revision": artifact.revision,
            }
        )

    dependency_recovery = changes.diagnose_superseded_dependency_recovery(
        lineage.change_id,
        recovery_generation="phase9-authoritative-source-dependency-v1",
    )

    continuations = [
        {
            "continuation_id": item.record_id,
            "plan_id": item.payload.get("plan_id"),
            "state": item.payload.get("state"),
            "blocked_by_type": item.payload.get("blocked_by_type"),
            "blocked_by_id": item.payload.get("blocked_by_id"),
            "work_ids": list(item.payload.get("work_ids") or ()),
        }
        for item in workspace.continuations
    ]

    status = "PASS"
    if (
        snapshot.resume_disposition
        in {
            ExistingObjectiveResumeDisposition.INACTIVE_LINKED_CHANGE,
            ExistingObjectiveResumeDisposition.LINEAGE_CONFLICT,
        }
        or unsafe_invariant_findings
    ):
        status = "BLOCKED"
    elif snapshot.resume_disposition in {
        ExistingObjectiveResumeDisposition.STARTUP_RECOVERY_REQUIRED,
        ExistingObjectiveResumeDisposition.FAILED_GOVERNING_CHANGE,
    }:
        status = "RECOVERY_REQUIRED"

    report = {
        "status": status,
        "mutation_performed": False,
        "inspection_mode": "sqlite_read_only_snapshot",
        "store_path": str(path),
        "snapshot": snapshot.canonical_payload() | {"digest": snapshot.digest},
        "diagnostics": {
            "snapshot_migrations": {
                "gicc_phase9_v1_to_v2": list(snapshot_lineage_migrations),
            },
            "goal": {
                "goal_id": workspace.goal.record_id,
                "state": workspace.goal.payload.get("state"),
                "current_plan_id": (
                    None if workspace.plan is None else workspace.plan.record_id
                ),
                "current_plan_state": (
                    None
                    if workspace.plan is None
                    else workspace.plan.payload.get("state")
                ),
            },
            "linked_changes": changes_report,
            "continuations": continuations,
            "requested_change_stages": stages_report,
            "requested_change_milestones": milestones,
            "superseded_dependency_recovery": dependency_recovery,
            "capability_system_invariants": {
                "passed": not unsafe_invariant_findings,
                "audit_passed": invariant_report.passed,
                "digest": invariant_report.digest,
                "blocking_codes": sorted(blocking_invariant_codes),
                "findings": [
                    finding.to_payload() for finding in invariant_report.findings
                ],
                "recoverable_findings": [
                    finding.to_payload() for finding in recoverable_invariant_findings
                ],
                "unsafe_findings": [
                    finding.to_payload() for finding in unsafe_invariant_findings
                ],
            },
            "workspace_observed_blockers": list(workspace.observed_blockers),
        },
    }
    snapshot_guard.cleanup()
    return report


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
    parser.add_argument(
        "--blind-target-resolution",
        action="store_true",
        help=(
            "Verify lineage without supplying an external device/resource answer. "
            "This is the required mode for blind capability-acquisition acceptance."
        ),
    )
    parser.add_argument(
        "--expected-target",
        help=(
            "Optional diagnostic assertion against already-canonical target state. "
            "Do not use with --blind-target-resolution."
        ),
    )
    parser.add_argument("--expected-capability-family")
    parser.add_argument("--output", type=pathlib.Path)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.blind_target_resolution and args.expected_target:
        parser.error(
            "--blind-target-resolution cannot be combined with --expected-target"
        )
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
    return 2 if report.get("status") == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
