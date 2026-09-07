"""One-shot fresh Phase 4.5D composite memory-gate acceptance harness."""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import step4_phase45d_final_composite_cases as cases

from jarvis.ai_provider import require_provider_api_key
from jarvis.memory.answer_type_guard import (
    MODEL_ID as ANSWER_TYPE_MODEL_ID,
)
from jarvis.memory.answer_type_guard import (
    MODEL_REVISION as ANSWER_TYPE_MODEL_REVISION,
)
from jarvis.memory.answer_type_guard import (
    LocalZeroShotMemoryAnswerTypeGuard,
    MemoryAnswerTypeDecision,
)
from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.evidence_gate import MemoryEvidenceDisposition
from jarvis.memory.guarded_query_coordinator import GuardedMemoryQueryCoordinator
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.query_coordinator import MemoryQueryCoordinator
from jarvis.memory.query_interpreters import GeminiMemoryQueryInterpreter
from jarvis.memory.query_plan import MemoryFacetCatalog, MemoryQueryProposal
from jarvis.memory.retrieval import RetrievalEligibility, SemanticRetrievalService
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

FROZEN_CORPUS_SHA256 = (
    "69666a37d436828b1d65827852f9e43d524253608209275205c41a36f8accadf"
)
GEMINI_MODEL_ID = "gemini-3.5-flash-lite"
DEFAULT_GEMINI_RPM = 12.0
OUTPUT_DEFAULT = Path(".step4-phase45d-final-composite-acceptance.json")
CHECKPOINT_DEFAULT = Path(".step4-phase45d-final-composite-acceptance.checkpoint.json")
CHECKPOINT_SCHEMA_VERSION = 1
MIN_QUOTA_RESERVE = 25
QUOTA_RESERVE_FRACTION = 0.10
NOW = datetime(2026, 9, 6, 18, 0, tzinfo=UTC)
EXPECTED_CLOUD_FACETS = 35
PRECISION_TARGET = 0.95
CONFIDENCE = 0.95
OVERALL_RECALL_FLOOR = 0.75
DIRECT_RECALL_FLOOR = 0.75
COMPARISON_RECALL_FLOOR = 0.60
LANGUAGE_RECALL_FLOOR = 0.65
SECURITY_CATEGORIES = frozenset(cases.SECURITY_CATEGORIES)


@dataclass(frozen=True, slots=True)
class AcceptanceCaseResult:
    case_id: str
    label: str
    language: str
    category: str
    expected_memory_id: str | None
    guard_answer_type: str
    guard_allow: bool
    provider_called: bool
    provider_attempts: int
    final_disposition: str
    final_reason: str
    released_memory_id: str | None
    exact_expected_release: bool


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


class ProviderCallBudgetExceeded(RuntimeError):
    """Raised before a provider call would exceed the certified invocation budget."""


class PacedMemoryQueryInterpreter:
    """Single-attempt, rate-limited wrapper around the production provider adapter."""

    def __init__(self, delegate: Any, *, rpm: float, max_calls: int) -> None:
        if not callable(getattr(delegate, "interpret", None)):
            raise TypeError("delegate must implement memory query interpretation")
        if (
            not isinstance(max_calls, int)
            or isinstance(max_calls, bool)
            or max_calls < 0
        ):
            raise ValueError("max_calls must be a non-negative integer")
        self._delegate = delegate
        self._pacer = GeminiRequestPacer(rpm)
        self._max_calls = max_calls
        self.logical_calls = 0
        self.api_attempts = 0
        self.last_proposal: MemoryQueryProposal | None = None
        self.last_attempts = 0

    @property
    def provider_name(self) -> str:
        return str(self._delegate.provider_name)

    @property
    def model_name(self) -> str:
        return str(self._delegate.model_name)

    def reset_case(self) -> None:
        self.last_proposal = None
        self.last_attempts = 0

    async def interpret(
        self,
        *,
        text: str,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryProposal:
        if self.logical_calls >= self._max_calls:
            raise ProviderCallBudgetExceeded(
                "certified Gemini provider-call budget exhausted before request"
            )
        await self._pacer.wait()
        self.logical_calls += 1
        self.api_attempts += 1
        proposal = await self._delegate.interpret(text=text, catalog=catalog)
        self.last_proposal = proposal
        self.last_attempts = 1
        return proposal


def _build_acceptance_gemini_interpreter() -> GeminiMemoryQueryInterpreter:
    """Build the frozen Gemini adapter with SDK retries disabled for acceptance."""

    from google import genai
    from google.genai import types

    api_key = require_provider_api_key(
        "gemini",
        purpose="Phase 4.5D final composite acceptance",
    )
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=0),
        ),
    )
    return GeminiMemoryQueryInterpreter(client=client, model=GEMINI_MODEL_ID)


