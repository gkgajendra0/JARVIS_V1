"""Harder research-only retrieval questions over the SAME 60 fictional facts.

No natural-language parsing is claimed: scope and gold answers are reviewed,
pre-labeled synthetic fixtures. Every engine receives identical raw questions;
ranked candidates alone cannot supply a missing source predecessor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from jarvis.memory.research_compare_fixture import (
    BY_ID,
    TOP_K,
    ComparisonFailure,
)
from jarvis.memory.research_decision_gate import (
    MemoryDecisionIndex,
    MemoryQuestion,
)

_ENGINE_NAMES = frozenset(("hindsight", "lexical", "hybrid"))
_PROJECT_IDS = (2, 7, 13, 19)


@dataclass(frozen=True, slots=True)
class ChallengeCase:
    case_id: str
    category: Literal[
        "paraphrase_current",
        "historical_original",
        "correction_history",
        "indirect_venue",
        "negative_disambiguation",
        "unsupported_question",
        "unresolved_reference",
    ]
    query: str
    subject: str | None
    predicate: str | None
    intent: Literal["current", "original", "history"] | None
    expected_answer: str | None
    required_ids: tuple[str, ...]


def challenge_cases() -> tuple[ChallengeCase, ...]:
    """Twenty evidence cases, two unknowns, two unresolved-reference cases."""
    rows: list[ChallengeCase] = []
    for i in _PROJECT_IDS:
        subject = f"synthetic-project-{i:04d}"
        day_v1 = f"{subject}-schedule-v1"
        day_v2 = f"{subject}-schedule-v2"
        venue = f"{subject}-venue-v1"
        old = BY_ID[day_v1].assertion.value
        new = BY_ID[day_v2].assertion.value
        rows.extend(
            (
                ChallengeCase(
                    f"current_{i:04d}",
                    "paraphrase_current",
                    f"Following the amendment, on which weekday does Meridian initiative {i:04d} meet?",
                    subject,
                    "schedule",
                    "current",
                    new,
                    (day_v1, day_v2),
                ),
                ChallengeCase(
                    f"before_{i:04d}",
                    "historical_original",
                    f"Before it was revised, what weekday had the fictional Meridian {i:04d} review been set for?",
                    subject,
                    "schedule",
                    "original",
                    old,
                    (day_v1, day_v2),
                ),
                ChallengeCase(
                    f"history_{i:04d}",
                    "correction_history",
                    f"Tell me the before-and-after weekday adjustment for project {i:04d} Meridian's review.",
                    subject,
                    "schedule",
                    "history",
                    f"{old}_corrected_to_{new}",
                    (day_v1, day_v2),
                ),
                ChallengeCase(
                    f"venue_{i:04d}",
                    "indirect_venue",
                    f"For Meridian {i:04d}, which space is the recurring check-in held in? I need the place, not its date.",
                    subject,
                    "venue",
                    "current",
                    BY_ID[venue].assertion.value,
                    (venue,),
                ),
                ChallengeCase(
                    f"distractor_{i:04d}",
                    "negative_disambiguation",
                    f"Not project {(i + 1) % 20:04d}: for Meridian project {i:04d}, which review day applies now?",
                    subject,
                    "schedule",
                    "current",
                    new,
                    (day_v1, day_v2),
                ),
            )
        )
    rows.extend(
        (
            ChallengeCase(
                "unknown_approved_cost",
                "unsupported_question",
                "For fictional Meridian project 0002, what amount was authorized for the review?",
                "synthetic-project-0002",
                "budget",
                "current",
                None,
                (),
            ),
            ChallengeCase(
                "unknown_meeting_start",
                "unsupported_question",
                "When exactly, down to the minute, does the weekly review for Meridian project 0007 begin?",
                "synthetic-project-0007",
                "start_time",
                "current",
                None,
                (),
            ),
            ChallengeCase(
                "unspecified_project",
                "unresolved_reference",
                "Which weekday is that Meridian review happening on now?",
                None,
                None,
                None,
                None,
                (),
            ),
            ChallengeCase(
                "ambiguous_project_weekday",
                "unresolved_reference",
                "Which Meridian project had its weekly review changed to Thursday?",
                None,
                None,
                None,
                None,
                (),
            ),
        )
    )
    if (
        len(rows) != 24
        or len({row.case_id for row in rows}) != len(rows)
        or sum(row.expected_answer is not None for row in rows) != 20
    ):
        raise ComparisonFailure("modified_challenge_suite")
    return tuple(rows)


CHALLENGE_CASES = challenge_cases()


def score_challenge_rankings(
    rankings: dict[str, dict[str, tuple[str, ...]]],
) -> dict[str, Any]:
    """Strict evidence-limited decisions with explicit scope-unknown abstention.

    A challenge case's subject/predicate/intent is *pre-labeled by humans*;
    this benchmark does not test an LLM's ability to resolve the question.
    """
    if not isinstance(rankings, dict) or set(rankings) != _ENGINE_NAMES:
        raise ComparisonFailure("invalid_challenge_engines")
    case_ids = {case.case_id for case in CHALLENGE_CASES}
    for ranked_cases in rankings.values():
        if not isinstance(ranked_cases, dict) or set(ranked_cases) != case_ids:
            raise ComparisonFailure("missing_challenge_cases")
        for ordered in ranked_cases.values():
            if (
                not isinstance(ordered, tuple)
                or len(ordered) > len(BY_ID)
                or len(ordered) != len(set(ordered))
                or any(not isinstance(a, str) or a not in BY_ID for a in ordered)
            ):
                raise ComparisonFailure("untrusted_challenge_candidates")

    by_id = {ident: fact.assertion for ident, fact in BY_ID.items()}
    measurements: dict[str, Any] = {}
    for name, cases in rankings.items():
        correct_answers = 0
        supported_retrieval = 0
        abstained_unknown = 0
        abstained_unresolved = 0
        by_category: dict[str, dict[str, int]] = {}

        for case in CHALLENGE_CASES:
            category = by_category.setdefault(case.category, {"cases": 0, "correct": 0})
            category["cases"] += 1
            ranked = cases[case.case_id][:TOP_K]
            if case.subject is None:
                # Without a uniquely resolved identity, no engine can
                # authorize a final factual decision. This is a *trusted
                # fixture gate*, not measured automatic NLU.
                decision_ok = True
                abstained_unresolved += 1
            else:
                if case.predicate is None or case.intent is None:
                    raise ComparisonFailure("invalid_question_scope")
                gold_group = tuple(
                    fact
                    for fact in by_id.values()
                    if fact.subject == case.subject and fact.predicate == case.predicate
                )
                full_lineage = all(fact.assertion_id in ranked for fact in gold_group)
                retrieved = all(
                    assertion_id in ranked for assertion_id in case.required_ids
                )
                if case.expected_answer is not None and retrieved:
                    supported_retrieval += 1
                decision = MemoryDecisionIndex(
                    tuple(by_id[ident] for ident in ranked)
                ).decide(MemoryQuestion(case.subject, case.predicate, case.intent))
                if case.expected_answer is None:
                    decision_ok = decision.status == "abstain"
                    abstained_unknown += int(decision_ok)
                else:
                    decision_ok = (
                        full_lineage
                        and decision.status == "answer"
                        and decision.answer_code == case.expected_answer
                    )
            if decision_ok:
                category["correct"] += 1
                correct_answers += 1

        measurements[name] = {
            "supported_retrieval": supported_retrieval,
            "supported_retrieval_required": 20,
            "decisions_correct": correct_answers,
            "decisions_required": 24,
            "unsupported_abstentions": abstained_unknown,
            "unsupported_required": 2,
            "unresolved_scope_gates": abstained_unresolved,
            "unresolved_required": 2,
            "per_category": by_category,
        }
    h = measurements["hindsight"]
    hybrid = measurements["hybrid"]
    return {
        "kind": "STEP8_HARDER_SYNTHETIC_LANGUAGE_RETRIEVAL",
        "same_60_fictional_facts_as_step7": True,
        "new_queries": 24,
        "supported_questions": 20,
        "unknown_questions": 2,
        "prelabeled_unresolved_questions": 2,
        "top_k": TOP_K,
        "engines": measurements,
        "hybrid_retrieval_delta": (
            hybrid["supported_retrieval"] - h["supported_retrieval"]
        ),
        "hybrid_decision_delta": (hybrid["decisions_correct"] - h["decisions_correct"]),
        "hybrid_noninferior_on_challenge": (
            hybrid["supported_retrieval"] >= h["supported_retrieval"]
            and hybrid["decisions_correct"] >= h["decisions_correct"]
        ),
        "automatic_reference_resolution_measured": False,
        "natural_language_fact_extraction_measured": False,
        "llm_answer_accuracy_measured": False,
        "production_promotion_allowed": False,
    }
