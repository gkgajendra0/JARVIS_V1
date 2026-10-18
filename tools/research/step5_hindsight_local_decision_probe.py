"""Opt-in owner-machine check of decision rules over actual local Hindsight recall.

Zero network by default. Approved run: ONE fictional-bank import, NINE
read-only memory recalls, deterministic correction/history/unknown decisions,
then guaranteed disposable-bank cleanup. NO cloud model or production memory.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from tools.research.step4_hindsight_loopback_import_probe import (
    DOCKER_CONTAINER,
    LocalHindsightHTTP,
    ProbeFailure,
    run_local_import,
    verify_local_container,
)
from tools.research.step4_hindsight_semantic_eval import (
    CASES,
    QUERY_TIMESTAMP,
    recall_request,
    score_candidates,
)
from tools.research.step5_memory_decision_acceptance import (
    decide_from_pinned_recall,
)

CASE_COUNT = 9


def capture_local_decisions(transport: Any, bank_root: str) -> dict[str, Any]:
    """Never persist or print recalled fact text; return fixed-key metrics."""
    if len(CASES) != CASE_COUNT:
        raise ProbeFailure("modified_case_count")
    rows = []
    for case in CASES:
        request = recall_request(case)
        if (
            request.get("query_timestamp") != QUERY_TIMESTAMP
            or request.get("types") != ["world"]
            or request.get("prefer_observations") is not False
            or request.get("tags_match") != "all_strict"
        ):
            raise ProbeFailure("modified_synthetic_recall_protocol")
        recalled = transport.request(
            "POST",
            f"{bank_root}/memories/recall",
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            "application/json",
        )
        try:
            decision = decide_from_pinned_recall(case.case_id, recalled)
        except (ValueError, TypeError) as exc:
            raise ProbeFailure("untrusted_or_malformed_recall_evidence") from None
        rows.append(
            {
                "case_id": case.case_id,
                "recall": recalled,
                "decision": {
                    "status": decision.status,
                    "answer_code": decision.answer_code,
                    "evidence_assertion_ids": list(decision.evidence_assertion_ids),
                },
            }
        )
    try:
        report = score_candidates({"cases": rows})
    except (ValueError, TypeError) as exc:
        raise ProbeFailure("invalid_recall_score") from None

    if (
        report.get("case_count") != CASE_COUNT
        or report.get("decision_evaluated_cases") != CASE_COUNT
    ):
        raise ProbeFailure("incomplete_decision_scoring")

    # No free text, source IDs or server-returned raw content is logged.
    return {
        "kind": "LOCAL_SYNTHETIC_STRUCTURED_DECISION_ACCEPTANCE",
        "queries_executed": CASE_COUNT,
        "retrieval_pass_cases": report["retrieval_pass_cases"],
        "retrieval_required_cases": report["retrieval_required_cases"],
        "retrieval_gate": report["retrieval_gate"],
        "structured_decision_pass_cases": report["decision_pass_cases"],
        "structured_decision_required_cases": CASE_COUNT,
        "structured_decision_gate": report["decision_gate"],
        "abstention_pass_cases": report["abstention_pass_cases"],
        "abstention_required_cases": 2,
        "provenance_gate": report["provenance_gate"],
        "is_rule_based_not_llm": True,
        "real_llm_accuracy_measured": False,
        "real_production_memory": False,
        "production_promotion_allowed": False,
        "details": [
            {
                "case_id": row["case_id"],
                "retrieval_pass": row["retrieval_evidence_pass"],
                "decision_pass": row["decision_pass"],
            }
            for row in report["details"]
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-one-local-structured-decision-evaluation",
        action="store_true",
        help="Explicit owner approval for one isolated synthetic import and nine recalls.",
    )
    args = parser.parse_args(argv)
    if not args.allow_one_local_structured_decision_evaluation:
        print(
            json.dumps(
                {
                    "kind": "STEP5_LOCAL_STRUCTURED_DECISION_PREVIEW",
                    "status": "dry_run_zero_network_calls",
                    "required_container": DOCKER_CONTAINER,
                    "synthetic_queries": CASE_COUNT,
                    "local_write_approved": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    try:
        verify_local_container()
        result = run_local_import(
            LocalHindsightHTTP(),
            inspected=True,
            bank_id=f"jarvis-dev-only-{uuid.uuid4().hex}",
            after_readback=capture_local_decisions,
        )
    except Exception as exc:  # noqa: BLE001 - sanitize all boundary failures
        code = str(exc) if isinstance(exc, ProbeFailure) else "decision_probe_failed"
        print(
            json.dumps(
                {
                    "kind": "STEP5_LOCAL_STRUCTURED_DECISION_EVALUATION",
                    "status": "fail_closed",
                    "reason_code": code,
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
    measured = result.get("research_recall")
    if not isinstance(measured, dict):
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "kind": "STEP5_LOCAL_STRUCTURED_DECISION_EVALUATION",
                "status": "completed",
                "archive_sha256": result["archive_sha256"],
                "documents_read_back": result["documents_read_back"],
                "facts_read_back": result["facts_read_back"],
                "fact_provenance_verified": result["fact_provenance_verified"],
                "disposable_bank_cleanup_verified": (
                    result["disposable_bank_cleanup_verified"]
                ),
                "no_provider_calls_configured": result["no_provider_calls_configured"],
                "no_consolidation_triggered": result["no_consolidation_triggered"],
                "no_production_memory": result["no_production_memory"],
                "production_promotion_allowed": False,
                "decision_research": measured,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if (
        measured["retrieval_gate"] != "pass"
        or measured["structured_decision_gate"] != "pass"
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
