"""Owner-machine Phase-2J live R2 independence probe.

This script deliberately does not import jarvis.engineering_knowledge. It verifies that
accepted deterministic R2 crash recovery still works on the integrated Phase-2 build
while EngineeringKnowledge is absent from this process import graph.

The owner must explicitly pass --confirm-live-repair-probe because the probe kills the
currently supervised production runtime once. The existing bounded supervisor is
expected to recover it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from jarvis.incidents import SqliteIncidentStore
from jarvis.self_awareness import default_incident_store_path
from jarvis.self_repair import (
    RepairActionKind,
    RepairVerdict,
    RepairVerificationStatus,
)
from jarvis.self_repair.fault_injection import (
    FaultKind,
    discover_supervised_runtime,
    inject_fault,
)

SAFETY_BUDGET_CLEAR_SECONDS = 360.0
DEFAULT_TIMEOUT_SECONDS = 150.0
POLL_SECONDS = 0.5


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _engineering_knowledge_imports() -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for name in sys.modules
            if name == "jarvis.engineering_knowledge"
            or name.startswith("jarvis.engineering_knowledge.")
        )
    )


def _require_repo_state(expected_sha: str | None) -> dict[str, object]:
    branch = _git("branch", "--show-current")
    sha = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    if branch != "main":
        raise RuntimeError(f"owner-machine acceptance requires main, found {branch!r}")
    if dirty:
        raise RuntimeError("owner-machine acceptance requires a clean Git worktree")
    if expected_sha is not None and sha != expected_sha:
        raise RuntimeError(
            "owner-machine acceptance SHA mismatch: "
            f"expected {expected_sha}, found {sha}"
        )
    return {"branch": branch, "sha": sha, "worktree_clean": True}


def _repair_snapshot(store: SqliteIncidentStore) -> tuple[object, ...]:
    return store.list_repair_attempts_for_component(
        "runtime.voice",
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        limit=100,
    )


def _require_clear_restart_budget(
    attempts: tuple[object, ...],
    *,
    now_epoch: float,
) -> None:
    recent = [
        attempt
        for attempt in attempts
        if getattr(attempt, "started_at_epoch", 0.0)
        >= now_epoch - SAFETY_BUDGET_CLEAR_SECONDS
    ]
    if recent:
        newest = max(float(getattr(item, "started_at_epoch")) for item in recent)
        wait_seconds = max(
            1,
            int(
                SAFETY_BUDGET_CLEAR_SECONDS
                - (now_epoch - newest)
            )
            + 1,
        )
        raise RuntimeError(
            "R2 restart budget safety window is not clear. "
            f"Wait at least {wait_seconds}s and rerun; refusing to consume another "
            "bounded restart while recent repair attempts exist."
        )


def run_live_probe(
    *,
    incident_db: Path,
    expected_sha: str | None,
    timeout_seconds: float,
) -> dict[str, object]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    repo = _require_repo_state(expected_sha)
    before_imports = _engineering_knowledge_imports()
    if before_imports:
        raise RuntimeError(
            "EngineeringKnowledge was imported before the R2 independence probe: "
            + ",".join(before_imports)
        )

    store = SqliteIncidentStore(incident_db)
    try:
        after_store_imports = _engineering_knowledge_imports()
        if after_store_imports:
            raise RuntimeError(
                "incident persistence imported EngineeringKnowledge on the R2 path: "
                + ",".join(after_store_imports)
            )

        before_attempts = _repair_snapshot(store)
        injection_epoch = time.time()
        _require_clear_restart_budget(
            before_attempts,
            now_epoch=injection_epoch,
        )
        before_ids = {
            str(getattr(attempt, "attempt_id"))
            for attempt in before_attempts
        }

        runtime_before = discover_supervised_runtime()
        affected = inject_fault(FaultKind.CRASH, runtime_before)
        if affected <= 0:
            raise RuntimeError("fault injector did not terminate any runtime process")

        deadline = time.monotonic() + timeout_seconds
        recovered_attempt = None
        runtime_after = None
        while time.monotonic() < deadline:
            attempts = _repair_snapshot(store)
            candidates = [
                attempt
                for attempt in attempts
                if str(getattr(attempt, "attempt_id")) not in before_ids
                and float(getattr(attempt, "started_at_epoch")) >= injection_epoch - 1.0
            ]
            for attempt in candidates:
                verification = getattr(attempt, "verification", None)
                if (
                    getattr(attempt, "verdict", None) is RepairVerdict.RECOVERED
                    and verification is not None
                    and verification.status is RepairVerificationStatus.PASS
                ):
                    recovered_attempt = attempt
                    break
            try:
                discovered = discover_supervised_runtime()
            except RuntimeError:
                discovered = None
            if (
                recovered_attempt is not None
                and discovered is not None
                and discovered.pid != runtime_before.pid
            ):
                runtime_after = discovered
                break
            time.sleep(POLL_SECONDS)

        if recovered_attempt is None:
            raise RuntimeError(
                "no new verified RECOVERED RepairAttempt appeared before timeout"
            )
        if runtime_after is None:
            raise RuntimeError(
                "repair attempt recovered but a replacement supervised runtime "
                "was not observed before timeout"
            )

        final_imports = _engineering_knowledge_imports()
        if final_imports:
            raise RuntimeError(
                "EngineeringKnowledge entered the live R2 acceptance import graph: "
                + ",".join(final_imports)
            )

        verification = recovered_attempt.verification
        assert verification is not None
        return {
            "status": "PASS",
            "check": "phase2j_r2_independence_live_crash_recovery",
            "repository": repo,
            "incident_db": str(incident_db),
            "engineering_knowledge_imports": [],
            "runtime_before_pid": runtime_before.pid,
            "runtime_after_pid": runtime_after.pid,
            "fault_affected_processes": affected,
            "repair_attempt_id": recovered_attempt.attempt_id,
            "repair_incident_id": recovered_attempt.incident_id,
            "repair_policy_id": recovered_attempt.policy_id,
            "repair_policy_version": recovered_attempt.policy_version,
            "repair_action_kind": recovered_attempt.action.kind.value,
            "repair_verdict": recovered_attempt.verdict.value,
            "verification_contract": verification.contract_id,
            "verification_status": verification.status.value,
            "verification_summary": verification.summary,
            "injected_at_epoch": injection_epoch,
            "observed_at_epoch": time.time(),
        }
    finally:
        store.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the explicit owner-machine Phase-2J live crash-recovery "
            "negative control without importing EngineeringKnowledge."
        )
    )
    parser.add_argument(
        "--confirm-live-repair-probe",
        action="store_true",
        help=(
            "Required acknowledgement that the probe will kill the supervised "
            "production runtime once and rely on bounded R2 recovery."
        ),
    )
    parser.add_argument(
        "--expected-sha",
        default="",
        help="Optional exact main SHA required before fault injection.",
    )
    parser.add_argument(
        "--incident-db",
        default=str(default_incident_store_path()),
        help="Engineering incident SQLite database path.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional JSON report path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_live_repair_probe:
        print(
            "REFUSED: --confirm-live-repair-probe is required because this "
            "acceptance check intentionally crashes the supervised runtime once.",
            file=sys.stderr,
        )
        return 2

    try:
        report = run_live_probe(
            incident_db=Path(args.incident_db).expanduser(),
            expected_sha=str(args.expected_sha).strip() or None,
            timeout_seconds=float(args.timeout_seconds),
        )
    except Exception as exc:
        report = {
            "status": "FAIL",
            "check": "phase2j_r2_independence_live_crash_recovery",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "observed_at_epoch": time.time(),
        }
        result_code = 1
    else:
        result_code = 0

    encoded = json.dumps(report, indent=2, sort_keys=True)
    print(encoded)
    output = str(args.output).strip()
    if output:
        destination = Path(output).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(encoded + "\n", encoding="utf-8")
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
