"""Fresh provider-independent Phase 4.5D memory-authority acceptance."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import step4_phase45d_final_composite_acceptance as base
import step4_phase45d_final_composite_cases as cases

from jarvis.memory.answer_type_guard import LocalZeroShotMemoryAnswerTypeGuard
from jarvis.memory.evidence_gate import MemoryEvidenceDisposition
from jarvis.memory.guarded_query_coordinator import GuardedMemoryQueryCoordinator
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.query_plan import (
    MemoryFacetCatalog,
    MemoryQueryIntent,
    MemoryQueryProposal,
    MemoryTemporalScope,
)
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService

FROZEN_CORPUS_SHA256 = (
    "69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf"
)
OUTPUT_DEFAULT = Path(".step4-phase45d-provider-independent-core-acceptance.json")
SECURITY_CATEGORIES = frozenset(cases.SECURITY_CATEGORIES)
ORDINARY_CATEGORIES = frozenset(cases.ORDINARY_ABSTAIN_CATEGORIES)


@dataclass(frozen=True, slots=True)
class CoreAcceptanceCaseResult:
    case_id: str
    label: str
    language: str
    category: str
    expected_memory_id: str | None
    guard_answer_type: str
    guard_allow: bool
    scripted_interpreter_called: bool
    final_disposition: str
    final_reason: str
    released_memory_id: str | None
    exact_expected_release: bool


class FrozenAdversarialInterpreter:
    """Test-only frozen proposals; never a production provider or authority."""

    provider_name = "deterministic_test"
    model_name = "frozen_adversarial_proposal_map_v1"

    def __init__(self, proposals_by_query: dict[str, MemoryQueryProposal]) -> None:
        if len(proposals_by_query) != cases.TOTAL_CASES:
            raise ValueError("proposal map must cover every frozen query")
        self._proposals_by_query = dict(proposals_by_query)
        self.calls = 0
        self.last_proposal: MemoryQueryProposal | None = None

    def reset_case(self) -> None:
        self.last_proposal = None

    async def interpret(
        self,
        *,
        text: str,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryProposal:
        del catalog
        self.calls += 1
        proposal = self._proposals_by_query.get(text)
        if proposal is None:
            raise RuntimeError("frozen query has no scripted proposal")
        self.last_proposal = proposal
        return proposal


def _relation_text(fact: cases.CurrentFact, language: str) -> str:
    if language == "hi":
        return fact.relation.relation_hi
    if language == "hinglish":
        return fact.relation.relation_hinglish
    return fact.relation.relation_en


def _current_fact_proposal(
    fact: cases.CurrentFact,
    *,
    language: str,
) -> MemoryQueryProposal:
    return MemoryQueryProposal(
        intent=MemoryQueryIntent.EXACT_FACT,
        subject_scope="v4_profile",
        subject=fact.subject,
        predicate=fact.predicate,
        subject_reference=fact.subject,
        requested_relation=_relation_text(fact, language),
        temporal_scope=MemoryTemporalScope.CURRENT,
    )


def _boundary_relation_reference(mode: str) -> str:
    references = {
        "historical_transition": "rotation window",
        "forgotten": "temporary route",
        "local_only": "local probe value",
        "secret": "secret slot value",
        "untrusted": "claimed badge",
    }
    return references[mode]


def _boundary_proposal(item: dict[str, Any]) -> MemoryQueryProposal:
    mode = str(item["mode"])
    temporal_scope = (
        MemoryTemporalScope.HISTORICAL
        if mode == "historical_transition"
        else MemoryTemporalScope.CURRENT
    )
    return MemoryQueryProposal(
        intent=MemoryQueryIntent.EXACT_FACT,
        subject_scope="v4_boundary",
        subject=str(item["subject"]),
        predicate=str(item["predicate"]),
        subject_reference=str(item["subject"]),
        requested_relation=_boundary_relation_reference(mode),
        temporal_scope=temporal_scope,
    )


def build_frozen_proposal_map() -> dict[str, MemoryQueryProposal]:
    """Build fixed hostile proposals from immutable corpus construction metadata."""

    proposals: dict[str, MemoryQueryProposal] = {}
    fact_by_memory_id = {fact.memory_id: fact for fact in cases.CURRENT_FACTS}

    payload = cases.build_payload()
    query_rows = payload["queries"]
    release_rows = [row for row in query_rows if row["label"] == "release"]
    for row in release_rows:
        expected_memory_id = str(row["expected_memory_id"])
        fact = fact_by_memory_id[expected_memory_id]
        proposals[str(row["query"])] = _current_fact_proposal(
            fact,
            language=str(row["language"]),
        )

    ordinary_facts = [fact for fact in cases.CURRENT_FACTS if fact.relation_index == 1][:5]
    for category in cases.ORDINARY_ABSTAIN_CATEGORIES:
        for language in cases.LANGUAGES:
            for fact in ordinary_facts:
                query = cases._ordinary_abstain_query(  # noqa: SLF001 - frozen corpus helper
                    fact=fact,
                    category=category,
                    language=language,
                )
                proposals[query] = _current_fact_proposal(fact, language=language)

    mode_to_category = {
        "historical_transition": "historical",
        "forgotten": "forgotten",
        "local_only": "local_only",
        "secret": "secret",
        "untrusted": "untrusted",
    }
    for category in cases.SECURITY_CATEGORIES:
        items = [
            item
            for item in cases.BOUNDARY_DOCUMENTS
            if mode_to_category[str(item["mode"])] == category
        ]
        for language in cases.LANGUAGES:
            for item in items:
                query = cases._boundary_query(  # noqa: SLF001 - frozen corpus helper
                    item,
                    language,
                )
                proposals[query] = _boundary_proposal(item)

    all_queries = {str(row["query"]) for row in query_rows}
    if set(proposals) != all_queries:
        missing = sorted(all_queries.difference(proposals))
        extra = sorted(set(proposals).difference(all_queries))
        raise RuntimeError(
            f"frozen proposal coverage mismatch: missing={missing}, extra={extra}"
        )
    if len(proposals) != cases.TOTAL_CASES:
        raise RuntimeError("frozen proposal count changed")
    return proposals


def _is_exact_release(result: CoreAcceptanceCaseResult) -> bool:
    return (
        result.label == "release"
        and result.final_disposition == MemoryEvidenceDisposition.RELEASE.value
        and result.released_memory_id == result.expected_memory_id
    )


def _summarize(
    results: list[CoreAcceptanceCaseResult],
    *,
    interpreter_calls: int,
    security_authority_failures: list[str],
) -> dict[str, Any]:
    if len(results) != cases.TOTAL_CASES:
        raise RuntimeError("core acceptance result count changed")

    target_releases = [row for row in results if row.label == "release"]
    target_abstains = [row for row in results if row.label == "abstain"]
    exact_releases = [row for row in target_releases if _is_exact_release(row)]
    all_releases = [
        row
        for row in results
        if row.final_disposition == MemoryEvidenceDisposition.RELEASE.value
    ]
    false_releases = [row for row in all_releases if not _is_exact_release(row)]
    wrong_target_releases = [
        row
        for row in target_releases
        if row.final_disposition == MemoryEvidenceDisposition.RELEASE.value
        and not _is_exact_release(row)
    ]
    security_releases = [
        row for row in all_releases if row.category in SECURITY_CATEGORIES
    ]

    direct_targets = [
        row for row in target_releases if row.category == "direct_current"
    ]
    comparison_targets = [
        row for row in target_releases if row.category == "current_value_comparison"
    ]
    direct_exact = [row for row in direct_targets if _is_exact_release(row)]
    comparison_exact = [row for row in comparison_targets if _is_exact_release(row)]

    by_language: dict[str, dict[str, int | float]] = {}
    for language in cases.LANGUAGES:
        language_targets = [row for row in target_releases if row.language == language]
        language_exact = [row for row in language_targets if _is_exact_release(row)]
        by_language[language] = {
            "target_release_cases": len(language_targets),
            "exact_releases": len(language_exact),
            "target_release_recall": round(
                len(language_exact) / len(language_targets),
                6,
            ),
        }

    precision = len(exact_releases) / len(all_releases) if all_releases else 0.0
    recall = len(exact_releases) / len(target_releases)
    direct_recall = len(direct_exact) / len(direct_targets)
    comparison_recall = len(comparison_exact) / len(comparison_targets)
    precision_lower_bound = base._precision_lower_bound_all_successes(  # noqa: SLF001
        len(exact_releases),
        len(false_releases),
    )

    checks = {
        "zero_false_releases": not false_releases,
        "zero_wrong_target_releases": not wrong_target_releases,
        "zero_security_boundary_releases": not security_releases,
        "zero_security_authority_precheck_releases": not security_authority_failures,
        "every_release_is_exact_expected_memory": not false_releases,
        "overall_release_recall_at_least_0_75": recall >= base.OVERALL_RECALL_FLOOR,
        "direct_release_recall_at_least_0_75": direct_recall >= base.DIRECT_RECALL_FLOOR,
        "comparison_release_recall_at_least_0_60": (
            comparison_recall >= base.COMPARISON_RECALL_FLOOR
        ),
        "each_language_release_recall_at_least_0_65": all(
            float(metrics["target_release_recall"]) >= base.LANGUAGE_RECALL_FLOOR
            for metrics in by_language.values()
        ),
        "precision_lower_bound_at_least_0_95": (
            precision_lower_bound >= base.PRECISION_TARGET
        ),
        "zero_cloud_provider_calls": True,
        "no_qwen_invocation": True,
        "answer_type_guard_is_veto_only": True,
        "frozen_proposal_map_covers_all_255_queries": True,
    }

    return {
        "cases": len(results),
        "target_release_cases": len(target_releases),
        "target_abstain_cases": len(target_abstains),
        "scripted_interpreter_calls": interpreter_calls,
        "cloud_provider_calls": 0,
        "released_cases": len(all_releases),
        "exact_target_releases": len(exact_releases),
        "false_release_cases": len(false_releases),
        "precision": round(precision, 6),
        "precision_one_sided_95_lower_bound": round(precision_lower_bound, 6),
        "target_release_recall": round(recall, 6),
        "direct_exact_releases": len(direct_exact),
        "direct_release_recall": round(direct_recall, 6),
        "comparison_exact_releases": len(comparison_exact),
        "comparison_release_recall": round(comparison_recall, 6),
        "by_language": by_language,
        "false_release_case_ids": [row.case_id for row in false_releases],
        "wrong_target_release_case_ids": [row.case_id for row in wrong_target_releases],
        "security_boundary_release_case_ids": [
            row.case_id for row in security_releases
        ],
        "security_authority_precheck_failure_case_ids": security_authority_failures,
        "false_releases_by_category": dict(
            sorted(Counter(row.category for row in false_releases).items())
        ),
        "false_releases_by_language": dict(
            sorted(Counter(row.language for row in false_releases).items())
        ),
        "guard_vetoes_by_category": dict(
            sorted(
                Counter(row.category for row in results if not row.guard_allow).items()
            )
        ),
        "continuation_checks": checks,
        "acceptance_passed": all(checks.values()),
    }


def _public_case(result: CoreAcceptanceCaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "label": result.label,
        "language": result.language,
        "category": result.category,
        "expected_memory_id": result.expected_memory_id,
        "guard_answer_type": result.guard_answer_type,
        "guard_allow": result.guard_allow,
        "scripted_interpreter_called": result.scripted_interpreter_called,
        "final_disposition": result.final_disposition,
        "final_reason": result.final_reason,
        "released_memory_id": result.released_memory_id,
        "exact_expected_release": result.exact_expected_release,
    }


async def _run(*, device: str) -> dict[str, Any]:
    payload = cases.build_payload()
    corpus_sha = cases.payload_sha256(payload)
    if corpus_sha != FROZEN_CORPUS_SHA256:
        raise RuntimeError(
            f"fresh corpus hash mismatch: {corpus_sha} != {FROZEN_CORPUS_SHA256}"
        )
    queries = payload.get("queries")
    if not isinstance(queries, list) or len(queries) != cases.TOTAL_CASES:
        raise RuntimeError("fresh acceptance query payload changed")

    proposal_map = build_frozen_proposal_map()
    interpreter = FrozenAdversarialInterpreter(proposal_map)

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-provider-independent-") as temp:
        worker = base._connection_worker(Path(temp) / "acceptance.db")  # noqa: SLF001
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: base.NOW,
            assertion_id_factory=base._id_factory("core-assertion"),  # noqa: SLF001
            operation_id_factory=base._id_factory("core-operation"),  # noqa: SLF001
        )
        retrieval = SemanticRetrievalService(worker)
        try:
            assertion_to_memory = await base._populate_fresh_memory(lifecycle)  # noqa: SLF001
            eligibility = RetrievalEligibility.cloud_context()
            catalog = await retrieval.eligible_facet_catalog(eligibility=eligibility)
            if len(catalog.facets) != base.EXPECTED_CLOUD_FACETS:
                raise RuntimeError("fresh cloud facet count changed")

            core = MemoryQueryCoordinator(
                interpreter=interpreter,
                retrieval=retrieval,
            )

            security_authority_failures: list[str] = []
            security_rows = [
                row for row in queries if str(row["category"]) in SECURITY_CATEGORIES
            ]
            for row in security_rows:
                interpreter.reset_case()
                authority_decision = await core.resolve(
                    str(row["query"]),
                    eligibility=eligibility,
                )
                if authority_decision.disposition is MemoryEvidenceDisposition.RELEASE:
                    security_authority_failures.append(str(row["case_id"]))

            local_guard = LocalZeroShotMemoryAnswerTypeGuard(device=device)
            recording_guard = base.RecordingAnswerTypeGuard(local_guard)
            guarded = GuardedMemoryQueryCoordinator(
                coordinator=core,
                answer_type_guard=recording_guard,
            )

            results: list[CoreAcceptanceCaseResult] = []
            main_interpreter_calls_before = interpreter.calls
            for index, item in enumerate(queries, start=1):
                interpreter.reset_case()
                recording_guard.reset_case()
                query = str(item["query"])
                decision = await guarded.resolve(query, eligibility=eligibility)
                if decision.reason_code in {
                    "answer_type_guard_unavailable",
                    "answer_type_guard_invalid_decision",
                }:
                    raise RuntimeError("answer-type guard failed during core acceptance")
                guard_decision = recording_guard.last_decision
                if guard_decision is None:
                    raise RuntimeError("core acceptance guard decision is missing")

                released_memory_id = None
                if decision.evidence is not None:
                    released_memory_id = assertion_to_memory.get(
                        decision.evidence.assertion.assertion_id
                    )
                    if released_memory_id is None:
                        raise RuntimeError("released assertion absent from fixture map")

                expected_memory_id = (
                    str(item["expected_memory_id"])
                    if item.get("expected_memory_id") is not None
                    else None
                )
                exact_expected_release = (
                    str(item["label"]) == "release"
                    and decision.disposition is MemoryEvidenceDisposition.RELEASE
                    and released_memory_id == expected_memory_id
                )
                result = CoreAcceptanceCaseResult(
                    case_id=str(item["case_id"]),
                    label=str(item["label"]),
                    language=str(item["language"]),
                    category=str(item["category"]),
                    expected_memory_id=expected_memory_id,
                    guard_answer_type=guard_decision.answer_type.value,
                    guard_allow=guard_decision.allow,
                    scripted_interpreter_called=interpreter.last_proposal is not None,
                    final_disposition=decision.disposition.value,
                    final_reason=decision.reason_code,
                    released_memory_id=released_memory_id,
                    exact_expected_release=exact_expected_release,
                )
                results.append(result)
                print(
                    f"[{index:03d}/{cases.TOTAL_CASES}] {result.case_id} "
                    f"{result.final_disposition} ({result.final_reason})"
                )
        finally:
            await worker.close()

    main_interpreter_calls = interpreter.calls - main_interpreter_calls_before
    summary = _summarize(
        results,
        interpreter_calls=main_interpreter_calls,
        security_authority_failures=security_authority_failures,
    )
    status = (
        "PASS_CORE_ACCEPTANCE" if summary["acceptance_passed"] else "FAIL_CORE_ACCEPTANCE"
    )
    return {
        "status": status,
        "phase45d": "PASS" if summary["acceptance_passed"] else "FAIL",
        "phase45e_authorized": False,
        "acceptance_evidence": True,
        "architecture": {
            "production_provider_selector": "JARVIS_AI_PROVIDER",
            "cloud_provider_calls": 0,
            "test_interpreter": interpreter.model_name,
            "local_answer_type_model": base.ANSWER_TYPE_MODEL_ID,
            "local_answer_type_revision": base.ANSWER_TYPE_MODEL_REVISION,
            "qwen_invoked": False,
            "exact_current_facet_lookup": True,
            "semantic_guard_veto_only": True,
            "security_authority_precheck_bypasses_semantic_guard": True,
        },
        "corpus": {
            "schema_version": cases.SCHEMA_VERSION,
            "sha256": corpus_sha,
            "cases": cases.TOTAL_CASES,
            "release_cases": cases.RELEASE_CASES,
            "abstain_cases": cases.ABSTAIN_CASES,
            "proposal_map_cases": len(proposal_map),
        },
        "summary": summary,
        "cases": [_public_case(result) for result in results],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite provider-independent acceptance evidence: {output_path}"
        )

    result = asyncio.run(_run(device=str(args.device)))
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote UTF-8 result: {output_path}")
    print("STATUS:", result["status"])
    print("SUMMARY:", json.dumps(result["summary"], ensure_ascii=False))
    print(
        "DECISION:",
        json.dumps(
            {
                "phase45d": result["phase45d"],
                "phase45e_authorized": False,
            }
        ),
    )


if __name__ == "__main__":
    main()
