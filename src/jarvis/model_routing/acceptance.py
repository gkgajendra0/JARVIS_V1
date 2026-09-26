"""Bounded Phase-4 model-routing evidence inspection on the owner machine."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from jarvis.model_routing.status import RoutingStatusReader
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import (
    SQLiteWorkStore,
    default_work_state_dir,
    default_work_store_path,
)


def _tested_commit() -> str | None:
    source_root = Path(__file__).resolve().parents[3]
    try:
        revision = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return revision.stdout.strip() if revision.returncode == 0 else None


def _is_sha256(value: str) -> bool:
    normalized = str(value).strip().casefold()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def inspect_routing_acceptance(
    work_store: SQLiteWorkStore,
    work_id: str,
    *,
    decision_id: str | None = None,
) -> dict[str, object]:
    """Inspect persisted route evidence without exposing prompts or credentials."""

    if not isinstance(work_store, SQLiteWorkStore):
        raise TypeError("work_store must be a SQLiteWorkStore")
    normalized_work_id = str(work_id).strip()
    if not normalized_work_id:
        raise ValueError("work_id must not be empty")

    work = work_store.require(normalized_work_id)
    routing_store = ModelRoutingStore(work_store)
    reader = RoutingStatusReader(routing_store)

    normalized_decision_id = str(decision_id or "").strip() or None
    status = (
        reader.for_decision(normalized_decision_id)
        if normalized_decision_id is not None
        else reader.latest_for_work(normalized_work_id)
    )

    if status is None:
        gates = {
            "routing_decision_present": False,
            "routing_links_canonical_work": False,
            "engineering_stage_v1": False,
            "strategy_registry_policy_provenance": False,
            "routing_attempt_present": False,
            "attempt_lineage_preserved": False,
            "bounded_attempt_lineage": False,
            "status_fallback_path_matches_attempts": False,
        }
        return {
            "phase": "4",
            "work_id": normalized_work_id,
            "work_state": work.state.value,
            "work_version": work.version,
            "tested_commit": _tested_commit(),
            "decision_id": normalized_decision_id,
            "store_gates": {
                key: "PASS" if value else "FAIL" for key, value in gates.items()
            },
            "external_gates": {
                "live_routed_reasoning": "PENDING",
                "controlled_fallback_or_health_test": "PENDING",
                "runtime_restart_same_lineage": "PENDING",
                "authority_security_regression": "PENDING",
                "owner_disposition": "PENDING",
            },
            "recorded_at": datetime.now(UTC).isoformat(),
            "result": "FAIL",
        }

    if status.work_id != normalized_work_id:
        raise ValueError("routing decision does not belong to requested work_id")

    persisted = routing_store.get_decision(status.decision_id)
    if persisted is None:
        raise RuntimeError("routing decision disappeared during acceptance inspection")
    attempts = routing_store.list_attempts(status.decision_id)

    lineage_ok = all(
        attempt.work_id == normalized_work_id
        and attempt.decision_id == status.decision_id
        for attempt in attempts
    )
    fallback_path = tuple(attempt.target_id for attempt in attempts)
    bounded_attempts = len(attempts) <= len(status.ordered_target_ids) + 1
    provenance_ok = all(
        (
            _is_sha256(status.strategy_digest),
            _is_sha256(status.registry_digest),
            _is_sha256(status.policy_digest),
        )
    )

    gates = {
        "routing_decision_present": True,
        "routing_links_canonical_work": persisted.work_id == normalized_work_id,
        "engineering_stage_v1": (
            status.strategy_key == "engineering_stage" and status.strategy_version == 1
        ),
        "strategy_registry_policy_provenance": provenance_ok,
        "routing_attempt_present": bool(attempts),
        "attempt_lineage_preserved": lineage_ok,
        "bounded_attempt_lineage": bounded_attempts,
        "status_fallback_path_matches_attempts": status.fallback_path == fallback_path,
    }

    return {
        "phase": "4",
        "work_id": normalized_work_id,
        "work_state": work.state.value,
        "work_version": work.version,
        "change_id": status.change_id,
        "stage_key": status.stage_key,
        "tested_commit": _tested_commit(),
        "decision_id": status.decision_id,
        "routing_request_id": status.routing_request_id,
        "strategy": f"{status.strategy_key}.v{status.strategy_version}",
        "strategy_digest": status.strategy_digest,
        "registry_digest": status.registry_digest,
        "policy_digest": status.policy_digest,
        "selected_target_id": status.selected_target_id,
        "selected_role": status.selected_role,
        "reason_codes": list(status.reason_codes),
        "ordered_target_ids": list(status.ordered_target_ids),
        "fallback_budget": status.fallback_budget,
        "fallback_path": list(status.fallback_path),
        "attempt_count": status.attempt_count,
        "attempts": [
            {
                "attempt_ordinal": attempt.attempt_ordinal,
                "target_id": attempt.target_id,
                "kind": attempt.kind.value,
                "failure_class": attempt.failure_class,
                "response_contract_result": attempt.response_contract_result.value,
            }
            for attempt in attempts
        ],
        "target_health": dict(status.target_health),
        "final_target_id": status.final_target_id,
        "verification_status": status.verification_status.value,
        "verifier_reference": status.verifier_reference,
        "outcome_evidence_reference": status.outcome_evidence_reference,
        "total_latency_ms": status.total_latency_ms,
        "aggregate_usage": status.aggregate_usage,
        "estimated_total_cost_usd": status.estimated_total_cost_usd,
        "store_gates": {
            key: "PASS" if value else "FAIL" for key, value in gates.items()
        },
        "external_gates": {
            "live_routed_reasoning": "PENDING",
            "controlled_fallback_or_health_test": "PENDING",
            "runtime_restart_same_lineage": "PENDING",
            "authority_security_regression": "PENDING",
            "owner_disposition": "PENDING",
        },
        "recorded_at": datetime.now(UTC).isoformat(),
        "result": "PENDING" if all(gates.values()) else "FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-id", required=True)
    parser.add_argument("--decision-id")
    parser.add_argument("--store-path", type=Path, default=default_work_store_path())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    work = SQLiteWorkStore(
        args.store_path,
        payload_codec=build_default_work_payload_codec(args.store_path),
    )
    result = inspect_routing_acceptance(
        work,
        args.work_id,
        decision_id=args.decision_id,
    )
    default_dir = default_work_state_dir().parent / "operations" / "acceptance"
    path = args.output or default_dir / f"phase4-model-routing-{args.work_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"RESULT: {result['result']} - evidence: {path}")
    return 0 if result["result"] == "PENDING" else 1


if __name__ == "__main__":
    raise SystemExit(main())
