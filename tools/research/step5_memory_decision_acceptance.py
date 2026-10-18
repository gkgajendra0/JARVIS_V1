"""Offline acceptance: nine exact fictional decisions + thousands of synthetic states.

No Hindsight calls, no owner data and no canonical SQLCipher access.
The 5-fact adapter intentionally recognizes ONLY the previously pinned texts:
it is a controlled fixture projection, not natural-language extraction.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from jarvis.memory.hindsight_transfer_shadow import PINNED_FACTS
from jarvis.memory.research_decision_gate import (
    Assertion,
    MemoryDecision,
    MemoryDecisionIndex,
    MemoryQuestion,
    compare_shadow,
)
from tools.research.step4_hindsight_semantic_eval import CASES

# Intentionally exact text -> structured value, with assertion-ID integrity.
# Any unreviewed change to the five official fixture texts fails closed.
_ALLOWED_FIXTURE = {
    "synthetic-workshop-day-v1": (
        "The fictional Atlas workshop was described as Saturday.",
        "synthetic-atlas", "saturday",
    ),
    "synthetic-workshop-day-v2": (
        "Correction: the fictional Atlas workshop is on Sunday, not Saturday.",
        "synthetic-atlas", "sunday",
    ),
    "synthetic-report-day-v1": (
        "The fictional Nile project report was sent on Monday.",
        "synthetic-nile", "monday",
    ),
    "synthetic-report-day-v2": (
        "The fictional Nile project report is now sent on Thursday.",
        "synthetic-nile", "thursday",
    ),
    "synthetic-workshop-venue-v1": (
        "The fictional Atlas workshop venue is Hall B.",
        "synthetic-atlas", "hall_b",
    ),
}

_CASE_QUESTIONS = {
    "atlas_current_day": MemoryQuestion("synthetic-atlas", "workshop_day", "current"),
    "atlas_original_day": MemoryQuestion("synthetic-atlas", "workshop_day", "original"),
    "atlas_correction_trace": MemoryQuestion("synthetic-atlas", "workshop_day", "history"),
    "nile_current_report_day": MemoryQuestion("synthetic-nile", "report_day", "current"),
    "nile_previous_report_day": MemoryQuestion("synthetic-nile", "report_day", "original"),
    "nile_historical_change": MemoryQuestion("synthetic-nile", "report_day", "history"),
    "atlas_unrelated_venue": MemoryQuestion("synthetic-atlas", "workshop_venue", "current"),
    "unknown_start_time": MemoryQuestion("synthetic-atlas", "workshop_start", "current"),
    "unresolved_ambiguous_statement": MemoryQuestion(
        "synthetic-nile", "unresolved_decision", "current"
    ),
}


def frozen_assertions() -> tuple[Assertion, ...]:
    if {f.assertion_id for f in PINNED_FACTS} != set(_ALLOWED_FIXTURE):
        raise ValueError("modified_synthetic_fixture_identity")
    records: list[Assertion] = []
    for fact in PINNED_FACTS:
        exact_text, subject, value = _ALLOWED_FIXTURE[fact.assertion_id]
        if fact.text != exact_text:
            raise ValueError("modified_synthetic_fixture_text")
        records.append(
            Assertion(
                assertion_id=fact.assertion_id,
                subject=subject,
                predicate=fact.predicate,
                value=value,
                source_ref=f"conversation:synthetic:{fact.source_turn_id}",
                mentioned_at=fact.mentioned_at,
                version=fact.version,
                revision_kind=fact.revision_kind,
                supersedes_id=fact.supersedes_id,
            )
        )
    return tuple(records)


def case_decisions() -> dict[str, MemoryDecision]:
    if set(_CASE_QUESTIONS) != {case.case_id for case in CASES}:
        raise ValueError("changed_question_suite")
    index = MemoryDecisionIndex(frozen_assertions())
    return {
        case.case_id: index.decide(_CASE_QUESTIONS[case.case_id])
        for case in CASES
    }


def verify_nine_cases() -> dict[str, object]:
    decisions = case_decisions()
    rows = []
    for case in CASES:
        actual = decisions[case.case_id]
        passed = (
            actual.status == ("answer" if case.answer_code is not None else "abstain")
            and actual.answer_code == case.answer_code
            and set(actual.evidence_assertion_ids) == set(case.required_ids)
        )
        rows.append({"case_id": case.case_id, "passed": passed})
    return {
        "kind": "OFFLINE_MEMORY_DECISION_ACCEPTANCE",
        "passed": all(row["passed"] for row in rows),
        "cases": len(rows),
        "passed_cases": sum(row["passed"] for row in rows),
        "answer_cases": 7,
        "abstention_cases": 2,
        "real_llm_accuracy_measured": False,
        "real_hindsight_decision_accuracy_measured": False,
        "no_memory_write": True,
        "production_promotion_allowed": False,
        "details": rows,
    }


def large_fictional_corpus(groups: int = 600) -> tuple[Assertion, ...]:
    """Deterministic 3,600-fact workload; no owner data or file I/O."""
    if type(groups) is not int or not 1 <= groups <= 600:
        raise ValueError("unbounded_synthetic_groups")
    result: list[Assertion] = []
    for i in range(groups):
        subject = f"synthetic-project-{i:04d}"
        for kind in ("schedule", "venue"):
            old_id = f"synthetic-{i:04d}-{kind}-v1"
            new_id = f"synthetic-{i:04d}-{kind}-v2"
            third_id = f"synthetic-{i:04d}-{kind}-v3"
            revision = "correction" if kind == "schedule" else "historical_change"
            for ver, assertion_id, predecessor, rkind, value in (
                (1, old_id, None, "original_statement", "alpha"),
                (2, new_id, old_id, revision, "bravo"),
                (3, third_id, new_id, revision, "charlie"),
            ):
                result.append(
                    Assertion(
                        assertion_id=assertion_id,
                        subject=subject,
                        predicate=kind,
                        value=value,
                        source_ref=(
                            f"conversation:synthetic:synthetic-{i:04d}-{kind}-turn-{ver}"
                        ),
                        mentioned_at=f"2026-01-0{ver}T10:00:00Z",
                        version=ver,
                        revision_kind=rkind,
                        supersedes_id=predecessor,
                    )
                )
    return tuple(result)


def verify_large_synthetic() -> dict[str, object]:
    corpus = large_fictional_corpus()
    index = MemoryDecisionIndex(corpus)
    passed = 0
    total = 0
    mismatches = 0
    for i in range(600):
        subject = f"synthetic-project-{i:04d}"
        for kind in ("schedule", "venue"):
            for intent, expected in (
                ("original", "alpha"),
                ("current", "charlie"),
                (
                    "history",
                    "alpha_corrected_to_bravo_corrected_to_charlie"
                    if kind == "schedule" else "alpha_then_bravo_then_charlie",
                ),
            ):
                result = index.decide(MemoryQuestion(subject, kind, intent))
                total += 1
                if result.status == "answer" and result.answer_code == expected:
                    passed += 1
                else:
                    mismatches += 1
    for i in range(600):
        result = index.decide(
            MemoryQuestion(f"synthetic-project-{i:04d}", "nonexistent", "current")
        )
        total += 1
        if result.status == "abstain" and result.answer_code is None:
            passed += 1
        else:
            mismatches += 1
    # The shadow comparison cannot override canonical knowledge.
    original = MemoryDecision("answer", "alpha", ("synthetic-original",), "grounded")
    proposed = MemoryDecision("answer", "bravo", ("synthetic-proposed",), "grounded")
    shadow = compare_shadow(original, proposed)
    return {
        "kind": "OFFLINE_LARGE_SYNTHETIC_DECISION_BENCHMARK",
        "status": "pass" if passed == total and shadow["equal"] is False else "fail",
        "assertions": len(corpus),
        "decision_cases": total,
        "passed_cases": passed,
        "mismatches": mismatches,
        "shadow_disagreement_detected": shadow["equal"] is False,
        "canonical_unmodified": shadow["canonical_unmodified"],
        "memory_write_performed": shadow["memory_write_performed"],
        "production_promotion_allowed": False,
        "real_server_benchmark": False,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--large-synthetic", action="store_true",
        help="Offline CPU-only 3,600-fact deterministic fixture benchmark.",
    )
    args = parser.parse_args(argv)
    result = verify_large_synthetic() if args.large_synthetic else verify_nine_cases()
    print(json.dumps(result, indent=2, sort_keys=True))
    if (result.get("passed") is False or result.get("status") == "fail"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