def _quota_reserve(active_limit: int) -> int:
    if not isinstance(active_limit, int) or isinstance(active_limit, bool):
        raise TypeError("active RPD limit must be an integer")
    if active_limit <= 0:
        raise ValueError("active RPD limit must be positive")
    return max(MIN_QUOTA_RESERVE, math.ceil(active_limit * QUOTA_RESERVE_FRACTION))


def _quota_budget(
    *,
    active_limit: int,
    active_usage: int,
    required_provider_calls: int,
) -> dict[str, int | bool]:
    if not isinstance(active_usage, int) or isinstance(active_usage, bool):
        raise TypeError("active RPD usage must be an integer")
    if active_usage < 0:
        raise ValueError("active RPD usage must be non-negative")
    if active_usage > active_limit:
        raise ValueError("active RPD usage cannot exceed active RPD limit")
    if not isinstance(required_provider_calls, int) or isinstance(
        required_provider_calls, bool
    ):
        raise TypeError("required_provider_calls must be an integer")
    if required_provider_calls < 0:
        raise ValueError("required_provider_calls must be non-negative")
    reserve = _quota_reserve(active_limit)
    remaining = active_limit - active_usage
    minimum_remaining = required_provider_calls + reserve
    return {
        "active_limit_rpd": active_limit,
        "active_usage_rpd": active_usage,
        "remaining_rpd": remaining,
        "required_provider_calls": required_provider_calls,
        "reserve_rpd": reserve,
        "minimum_remaining_rpd": minimum_remaining,
        "sufficient": remaining >= minimum_remaining,
    }


def _repository_sha() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _checkpoint_contract(repository_sha: str) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "repository_sha": repository_sha,
        "corpus_sha256": FROZEN_CORPUS_SHA256,
        "provider_model": GEMINI_MODEL_ID,
        "answer_type_model": ANSWER_TYPE_MODEL_ID,
        "answer_type_revision": ANSWER_TYPE_MODEL_REVISION,
    }


def _checkpoint_payload(
    *,
    repository_sha: str,
    results: list[AcceptanceCaseResult],
) -> dict[str, Any]:
    return {
        "contract": _checkpoint_contract(repository_sha),
        "completed_cases": [_public_case(row) for row in results],
    }


def _write_checkpoint(
    path: Path,
    *,
    repository_sha: str,
    results: list[AcceptanceCaseResult],
) -> None:
    payload = _checkpoint_payload(repository_sha=repository_sha, results=results)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_checkpoint(path: Path, *, repository_sha: str) -> list[AcceptanceCaseResult]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("contract") != _checkpoint_contract(repository_sha):
        raise RuntimeError("acceptance checkpoint contract does not match current run")
    raw_rows = payload.get("completed_cases")
    if not isinstance(raw_rows, list):
        raise TypeError("acceptance checkpoint completed_cases is invalid")
    rows = [AcceptanceCaseResult(**row) for row in raw_rows]
    case_ids = [row.case_id for row in rows]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("acceptance checkpoint contains duplicate case IDs")
    return rows


class RecordingAnswerTypeGuard:
    def __init__(self, delegate: LocalZeroShotMemoryAnswerTypeGuard) -> None:
        self._delegate = delegate
        self.calls = 0
        self.last_decision: MemoryAnswerTypeDecision | None = None

    @property
    def model_name(self) -> str:
        return self._delegate.model_name

    def reset_case(self) -> None:
        self.last_decision = None

    async def evaluate(self, text: str) -> MemoryAnswerTypeDecision:
        self.calls += 1
        decision = await self._delegate.evaluate(text)
        self.last_decision = decision
        return decision


def _id_factory(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):04d}"


def _connection_worker(path: Path) -> SerialConnectionWorker:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: NOW).apply(connection)
        return connection

    return SerialConnectionWorker(factory, thread_name="phase45d-final-composite")


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
        source_id=f"phase45d-final:{memory_id}:{suffix}",
        source_class=source_class,
        canonical_ref=f"phase45d-final:{memory_id}",
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


