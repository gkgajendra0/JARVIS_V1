"""Owner-opt-in, single-use synthetic import + nine actual local recall queries.

Default execution is zero-network. Never import real JARVIS memories or start
Docker. All network calls are limited to the already-verified localhost Docker
Hindsight instance, and its disposable bank is deleted even when recall fails.
No LLM answer is generated; this measures retrieval and provenance only.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
# Isolated Python (-I) omits the checkout root and src from sys.path.
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

EXPECTED_CASE_COUNT = 9


def capture_recall(transport: Any, root: str) -> dict[str, Any]:
    """Read-only POST /memories/recall over an imported disposable five-fact bank.

    The supplied transport must be the already-verified local Docker transport
    during a real run. Response metadata is validated by the frozen scorer;
    results are NEVER printed, written to a file, or sent to a provider.
    """
    if len(CASES) != EXPECTED_CASE_COUNT:
        raise ProbeFailure("semantic_protocol_case_count_changed")
    cases = []
    for case in CASES:
        request = recall_request(case)
        if (
            request.get("types") != ["world"]
            or request.get("prefer_observations") is not False
            or request.get("tags_match") != "all_strict"
            or request.get("query_timestamp") != QUERY_TIMESTAMP
        ):
            raise ProbeFailure("semantic_protocol_mutated")
        recall = transport.request(
            "POST",
            f"{root}/memories/recall",
            json.dumps(request, separators=(",", ":"), sort_keys=True).encode("utf-8"),
            "application/json",
        )
        cases.append({"case_id": case.case_id, "recall": recall})

    try:
        score = score_candidates({"cases": cases})
    except ValueError as exc:
        # Fail closed without printing server text, URLs or arbitrary exception.
        if type(exc).__name__ == "EvaluationFailure":
            raise ProbeFailure("semantic_recall_provenance_or_schema_failed") from None
        raise ProbeFailure("semantic_recall_validation_failed") from None
    if score.get("case_count") != EXPECTED_CASE_COUNT:
        raise ProbeFailure("semantic_recall_incomplete")

    # Source-backed measured scores only; no answer generation has happened.
    return {
        "kind": "LOCAL_HINDSIGHT_RECALL_EVIDENCE_ONLY",
        "case_count": score["case_count"],
        "retrieval_pass_cases": score["retrieval_pass_cases"],
        "retrieval_required_cases": score["retrieval_required_cases"],
        "retrieval_gate": score["retrieval_gate"],
        "provenance_gate": score["provenance_gate"],
        "decision_gate": "not_evaluated",
        "answer_accuracy_measured": False,
        "abstention_accuracy_measured": False,
        "queries_executed": len(cases),
        "details": [
            {
                "case_id": detail["case_id"],
                "retrieval_evidence_pass": detail["retrieval_evidence_pass"],
                "first_required_rank": detail["first_required_rank"],
            }
            for detail in score["details"]
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-one-local-recall-evaluation",
        action="store_true",
        help="Owner approves exactly one disposable synthetic import + nine local recalls.",
    )
    args = parser.parse_args(argv)
    if not args.allow_one_local_recall_evaluation:
        print(
            json.dumps(
                {
                    "kind": "STEP4_LOCAL_RECALL_PROTOCOL_PREVIEW_ONLY",
                    "status": "dry_run_zero_network_calls",
                    "required_container": DOCKER_CONTAINER,
                    "queries_planned": len(CASES),
                    "synthetic_only": True,
                    "live_retrieval_not_yet_measured": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    try:
        verify_local_container()
        report = run_local_import(
            LocalHindsightHTTP(),
            inspected=True,
            bank_id=f"jarvis-dev-only-{uuid.uuid4().hex}",
            after_readback=capture_recall,
        )
    except Exception as exc:  # noqa: BLE001 - never leak server/owner details
        # Keep stdout sanitized; the lower-level import helper still enforces
        # cleanup in a finally block, including when a recall raises.
        reason = (
            str(exc) if isinstance(exc, ProbeFailure) else "local_recall_probe_failed"
        )
        print(
            json.dumps(
                {
                    "status": "fail_closed",
                    "reason_code": reason,
                    "kind": "STEP4_LOCAL_RECALL_EVALUATION",
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None

    recall = report.pop("research_recall", None)
    if not isinstance(recall, dict):
        raise SystemExit(1)
    result = {
        "kind": "STEP4_LOCAL_RECALL_EVALUATION",
        "status": "completed",
        "archive_sha256": report["archive_sha256"],
        "import_completed": report["import_completed"],
        "documents_read_back": report["documents_read_back"],
        "facts_read_back": report["facts_read_back"],
        "fact_provenance_verified": report["fact_provenance_verified"],
        "disposable_bank_cleanup_verified": report["disposable_bank_cleanup_verified"],
        "no_consolidation_triggered": report["no_consolidation_triggered"],
        "no_production_memory": report["no_production_memory"],
        "no_provider_calls_configured": report["no_provider_calls_configured"],
        "recall": recall,
        "production_promotion_allowed": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if recall["retrieval_gate"] != "pass":
        # Measured failure is valuable evidence, but not a passing acceptance.
        raise SystemExit(2)


if __name__ == "__main__":
    main()
