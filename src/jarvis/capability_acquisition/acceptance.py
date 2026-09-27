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
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy


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
            "production_observation_ref": real_evidence[
                "production_observation_ref"
            ],
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
