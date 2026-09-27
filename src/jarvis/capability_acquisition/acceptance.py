"""Non-destructive owner-machine acceptance for Phase 9 capability acquisition."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.capability_acquisition.evaluation import (
    build_real_capability_evidence,
    run_replay_suite,
    validate_real_capability_evidence,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy
from jarvis.promotion.release import DeploymentMetadataStore, default_deployment_root
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path


class Phase9AcceptanceError(RuntimeError):
    """Phase-9 owner-machine acceptance could not prove a required invariant."""


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    head_sha: str
    tracked_status: str


def _git(repo: pathlib.Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30.0,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Phase9AcceptanceError(f"Git command failed: {' '.join(args)}") from exc
    return completed.stdout.strip()


def _snapshot(repo: pathlib.Path) -> RepositorySnapshot:
    head = _git(repo, "rev-parse", "HEAD").casefold()
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head):
        raise Phase9AcceptanceError("repository HEAD is not an exact Git SHA")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=no")
    return RepositorySnapshot(head_sha=head, tracked_status=status)


def _load_real_evidence(path: pathlib.Path) -> dict[str, object]:
    source = pathlib.Path(path)
    if source.is_symlink() or not source.is_file():
        raise Phase9AcceptanceError("real capability evidence must be a regular file")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase9AcceptanceError(
            "real capability evidence file is unreadable or invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise Phase9AcceptanceError("real capability evidence root must be an object")
    return payload


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    real_evidence_path: pathlib.Path,
    require_windows: bool = True,
) -> dict[str, object]:
    if require_windows and sys.platform != "win32":
        raise Phase9AcceptanceError("Phase-9 owner acceptance requires Windows")

    repo = pathlib.Path(repo_root)
    if repo.is_symlink() or not repo.is_dir():
        raise Phase9AcceptanceError("repo_root must be a regular directory")
    repo = repo.resolve()

    before = _snapshot(repo)
    if before.tracked_status:
        raise Phase9AcceptanceError(
            "owner acceptance requires a clean tracked working tree"
        )

    policy = RepairProtectedSurfacePolicy()
    protected = policy.assess(
        (
            "src/jarvis/capability_acquisition/evaluation.py",
            "src/jarvis/capability_acquisition/acceptance.py",
            "src/jarvis/capability_acquisition/verification.py",
            "src/jarvis/capability_acquisition/promotion.py",
            "src/jarvis/engineering_change/gates.py",
            ".github/workflows/code-quality.yml",
        )
    )
    if protected.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise Phase9AcceptanceError(
            "Phase-9 acquisition/evaluation/promotion controls are not protected"
        )
    if len(protected.protected) != 6:
        raise Phase9AcceptanceError(
            "Phase-9 acceptance expected all control surfaces to be protected"
        )

    replay_root = repo.parent / ".jarvis-phase9-acceptance-replay"
    if replay_root.exists():
        import shutil

        shutil.rmtree(replay_root)
    replay_root.mkdir(parents=True)
    try:
        replay = run_replay_suite(replay_root)
    finally:
        import shutil

        shutil.rmtree(replay_root, ignore_errors=True)

    failures = {item.case_id: item.evidence for item in replay.cases if not item.passed}
    if replay.status != "PASS" or failures:
        raise Phase9AcceptanceError(
            "deterministic Phase-9 replay failed: "
            + json.dumps(failures, sort_keys=True)
        )
    if len(replay.cases) != 24:
        raise Phase9AcceptanceError(
            f"Phase-9 replay expected 24 cases, got {len(replay.cases)}"
        )

    try:
        real_evidence = validate_real_capability_evidence(
            _load_real_evidence(real_evidence_path),
            tested_commit=before.head_sha,
        )
    except ValueError as exc:
        raise Phase9AcceptanceError(str(exc)) from exc

    after = _snapshot(repo)
    if after != before:
        raise Phase9AcceptanceError(
            "Phase-9 acceptance changed protected repository state"
        )

    evidence = {
        "status": "PASS",
        "phase": "phase9_owner_requested_capability_acquisition",
        "tested_commit": before.head_sha,
        "recorded_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "replay": {
            "status": replay.status,
            "case_count": len(replay.cases),
            "suite_digest": replay.suite_digest,
        },
        "real_capability": {
            "change_id": real_evidence["change_id"],
            "acquisition_work_id": real_evidence["acquisition_work_id"],
            "development_work_id": real_evidence["development_work_id"],
            "capability_id": real_evidence["capability_id"],
            "package_id": real_evidence["package_id"],
            "package_version": real_evidence["package_version"],
            "package_digest": real_evidence["package_digest"],
            "promotion_attempt_id": real_evidence["promotion_attempt_id"],
            "active_release_sha": real_evidence["active_release_sha"],
            "operation": real_evidence["operation"],
            "target": real_evidence["target"],
            "observed_effect": real_evidence["observed_effect"],
            "observation_method": real_evidence["observation_method"],
            "production_observation_ref": real_evidence["production_observation_ref"],
            "rollback_disable_evidence_ref": real_evidence[
                "rollback_disable_evidence_ref"
            ],
            "evidence_digest": real_evidence["evidence_digest"],
        },
        "protected_surface_policy": {
            "policy_id": protected.policy_id,
            "policy_version": protected.policy_version,
            "verdict": protected.verdict.value,
            "protected_count": len(protected.protected),
        },
        "protected_repo_unchanged": True,
    }
    evidence["evidence_digest"] = canonical_digest(evidence)
    return evidence


def _artifact_ref(artifact) -> str:
    return f"{artifact.artifact_id}:sha256:{artifact.digest}"


def collect_real_capability_evidence(
    *,
    repo_root: pathlib.Path,
    change_id: str,
    operation: str,
    target: str,
    observed_effect: str,
    observation_method: str,
) -> dict[str, object]:
    """Build real evidence from canonical durable Phase-9 state plus owner observation."""

    repo = pathlib.Path(repo_root).resolve()
    tested_commit = _snapshot(repo).head_sha
    store_path = default_work_store_path()
    work = SQLiteWorkStore(
        store_path,
        payload_codec=build_default_work_payload_codec(store_path),
    )
    changes = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    change = changes.require(str(change_id).strip())
    if change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key:
        raise Phase9AcceptanceError("change is not Phase-9 capability acquisition")

    stages = changes.list_stages(change.change_id)
    acquisition_stage = next(
        (
            item
            for item in stages
            if item.stage_key
            == OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
        ),
        None,
    )
    development_stage = next(
        (
            item
            for item in reversed(stages)
            if item.stage_key
            == OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
        ),
        None,
    )
    if acquisition_stage is None or development_stage is None:
        raise Phase9AcceptanceError(
            "Phase-9 acquisition/development WorkItem lineage is incomplete"
        )

    goal = changes.latest_artifact(change.change_id, "capability_goal")
    plan = changes.latest_artifact(change.change_id, "acquisition_plan")
    architecture = changes.latest_artifact(change.change_id, "architecture")
    candidate = changes.latest_artifact(change.change_id, "capability_candidate")
    admission = changes.latest_artifact(
        change.change_id,
        "capability_package_admission",
    )
    activation = changes.latest_artifact(
        change.change_id,
        "capability_lifecycle_activation",
    )
    disabled = changes.latest_artifact(
        change.change_id,
        "capability_lifecycle_disable",
    )
    observations = changes.list_artifacts(
        change.change_id,
        kind="production_observation",
    )
    healthy_observation = next(
        (
            item
            for item in reversed(observations)
            if item.payload.get("healthy") is True
        ),
        None,
    )
    required = {
        "goal": goal,
        "plan": plan,
        "architecture": architecture,
        "candidate": candidate,
        "admission": admission,
        "activation": activation,
        "disable": disabled,
        "production_observation": healthy_observation,
    }
    missing = tuple(name for name, artifact in required.items() if artifact is None)
    if missing:
        raise Phase9AcceptanceError(
            "real capability evidence is incomplete: " + ", ".join(missing)
        )
    assert goal is not None
    assert plan is not None
    assert architecture is not None
    assert candidate is not None
    assert admission is not None
    assert activation is not None
    assert disabled is not None
    assert healthy_observation is not None

    if activation.payload.get("effective_enabled") is not True:
        raise Phase9AcceptanceError(
            "latest acquisition activation did not become effectively enabled"
        )
    if disabled.payload.get("effective_enabled") is not False:
        raise Phase9AcceptanceError(
            "latest acquisition disable did not restore disabled effective state"
        )
    if (
        activation.payload.get("candidate_artifact_id") != candidate.artifact_id
        or activation.payload.get("candidate_artifact_digest") != candidate.digest
        or disabled.payload.get("candidate_artifact_id") != candidate.artifact_id
        or disabled.payload.get("candidate_artifact_digest") != candidate.digest
    ):
        raise Phase9AcceptanceError(
            "activation/disable evidence is not bound to current candidate"
        )

    active = DeploymentMetadataStore(default_deployment_root()).active()
    active_release_sha = str(admission.payload.get("active_release_sha") or "").strip()
    attempt_id = str(admission.payload.get("attempt_id") or "").strip()
    if (
        active is None
        or active.release_sha != active_release_sha
        or active.promotion_attempt_id != attempt_id
    ):
        raise Phase9AcceptanceError(
            "current active release differs from Phase-9 package admission"
        )

    goal_digest = str(goal.payload.get("digest") or "").strip().casefold()
    plan_digest = str(plan.payload.get("digest") or "").strip().casefold()
    candidate_digest = str(candidate.payload.get("digest") or "").strip().casefold()
    if not all((goal_digest, plan_digest, candidate_digest)):
        raise Phase9AcceptanceError(
            "canonical Phase-9 goal/plan/candidate digest evidence is incomplete"
        )

    payload = build_real_capability_evidence(
        tested_commit=tested_commit,
        change_id=change.change_id,
        acquisition_work_id=acquisition_stage.work_id,
        development_work_id=development_stage.work_id,
        goal_digest=goal_digest,
        plan_digest=plan_digest,
        architecture_digest=architecture.digest,
        candidate_digest=candidate_digest,
        capability_id=str(candidate.payload.get("capability_id") or ""),
        package_id=str(candidate.payload.get("package_id") or ""),
        package_version=str(candidate.payload.get("package_version") or ""),
        package_digest=str(candidate.payload.get("package_digest") or "").casefold(),
        promotion_attempt_id=attempt_id,
        active_release_sha=active_release_sha.casefold(),
        lifecycle_evidence_ref=_artifact_ref(activation),
        operation=str(operation).strip(),
        target=str(target).strip(),
        observed_effect=str(observed_effect).strip(),
        observation_method=str(observation_method).strip().casefold(),
        production_observation_ref=_artifact_ref(healthy_observation),
        rollback_disable_evidence_ref=_artifact_ref(disabled),
        recorded_at=datetime.now(UTC).isoformat(),
        owner_confirmed=True,
        production_observed=True,
        rollback_disable_verified=True,
    )
    return validate_real_capability_evidence(
        payload,
        tested_commit=tested_commit,
    )


def _record_change_real(args: argparse.Namespace) -> int:
    payload = collect_real_capability_evidence(
        repo_root=args.repo_root,
        change_id=args.change_id,
        operation=args.operation,
        target=args.target,
        observed_effect=args.observed_effect,
        observation_method=args.observation_method,
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "RECORDED",
                "change_id": payload["change_id"],
                "evidence_digest": payload["evidence_digest"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


def _record_real(args: argparse.Namespace) -> int:
    payload = build_real_capability_evidence(
        tested_commit=args.tested_commit.strip().casefold(),
        change_id=args.change_id,
        acquisition_work_id=args.acquisition_work_id,
        development_work_id=args.development_work_id,
        goal_digest=args.goal_digest.strip().casefold(),
        plan_digest=args.plan_digest.strip().casefold(),
        architecture_digest=args.architecture_digest.strip().casefold(),
        candidate_digest=args.candidate_digest.strip().casefold(),
        capability_id=args.capability_id,
        package_id=args.package_id,
        package_version=args.package_version,
        package_digest=args.package_digest.strip().casefold(),
        promotion_attempt_id=args.promotion_attempt_id,
        active_release_sha=args.active_release_sha.strip().casefold(),
        lifecycle_evidence_ref=args.lifecycle_evidence_ref,
        operation=args.operation,
        target=args.target,
        observed_effect=args.observed_effect,
        observation_method=args.observation_method,
        production_observation_ref=args.production_observation_ref,
        rollback_disable_evidence_ref=args.rollback_disable_evidence_ref,
        recorded_at=datetime.now(UTC).isoformat(),
        owner_confirmed=True,
        production_observed=True,
        rollback_disable_verified=True,
    )
    validate_real_capability_evidence(
        payload,
        tested_commit=args.tested_commit.strip().casefold(),
    )
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "RECORDED",
                "evidence_digest": payload["evidence_digest"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


def _accept(args: argparse.Namespace) -> int:
    evidence = run_acceptance(
        repo_root=args.repo_root,
        real_evidence_path=args.real_evidence,
    )
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis-phase9-acceptance")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser(
        "record-real",
        help="Record explicit owner-observed real capability evidence.",
    )
    record.add_argument("--tested-commit", required=True)
    record.add_argument("--change-id", required=True)
    record.add_argument("--acquisition-work-id", required=True)
    record.add_argument("--development-work-id", required=True)
    record.add_argument("--goal-digest", required=True)
    record.add_argument("--plan-digest", required=True)
    record.add_argument("--architecture-digest", required=True)
    record.add_argument("--candidate-digest", required=True)
    record.add_argument("--capability-id", required=True)
    record.add_argument("--package-id", required=True)
    record.add_argument("--package-version", required=True)
    record.add_argument("--package-digest", required=True)
    record.add_argument("--promotion-attempt-id", required=True)
    record.add_argument("--active-release-sha", required=True)
    record.add_argument("--lifecycle-evidence-ref", required=True)
    record.add_argument("--operation", required=True)
    record.add_argument("--target", required=True)
    record.add_argument("--observed-effect", required=True)
    record.add_argument(
        "--observation-method",
        choices=(
            "owner_observed",
            "device_state_readback",
            "external_system_readback",
        ),
        required=True,
    )
    record.add_argument("--production-observation-ref", required=True)
    record.add_argument("--rollback-disable-evidence-ref", required=True)
    record.add_argument("--output", type=pathlib.Path, required=True)
    record.set_defaults(handler=_record_real)

    record_change = sub.add_parser(
        "record-change-real",
        help=(
            "Collect canonical Phase-9 evidence for one real owner-observed "
            "capability effect."
        ),
    )
    record_change.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
    )
    record_change.add_argument("--change-id", required=True)
    record_change.add_argument("--operation", required=True)
    record_change.add_argument("--target", required=True)
    record_change.add_argument("--observed-effect", required=True)
    record_change.add_argument(
        "--observation-method",
        choices=(
            "owner_observed",
            "device_state_readback",
            "external_system_readback",
        ),
        default="owner_observed",
    )
    record_change.add_argument("--output", type=pathlib.Path, required=True)
    record_change.set_defaults(handler=_record_change_real)

    accept = sub.add_parser(
        "accept",
        help="Run final Phase-9 owner-machine acceptance.",
    )
    accept.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
    )
    accept.add_argument("--real-evidence", type=pathlib.Path, required=True)
    accept.add_argument("--output", type=pathlib.Path)
    accept.set_defaults(handler=_accept)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "reason": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
