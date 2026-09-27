"""Non-destructive owner-machine acceptance for Phase 7 release mechanics."""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy

from .release import DeploymentMetadataStore, GitReleaseStager, ReleaseRecord


class Phase7AcceptanceError(RuntimeError):
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
        raise Phase7AcceptanceError(f"Git command failed: {' '.join(args)}") from exc
    return completed.stdout.strip()


def _snapshot(repo: pathlib.Path) -> RepositorySnapshot:
    head = _git(repo, "rev-parse", "HEAD").casefold()
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head):
        raise Phase7AcceptanceError("repository HEAD is not an exact Git SHA")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=no")
    return RepositorySnapshot(head, status)


def _config_digest(repo: pathlib.Path) -> str:
    payload = {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "repo": str(repo),
    }
    return canonical_digest(payload)


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    require_windows: bool = True,
) -> dict[str, object]:
    if require_windows and sys.platform != "win32":
        raise Phase7AcceptanceError("Phase-7 owner acceptance requires Windows")
    repo = pathlib.Path(repo_root)
    if repo.is_symlink() or not repo.is_dir():
        raise Phase7AcceptanceError("repo_root must be a regular directory")
    repo = repo.resolve()
    before = _snapshot(repo)
    if before.tracked_status:
        raise Phase7AcceptanceError(
            "owner acceptance requires a clean tracked working tree"
        )

    policy = RepairProtectedSurfacePolicy()
    protected = policy.assess(
        (
            "src/jarvis/promotion/deployment.py",
            "src/jarvis/dev_supervisor.py",
            ".github/workflows/code-quality.yml",
        )
    )
    if protected.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise Phase7AcceptanceError(
            "Phase-7 promotion/deployment surfaces are not protected"
        )

    with tempfile.TemporaryDirectory(prefix="jarvis-phase7-acceptance-") as temp:
        root = pathlib.Path(temp)
        releases = root / "releases"
        metadata = DeploymentMetadataStore(root / "deployment")
        stager = GitReleaseStager(repo, releases)

        slot = stager.stage(before.head_sha)
        staged_sha = _git(slot, "rev-parse", "HEAD").casefold()
        if staged_sha != before.head_sha:
            raise Phase7AcceptanceError("release slot did not preserve exact SHA")
        staged_again = stager.stage(before.head_sha)
        if staged_again != slot:
            raise Phase7AcceptanceError("exact release staging is not idempotent")

        config_digest = _config_digest(repo)
        bootstrap_digest = canonical_digest(
            {
                "kind": "phase7_acceptance_lkg",
                "release_sha": before.head_sha,
                "config_digest": config_digest,
            }
        )
        record = ReleaseRecord(
            release_sha=before.head_sha,
            release_root=str(slot),
            promotion_attempt_id=f"promotion_acceptance_{before.head_sha[:16]}",
            promotion_evidence_digest=bootstrap_digest,
            config_digest=config_digest,
            schema_versions=(),
            accepted_at_epoch=1.0,
        )
        metadata.set_active(record)
        metadata.set_lkg(record)
        if metadata.active() != record or metadata.lkg() != record:
            raise Phase7AcceptanceError("atomic deployment metadata did not round-trip")
        runtime_identity = record.runtime_identity()
        if (
            runtime_identity.release_sha != before.head_sha
            or pathlib.Path(runtime_identity.release_root) != slot
        ):
            raise Phase7AcceptanceError("runtime release identity changed")

        slot_status = _git(
            slot,
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
        )
        if slot_status:
            raise Phase7AcceptanceError("staged release has tracked mutations")

        after = _snapshot(repo)
        if after != before:
            raise Phase7AcceptanceError("acceptance changed protected repository state")

        evidence = {
            "status": "PASS",
            "tested_commit": before.head_sha,
            "recorded_at": datetime.now(UTC).isoformat(),
            "release_slot": {
                "sha": staged_sha,
                "idempotent": True,
                "tracked_clean": True,
            },
            "deployment_metadata": {
                "active_sha": metadata.active().release_sha,
                "lkg_sha": metadata.lkg().release_sha,
                "config_digest": config_digest,
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
    parser = argparse.ArgumentParser(prog="jarvis-phase7-acceptance")
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument("--output", type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_acceptance(repo_root=args.repo_root)
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
