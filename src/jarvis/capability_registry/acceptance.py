"""Non-destructive owner-machine acceptance for Phase 8 capability lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.capability_registry.evaluation import run_replay_suite
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import RepairProtectedSurfacePolicy


class Phase8AcceptanceError(RuntimeError):
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
        raise Phase8AcceptanceError(
            f"Git command failed: {' '.join(args)}"
        ) from exc
    return completed.stdout.strip()


def _snapshot(repo: pathlib.Path) -> RepositorySnapshot:
    head = _git(repo, "rev-parse", "HEAD").casefold()
    if len(head) != 40 or any(char not in "0123456789abcdef" for char in head):
        raise Phase8AcceptanceError("repository HEAD is not an exact Git SHA")
    status = _git(repo, "status", "--porcelain=v1", "--untracked-files=no")
    return RepositorySnapshot(head_sha=head, tracked_status=status)


def _registry_file_handle_acceptance(root: pathlib.Path) -> dict[str, object]:
    path = root / "registry-file-handle.sqlite3"
    store = CapabilityRegistryStore(path)
    if not path.is_file():
        raise Phase8AcceptanceError("capability registry database was not created")

    with sqlite3.connect(path) as connection:
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if user_version <= 0:
        raise Phase8AcceptanceError("capability registry schema was not initialized")

    # CapabilityRegistryStore owns no long-lived connection. On Windows this rename
    # fails if our code accidentally leaked a SQLite file handle.
    moved = root / "registry-file-handle.moved.sqlite3"
    os.replace(path, moved)
    os.replace(moved, path)

    reopened = CapabilityRegistryStore(path)
    with sqlite3.connect(reopened.path) as connection:
        reopened_version = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
    if reopened_version != user_version:
        raise Phase8AcceptanceError(
            "capability registry schema changed after file-handle restart proof"
        )

    return {
        "replace_roundtrip": True,
        "reopened": True,
        "schema_version": reopened_version,
    }


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    require_windows: bool = True,
) -> dict[str, object]:
    if require_windows and sys.platform != "win32":
        raise Phase8AcceptanceError("Phase-8 owner acceptance requires Windows")

    repo = pathlib.Path(repo_root)
    if repo.is_symlink() or not repo.is_dir():
        raise Phase8AcceptanceError("repo_root must be a regular directory")
    repo = repo.resolve()

    before = _snapshot(repo)
    if before.tracked_status:
        raise Phase8AcceptanceError(
            "owner acceptance requires a clean tracked working tree"
        )

    policy = RepairProtectedSurfacePolicy()
    protected = policy.assess(
        (
            "src/jarvis/capability_registry/lifecycle.py",
            "src/jarvis/capability_registry/evaluation.py",
            "src/jarvis/capabilities/runtime.py",
            ".github/workflows/code-quality.yml",
        )
    )
    if protected.verdict is not ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
        raise Phase8AcceptanceError(
            "Phase-8 lifecycle/evaluation/runtime surfaces are not protected"
        )
    if len(protected.protected) != 4:
        raise Phase8AcceptanceError(
            "Phase-8 owner acceptance expected all control surfaces to be protected"
        )

    with tempfile.TemporaryDirectory(prefix="jarvis-phase8-acceptance-") as temp:
        root = pathlib.Path(temp)

        replay = run_replay_suite(root / "replay")
        failures = {
            item.case_id: item.evidence for item in replay.cases if not item.passed
        }
        if replay.status != "PASS" or failures:
            raise Phase8AcceptanceError(
                "deterministic Phase-8 replay failed: "
                + json.dumps(failures, sort_keys=True)
            )
        if len(replay.cases) != 45:
            raise Phase8AcceptanceError(
                f"Phase-8 replay expected 45 cases, got {len(replay.cases)}"
            )

        file_handle = _registry_file_handle_acceptance(root)

        after = _snapshot(repo)
        if after != before:
            raise Phase8AcceptanceError(
                "Phase-8 acceptance changed protected repository state"
            )

        evidence = {
            "status": "PASS",
            "phase": "phase8_capability_package_registry_lifecycle",
            "tested_commit": before.head_sha,
            "recorded_at": datetime.now(UTC).isoformat(),
            "python": sys.version.split()[0],
            "platform": sys.platform,
            "replay": {
                "status": replay.status,
                "case_count": len(replay.cases),
                "suite_digest": replay.suite_digest,
            },
            "registry_file_handle": file_handle,
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
    parser = argparse.ArgumentParser(prog="jarvis-phase8-acceptance")
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path.cwd(),
    )
    parser.add_argument("--output", type=pathlib.Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run_acceptance(repo_root=args.repo_root)
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
