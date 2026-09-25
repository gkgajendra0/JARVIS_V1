"""Bounded Phase-3 evidence inspection on the owner's JARVIS machine."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from jarvis.work.models import WorkState
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import (
    SQLiteWorkStore,
    default_work_state_dir,
    default_work_store_path,
)

from .models import ChangeState
from .store import ChangeStore


def inspect_change(store: ChangeStore, change_id: str) -> dict[str, object]:
    """Inspect persisted evidence; never echo requests, proposals or test output."""
    change = store.require(change_id)
    source_root = Path(__file__).resolve().parents[3]
    try:
        revision = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        tested_commit = revision.stdout.strip() if revision.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        tested_commit = None
    stages = store.list_stages(change_id)
    research = [stage for stage in stages if stage.stage_key == "research"]
    development = [stage for stage in stages if stage.stage_key == "development"]
    architecture = store.latest_artifact(change_id, "architecture")
    acceptance = store.latest_artifact(change_id, "acceptance")
    with store.work._lock, store.work._connect() as db:
        decisions = db.execute(
            """SELECT gate.kind, gate.artifact_id, gate.artifact_digest,
            decision.approved FROM engineering_change_gates AS gate
            JOIN engineering_change_decisions AS decision USING (gate_id)
            WHERE gate.change_id=?""",
            (change_id,),
        ).fetchall()

    def approved(kind: str, artifact) -> bool:
        return artifact is not None and any(
            row["kind"] == kind
            and row["artifact_id"] == artifact.artifact_id
            and row["artifact_digest"] == artifact.digest
            and row["approved"] == 1
            for row in decisions
        )

    last_dev = store.work.require(development[-1].work_id) if development else None
    verification = last_dev.result.get("verification") if last_dev else None
    gates = {
        "research_completed": bool(
            research
            and store.work.require(research[-1].work_id).state is WorkState.COMPLETED
        ),
        "current_architecture_approved": approved("architecture", architecture),
        "development_completed": bool(
            last_dev and last_dev.state is WorkState.COMPLETED
        ),
        "canonical_verified_commit": bool(
            last_dev
            and last_dev.result.get("commit")
            and last_dev.result.get("branch")
            and isinstance(verification, dict)
            and verification.get("passed") is True
        ),
        "current_acceptance_approved": approved("acceptance", acceptance),
        "no_automatic_promotion": change.state
        not in {
            ChangeState.PROMOTED,
            ChangeState.OBSERVING,
            ChangeState.CLOSED,
        },
    }
    return {
        "phase": "3",
        "change_id": change_id,
        "tested_commit": tested_commit,
        "process": f"{change.process_key}/{change.process_version}",
        "state": change.state.value,
        "store_gates": {
            key: "PASS" if value else "FAIL" for key, value in gates.items()
        },
        "external_gates": {
            "production_postgres_dbos_restart": "PENDING",
            "owner_voice_gate_delivery": "PENDING",
            "isolated_development_review": "PENDING",
        },
        "stages": [
            {
                "stage": stage.stage_key,
                "attempt": stage.attempt,
                "work_id": stage.work_id,
                "state": store.work.require(stage.work_id).state.value,
                "plan_artifact_id": stage.plan_artifact_id,
            }
            for stage in stages
        ],
        "architecture_digest": architecture.digest if architecture else None,
        "acceptance_digest": acceptance.digest if acceptance else None,
        "event_count": len(store.list_events(change_id)),
        "recorded_at": datetime.now(UTC).isoformat(),
        "result": "PENDING" if all(gates.values()) else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--store-path", type=Path, default=default_work_store_path())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    work = SQLiteWorkStore(
        args.store_path,
        payload_codec=build_default_work_payload_codec(args.store_path),
    )
    result = inspect_change(ChangeStore(work), args.change_id)
    default_dir = default_work_state_dir().parent / "operations" / "acceptance"
    path = (
        args.output or default_dir / f"phase3-engineering-change-{args.change_id}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"RESULT: {result['result']} - evidence: {path}")
    return 0 if result["result"] == "PENDING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
