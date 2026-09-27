"""Consolidated owner-machine acceptance for Phase 6.

This harness proves the real Windows Git-worktree, Docker sandbox, restart/reopen,
and deterministic replay path. It never grants owner approval, promotion, merge,
deployment, or protected-surface mutation authority.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime

from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.incident_repair.evaluation import run_replay_suite
from jarvis.incident_repair.process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from jarvis.work.development import (
    DevelopmentWorkspaceManager,
    DockerDevelopmentTestRunner,
)
from jarvis.work.models import WorkPriority
from jarvis.work.store import SQLiteWorkStore


class Phase6AcceptanceError(RuntimeError):
    """Owner-machine Phase-6 acceptance could not prove an invariant."""


@dataclass(frozen=True, slots=True)
class _Backend:
    submitted: list[str]

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


@dataclass(frozen=True, slots=True)
class _FixedRevisionResolver:
    revision: str

    def revision_for(self, work_id: str) -> str | None:
        if not str(work_id).strip():
            return None
        return self.revision


def _run(
    command: list[str],
    *,
    cwd: pathlib.Path | None = None,
    timeout: float = 30.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=check,
            shell=False,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise Phase6AcceptanceError(str(exc)) from exc


def _tested_commit(repo: pathlib.Path) -> str:
    completed = _run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        timeout=10.0,
    )
    commit = completed.stdout.strip().casefold()
    if (
        completed.returncode != 0
        or len(commit) != 40
        or any(char not in "0123456789abcdef" for char in commit)
    ):
        raise Phase6AcceptanceError(
            "acceptance Git revision is not a full commit SHA"
        )
    return commit


def _repo_snapshot(repo: pathlib.Path) -> dict[str, str]:
    head = _tested_commit(repo)
    status = _run(
        ["git", "-C", str(repo), "status", "--porcelain=v1"],
        timeout=10.0,
    )
    if status.returncode != 0:
        raise Phase6AcceptanceError("protected checkout status is unavailable")
    return {
        "head": head,
        "status_sha256": hashlib.sha256(status.stdout.encode("utf-8")).hexdigest(),
    }


def _require_windows_docker(test_image: str) -> dict[str, object]:
    if os.name != "nt":
        raise Phase6AcceptanceError(
            "Phase-6 owner-machine acceptance must run on Windows"
        )
    docker = shutil.which("docker")
    if docker is None:
        raise Phase6AcceptanceError("Docker executable is unavailable")
    info = _run([docker, "info"], timeout=30.0)
    if info.returncode != 0:
        raise Phase6AcceptanceError("Docker daemon is unavailable")

    inspect = _run(
        [
            docker,
            "image",
            "inspect",
            test_image,
            "--format",
            "{{json .}}",
        ],
        timeout=30.0,
    )
    if inspect.returncode != 0:
        raise Phase6AcceptanceError(
            "approved Phase-6 test image is unavailable"
        )
    try:
        payload = json.loads(inspect.stdout)
    except json.JSONDecodeError as exc:
        raise Phase6AcceptanceError(
            "Docker image identity is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise Phase6AcceptanceError("Docker image identity is malformed")
    image_id = str(payload.get("Id") or "").strip()
    repo_digests = payload.get("RepoDigests")
    if not image_id.startswith("sha256:"):
        raise Phase6AcceptanceError("Docker image has no immutable image ID")
    return {
        "test_image": test_image,
        "image_id": image_id,
        "repo_digests": (
            sorted(str(item) for item in repo_digests)
            if isinstance(repo_digests, list)
            else []
        ),
    }


def _git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if git is None:
        raise Phase6AcceptanceError("Git executable is unavailable")
    result = _run([git, *args], cwd=root, timeout=30.0)
    if result.returncode != 0:
        raise Phase6AcceptanceError(
            "Git fixture command failed: " + " ".join(args)
        )
    return result


def _owner_worktree_and_docker_acceptance(
    root: pathlib.Path,
    *,
    test_image: str,
) -> dict[str, object]:
    fixture = root / "owner-fixture"
    fixture.mkdir(parents=True)
    _git(fixture, "init")
    _git(fixture, "config", "user.email", "jarvis-phase6@example.invalid")
    _git(fixture, "config", "user.name", "JARVIS Phase6 Acceptance")
    tests = fixture / "tests"
    tests.mkdir()
    (fixture / "fixture_module.py").write_text("VALUE = 7\n", encoding="utf-8")
    (tests / "test_phase6_owner_fixture.py").write_text(
        "from fixture_module import VALUE\n\n"
        "def test_value():\n"
        "    assert VALUE == 7\n",
        encoding="utf-8",
    )
    _git(fixture, "add", ".")
    _git(fixture, "commit", "-m", "owner acceptance fixture")
    revision = _git(fixture, "rev-parse", "HEAD").stdout.strip().casefold()

    # Move the protected checkout forward after the approved revision. The worktree
    # must still reopen from the exact approved SHA.
    (fixture / "fixture_module.py").write_text("VALUE = 99\n", encoding="utf-8")
    _git(fixture, "add", "fixture_module.py")
    _git(fixture, "commit", "-m", "advance protected fixture checkout")
    protected_head = _git(fixture, "rev-parse", "HEAD").stdout.strip().casefold()
    if protected_head == revision:
        raise Phase6AcceptanceError("fixture checkout did not advance")

    resolver = _FixedRevisionResolver(revision)
    workspace_root = root / "owner-worktrees"
    manager = DevelopmentWorkspaceManager(
        repository_root=fixture,
        workspace_root=workspace_root,
        base_revision_resolver=resolver,
    )
    workspace = manager.ensure("phase6_owner_acceptance")
    workspace_head = _git(
        workspace.path,
        "rev-parse",
        "HEAD",
    ).stdout.strip().casefold()
    if workspace_head != revision:
        raise Phase6AcceptanceError(
            "Windows development worktree was not pinned to approved revision"
        )

    docker_result = asyncio.run(
        DockerDevelopmentTestRunner(test_image).run(
            workspace.path,
            targets=("tests/test_phase6_owner_fixture.py",),
            timeout_seconds=120.0,
        )
    )
    if (
        docker_result.get("passed") is not True
        or docker_result.get("network") != "disabled"
        or docker_result.get("workspace") != "read_only"
        or docker_result.get("sandbox_profile") != "test.offline.v1"
    ):
        raise Phase6AcceptanceError(
            "real Docker development sandbox did not satisfy Phase-6 controls"
        )

    # Simulate process restart by reconstructing the manager from durable identity.
    reopened = DevelopmentWorkspaceManager(
        repository_root=fixture,
        workspace_root=workspace_root,
        base_revision_resolver=resolver,
    )
    reopened_workspace = reopened.ensure("phase6_owner_acceptance")
    reopened_head = _git(
        reopened_workspace.path,
        "rev-parse",
        "HEAD",
    ).stdout.strip().casefold()
    if (
        reopened_workspace.path != workspace.path
        or reopened_workspace.branch != workspace.branch
        or reopened_head != revision
    ):
        raise Phase6AcceptanceError(
            "development workspace identity changed after restart/reopen"
        )

    protected_after = _git(fixture, "rev-parse", "HEAD").stdout.strip().casefold()
    protected_status = _git(fixture, "status", "--porcelain=v1").stdout
    if protected_after != protected_head or protected_status:
        raise Phase6AcceptanceError(
            "protected fixture checkout changed during worktree/Docker acceptance"
        )

    return {
        "approved_source_revision": revision,
        "protected_checkout_head": protected_head,
        "workspace_branch": workspace.branch,
        "workspace_head": workspace_head,
        "reopened_workspace_head": reopened_head,
        "sandbox": {
            "passed": docker_result.get("passed"),
            "network": docker_result.get("network"),
            "workspace": docker_result.get("workspace"),
            "profile_id": docker_result.get("sandbox_profile"),
            "profile_version": docker_result.get("sandbox_profile_version"),
        },
    }


def _owner_restart_lineage_acceptance(root: pathlib.Path) -> dict[str, object]:
    path = root / "restart-work.sqlite3"
    first_work = SQLiteWorkStore(path)
    first_changes = ChangeStore(
        first_work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    backend = _Backend([])
    coordinator = ChangeCoordinator(first_changes, backend)
    change = coordinator.start(
        "Phase-6 owner restart lineage fixture",
        "incident:owner-acceptance",
        "revision:" + ("a" * 40),
        process_key=UNKNOWN_INCIDENT_REPAIR_PROCESS.key,
        process_version=UNKNOWN_INCIDENT_REPAIR_PROCESS.version,
    )
    stage = first_changes.list_stages(change.change_id)[0]

    second_work = SQLiteWorkStore(path)
    second_changes = ChangeStore(
        second_work,
        processes=(UNKNOWN_INCIDENT_REPAIR_PROCESS,),
    )
    second_stage = second_changes.list_stages(change.change_id)[0]
    if (
        second_stage.work_id != stage.work_id
        or second_stage.stage_key != "diagnostics"
        or len(second_changes.list_stages(change.change_id)) != 1
    ):
        raise Phase6AcceptanceError(
            "Phase-6 change/work lineage changed after store restart"
        )
    return {
        "change_id": change.change_id,
        "diagnostics_work_id": stage.work_id,
        "stage_key": second_stage.stage_key,
        "change_state": second_changes.require(change.change_id).state.value,
    }


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    test_image: str,
) -> dict[str, object]:
    repo = pathlib.Path(repo_root).resolve()
    if not (repo / ".git").exists():
        raise Phase6AcceptanceError("repo_root is not a Git repository")
    image = str(test_image or "").strip()
    if not image:
        raise Phase6AcceptanceError("test_image must not be empty")

    tested_commit = _tested_commit(repo)
    protected_before = _repo_snapshot(repo)
    docker_identity = _require_windows_docker(image)

    with tempfile.TemporaryDirectory(prefix="jarvis-phase6-acceptance-") as temporary:
        root = pathlib.Path(temporary).resolve()
        replay = run_replay_suite(root / "replay")
        if replay.status != "PASS":
            failures = [
                item.case_id for item in replay.cases if not item.passed
            ]
            raise Phase6AcceptanceError(
                "deterministic replay failed: " + ", ".join(failures)
            )
        worktree = _owner_worktree_and_docker_acceptance(
            root,
            test_image=image,
        )
        restart = _owner_restart_lineage_acceptance(root)

    protected_after = _repo_snapshot(repo)
    if protected_before != protected_after:
        raise Phase6AcceptanceError(
            "JARVIS protected checkout changed during owner acceptance"
        )

    evidence: dict[str, object] = {
        "status": "PASS",
        "tested_commit": tested_commit,
        "recorded_at": datetime.now(UTC).isoformat(),
        "platform": {
            "os_name": os.name,
            "windows": True,
        },
        "docker": docker_identity,
        "replay": replay.to_payload(),
        "owner_worktree": worktree,
        "restart": restart,
        "protected_checkout": {
            "before": protected_before,
            "after": protected_after,
            "unchanged": True,
        },
        "governance": {
            "owner_approval_granted": False,
            "promotion_granted": False,
            "merge_performed": False,
            "deployment_performed": False,
            "protected_surface_bypass": False,
        },
    }
    evidence["evidence_digest"] = canonical_digest(evidence)
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--test-image", required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)

    try:
        evidence = run_acceptance(
            repo_root=args.repo_root,
            test_image=args.test_image,
        )
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
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

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "tested_commit": evidence["tested_commit"],
                "evidence_digest": evidence["evidence_digest"],
                "output": str(output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
