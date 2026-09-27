"""Non-destructive Windows owner-machine acceptance for Phase 9."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.capability_acquisition.architecture import (
    ensure_capability_acquisition_architecture_current,
)
from jarvis.capability_acquisition.evaluation import run_replay_suite
from jarvis.capability_acquisition.external_acceptance import (
    Phase9ExternalAcceptanceEvidenceV1,
    load_external_acceptance,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.promotion import (
    ensure_capability_release_bridge_current,
)
from jarvis.capability_acquisition.verification import (
    ensure_capability_candidate_acceptance_current,
)
from jarvis.capability_registry.models import DesiredActivationState
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_change.models import ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy
from jarvis.promotion.models import PromotionAttemptState
from jarvis.promotion.release import (
    DeploymentMetadataStore,
    default_deployment_root,
)
from jarvis.promotion.store import PromotionStore
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore, default_work_store_path


class Phase9AcceptanceError(RuntimeError):
    pass


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
    if len(head) != 40 or any(character not in "0123456789abcdef" for character in head):
        raise Phase9AcceptanceError("repository HEAD is not an exact Git SHA")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=no")
    return RepositorySnapshot(head_sha=head, tracked_status=status)


def _validate_live_acquisition(
    *,
    change_id: str,
    external: Phase9ExternalAcceptanceEvidenceV1,
) -> dict[str, object]:
    normalized_change_id = str(change_id).strip()
    if not normalized_change_id:
        raise Phase9AcceptanceError("change_id must not be empty")

    work_path = default_work_store_path()
    if not work_path.is_file():
        raise Phase9AcceptanceError(
            "canonical Work/EngineeringChange database is unavailable"
        )
    work_store = SQLiteWorkStore(
        work_path,
        payload_codec=build_default_work_payload_codec(work_path),
    )
    changes = ChangeStore(
        work_store,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    change = changes.require(normalized_change_id)
    if (
        change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
        or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
    ):
        raise Phase9AcceptanceError(
            "owner-machine evidence references a non-Phase-9 EngineeringChange"
        )
    if change.state is not ChangeState.CLOSED:
        raise Phase9AcceptanceError(
            "Phase-9 EngineeringChange must be CLOSED after production observation"
        )

    architecture = ensure_capability_acquisition_architecture_current(
        changes,
        normalized_change_id,
    )
    acceptance = ensure_capability_candidate_acceptance_current(
        changes,
        normalized_change_id,
    )
    candidate = changes.latest_artifact(
        normalized_change_id,
        "capability_candidate",
    )
    admission = changes.latest_artifact(
        normalized_change_id,
        "capability_package_admission",
    )
    lifecycle = changes.latest_artifact(
        normalized_change_id,
        "capability_lifecycle_proposal",
    )
    if candidate is None or admission is None or lifecycle is None:
        raise Phase9AcceptanceError(
            "Phase-9 durable candidate/package/lifecycle evidence is incomplete"
        )

    attempt_id = str(admission.payload.get("attempt_id") or "").strip()
    if not attempt_id:
        raise Phase9AcceptanceError("Phase-9 admission has no promotion attempt")
    deployment = DeploymentMetadataStore(default_deployment_root())
    ensure_capability_release_bridge_current(
        changes,
        deployment,
        normalized_change_id,
        attempt_id=attempt_id,
    )

    promotions = PromotionStore(changes)
    attempt = promotions.require(attempt_id)
    if attempt.state is not PromotionAttemptState.COMPLETED:
        raise Phase9AcceptanceError(
            "Phase-7 promotion attempt must be COMPLETED after observation"
        )
    active = deployment.active()
    lkg = deployment.lkg()
    if (
        active is None
        or lkg is None
        or active.promotion_attempt_id != attempt_id
        or lkg.promotion_attempt_id != attempt_id
        or active.release_sha != lkg.release_sha
    ):
        raise Phase9AcceptanceError(
            "active/LKG production release is not the completed Phase-9 promotion"
        )

    package_id = str(candidate.payload.get("package_id") or "").strip().casefold()
    package_version = str(candidate.payload.get("package_version") or "").strip()
    package_digest = str(candidate.payload.get("package_digest") or "").strip().casefold()
    capability_id = str(candidate.payload.get("capability_id") or "").strip().casefold()
    if (
        external.capability_id != capability_id
        or external.package_id != package_id
        or external.package_version != package_version
        or external.package_digest != package_digest
    ):
        raise Phase9AcceptanceError(
            "real external evidence does not match the promoted Phase-9 package"
        )

    registry = CapabilityRegistryStore()
    state = registry.require_registry(capability_id)
    if (
        state.desired_state is not DesiredActivationState.ENABLED
        or state.selected_package_id != package_id
        or state.selected_package_version != package_version
        or state.selected_package_digest != package_digest
    ):
        raise Phase9AcceptanceError(
            "Phase-8 lifecycle truth is not enabled on the exact acquired package"
        )
    admitted = registry.get_package(package_id, package_version)
    if admitted is None or admitted.package_digest != package_digest:
        raise Phase9AcceptanceError(
            "Phase-8 registry does not contain the exact acquired package"
        )

    requested = {
        str(item).strip().casefold()
        for item in architecture.payload.get("requested_operations", [])
        if str(item).strip()
    }
    observed = {item.operation for item in external.operations}
    if not requested or not requested.issubset(observed):
        raise Phase9AcceptanceError(
            "real external evidence does not cover all requested operations"
        )
    if acceptance.payload.get("candidate_artifact_id") != candidate.artifact_id:
        raise Phase9AcceptanceError(
            "canonical acceptance no longer binds the current capability candidate"
        )
    if (
        admission.payload.get("candidate_artifact_id") != candidate.artifact_id
        or admission.payload.get("compatibility_verdict") != "ready"
        or admission.payload.get("auto_activated") is not False
        or lifecycle.payload.get("authority_required") is not True
    ):
        raise Phase9AcceptanceError(
            "package admission/lifecycle evidence is stale or bypasses Authority"
        )

    return {
        "change_id": normalized_change_id,
        "change_state": change.state.value,
        "architecture_artifact_id": architecture.artifact_id,
        "architecture_digest": architecture.digest,
        "candidate_artifact_id": candidate.artifact_id,
        "candidate_artifact_digest": candidate.digest,
        "candidate_id": candidate.payload.get("candidate_id"),
        "candidate_digest": candidate.payload.get("digest"),
        "promotion_attempt_id": attempt.attempt_id,
        "promotion_state": attempt.state.value,
        "active_release_sha": active.release_sha,
        "lkg_release_sha": lkg.release_sha,
        "package_admission_artifact_id": admission.artifact_id,
        "package_admission_digest": admission.digest,
        "lifecycle_proposal_artifact_id": lifecycle.artifact_id,
        "lifecycle_proposal_digest": lifecycle.digest,
        "registry_generation": state.generation,
        "registry_desired_state": state.desired_state.value,
        "selected_package_id": state.selected_package_id,
        "selected_package_version": state.selected_package_version,
        "selected_package_digest": state.selected_package_digest,
        "requested_operations": sorted(requested),
        "verified_external_operations": sorted(observed),
    }


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    external_evidence: pathlib.Path,
    change_id: str,
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
            "src/jarvis/capability_acquisition/verification.py",
            "src/jarvis/capability_acquisition/promotion.py",
            "src/jarvis/capability_acquisition/evaluation.py",
            "src/jarvis/capability_acquisition/external_acceptance.py",
            "src/jarvis/promotion/observation.py",
        )
    )
    if protected.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise Phase9AcceptanceError(
            "Phase-9 acquisition/promotion/acceptance surfaces are not protected"
        )
    if len(protected.protected) != 5:
        raise Phase9AcceptanceError(
            "Phase-9 owner acceptance expected all control surfaces to be protected"
        )

    real = load_external_acceptance(external_evidence)
    live = _validate_live_acquisition(
        change_id=change_id,
        external=real,
    )

    with tempfile.TemporaryDirectory(prefix="jarvis-phase9-acceptance-") as temp:
        root = pathlib.Path(temp)
        replay = run_replay_suite(root / "replay")
        failures = {
            item.case_id: item.evidence for item in replay.cases if not item.passed
        }
        if replay.status != "PASS" or failures:
            raise Phase9AcceptanceError(
                "deterministic Phase-9 replay failed: "
                + json.dumps(failures, sort_keys=True)
            )
        if len(replay.cases) != 24:
            raise Phase9AcceptanceError(
                f"Phase-9 replay expected 24 cases, got {len(replay.cases)}"
            )

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
                "phase7_suite_digest": replay.phase7_suite_digest,
                "phase8_suite_digest": replay.phase8_suite_digest,
            },
            "live_acquisition": live,
            "real_external_capability": {
                "capability_id": real.capability_id,
                "package_id": real.package_id,
                "package_version": real.package_version,
                "package_digest": real.package_digest,
                "target_kind": real.target_kind,
                "target_identity": real.target_identity,
                "operations": [item.operation for item in real.operations],
                "evidence_digest": real.digest,
                "effective_enabled_verified": real.effective_enabled_verified,
                "disable_rollback_verified": real.disable_rollback_verified,
                "owner_confirmed": real.owner_confirmed,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis-phase9-acceptance")
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
    )
    parser.add_argument(
        "--change-id",
        required=True,
        help="Canonical Phase-9 EngineeringChange ID for the real acquisition.",
    )
    parser.add_argument(
        "--external-evidence",
        type=pathlib.Path,
        required=True,
        help="JSON evidence from one real owner-requested external capability test.",
    )
    parser.add_argument("--output", type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_acceptance(
        repo_root=args.repo_root,
        external_evidence=args.external_evidence,
        change_id=args.change_id,
    )
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