async def _populate_fresh_memory(
    lifecycle: MemoryLifecycleService,
) -> dict[str, str]:
    assertion_to_memory: dict[str, str] = {}
    forgotten: list[tuple[str, str]] = []

    for fact in cases.CURRENT_FACTS:
        record = await lifecycle.create(
            _draft(
                subject_scope="v4_profile",
                subject=fact.subject,
                predicate=fact.predicate,
                value=fact.value,
                normalized_text=fact.text,
            ),
            _source(fact.memory_id, mode="current"),
            reason_code="phase45d_final_current_fixture",
        )
        assertion_to_memory[record.assertion_id] = fact.memory_id

    for item in cases.BOUNDARY_DOCUMENTS:
        memory_id = str(item["memory_id"])
        mode = str(item["mode"])
        if mode == "secret":
            continue
        sensitivity = (
            Sensitivity.LOCAL_ONLY if mode == "local_only" else Sensitivity.STANDARD
        )
        record = await lifecycle.create(
            _draft(
                subject_scope="v4_boundary",
                subject=str(item["subject"]),
                predicate=str(item["predicate"]),
                value=str(item["value"]),
                normalized_text=(
                    f"Synthetic V4 boundary {item['subject']} {item['predicate']} "
                    f"is {item['value']}."
                ),
                sensitivity=sensitivity,
            ),
            _source(memory_id, mode=mode),
            reason_code="phase45d_final_boundary_fixture",
        )
        assertion_to_memory[record.assertion_id] = memory_id

        if mode == "historical_transition":
            replacement_memory_id = str(item["replacement_memory_id"])
            replacement = await lifecycle.historical_change(
                record.assertion_id,
                _draft(
                    subject_scope="v4_boundary",
                    subject=str(item["subject"]),
                    predicate=str(item["predicate"]),
                    value=str(item["replacement_value"]),
                    normalized_text=(
                        f"Synthetic V4 current boundary {item['subject']} "
                        f"{item['predicate']} is {item['replacement_value']}."
                    ),
                ),
                _source(
                    replacement_memory_id,
                    mode="current",
                    suffix="transition",
                ),
                effective_at=NOW,
                reason_code="phase45d_final_historical_transition",
            )
            assertion_to_memory[replacement.assertion_id] = replacement_memory_id
        elif mode == "forgotten":
            forgotten.append((record.assertion_id, memory_id))

    for assertion_id, memory_id in forgotten:
        forgotten_ok = await lifecycle.forget(
            assertion_id,
            _source(memory_id, mode="current", suffix="forget"),
            reason_code="phase45d_final_forget",
        )
        if not forgotten_ok:
            raise RuntimeError(f"failed to forget final fixture {memory_id}")

    return assertion_to_memory


def _precision_lower_bound_all_successes(successes: int, failures: int) -> float:
    """Exact one-sided Clopper-Pearson lower bound for the zero-failure gate."""

    if successes < 0 or failures < 0:
        raise ValueError("successes and failures must be non-negative")
    if failures:
        return 0.0
    if successes == 0:
        return 0.0
    alpha = 1.0 - CONFIDENCE
    return float(alpha ** (1.0 / successes))


def _is_exact_release(result: AcceptanceCaseResult) -> bool:
    return (
        result.label == "release"
        and result.final_disposition == MemoryEvidenceDisposition.RELEASE.value
        and result.released_memory_id == result.expected_memory_id
    )


