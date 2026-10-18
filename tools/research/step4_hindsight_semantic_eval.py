"""Offline-only Step 4 Hindsight retrieval/evidence/answer acceptance rubric.

This module NEVER starts Docker, reads SQLCipher, contacts an API, or calls an LLM.
Owner-local live capture must be separately approved and implemented as an
isolated step; caller-supplied examples do NOT establish real-server accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any

from jarvis.memory.hindsight_transfer_shadow import PINNED_FACTS

QUERY_TIMESTAMP = "2026-02-02T00:00:00Z"
MAX_CANDIDATE_BYTES = 131_072
FACTS_BY_ID = {fact.assertion_id: fact for fact in PINNED_FACTS}
PINNED_IDS = frozenset(FACTS_BY_ID)


class EvaluationFailure(ValueError):
    """Safe fixed-string code only; never include submitted fact text."""


@dataclass(frozen=True, slots=True)
class SemanticCase:
    case_id: str
    query: str
    required_ids: tuple[str, ...]
    answer_code: str | None
    max_rank: int


CASES: tuple[SemanticCase, ...] = (
    SemanticCase(
        "atlas_current_day",
        "What day is the fictional Atlas workshop on now?",
        ("synthetic-workshop-day-v2",),
        "sunday",
        3,
    ),
    SemanticCase(
        "atlas_original_day",
        "Which day was the fictional Atlas workshop originally described as?",
        ("synthetic-workshop-day-v1",),
        "saturday",
        3,
    ),
    SemanticCase(
        "atlas_correction_trace",
        "What was the original Atlas workshop day, and how was it corrected?",
        ("synthetic-workshop-day-v1", "synthetic-workshop-day-v2"),
        "saturday_corrected_to_sunday",
        5,
    ),
    SemanticCase(
        "nile_current_report_day",
        "On which day is the fictional Nile project report now sent?",
        ("synthetic-report-day-v2",),
        "thursday",
        3,
    ),
    SemanticCase(
        "nile_previous_report_day",
        "On which day was the fictional Nile report sent in its earlier state?",
        ("synthetic-report-day-v1",),
        "monday",
        3,
    ),
    SemanticCase(
        "nile_historical_change",
        "How did the fictional Nile report day change over time?",
        ("synthetic-report-day-v1", "synthetic-report-day-v2"),
        "monday_then_thursday",
        5,
    ),
    SemanticCase(
        "atlas_unrelated_venue",
        "Where is the fictional Atlas workshop held?",
        ("synthetic-workshop-venue-v1",),
        "hall_b",
        3,
    ),
    SemanticCase(
        "unknown_start_time",
        "What time of day does the fictional Atlas workshop start?",
        (),
        None,
        0,
    ),
    SemanticCase(
        "unresolved_ambiguous_statement",
        "What final decision came from an unresolved ambiguous utterance?",
        (),
        None,
        0,
    ),
)
_CASE_BY_ID = {case.case_id: case for case in CASES}
if len(_CASE_BY_ID) != len(CASES):
    raise RuntimeError("duplicate_static_case")


def recall_request(case: SemanticCase) -> dict[str, Any]:
    """Pinned Hindsight 1.0 request; temporal relevance is NOT a hard filter."""
    return {
        "query": case.query,
        "query_timestamp": QUERY_TIMESTAMP,
        "types": ["world"],
        "budget": "mid",
        "max_tokens": 1024,
        "prefer_observations": False,
        "tags": ["jarvis-dev-only", "synthetic"],
        "tags_match": "all_strict",
        "trace": False,
    }


def protocol() -> dict[str, Any]:
    """No network, no candidate data, no measured scores."""
    return {
        "kind": "STEP4_SEMANTIC_EVAL_PROTOCOL_ONLY",
        "status": "not_measured",
        "case_count": len(CASES),
        "answer_cases": sum(case.answer_code is not None for case in CASES),
        "abstention_cases": sum(case.answer_code is None for case in CASES),
        "cases": [
            {
                "case_id": case.case_id,
                "request": recall_request(case),
                "required_assertion_ids": list(case.required_ids),
                "required_max_rank": case.max_rank,
                "expected_answer_code": case.answer_code,
            }
            for case in CASES
        ],
        "real_hindsight_results_present": False,
        "production_promotion_allowed": False,
    }


def _validate_result(item: Any) -> str:
    """Require exact pinned, source-linked, canonical fictional assertions."""
    if not isinstance(item, dict):
        raise EvaluationFailure("invalid_recall_item")
    meta = item.get("metadata")
    if not isinstance(meta, dict):
        raise EvaluationFailure("missing_fact_provenance")
    assertion_id = meta.get("assertion_id")
    if not isinstance(assertion_id, str) or assertion_id not in PINNED_IDS:
        raise EvaluationFailure("unrecognized_assertion")
    fact = FACTS_BY_ID[assertion_id]
    expected = {
        "assertion_id": fact.assertion_id,
        "assertion_version": str(fact.version),
        "source_turn_id": fact.source_turn_id,
        "canonical_source_ref": f"conversation:synthetic:{fact.source_turn_id}",
        "predicate": fact.predicate,
        "revision_kind": fact.revision_kind,
        "source_class": "synthetic_owner_direct",
        "admission_policy": "shadow_only_no_write",
    }
    if fact.supersedes_id:
        expected["supersedes_id"] = fact.supersedes_id
    if meta != expected:
        raise EvaluationFailure("fact_provenance_mismatch")
    if (
        item.get("type") != "world"
        or item.get("text") != fact.text
        or item.get("document_id") != f"jarvis-dev-only-{assertion_id}"
    ):
        raise EvaluationFailure("fact_identity_mismatch")
    return assertion_id


def _score_decision(
    decision: Any,
    case: SemanticCase,
    ranked_ids: list[str],
) -> bool | None:
    """Structured candidate answer; NOT an LLM judge or a generated answer."""
    if decision is None:
        return None
    if not isinstance(decision, dict):
        raise EvaluationFailure("invalid_decision")
    cited = decision.get("evidence_assertion_ids")
    if not isinstance(cited, list) or any(
        not isinstance(i, str) or i not in PINNED_IDS for i in cited
    ):
        raise EvaluationFailure("invalid_decision_evidence")
    if len(cited) != len(set(cited)):
        raise EvaluationFailure("invalid_decision_evidence")
    if set(decision) - {"status", "answer_code", "evidence_assertion_ids"}:
        raise EvaluationFailure("invalid_decision")
    if case.answer_code is None:
        return (
            decision.get("status") == "abstain"
            and decision.get("answer_code") is None
            and cited == []
        )
    return (
        decision.get("status") == "answer"
        and decision.get("answer_code") == case.answer_code
        and set(cited) == set(case.required_ids)
        and all(i in ranked_ids for i in cited)
    )


def score_candidates(payload: Any) -> dict[str, Any]:
    """Score caller-supplied synthetic responses, never certify their origin.

    Payload format: {"cases": [{"case_id": str, "recall": {"results": [...]},
    "decision": {"status": ..., "answer_code": ..., "evidence_assertion_ids":
    [...]}}]}.  Omit `decision` to score retrieval only. Ranking is returned
    directly by /recall; there is no claim that recall itself decides truth.
    """
    if not isinstance(payload, dict) or set(payload) != {"cases"}:
        raise EvaluationFailure("invalid_payload")
    rows = payload["cases"]
    if not isinstance(rows, list) or len(rows) != len(CASES):
        raise EvaluationFailure("invalid_case_set")
    seen: set[str] = set()
    details: list[dict[str, Any]] = []
    total_units = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise EvaluationFailure("invalid_case")
        case_id = row["case_id"]
        if case_id not in _CASE_BY_ID or case_id in seen:
            raise EvaluationFailure("invalid_case_set")
        seen.add(case_id)
        if set(row) - {"case_id", "recall", "decision"}:
            raise EvaluationFailure("unexpected_case_fields")
        case = _CASE_BY_ID[case_id]
        recall = row.get("recall")
        if not isinstance(recall, dict) or not isinstance(recall.get("results"), list):
            raise EvaluationFailure("missing_recall_results")
        results = recall["results"]
        if len(results) > len(PINNED_FACTS):
            raise EvaluationFailure("unexpected_recall_volume")
        ranked_ids = [_validate_result(item) for item in results]
        if len(set(ranked_ids)) != len(ranked_ids):
            raise EvaluationFailure("duplicate_recalled_fact")
        total_units += len(ranked_ids)
        retrieval_pass = all(
            req in ranked_ids[: case.max_rank] for req in case.required_ids
        )
        answer_pass = _score_decision(row.get("decision"), case, ranked_ids)
        details.append(
            {
                "case_id": case_id,
                "retrieval_evidence_pass": retrieval_pass,
                "first_required_rank": min(
                    (
                        ranked_ids.index(req) + 1
                        for req in case.required_ids
                        if req in ranked_ids
                    ),
                    default=None,
                ),
                "decision_evaluated": answer_pass is not None,
                "decision_pass": answer_pass,
            }
        )
    if seen != set(_CASE_BY_ID):
        raise EvaluationFailure("invalid_case_set")
    details.sort(key=lambda row: list(_CASE_BY_ID).index(row["case_id"]))
    evidence_cases = [
        row for row in details if _CASE_BY_ID[row["case_id"]].required_ids
    ]
    decisions = [row for row in details if row["decision_evaluated"]]
    recall_ok = all(row["retrieval_evidence_pass"] for row in evidence_cases)
    all_decisions = len(decisions) == len(CASES)
    decision_ok = all_decisions and all(row["decision_pass"] for row in decisions)
    return {
        "kind": "STEP4_OFFLINE_SYNTHETIC_EVIDENCE_SCORING",
        "origin": "caller_supplied_unverified",
        "real_server_accuracy_verified": False,
        "production_promotion_allowed": False,
        "case_count": len(CASES),
        "verified_synthetic_recall_units": total_units,
        "provenance_gate": "pass",
        "retrieval_gate": "pass" if recall_ok else "fail",
        "retrieval_pass_cases": sum(
            row["retrieval_evidence_pass"] for row in evidence_cases
        ),
        "retrieval_required_cases": len(evidence_cases),
        "decision_gate": (
            "not_evaluated" if not decisions else "pass" if decision_ok else "fail"
        ),
        "decision_pass_cases": sum(row["decision_pass"] is True for row in decisions),
        "decision_evaluated_cases": len(decisions),
        "abstention_pass_cases": sum(
            row["decision_pass"] is True
            for row in details
            if _CASE_BY_ID[row["case_id"]].answer_code is None
        ),
        "details": details,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--score-stdin",
        action="store_true",
        help="Offline JSON input over stdin only; does not contact Hindsight.",
    )
    args = parser.parse_args(argv)
    if not args.score_stdin:
        print(json.dumps(protocol(), indent=2, sort_keys=True))
        return
    try:
        raw = sys.stdin.buffer.read(MAX_CANDIDATE_BYTES + 1)
        if len(raw) > MAX_CANDIDATE_BYTES:
            raise EvaluationFailure("candidate_input_too_large")
        report = score_candidates(json.loads(raw))
    except (ValueError, UnicodeError, TypeError) as exc:
        code = (
            str(exc) if isinstance(exc, EvaluationFailure) else "invalid_candidate_json"
        )
        report = {
            "kind": "STEP4_OFFLINE_SYNTHETIC_EVIDENCE_SCORING",
            "status": "fail_closed",
            "reason_code": code,
            "real_server_accuracy_verified": False,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(1) from None
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["retrieval_gate"] != "pass" or report["decision_gate"] == "fail":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
