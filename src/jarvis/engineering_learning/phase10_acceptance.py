"""Consolidated owner-machine acceptance for Phase 10.

The harness is isolated and non-destructive. It never grants Authority, creates
engineering projects, deploys code, changes protected main, or mutates production.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import tempfile
from datetime import UTC, datetime

from jarvis.engineering_learning.evaluation import (
    PHASE10_REPLAY_CASE_IDS,
    run_replay_suite,
)
from jarvis.engineering_substrate.canonical import canonical_digest


class Phase10AcceptanceError(RuntimeError):
    """Owner-machine Phase-10 acceptance could not prove an invariant."""


def _run(
    command: list[str],
    *,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Phase10AcceptanceError(str(exc)) from exc


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
        raise Phase10AcceptanceError("acceptance Git revision is not a full commit SHA")
    return commit


def _repo_snapshot(repo: pathlib.Path) -> dict[str, str]:
    head = _tested_commit(repo)
    status = _run(
        ["git", "-C", str(repo), "status", "--porcelain=v1"],
        timeout=10.0,
    )
    if status.returncode != 0:
        raise Phase10AcceptanceError("protected checkout status is unavailable")
    return {
        "head": head,
        "status_sha256": hashlib.sha256(status.stdout.encode("utf-8")).hexdigest(),
    }


def _require_windows() -> None:
    if os.name != "nt":
        raise Phase10AcceptanceError(
            "Phase-10 owner-machine acceptance must run on Windows"
        )


def run_acceptance(*, repo_root: pathlib.Path) -> dict[str, object]:
    _require_windows()
    repo = pathlib.Path(repo_root)
    if repo.is_symlink() or not repo.is_dir():
        raise Phase10AcceptanceError("acceptance repo_root must be a regular directory")
    repo = repo.resolve()
    before = _repo_snapshot(repo)

    with tempfile.TemporaryDirectory(prefix="jarvis-phase10-acceptance-") as temp:
        report = run_replay_suite(pathlib.Path(temp) / "replay")

    after = _repo_snapshot(repo)
    if after != before:
        raise Phase10AcceptanceError(
            "owner-machine acceptance changed the tested repository checkout"
        )

    if report.status != "PASS":
        failures = {
            item.case_id: item.evidence for item in report.cases if not item.passed
        }
        raise Phase10AcceptanceError(
            "Phase-10 replay suite failed: "
            + json.dumps(failures, sort_keys=True, ensure_ascii=True)
        )

    evidence: dict[str, object] = {
        "schema_version": 1,
        "status": "PASS",
        "tested_commit": before["head"],
        "repo_status_sha256": before["status_sha256"],
        "repo_unchanged": True,
        "recorded_at": datetime.now(UTC).isoformat(),
        "suite_status": report.status,
        "suite_digest": report.suite_digest,
        "case_count": len(report.cases),
        "case_ids": [item.case_id for item in report.cases],
        "authority_granted": False,
        "production_mutated": False,
    }
    evidence["evidence_digest"] = canonical_digest(evidence)
    return evidence


def validate_acceptance_evidence(
    payload: dict[str, object],
    *,
    tested_commit: str,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise Phase10AcceptanceError("acceptance evidence must be an object")
    expected_commit = str(tested_commit).strip().casefold()
    if len(expected_commit) != 40 or any(
        char not in "0123456789abcdef" for char in expected_commit
    ):
        raise Phase10AcceptanceError("expected tested commit is invalid")

    evidence = dict(payload)
    digest = str(evidence.pop("evidence_digest", "")).strip().casefold()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise Phase10AcceptanceError("acceptance evidence digest is invalid")
    if canonical_digest(evidence) != digest:
        raise Phase10AcceptanceError("acceptance evidence digest mismatch")
    if evidence.get("schema_version") != 1:
        raise Phase10AcceptanceError("unsupported acceptance evidence schema")
    if evidence.get("status") != "PASS" or evidence.get("suite_status") != "PASS":
        raise Phase10AcceptanceError("acceptance evidence did not pass")
    if evidence.get("tested_commit") != expected_commit:
        raise Phase10AcceptanceError("acceptance evidence tested commit mismatch")
    if evidence.get("authority_granted") is not False:
        raise Phase10AcceptanceError("acceptance unexpectedly granted Authority")
    if evidence.get("production_mutated") is not False:
        raise Phase10AcceptanceError("acceptance unexpectedly mutated production")
    if evidence.get("repo_unchanged") is not True:
        raise Phase10AcceptanceError("acceptance did not prove checkout immutability")

    case_ids = evidence.get("case_ids")
    if not isinstance(case_ids, list) or not all(
        isinstance(item, str) and item for item in case_ids
    ):
        raise Phase10AcceptanceError("acceptance case_ids are malformed")
    if evidence.get("case_count") != len(case_ids):
        raise Phase10AcceptanceError("acceptance case_count mismatch")
    if tuple(case_ids) != PHASE10_REPLAY_CASE_IDS:
        raise Phase10AcceptanceError(
            "acceptance evidence does not match the exact Phase-10 replay matrix"
        )
    suite_digest = str(evidence.get("suite_digest") or "").strip().casefold()
    if len(suite_digest) != 64 or any(
        char not in "0123456789abcdef" for char in suite_digest
    ):
        raise Phase10AcceptanceError("acceptance suite digest is invalid")
    return payload


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Run isolated Windows owner-machine acceptance for Phase 10."
    )
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        required=True,
        help="Exact JARVIS repository checkout to bind acceptance to.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=None,
        help="Optional JSON evidence output path.",
    )
    args = parser.parse_args()
    evidence = run_acceptance(repo_root=args.repo_root)
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