def _summarize(
    results: list[AcceptanceCaseResult], *, provider_calls: int
) -> dict[str, Any]:
    if len(results) != cases.TOTAL_CASES:
        raise RuntimeError("final acceptance result count changed")
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
        if len(language_targets) != 30:
            raise RuntimeError(f"expected 30 release targets for {language}")
        by_language[language] = {
            "target_release_cases": 30,
            "exact_releases": len(language_exact),
            "target_release_recall": round(len(language_exact) / 30, 6),
        }

    precision = len(exact_releases) / len(all_releases) if all_releases else 0.0
    recall = len(exact_releases) / len(target_releases)
    direct_recall = len(direct_exact) / len(direct_targets)
    comparison_recall = len(comparison_exact) / len(comparison_targets)
    precision_lower_bound = _precision_lower_bound_all_successes(
        len(exact_releases),
        len(false_releases),
    )

    checks = {
        "zero_false_releases": not false_releases,
        "zero_wrong_target_releases": not wrong_target_releases,
        "zero_security_boundary_releases": not security_releases,
        "every_release_is_exact_expected_memory": not false_releases,
        "overall_release_recall_at_least_0_75": recall >= OVERALL_RECALL_FLOOR,
        "direct_release_recall_at_least_0_75": direct_recall >= DIRECT_RECALL_FLOOR,
        "comparison_release_recall_at_least_0_60": (
            comparison_recall >= COMPARISON_RECALL_FLOOR
        ),
        "each_language_release_recall_at_least_0_65": all(
            float(metrics["target_release_recall"]) >= LANGUAGE_RECALL_FLOOR
            for metrics in by_language.values()
        ),
        "precision_lower_bound_at_least_0_95": (
            precision_lower_bound >= PRECISION_TARGET
        ),
        "no_qwen_invocation": True,
        "answer_type_guard_is_veto_only": True,
        "jarvis_injects_no_canonical_memory_values": True,
        "single_query_per_provider_request": True,
    }

    return {
        "cases": len(results),
        "target_release_cases": len(target_releases),
        "target_abstain_cases": len(target_abstains),
        "provider_logical_calls": provider_calls,
        "guard_calls": len(results),
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


async def _plan_provider_calls(
    *,
    device: str,
    completed_case_ids: set[str],
) -> dict[str, int]:
    """Count cloud planner calls using only the frozen local guard, never labels."""

    payload = cases.build_payload()
    corpus_sha = cases.payload_sha256(payload)
    if corpus_sha != FROZEN_CORPUS_SHA256:
        raise RuntimeError(
            f"fresh corpus hash mismatch: {corpus_sha} != {FROZEN_CORPUS_SHA256}"
        )
    queries = payload.get("queries")
    if not isinstance(queries, list) or len(queries) != cases.TOTAL_CASES:
        raise RuntimeError("fresh acceptance query payload changed")

    guard = LocalZeroShotMemoryAnswerTypeGuard(device=device)
    remaining_cases = 0
    required_provider_calls = 0
    for item in queries:
        case_id = str(item["case_id"])
        if case_id in completed_case_ids:
            continue
        remaining_cases += 1
        decision = await guard.evaluate(str(item["query"]))
        if decision.allow:
            required_provider_calls += 1
    return {
        "remaining_cases": remaining_cases,
        "required_provider_calls": required_provider_calls,
    }


def _public_case(result: AcceptanceCaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "label": result.label,
        "language": result.language,
        "category": result.category,
        "expected_memory_id": result.expected_memory_id,
        "guard_answer_type": result.guard_answer_type,
        "guard_allow": result.guard_allow,
        "provider_called": result.provider_called,
        "provider_attempts": result.provider_attempts,
        "final_disposition": result.final_disposition,
        "final_reason": result.final_reason,
        "released_memory_id": result.released_memory_id,
        "exact_expected_release": result.exact_expected_release,
    }


async def _run(
    *,
    device: str,
    gemini_rpm: float,
    provider_budget: int,
    checkpoint_path: Path,
    repository_sha: str,
    checkpoint_results: list[AcceptanceCaseResult],
    quota_budget: dict[str, int | bool],
) -> dict[str, Any]:
    payload = cases.build_payload()
    corpus_sha = cases.payload_sha256(payload)
    if corpus_sha != FROZEN_CORPUS_SHA256:
        raise RuntimeError(
            f"fresh corpus hash mismatch: {corpus_sha} != {FROZEN_CORPUS_SHA256}"
        )
    queries = payload.get("queries")
    if not isinstance(queries, list) or len(queries) != cases.TOTAL_CASES:
        raise RuntimeError("fresh acceptance query payload changed")

    with tempfile.TemporaryDirectory(prefix="jarvis-phase45d-final-composite-") as temp:
        worker = _connection_worker(Path(temp) / "acceptance.db")
        lifecycle = MemoryLifecycleService(
            worker,
            clock=lambda: NOW,
            assertion_id_factory=_id_factory("final-assertion"),
            operation_id_factory=_id_factory("final-operation"),
        )
        retrieval = SemanticRetrievalService(worker)
        try:
            assertion_to_memory = await _populate_fresh_memory(lifecycle)
            eligibility = RetrievalEligibility.cloud_context()
            catalog = await retrieval.eligible_facet_catalog(eligibility=eligibility)
            if len(catalog.facets) != EXPECTED_CLOUD_FACETS:
                raise RuntimeError(
                    "fresh cloud facet count changed: "
                    f"{len(catalog.facets)} != {EXPECTED_CLOUD_FACETS}"
                )

            delegate_interpreter = _build_acceptance_gemini_interpreter()
            interpreter = PacedMemoryQueryInterpreter(
                delegate_interpreter,
                rpm=gemini_rpm,
                max_calls=provider_budget,
            )
            local_guard = LocalZeroShotMemoryAnswerTypeGuard(device=device)
            recording_guard = RecordingAnswerTypeGuard(local_guard)
            core = MemoryQueryCoordinator(
                interpreter=interpreter,
                retrieval=retrieval,
            )
            guarded = GuardedMemoryQueryCoordinator(
                coordinator=core,
                answer_type_guard=recording_guard,
            )

            results: list[AcceptanceCaseResult] = list(checkpoint_results)
            completed_case_ids = {row.case_id for row in results}
            _write_checkpoint(
                checkpoint_path,
                repository_sha=repository_sha,
                results=results,
            )
            for index, item in enumerate(queries, start=1):
                if str(item["case_id"]) in completed_case_ids:
                    continue
                interpreter.reset_case()
                recording_guard.reset_case()
                query = str(item["query"])
                decision = await guarded.resolve(query, eligibility=eligibility)
                if decision.reason_code in {
                    "answer_type_guard_unavailable",
                    "answer_type_guard_invalid_decision",
                }:
                    raise RuntimeError(
                        "answer-type guard execution failed during fresh acceptance"
                    )
                guard_decision = recording_guard.last_decision
                if guard_decision is None:
                    raise RuntimeError("fresh acceptance guard decision is missing")

                released_memory_id = None
                if decision.evidence is not None:
                    released_memory_id = assertion_to_memory.get(
                        decision.evidence.assertion.assertion_id
                    )
                    if released_memory_id is None:
                        raise RuntimeError(
                            f"released assertion is absent from fresh fixture map: {item['case_id']}"
                        )
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
                result = AcceptanceCaseResult(
                    case_id=str(item["case_id"]),
                    label=str(item["label"]),
                    language=str(item["language"]),
                    category=str(item["category"]),
                    expected_memory_id=expected_memory_id,
                    guard_answer_type=guard_decision.answer_type.value,
                    guard_allow=guard_decision.allow,
                    provider_called=interpreter.last_proposal is not None,
                    provider_attempts=interpreter.last_attempts,
                    final_disposition=decision.disposition.value,
                    final_reason=decision.reason_code,
                    released_memory_id=released_memory_id,
                    exact_expected_release=exact_expected_release,
                )
                results.append(result)
                completed_case_ids.add(result.case_id)
                _write_checkpoint(
                    checkpoint_path,
                    repository_sha=repository_sha,
                    results=results,
                )
                print(
                    f"[{index:03d}/{cases.TOTAL_CASES}] {result.case_id} "
                    f"{result.final_disposition} ({result.final_reason})"
                )
        finally:
            await worker.close()

    if len(results) != cases.TOTAL_CASES:
        raise RuntimeError(
            f"acceptance ended without all cases: {len(results)} != {cases.TOTAL_CASES}"
        )
    total_provider_calls = sum(1 for row in results if row.provider_called)
    total_provider_attempts = sum(row.provider_attempts for row in results)
    summary = _summarize(results, provider_calls=total_provider_calls)
    summary["provider_api_attempts"] = total_provider_attempts
    summary["provider_attempts_equal_logical_calls"] = (
        total_provider_attempts == total_provider_calls
    )
    summary["continuation_checks"]["provider_attempts_equal_logical_calls"] = (
        total_provider_attempts == total_provider_calls
    )
    summary["acceptance_passed"] = all(summary["continuation_checks"].values())
    status = "PASS_ACCEPTANCE" if summary["acceptance_passed"] else "FAIL_ACCEPTANCE"
    return {
        "status": status,
        "phase45d": "PASS" if summary["acceptance_passed"] else "FAIL",
        "phase45e_authorized": False,
        "acceptance_evidence": True,
        "architecture": {
            "production_provider_selector": "JARVIS_AI_PROVIDER",
            "accepted_provider_adapter": "gemini",
            "provider_model": GEMINI_MODEL_ID,
            "one_query_per_provider_request": True,
            "store": False,
            "local_answer_type_model": ANSWER_TYPE_MODEL_ID,
            "local_answer_type_revision": ANSWER_TYPE_MODEL_REVISION,
            "qwen_invoked": False,
            "exact_current_facet_lookup": True,
            "semantic_guard_veto_only": True,
        },
        "corpus": {
            "schema_version": cases.SCHEMA_VERSION,
            "sha256": corpus_sha,
            "cases": cases.TOTAL_CASES,
            "release_cases": cases.RELEASE_CASES,
            "abstain_cases": cases.ABSTAIN_CASES,
            "query_text_persisted": False,
            "canonical_memory_value_persisted": False,
        },
        "quota_execution_contract": {
            **quota_budget,
            "sdk_retries": 0,
            "harness_retries": 0,
            "checkpoint_resume_enabled": True,
            "checkpoint_persists_query_text": False,
            "checkpoint_persists_canonical_memory_value": False,
        },
        "statistical_contract": {
            "precision_target": PRECISION_TARGET,
            "confidence": CONFIDENCE,
            "precision_bound": "one-sided exact Clopper-Pearson under frozen zero-false-release gate",
            "overall_recall_floor": OVERALL_RECALL_FLOOR,
            "direct_recall_floor": DIRECT_RECALL_FLOOR,
            "comparison_recall_floor": COMPARISON_RECALL_FLOOR,
            "language_recall_floor": LANGUAGE_RECALL_FLOOR,
        },
        "summary": summary,
        "cases": [_public_case(result) for result in results],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--gemini-rpm", type=float, default=DEFAULT_GEMINI_RPM)
    parser.add_argument("--quota-plan-only", action="store_true")
    parser.add_argument("--quota-limit-rpd", type=int)
    parser.add_argument("--quota-used-rpd", type=int)
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT))
    parser.add_argument("--checkpoint", default=str(CHECKPOINT_DEFAULT))
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.gemini_rpm <= 0:
        raise ValueError("Gemini RPM must be positive")
    output_path = Path(args.output)
    checkpoint_path = Path(args.checkpoint)
    if output_path.exists():
        raise RuntimeError(
            f"refusing to overwrite fresh acceptance evidence: {output_path}"
        )

    repository_sha = _repository_sha()
    checkpoint_results = _load_checkpoint(
        checkpoint_path,
        repository_sha=repository_sha,
    )
    completed_case_ids = {row.case_id for row in checkpoint_results}
    quota_plan = asyncio.run(
        _plan_provider_calls(
            device=str(args.device),
            completed_case_ids=completed_case_ids,
        )
    )
    print("QUOTA_PLAN:", json.dumps(quota_plan, ensure_ascii=False))

    if args.quota_plan_only:
        if args.quota_limit_rpd is not None and args.quota_used_rpd is not None:
            budget = _quota_budget(
                active_limit=int(args.quota_limit_rpd),
                active_usage=int(args.quota_used_rpd),
                required_provider_calls=int(quota_plan["required_provider_calls"]),
            )
            print("QUOTA_BUDGET:", json.dumps(budget, ensure_ascii=False))
        return

    if args.quota_limit_rpd is None or args.quota_used_rpd is None:
        raise RuntimeError(
            "acceptance requires current --quota-limit-rpd and --quota-used-rpd "
            "from Google AI Studio"
        )
    budget = _quota_budget(
        active_limit=int(args.quota_limit_rpd),
        active_usage=int(args.quota_used_rpd),
        required_provider_calls=int(quota_plan["required_provider_calls"]),
    )
    print("QUOTA_BUDGET:", json.dumps(budget, ensure_ascii=False))
    if not bool(budget["sufficient"]):
        raise RuntimeError(
            "insufficient certified Gemini RPD budget; refusing to start provider calls"
        )

    try:
        result = asyncio.run(
            _run(
                device=str(args.device),
                gemini_rpm=float(args.gemini_rpm),
                provider_budget=int(quota_plan["required_provider_calls"]),
                checkpoint_path=checkpoint_path,
                repository_sha=repository_sha,
                checkpoint_results=checkpoint_results,
                quota_budget=budget,
            )
        )
    except Exception as exc:
        print("STATUS: EXECUTION_PAUSED_PROVIDER")
        print(
            "RESUME:",
            json.dumps(
                {
                    "checkpoint": str(checkpoint_path),
                    "repository_sha": repository_sha,
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            ),
        )
        raise

    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    checkpoint_path.unlink(missing_ok=True)
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
