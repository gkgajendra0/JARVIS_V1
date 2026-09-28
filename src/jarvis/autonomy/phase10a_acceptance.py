"""Exact-commit Windows owner-machine acceptance for Phase 10A.

The harness is isolated and non-destructive. It runs the locked replay evidence
matrix against one exact checkout, uses temporary machine state, and verifies
that neither the checkout nor the local protected-main ref changes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import UTC, datetime

from jarvis.autonomy.replay import (
    PHASE10A_REPLAY_CORPUS_V1,
    phase10a_pytest_node_ids,
    phase10a_replay_corpus_digest,
    validate_phase10a_replay_corpus,
)
from jarvis.engineering_substrate.canonical import canonical_digest


class Phase10AAcceptanceError(RuntimeError):
    """Owner-machine Phase-10A acceptance could not prove an invariant."""


def _run(
    command: list[str],
    *,
    cwd: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 60.0,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=None if cwd is None else str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Phase10AAcceptanceError(str(exc)) from exc


def _git_revision(repo: pathlib.Path, revision: str) -> str:
    completed = _run(
        ["git", "-C", str(repo), "rev-parse", revision],
        timeout=10.0,
    )
    value = completed.stdout.strip().casefold()
    if (
        completed.returncode != 0
        or len(value) != 40
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise Phase10AAcceptanceError(
            f"Git revision {revision!r} is not a full commit SHA"
        )
    return value


def _repo_snapshot(repo: pathlib.Path) -> dict[str, str]:
    status = _run(
        ["git", "-C", str(repo), "status", "--porcelain=v1"],
        timeout=10.0,
    )
    if status.returncode != 0:
        raise Phase10AAcceptanceError("tested checkout status is unavailable")
    return {
        "head": _git_revision(repo, "HEAD"),
        "main": _git_revision(repo, "main"),
        "status_sha256": hashlib.sha256(
            status.stdout.encode("utf-8")
        ).hexdigest(),
    }


def _require_windows() -> None:
    if os.name != "nt":
        raise Phase10AAcceptanceError(
            "Phase-10A owner-machine acceptance must run on Windows"
        )


def _require_output_outside_repo(
    output: pathlib.Path,
    *,
    repo: pathlib.Path,
) -> pathlib.Path:
    resolved_output = output.expanduser().resolve()
    resolved_repo = repo.expanduser().resolve()
    try:
        resolved_output.relative_to(resolved_repo)
    except ValueError:
        return resolved_output
    raise Phase10AAcceptanceError(
        "acceptance evidence output must be outside the tested repository"
    )


def _validate_exact_commit(expected_commit: str, actual_commit: str) -> str:
    expected = str(expected_commit).strip().casefold()
    if len(expected) != 40 or any(
        char not in "0123456789abcdef" for char in expected
    ):
        raise Phase10AAcceptanceError("expected acceptance commit is invalid")
    if actual_commit != expected:
        raise Phase10AAcceptanceError(
            f"checkout HEAD {actual_commit} does not match expected commit {expected}"
        )
    return expected


def _run_locked_replay(
    repo: pathlib.Path,
    *,
    temp_root: pathlib.Path,
) -> dict[str, object]:
    validate_phase10a_replay_corpus()
    node_ids = phase10a_pytest_node_ids()
    if not node_ids:
        raise Phase10AAcceptanceError("locked replay corpus has no pytest evidence")
    for node_id in node_ids:
        relative = node_id.split("::", 1)[0]
        if not (repo / relative).is_file():
            raise Phase10AAcceptanceError(
                f"locked replay evidence file is missing: {relative}"
            )

    env = os.environ.copy()
    source_root = str(repo / "src")
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        source_root
        if not current_pythonpath
        else source_root + os.pathsep + current_pythonpath
    )
    local_app_data = temp_root / "localappdata"
    local_app_data.mkdir(parents=True, exist_ok=True)
    env["LOCALAPPDATA"] = str(local_app_data)

    completed = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *node_ids,
            "--basetemp",
            str(temp_root / "pytest"),
        ],
        cwd=repo,
        env=env,
        timeout=1800.0,
    )
    evidence = {
        "returncode": completed.returncode,
        "node_count": len(node_ids),
        "stdout_sha256": hashlib.sha256(
            completed.stdout.encode("utf-8")
        ).hexdigest(),
        "stderr_sha256": hashlib.sha256(
            completed.stderr.encode("utf-8")
        ).hexdigest(),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }
    if completed.returncode != 0:
        raise Phase10AAcceptanceError(
            "locked Phase-10A replay pytest failed: "
            + json.dumps(evidence, sort_keys=True, ensure_ascii=True)
        )
    return evidence


def run_acceptance(
    *,
    repo_root: pathlib.Path,
    expected_commit: str,
) -> dict[str, object]:
    _require_windows()
    repo = pathlib.Path(repo_root)
    if repo.is_symlink() or not repo.is_dir():
        raise Phase10AAcceptanceError(
            "acceptance repo_root must be a regular directory"
        )
    repo = repo.resolve()
    before = _repo_snapshot(repo)
    tested_commit = _validate_exact_commit(expected_commit, before["head"])

    with tempfile.TemporaryDirectory(
        prefix="jarvis-phase10a-acceptance-"
    ) as temp:
        replay = _run_locked_replay(
            repo,
            temp_root=pathlib.Path(temp),
        )

    after = _repo_snapshot(repo)
    if after != before:
        raise Phase10AAcceptanceError(
            "owner-machine acceptance changed checkout or protected-main ref"
        )

    case_ids = [item.case_id for item in PHASE10A_REPLAY_CORPUS_V1]
    evidence: dict[str, object] = {
        "schema_version": 1,
        "status": "PASS",
        "tested_commit": tested_commit,
        "protected_main_commit": before["main"],
        "repo_status_sha256": before["status_sha256"],
        "repo_unchanged": True,
        "protected_main_unchanged": True,
        "recorded_at": datetime.now(UTC).isoformat(),
        "replay_corpus_digest": phase10a_replay_corpus_digest(),
        "case_count": len(case_ids),
        "case_ids": case_ids,
        "pytest_node_count": replay["node_count"],
        "pytest_stdout_sha256": replay["stdout_sha256"],
        "pytest_stderr_sha256": replay["stderr_sha256"],
        "authority_granted": False,
        "production_mutated": False,
        "production_autonomy_mode_enabled": False,
    }
    evidence["evidence_digest"] = canonical_digest(evidence)
    return evidence


def validate_acceptance_evidence(
    payload: dict[str, object],
    *,
    tested_commit: str,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise Phase10AAcceptanceError("acceptance evidence must be an object")
    expected_commit = str(tested_commit).strip().casefold()
    if len(expected_commit) != 40 or any(
        char not in "0123456789abcdef" for char in expected_commit
    ):
        raise Phase10AAcceptanceError("expected tested commit is invalid")

    evidence = dict(payload)
    digest = str(evidence.pop("evidence_digest", "")).strip().casefold()
    if len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise Phase10AAcceptanceError("acceptance evidence digest is invalid")
    if canonical_digest(evidence) != digest:
        raise Phase10AAcceptanceError("acceptance evidence digest mismatch")
    if evidence.get("schema_version") != 1:
        raise Phase10AAcceptanceError("unsupported acceptance evidence schema")
    if evidence.get("status") != "PASS":
        raise Phase10AAcceptanceError("acceptance evidence did not pass")
    if evidence.get("tested_commit") != expected_commit:
        raise Phase10AAcceptanceError("acceptance evidence tested commit mismatch")
    if evidence.get("repo_unchanged") is not True:
        raise Phase10AAcceptanceError(
            "acceptance did not prove checkout immutability"
        )
    if evidence.get("protected_main_unchanged") is not True:
        raise Phase10AAcceptanceError(
            "acceptance did not prove protected-main immutability"
        )
    if evidence.get("authority_granted") is not False:
        raise Phase10AAcceptanceError(
            "acceptance unexpectedly granted Authority"
        )
    if evidence.get("production_mutated") is not False:
        raise Phase10AAcceptanceError(
            "acceptance unexpectedly mutated production"
        )
    if evidence.get("production_autonomy_mode_enabled") is not False:
        raise Phase10AAcceptanceError(
            "acceptance unexpectedly enabled production autonomy"
        )

    case_ids = evidence.get("case_ids")
    expected_ids = [item.case_id for item in PHASE10A_REPLAY_CORPUS_V1]
    if case_ids != expected_ids:
        raise Phase10AAcceptanceError(
            "acceptance evidence does not match locked Phase-10A replay corpus"
        )
    if evidence.get("case_count") != len(expected_ids):
        raise Phase10AAcceptanceError("acceptance case_count mismatch")
    if evidence.get("replay_corpus_digest") != phase10a_replay_corpus_digest():
        raise Phase10AAcceptanceError("acceptance replay-corpus digest mismatch")
    return payload


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Run isolated Windows owner-machine acceptance for Phase 10A."
    )
    parser.add_argument(
        "--repo-root",
        type=pathlib.Path,
        required=True,
        help="Exact JARVIS repository checkout to test.",
    )
    parser.add_argument(
        "--expected-commit",
        required=True,
        help="Full 40-character implementation commit SHA to bind acceptance to.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=None,
        help="Optional JSON evidence output path outside the repository.",
    )
    args = parser.parse_args()
    evidence = run_acceptance(
        repo_root=args.repo_root,
        expected_commit=args.expected_commit,
    )
    rendered = json.dumps(evidence, indent=2, sort_keys=True)
    if args.output is not None:
        output = _require_output_outside_repo(
            args.output,
            repo=args.repo_root,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
