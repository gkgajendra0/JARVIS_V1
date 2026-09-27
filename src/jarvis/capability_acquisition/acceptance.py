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

from jarvis.capability_acquisition.evaluation import run_replay_suite
from jarvis.capability_acquisition.external_acceptance import load_external_acceptance
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy


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


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    external_evidence: pathlib.Path,
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
    )
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
