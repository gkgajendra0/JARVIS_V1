"""Development-only structured-query planner diagnostic for Phase 4.5D.

This harness reuses exactly 45 already-exposed V2 validation query texts but rebuilds
their known structured fixture metadata so the new exact-facet architecture can be
measured without the old retrieval harness's owner/owner flattening. It sends exactly
one query per Gemini request, injects only eligible facet keys, and passes every
proposal through production grounding, query policy, and evidence-gate code.

The old V2 ``relation_mismatch`` rows are preserved for provenance but are evaluated
as resolvable relation-comparison lookups here: the new architecture can select the
relation actually requested by the user instead of being forced to judge an already
retrieved wrong-relation document.

The result is development evidence only. It cannot authorize Phase 4.5E or serve as
fresh V3 acceptance evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import re
import sqlite3
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import step4_phase45d_final_v2_cases as v2_cases

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.evidence_gate import (
    MemoryEvidenceDisposition,
    MemoryEvidenceGate,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query_grounding import (
    MemoryQueryGroundingDisposition,
    MemoryQueryGroundingPolicy,
    surface_phrase_is_grounded,
)
from jarvis.memory.query_interpreters import build_memory_query_interpreter
from jarvis.memory.query_plan import (
    MemoryFacetCatalog,
    MemoryFacetKey,
    MemoryQueryPlanDisposition,
    MemoryQueryPolicy,
    MemoryQueryProposal,
)
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

GEMINI_MODEL_ID = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_RPM = 12.0
GEMINI_MAX_ATTEMPTS = 5
OUTPUT_DEFAULT = Path(
    ".step4-phase45d-v2-structured-query-planner-diagnostic-v1.json"
)
NOW = __import__("datetime").datetime(2026, 9, 6, 16, 30, tzinfo=__import__("datetime").UTC)
TARGET_DOMAINS = ("project", "travel", "workspace")
TARGET_LANGUAGES = tuple(v2_cases.LANGUAGES)
RELATION_COMPARISON_CATEGORY = "relation_mismatch"
TARGET_TRUE_ABSTAIN_CATEGORIES = tuple(
    category
    for category in v2_cases.ABSTAIN_CATEGORIES
    if category != RELATION_COMPARISON_CATEGORY
)
SECURITY_BOUNDARY_CATEGORIES = frozenset(v2_cases.SECURITY_BOUNDARY_CATEGORIES)
EXPECTED_DIRECT_POSITIVE_CASES = len(TARGET_DOMAINS) * len(TARGET_LANGUAGES)
EXPECTED_RELATION_COMPARISON_CASES = len(TARGET_LANGUAGES)
EXPECTED_TARGET_RELEASE_CASES = (
    EXPECTED_DIRECT_POSITIVE_CASES + EXPECTED_RELATION_COMPARISON_CASES
)
EXPECTED_TRUE_ABSTAIN_CASES = len(TARGET_TRUE_ABSTAIN_CATEGORIES) * len(TARGET_LANGUAGES)
EXPECTED_CASES = EXPECTED_TARGET_RELEASE_CASES + EXPECTED_TRUE_ABSTAIN_CASES
EXPECTED_CLOUD_FACETS = len(v2_cases.CURRENT_FACTS) + 75


@dataclass(frozen=True, slots=True)
class PlannerCaseResult:
    case_id: str
    source_v2_label: str
    target_label: str
    language: str
    category: str
    expected_memory_id: str | None
    proposed_intent: str
    proposed_temporal_scope: str
    proposed_subject_scope: str | None
    proposed_subject: str | None
    proposed_predicate: str | None
    subject_reference_present: bool
    relation_reference_present: bool
    subject_reference_grounded: bool
    relation_reference_grounded: bool
    grounding_disposition: str
    grounding_reason: str
    query_policy_disposition: str
    query_policy_reason: str
    final_disposition: str
    final_reason: str
    released_memory_id: str | None
    proposed_facet_matches_expected: bool | None
    request_seconds: float
    request_attempts: int


class GeminiRequestPacer:
    def __init__(self, rpm: float) -> None:
        if not isinstance(rpm, int | float) or isinstance(rpm, bool):
            raise TypeError("Gemini RPM must be numeric")
        if float(rpm) <= 0:
            raise ValueError("Gemini RPM must be positive")
        self.interval_seconds = 60.0 / float(rpm)
        self._lock = asyncio.Lock()
        self._next_start = 0.0

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_start - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_start = time.monotonic() + self.interval_seconds


def _retry_after_seconds(message: str) -> float | None:
    match = re.search(
        r"retry in\s+([0-9]+(?:\.[0-9]+)?)s",
        message,
        flags=re.IGNORECASE,
    )
    return float(match.group(1)) if match else None


def _id_factory(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):04d}"


def _connection_worker(path: Path) -> SerialConnectionWorker:
    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: NOW).apply(connection)
        return connection

    return SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-phase45d-query-planner",
    )


def _source(
    memory_id: str,
    *,
    mode: str,
    suffix: str = "source",
) -> MemorySource:
    authority = (
        AuthorityClass.UNTRUSTED
        if mode == "untrusted"
        else AuthorityClass.OWNER_EXPLICIT
    )
    sensitivity = (
        Sensitivity.LOCAL_ONLY if mode == "local_only" else Sensitivity.STANDARD
    )
    source_class = (
        MemorySourceClass.EXTERNAL_WEB
        if authority is AuthorityClass.UNTRUSTED
        else MemorySourceClass.OWNER_EXPLICIT
    )
    return MemorySource(
        source_id=f"phase45d-planner:{memory_id}:{suffix}",
        source_class=source_class,
        canonical_ref=f"phase45d-planner:{memory_id}",
        observed_at=NOW,
        authority_class=authority,
        sensitivity=sensitivity,
        created_at=NOW,
    )


def _draft(
    *,
    subject_scope: str,
    subject: str,
    predicate: str,
    value: str,
    normalized_text: str,
    sensitivity: Sensitivity = Sensitivity.STANDARD,
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope=subject_scope,
        subject=subject,
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=value,
        normalized_text=normalized_text,
        freshness_class=FreshnessClass.STABLE,
        sensitivity=sensitivity,
    )


def _boundary_token(item: dict[str, Any]) -> str:
    memory_id = str(item["memory_id"])
    token = memory_id.rsplit("_", 1)[-1]
    if not token.isdigit():
        raise RuntimeError(f"unexpected V2 boundary memory id: {memory_id}")
    return token


def _boundary_subject(item: dict[str, Any]) -> str:
    token = _boundary_token(item)
    mode = str(item["mode"])
    if mode == "historical_transition":
        return f"Ledger-{token}"
    if mode == "forgotten":
        return f"ForgottenRoute-{token}"
    if mode == "local_only":
        return f"LocalDiagnostic-{token}"
    if mode == "secret":
        return f"SecretPlaceholder-{token}"
    if mode == "untrusted":
        return f"UntrustedClaim-{token}"
    raise RuntimeError(f"unsupported V2 boundary mode: {mode}")


def _fact_by_memory_id() -> dict[str, v2_cases.CurrentFact]:
    return {fact.memory_id: fact for fact in v2_cases.CURRENT_FACTS}


def _relation_comparison_target_memory_id(case: dict[str, Any]) -> str:
    """Resolve the canonical relation actually requested by an exposed V2 query."""

    query = str(case["query"])
    language = str(case["language"])
    source_matches = [
        fact
        for fact in v2_cases.CURRENT_FACTS
        if fact.split == "validation"
        and v2_cases._current_abstain_query(
            fact,
            RELATION_COMPARISON_CATEGORY,
            language,
        )
        == query
    ]
    if len(source_matches) != 1:
        raise RuntimeError(
            "relation-comparison query must map to exactly one frozen V2 source fact"
        )
    source_fact = source_matches[0]
    requested_relation_index = (source_fact.relation_index + 1) % len(v2_cases.RELATIONS)
    targets = [
        fact
        for fact in v2_cases.CURRENT_FACTS
        if fact.domain == source_fact.domain
        and fact.profile == source_fact.profile
        and fact.relation_index == requested_relation_index
    ]
    if len(targets) != 1:
        raise RuntimeError(
            "relation-comparison query must map to exactly one requested V2 facet"
        )
    return targets[0].memory_id


def _diagnostic_case(
    source: dict[str, Any],
    *,
    target_label: str,
    expected_memory_id: str | None,
) -> dict[str, Any]:
    item = dict(source)
    item["source_v2_label"] = str(source["label"])
    item["target_label"] = target_label
    item["diagnostic_expected_memory_id"] = expected_memory_id
    return item


def select_diagnostic_cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    queries = payload.get("queries")
    if not isinstance(queries, list):
        raise TypeError("V2 payload queries must be a list")
    facts = _fact_by_memory_id()
    selected: list[dict[str, Any]] = []

    for domain in TARGET_DOMAINS:
        for language in TARGET_LANGUAGES:
            matches = []
            for item in queries:
                expected = item.get("expected_memory_id")
                fact = facts.get(str(expected)) if expected is not None else None
                if (
                    item.get("split") == "validation"
                    and item.get("label") == "release"
                    and item.get("language") == language
                    and fact is not None
                    and fact.domain == domain
                ):
                    matches.append(item)
            if not matches:
                raise RuntimeError(
                    f"missing validation release cell for {domain}/{language}"
                )
            chosen = min(matches, key=lambda item: str(item["case_id"]))
            selected.append(
                _diagnostic_case(
                    chosen,
                    target_label="release",
                    expected_memory_id=str(chosen["expected_memory_id"]),
                )
            )

    for category in v2_cases.ABSTAIN_CATEGORIES:
        for language in TARGET_LANGUAGES:
            matches = [
                item
                for item in queries
                if item.get("split") == "validation"
                and item.get("label") == "abstain"
                and item.get("category") == category
                and item.get("language") == language
            ]
            if not matches:
                raise RuntimeError(
                    f"missing validation abstain cell for {category}/{language}"
                )
            chosen = min(matches, key=lambda item: str(item["case_id"]))
            if category == RELATION_COMPARISON_CATEGORY:
                selected.append(
                    _diagnostic_case(
                        chosen,
                        target_label="release",
                        expected_memory_id=_relation_comparison_target_memory_id(chosen),
                    )
                )
            else:
                selected.append(
                    _diagnostic_case(
                        chosen,
                        target_label="abstain",
                        expected_memory_id=None,
                    )
                )

    case_ids = [str(item["case_id"]) for item in selected]
    if len(selected) != EXPECTED_CASES or len(case_ids) != len(set(case_ids)):
        raise RuntimeError(
            f"planner diagnostic must select exactly {EXPECTED_CASES} unique cases"
        )

    source_release_count = sum(item["source_v2_label"] == "release" for item in selected)
    source_abstain_count = sum(item["source_v2_label"] == "abstain" for item in selected)
    target_release_count = sum(item["target_label"] == "release" for item in selected)
    target_abstain_count = sum(item["target_label"] == "abstain" for item in selected)
    if (source_release_count, source_abstain_count) != (9, 36):
        raise RuntimeError("planner diagnostic source V2 label counts changed")
    if (target_release_count, target_abstain_count) != (
        EXPECTED_TARGET_RELEASE_CASES,
        EXPECTED_TRUE_ABSTAIN_CASES,
    ):
        raise RuntimeError("planner diagnostic target label counts changed")
    return selected


async def populate_structured_v2(
    lifecycle: MemoryLifecycleService,
) -> dict[str, str]:
    """Populate V2 with structured subjects while preserving frozen lifecycle modes."""

    assertion_to_memory: dict[str, str] = {}
    forgotten: list[tuple[str, str]] = []

    for fact in v2_cases.CURRENT_FACTS:
        record = await lifecycle.create(
            _draft(
                subject_scope="v2_profile",
                subject=fact.profile,
                predicate=fact.predicate,
                value=fact.value,
                normalized_text=fact.text,
            ),
            _source(fact.memory_id, mode="current"),
            reason_code="phase45d_planner_fixture",
        )
        assertion_to_memory[record.assertion_id] = fact.memory_id

    for item in v2_cases.BOUNDARY_DOCUMENTS:
        memory_id = str(item["memory_id"])
        predicate = str(item["predicate"])
        mode = str(item["mode"])
        subject = _boundary_subject(item)
        if mode == "secret":
            continue
        sensitivity = (
            Sensitivity.LOCAL_ONLY
            if mode == "local_only"
            else Sensitivity.STANDARD
        )
        record = await lifecycle.create(
            _draft(
                subject_scope="v2_boundary",
                subject=subject,
                predicate=predicate,
                value=str(item["text"]),
                normalized_text=str(item["text"]),
                sensitivity=sensitivity,
            ),
            _source(memory_id, mode=mode),
            reason_code="phase45d_planner_fixture",
        )
        assertion_to_memory[record.assertion_id] = memory_id

        if mode == "historical_transition":
            replacement_memory_id = str(item["replacement_memory_id"])
            replacement = await lifecycle.historical_change(
                record.assertion_id,
                _draft(
                    subject_scope="v2_boundary",
                    subject=subject,
                    predicate=predicate,
                    value=str(item["replacement_text"]),
                    normalized_text=str(item["replacement_text"]),
                ),
                _source(
                    replacement_memory_id,
                    mode="current",
                    suffix="transition",
                ),
                effective_at=NOW,
                reason_code="phase45d_planner_transition",
            )
            assertion_to_memory[replacement.assertion_id] = replacement_memory_id
        elif mode == "forgotten":
            forgotten.append((record.assertion_id, memory_id))

    for assertion_id, memory_id in forgotten:
        forgotten_ok = await lifecycle.forget(
            assertion_id,
            _source(memory_id, mode="current", suffix="forget"),
            reason_code="phase45d_planner_forget",
        )
        if not forgotten_ok:
            raise RuntimeError(f"failed to forget V2 planner fixture {memory_id}")

    return assertion_to_memory


async def _call_interpreter(
    interpreter: Any,
    *,
    query: str,
    catalog: MemoryFacetCatalog,
    pacer: GeminiRequestPacer,
) -> tuple[MemoryQueryProposal, float, int]:
    last_error: Exception | None = None
    total_started = time.perf_counter()
    for attempt in range(GEMINI_MAX_ATTEMPTS):
        await pacer.wait()
        try:
            proposal = await interpreter.interpret(text=query, catalog=catalog)
            return proposal, time.perf_counter() - total_started, attempt + 1
        except Exception as exc:
            last_error = exc
            raw_message = str(exc)
            message = raw_message.upper()
            retryable = any(
                marker in message
                for marker in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")
            )
            if not retryable or attempt == GEMINI_MAX_ATTEMPTS - 1:
                raise
            retry_after = _retry_after_seconds(raw_message)
            retry_delay = max(
                float(2**attempt),
                pacer.interval_seconds,
                (retry_after + 1.0) if retry_after is not None else 0.0,
            )
            await asyncio.sleep(retry_delay)
    raise AssertionError(f"unreachable Gemini retry state: {last_error}")


def _proposal_facet(proposal: MemoryQueryProposal) -> MemoryFacetKey | None:
    if (
        proposal.subject_scope is None
        or proposal.subject is None
        or proposal.predicate is None
    ):
        return None
    return MemoryFacetKey(
        proposal.subject_scope,
        proposal.subject,
        proposal.predicate,
    )


def _expected_facet(case: dict[str, Any]) -> MemoryFacetKey | None:
    expected = case.get("diagnostic_expected_memory_id")
    if expected is None:
        return None
    fact = _fact_by_memory_id().get(str(expected))
    if fact is None:
        raise RuntimeError(f"unknown diagnostic expected memory id: {expected}")
    return MemoryFacetKey("v2_profile", fact.profile, fact.predicate)


async def _evaluate_case(
    *,
    case: dict[str, Any],
    catalog: MemoryFacetCatalog,
    interpreter: Any,
    pacer: GeminiRequestPacer,
    grounding_policy: MemoryQueryGroundingPolicy,
    query_policy: MemoryQueryPolicy,
    evidence_gate: MemoryEvidenceGate,
    assertion_to_memory: dict[str, str],
) -> PlannerCaseResult:
    query = str(case["query"])
    proposal, request_seconds, request_attempts = await _call_interpreter(
        interpreter,
        query=query,
        catalog=catalog,
        pacer=pacer,
    )
    grounding = grounding_policy.evaluate(
        text=query,
        proposal=proposal,
        catalog=catalog,
    )
    query_decision = query_policy.evaluate(proposal, catalog)

    if grounding.disposition is MemoryQueryGroundingDisposition.ABSTAIN:
        final_disposition = MemoryEvidenceDisposition.ABSTAIN
        final_reason = grounding.reason_code
        released_memory_id = None
    else:
        evidence_decision = await evidence_gate.evaluate(
            proposal,
            eligibility=RetrievalEligibility.cloud_context(),
        )
        final_disposition = evidence_decision.disposition
        final_reason = evidence_decision.reason_code
        released_memory_id = None
        if evidence_decision.evidence is not None:
            released_memory_id = assertion_to_memory.get(
                evidence_decision.evidence.assertion.assertion_id
            )
            if released_memory_id is None:
                raise RuntimeError(
                    f"released assertion is absent from fixture mapping: {case['case_id']}"
                )

    proposed_facet = _proposal_facet(proposal)
    expected_facet = _expected_facet(case)
    return PlannerCaseResult(
        case_id=str(case["case_id"]),
        source_v2_label=str(case["source_v2_label"]),
        target_label=str(case["target_label"]),
        language=str(case["language"]),
        category=str(case["category"]),
        expected_memory_id=(
            str(case["diagnostic_expected_memory_id"])
            if case.get("diagnostic_expected_memory_id") is not None
            else None
        ),
        proposed_intent=proposal.intent.value,
        proposed_temporal_scope=proposal.temporal_scope.value,
        proposed_subject_scope=proposal.subject_scope,
        proposed_subject=proposal.subject,
        proposed_predicate=proposal.predicate,
        subject_reference_present=proposal.subject_reference is not None,
        relation_reference_present=proposal.requested_relation is not None,
        subject_reference_grounded=(
            proposal.subject_reference is not None
            and surface_phrase_is_grounded(query, proposal.subject_reference)
        ),
        relation_reference_grounded=(
            proposal.requested_relation is not None
            and surface_phrase_is_grounded(query, proposal.requested_relation)
        ),
        grounding_disposition=grounding.disposition.value,
        grounding_reason=grounding.reason_code,
        query_policy_disposition=query_decision.disposition.value,
        query_policy_reason=query_decision.reason_code,
        final_disposition=final_disposition.value,
        final_reason=final_reason,
        released_memory_id=released_memory_id,
        proposed_facet_matches_expected=(
            proposed_facet == expected_facet if expected_facet is not None else None
        ),
        request_seconds=round(request_seconds, 6),
        request_attempts=request_attempts,
    )


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int((len(ordered) - 1) * fraction))
    return round(ordered[index], 6)


def _is_exact_target_release(result: PlannerCaseResult) -> bool:
    return (
        result.target_label == "release"
        and result.final_disposition == MemoryEvidenceDisposition.RELEASE.value
        and result.released_memory_id == result.expected_memory_id
    )


def summarize(results: list[PlannerCaseResult]) -> dict[str, Any]:
    target_release_total = sum(result.target_label == "release" for result in results)
    target_abstain_total = sum(result.target_label == "abstain" for result in results)
    released = [
        result
        for result in results
        if result.final_disposition == MemoryEvidenceDisposition.RELEASE.value
    ]
    true_releases = [result for result in released if _is_exact_target_release(result)]
    false_releases = [result for result in released if result not in true_releases]
    direct_targets = [
        result
        for result in results
        if result.source_v2_label == "release" and result.target_label == "release"
    ]
    relation_targets = [
        result
        for result in results
        if result.category == RELATION_COMPARISON_CATEGORY
        and result.target_label == "release"
    ]
    direct_exact = [result for result in direct_targets if _is_exact_target_release(result)]
    relation_exact = [
        result for result in relation_targets if _is_exact_target_release(result)
    ]
    target_recall = (
        len(true_releases) / target_release_total if target_release_total else 0.0
    )
    precision = len(true_releases) / len(released) if released else 1.0

    by_language: dict[str, dict[str, Any]] = {}
    for language in TARGET_LANGUAGES:
        positives = [
            result
            for result in results
            if result.language == language and result.target_label == "release"
        ]
        exact = [result for result in positives if _is_exact_target_release(result)]
        by_language[language] = {
            "target_release_cases": len(positives),
            "exact_releases": len(exact),
            "target_release_recall": round(
                len(exact) / len(positives) if positives else 0.0,
                6,
            ),
        }

    intents_by_category: dict[str, dict[str, int]] = {}
    for category in sorted({result.category for result in results}):
        intents_by_category[category] = dict(
            sorted(
                Counter(
                    result.proposed_intent
                    for result in results
                    if result.category == category
                ).items()
            )
        )

    grounding_reasons = Counter(
        result.grounding_reason
        for result in results
        if result.grounding_disposition
        == MemoryQueryGroundingDisposition.ABSTAIN.value
    )
    query_policy_reasons = Counter(
        result.query_policy_reason
        for result in results
        if result.query_policy_disposition
        != MemoryQueryPlanDisposition.ALLOW_CURRENT_FACT.value
    )
    security_release_ids = [
        result.case_id
        for result in released
        if result.category in SECURITY_BOUNDARY_CATEGORIES
    ]
    wrong_target_release_ids = [
        result.case_id
        for result in released
        if result.target_label == "release"
        and result.released_memory_id != result.expected_memory_id
    ]
    target_facet_misses = [
        result.case_id
        for result in results
        if result.target_label == "release"
        and result.proposed_facet_matches_expected is not True
    ]
    false_release_by_category = dict(
        sorted(Counter(result.category for result in false_releases).items())
    )
    false_release_by_language = dict(
        sorted(Counter(result.language for result in false_releases).items())
    )
    request_seconds = [result.request_seconds for result in results]

    continuation_checks = {
        "zero_false_releases": not false_releases,
        "zero_security_boundary_releases": not security_release_ids,
        "direct_exact_release_at_least_8_of_9": len(direct_exact) >= 8,
        "relation_comparison_exact_release_3_of_3": (
            len(relation_exact) == EXPECTED_RELATION_COMPARISON_CASES
        ),
        "each_language_at_least_3_of_4": all(
            metrics["exact_releases"] >= 3 for metrics in by_language.values()
        ),
        "every_release_is_exact_expected_memory": not false_releases,
        "jarvis_injects_no_canonical_memory_values": True,
        "qwen_invoked": False,
    }

    true_abstains = sum(
        result.target_label == "abstain"
        and result.final_disposition != MemoryEvidenceDisposition.RELEASE.value
        for result in results
    )
    return {
        "cases": len(results),
        "source_v2_release_labels": sum(
            result.source_v2_label == "release" for result in results
        ),
        "source_v2_abstain_labels": sum(
            result.source_v2_label == "abstain" for result in results
        ),
        "target_release_cases": target_release_total,
        "target_abstain_cases": target_abstain_total,
        "direct_target_release_cases": len(direct_targets),
        "relation_comparison_target_release_cases": len(relation_targets),
        "released_cases": len(released),
        "tp_exact_release": len(true_releases),
        "fp_or_wrong_release": len(false_releases),
        "fn_target_release": target_release_total - len(true_releases),
        "tn_target_abstain": true_abstains,
        "precision": round(precision, 6),
        "target_release_recall": round(target_recall, 6),
        "direct_exact_releases": len(direct_exact),
        "relation_comparison_exact_releases": len(relation_exact),
        "by_language": by_language,
        "false_release_case_ids": [result.case_id for result in false_releases],
        "false_releases_by_category": false_release_by_category,
        "false_releases_by_language": false_release_by_language,
        "wrong_target_release_case_ids": wrong_target_release_ids,
        "security_boundary_release_case_ids": security_release_ids,
        "target_proposed_facet_miss_case_ids": target_facet_misses,
        "intents_by_category": intents_by_category,
        "grounding_abstain_reasons": dict(sorted(grounding_reasons.items())),
        "query_policy_abstain_reasons": dict(sorted(query_policy_reasons.items())),
        "request_latency_seconds": {
            "p50": _percentile(request_seconds, 0.50),
            "p95": _percentile(request_seconds, 0.95),
            "max": round(max(request_seconds), 6) if request_seconds else None,
        },
        "continuation_checks": continuation_checks,
        "promising_for_larger_retired_review": all(continuation_checks.values()),
    }


def _public_case(result: PlannerCaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "source_v2_label": result.source_v2_label,
        "target_label": result.target_label,
        "language": result.language,
        "category": result.category,
        "expected_memory_id": result.expected_memory_id,
        "proposed_intent": result.proposed_intent,
        "proposed_temporal_scope": result.proposed_temporal_scope,
        "proposed_subject_scope": result.proposed_subject_scope,
        "proposed_subject": result.proposed_subject,
        "proposed_predicate": result.proposed_predicate,
        "subject_reference_present": result.subject_reference_present,
        "relation_reference_present": result.relation_reference_present,
        "subject_reference_grounded": result.subject_reference_grounded,
        "relation_reference_grounded": result.relation_reference_grounded,
        "grounding_disposition": result.grounding_disposition,
        "grounding_reason": result.grounding_reason,
        "query_policy_disposition": result.query_policy_disposition,
        "query_policy_reason": result.query_policy_reason,
        "final_disposition": result.final_disposition,
        "final_reason": result.final_reason,
        "released_memory_id": result.released_memory_id,
        "proposed_facet_matches_expected": result.proposed_facet_matches_expected,
        "request_seconds": result.request_seconds,
        "request_attempts": result.request_attempts,
    }


async def _run(*, gemini_rpm: float) -> dict[str, Any]:
    payload = v2_cases.build_payload()
    selected = select_diagnostic_cases(payload)

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-query-planner-") as temp_dir:
        worker = _connection_worker(Path(temp_dir) / "planner.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: NOW,
            assertion_id_factory=_id_factory("phase45d-planner-assertion"),
            operation_id_factory=_id_factory("phase45d-planner-operation"),
        )
        retrieval = SemanticRetrievalService(worker)
        try:
            assertion_to_memory = await populate_structured_v2(lifecycle)
            cloud_eligibility = RetrievalEligibility.cloud_context()
            catalog = await retrieval.eligible_facet_catalog(
                eligibility=cloud_eligibility
            )
            if len(catalog.facets) != EXPECTED_CLOUD_FACETS:
                raise RuntimeError(
                    "structured V2 cloud facet count changed: "
                    f"{len(catalog.facets)} != {EXPECTED_CLOUD_FACETS}"
                )

            interpreter = build_memory_query_interpreter(
                provider="gemini",
                model=GEMINI_MODEL_ID,
            )
            grounding_policy = MemoryQueryGroundingPolicy()
            query_policy = MemoryQueryPolicy()
            evidence_gate = MemoryEvidenceGate(retrieval, query_policy=query_policy)
            pacer = GeminiRequestPacer(gemini_rpm)

            results: list[PlannerCaseResult] = []
            for index, case in enumerate(selected, start=1):
                result = await _evaluate_case(
                    case=case,
                    catalog=catalog,
                    interpreter=interpreter,
                    pacer=pacer,
                    grounding_policy=grounding_policy,
                    query_policy=query_policy,
                    evidence_gate=evidence_gate,
                    assertion_to_memory=assertion_to_memory,
                )
                results.append(result)
                print(
                    f"[{index:02d}/{EXPECTED_CASES}] {result.case_id} "
                    f"{result.final_disposition} ({result.final_reason})"
                )
        finally:
            await worker.close()

    summary = summarize(results)
    return {
        "status": "DEVELOPMENT_STRUCTURED_QUERY_PLANNER_DIAGNOSTIC_COMPLETE",
        "purpose": (
            "Measure provider-proposed structured memory queries under deterministic "
            "JARVIS grounding, policy, and exact-facet release authority"
        ),
        "development_only": True,
        "acceptance_evidence": False,
        "v2_is_exposed_and_retired": True,
        "phase45e_authorized": False,
        "model": {
            "provider": "gemini",
            "model_id": GEMINI_MODEL_ID,
            "request_shape": "one user query per request",
            "concurrency": 1,
            "rpm_cap": gemini_rpm,
            "structured_output": True,
            "store": False,
            "diagnostic_provider_pin_is_not_production_selector": True,
        },
        "architecture": {
            "production_provider_selector": "JARVIS_AI_PROVIDER",
            "interpreter_has_release_authority": False,
            "planner_context_fields": ["user_query", "eligible_facets"],
            "canonical_memory_values_injected_by_jarvis": False,
            "qwen_invoked": False,
            "exact_lookup": True,
            "cloud_facet_count": EXPECTED_CLOUD_FACETS,
        },
        "corpus": {
            "source": "exposed_retired_v2_validation_queries",
            "v2_schema_version": v2_cases.V2_CORPUS_SCHEMA_VERSION,
            "v2_sha256": v2_cases.payload_sha256(payload),
            "selection_rule": (
                "lexicographically first validation case in each frozen direct-positive "
                "domain/language cell and V2 abstain category/language cell; old "
                "relation_mismatch cells are re-targeted pre-run to the relation actually asked"
            ),
            "cases": EXPECTED_CASES,
            "source_v2_release_labels": 9,
            "source_v2_abstain_labels": 36,
            "target_release_cases": EXPECTED_TARGET_RELEASE_CASES,
            "target_abstain_cases": EXPECTED_TRUE_ABSTAIN_CASES,
            "direct_target_release_cases": EXPECTED_DIRECT_POSITIVE_CASES,
            "relation_comparison_target_release_cases": EXPECTED_RELATION_COMPARISON_CASES,
            "query_text_persisted": False,
            "canonical_memory_value_persisted": False,
        },
        "summary": summary,
        "cases": [_public_case(result) for result in results],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.gemini_rpm <= 0:
        raise ValueError("Gemini RPM must be positive")
    output_path = Path(args.output)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite existing development diagnostic: {output_path}"
        )

    result = asyncio.run(_run(gemini_rpm=float(args.gemini_rpm)))
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
                "promising_for_larger_retired_review": result["summary"][
                    "promising_for_larger_retired_review"
                ],
                "phase45e_authorized": False,
            }
        ),
    )


if __name__ == "__main__":
    main()
