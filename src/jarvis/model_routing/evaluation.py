"""Deterministic replay evaluation for the Phase-4 model router.

This module is intentionally offline. It evaluates frozen benchmark observations and
never invokes providers, mutates routing policy, or learns production preferences.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from jarvis.model_routing.models import ModelTarget, RoutingRequest
from jarvis.model_routing.strategy import EngineeringStageStrategy


def _token(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _sha256(value: object, *, field: str) -> str:
    normalized = _token(value, field=field)
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return normalized


def _non_negative_float(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if normalized < 0:
        raise ValueError(f"{field} must not be negative")
    return normalized


def _non_negative_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(f"{field} must be a JSON array")
    if any(not isinstance(item, str) for item in value):
        raise TypeError(f"{field} must contain only strings")
    return tuple(value)


def _json_object(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be a JSON object")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field} keys must be strings")
    return dict(value)


class BenchmarkBaseline(StrEnum):
    FIXED_CURRENT = "fixed_current"
    ALWAYS_CAPABLE = "always_capable"
    ALWAYS_EFFICIENT = "always_efficient"
    ENGINEERING_STAGE_V1 = "engineering_stage.v1"


@dataclass(frozen=True, slots=True)
class TargetReplayObservation:
    target_id: str
    invocation_succeeded: bool
    structured_output_valid: bool
    verified_success: bool
    verifier_reference: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float
    failure_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_id", _token(self.target_id, field="target_id"))
        for field_name in (
            "invocation_succeeded",
            "structured_output_valid",
            "verified_success",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")
        object.__setattr__(
            self,
            "verifier_reference",
            _required_text(self.verifier_reference, field="verifier_reference"),
        )
        object.__setattr__(
            self,
            "latency_ms",
            _non_negative_float(self.latency_ms, field="latency_ms"),
        )
        object.__setattr__(
            self,
            "input_tokens",
            _non_negative_int(self.input_tokens, field="input_tokens"),
        )
        object.__setattr__(
            self,
            "output_tokens",
            _non_negative_int(self.output_tokens, field="output_tokens"),
        )
        object.__setattr__(
            self,
            "estimated_cost_usd",
            _non_negative_float(
                self.estimated_cost_usd,
                field="estimated_cost_usd",
            ),
        )
        failure = None
        if self.failure_class is not None:
            failure = _token(self.failure_class, field="failure_class")
        if self.invocation_succeeded and failure is not None:
            raise ValueError("successful invocation cannot have a failure_class")
        if not self.invocation_succeeded and failure is None:
            raise ValueError("failed invocation requires a failure_class")
        if not self.invocation_succeeded and self.structured_output_valid:
            raise ValueError("failed invocation cannot have valid structured output")
        object.__setattr__(self, "failure_class", failure)


@dataclass(frozen=True, slots=True)
class RoutingBenchmarkCase:
    case_id: str
    category: str
    expected_role: str
    request: RoutingRequest
    observations: tuple[TargetReplayObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _token(self.case_id, field="case_id"))
        object.__setattr__(self, "category", _token(self.category, field="category"))
        role = _token(self.expected_role, field="expected_role")
        if role not in {"efficient", "capable"}:
            raise ValueError("expected_role must be efficient or capable")
        object.__setattr__(self, "expected_role", role)
        if not isinstance(self.request, RoutingRequest):
            raise TypeError("request must be a RoutingRequest")
        if not self.observations:
            raise ValueError("benchmark case requires target observations")
        target_ids = tuple(item.target_id for item in self.observations)
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("benchmark observations must have unique target IDs")

    def observation_for(self, target_id: str) -> TargetReplayObservation:
        normalized = _token(target_id, field="target_id")
        for observation in self.observations:
            if observation.target_id == normalized:
                return observation
        raise KeyError(f"benchmark case has no observation for target: {normalized}")


@dataclass(frozen=True, slots=True)
class RoutingEvaluationConfig:
    fixture_id: str
    source_revision: str
    registry_digest: str
    current_target_id: str
    capable_target_id: str
    efficient_target_id: str
    engineering_fallback_budget: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fixture_id",
            _token(self.fixture_id, field="fixture_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _required_text(self.source_revision, field="source_revision"),
        )
        object.__setattr__(
            self,
            "registry_digest",
            _sha256(self.registry_digest, field="registry_digest"),
        )
        for field_name in (
            "current_target_id",
            "capable_target_id",
            "efficient_target_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _token(getattr(self, field_name), field=field_name),
            )
        object.__setattr__(
            self,
            "engineering_fallback_budget",
            _non_negative_int(
                self.engineering_fallback_budget,
                field="engineering_fallback_budget",
            ),
        )


@dataclass(frozen=True, slots=True)
class RoutingCaseEvaluation:
    baseline: BenchmarkBaseline
    case_id: str
    category: str
    expected_role: str
    selected_role: str
    ordered_target_ids: tuple[str, ...]
    attempted_target_ids: tuple[str, ...]
    final_target_id: str | None
    verified_success: bool
    structured_output_valid: bool
    fallback_recovered: bool
    wrong_route: bool | None
    unnecessary_escalation: bool
    model_calls: int
    route_churn: int
    total_latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True, slots=True)
class RoutingEvaluationMetrics:
    cases: int
    verified_successes: int
    structured_output_valid_cases: int
    fallback_opportunities: int
    fallback_recoveries: int
    comparable_route_cases: int
    wrong_routes: int
    unnecessary_escalations: int
    model_calls: int
    route_churn: int
    total_latency_ms: float
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    @property
    def verified_success_rate(self) -> float:
        return self.verified_successes / self.cases if self.cases else 0.0

    @property
    def structured_output_valid_rate(self) -> float:
        return self.structured_output_valid_cases / self.cases if self.cases else 0.0

    @property
    def fallback_recovery_rate(self) -> float | None:
        if not self.fallback_opportunities:
            return None
        return self.fallback_recoveries / self.fallback_opportunities

    @property
    def wrong_route_rate(self) -> float | None:
        if not self.comparable_route_cases:
            return None
        return self.wrong_routes / self.comparable_route_cases


@dataclass(frozen=True, slots=True)
class RoutingEvaluationReport:
    fixture_id: str
    fixture_digest: str
    source_revision: str
    registry_digest: str
    strategy_digest: str
    results: tuple[RoutingCaseEvaluation, ...]
    overall: dict[str, RoutingEvaluationMetrics]
    by_category: dict[str, dict[str, RoutingEvaluationMetrics]]


def _observation_payload(observation: TargetReplayObservation) -> dict[str, object]:
    return {
        "target_id": observation.target_id,
        "invocation_succeeded": observation.invocation_succeeded,
        "structured_output_valid": observation.structured_output_valid,
        "verified_success": observation.verified_success,
        "verifier_reference": observation.verifier_reference,
        "latency_ms": observation.latency_ms,
        "input_tokens": observation.input_tokens,
        "output_tokens": observation.output_tokens,
        "estimated_cost_usd": observation.estimated_cost_usd,
        "failure_class": observation.failure_class,
    }


def benchmark_fixture_digest(cases: tuple[RoutingBenchmarkCase, ...]) -> str:
    payload = []
    for case in sorted(cases, key=lambda item: item.case_id):
        request = case.request
        payload.append(
            {
                "case_id": case.case_id,
                "category": case.category,
                "expected_role": case.expected_role,
                "request": {
                    "routing_request_id": request.routing_request_id,
                    "work_id": request.work_id,
                    "task_kind": request.task_kind,
                    "strategy_key": request.strategy_key,
                    "strategy_version": request.strategy_version,
                    "required_capabilities": request.required_capabilities,
                    "privacy_class": request.privacy_class.value,
                    "locality_requirement": request.locality_requirement.value,
                    "estimated_context_tokens": request.estimated_context_tokens,
                    "evidence_size_class": request.evidence_size_class.value,
                    "recent_progress_signals": request.recent_progress_signals,
                    "recent_failure_signals": request.recent_failure_signals,
                    "latency_preference": request.latency_preference,
                    "cost_preference": request.cost_preference,
                    "change_id": request.change_id,
                    "stage_key": request.stage_key,
                    "affinity_key": request.affinity_key,
                    "routing_features": request.routing_features,
                },
                "observations": [
                    _observation_payload(observation)
                    for observation in sorted(
                        case.observations,
                        key=lambda item: item.target_id,
                    )
                ],
            }
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _baseline_route(
    baseline: BenchmarkBaseline,
    *,
    case: RoutingBenchmarkCase,
    targets: tuple[ModelTarget, ...],
    config: RoutingEvaluationConfig,
    strategy: EngineeringStageStrategy,
) -> tuple[str, tuple[str, ...]]:
    if baseline is BenchmarkBaseline.FIXED_CURRENT:
        return "fixed", (config.current_target_id,)
    if baseline is BenchmarkBaseline.ALWAYS_CAPABLE:
        return "capable", (config.capable_target_id,)
    if baseline is BenchmarkBaseline.ALWAYS_EFFICIENT:
        return "efficient", (config.efficient_target_id,)
    result = strategy.rank(
        request=case.request,
        eligible_targets=targets,
        history=None,
    )
    budget = min(
        config.engineering_fallback_budget,
        max(0, len(result.ordered_target_ids) - 1),
    )
    return result.selected_role, result.ordered_target_ids[: 1 + budget]


def _evaluate_case(
    baseline: BenchmarkBaseline,
    *,
    case: RoutingBenchmarkCase,
    targets: tuple[ModelTarget, ...],
    config: RoutingEvaluationConfig,
    strategy: EngineeringStageStrategy,
) -> RoutingCaseEvaluation:
    selected_role, route = _baseline_route(
        baseline,
        case=case,
        targets=targets,
        config=config,
        strategy=strategy,
    )
    if not route:
        raise ValueError("benchmark route cannot be empty")

    attempts: list[TargetReplayObservation] = []
    for target_id in route:
        observation = case.observation_for(target_id)
        attempts.append(observation)
        if observation.invocation_succeeded and observation.structured_output_valid:
            break

    final = attempts[-1]
    fallback_opportunity = bool(
        len(attempts) > 1
        and (
            not attempts[0].invocation_succeeded
            or not attempts[0].structured_output_valid
        )
    )
    fallback_recovered = bool(
        fallback_opportunity
        and final.invocation_succeeded
        and final.structured_output_valid
        and final.verified_success
    )
    wrong_route = (
        None if selected_role == "fixed" else selected_role != case.expected_role
    )
    return RoutingCaseEvaluation(
        baseline=baseline,
        case_id=case.case_id,
        category=case.category,
        expected_role=case.expected_role,
        selected_role=selected_role,
        ordered_target_ids=route,
        attempted_target_ids=tuple(item.target_id for item in attempts),
        final_target_id=final.target_id,
        verified_success=bool(
            final.invocation_succeeded
            and final.structured_output_valid
            and final.verified_success
        ),
        structured_output_valid=bool(
            final.invocation_succeeded and final.structured_output_valid
        ),
        fallback_recovered=fallback_recovered,
        wrong_route=wrong_route,
        unnecessary_escalation=bool(
            selected_role == "capable" and case.expected_role == "efficient"
        ),
        model_calls=len(attempts),
        route_churn=max(0, len(attempts) - 1),
        total_latency_ms=sum(item.latency_ms for item in attempts),
        input_tokens=sum(item.input_tokens for item in attempts),
        output_tokens=sum(item.output_tokens for item in attempts),
        estimated_cost_usd=sum(item.estimated_cost_usd for item in attempts),
    )


def _metrics(results: tuple[RoutingCaseEvaluation, ...]) -> RoutingEvaluationMetrics:
    fallback_opportunities = sum(
        1 for item in results if len(item.attempted_target_ids) > 1
    )
    comparable = sum(1 for item in results if item.wrong_route is not None)
    return RoutingEvaluationMetrics(
        cases=len(results),
        verified_successes=sum(item.verified_success for item in results),
        structured_output_valid_cases=sum(
            item.structured_output_valid for item in results
        ),
        fallback_opportunities=fallback_opportunities,
        fallback_recoveries=sum(item.fallback_recovered for item in results),
        comparable_route_cases=comparable,
        wrong_routes=sum(item.wrong_route is True for item in results),
        unnecessary_escalations=sum(item.unnecessary_escalation for item in results),
        model_calls=sum(item.model_calls for item in results),
        route_churn=sum(item.route_churn for item in results),
        total_latency_ms=sum(item.total_latency_ms for item in results),
        input_tokens=sum(item.input_tokens for item in results),
        output_tokens=sum(item.output_tokens for item in results),
        estimated_cost_usd=sum(item.estimated_cost_usd for item in results),
    )


def evaluate_routing_replay(
    *,
    cases: tuple[RoutingBenchmarkCase, ...],
    targets: tuple[ModelTarget, ...],
    config: RoutingEvaluationConfig,
    strategy: EngineeringStageStrategy | None = None,
) -> RoutingEvaluationReport:
    """Evaluate frozen observations without changing runtime routing policy."""

    if not cases:
        raise ValueError("routing evaluation requires at least one case")
    if not targets:
        raise ValueError("routing evaluation requires at least one target")
    target_ids = {target.target_id for target in targets}
    required_ids = {
        config.current_target_id,
        config.capable_target_id,
        config.efficient_target_id,
    }
    missing = sorted(required_ids - target_ids)
    if missing:
        raise ValueError(
            "evaluation config references unknown target(s): " + ", ".join(missing)
        )

    selected_strategy = strategy or EngineeringStageStrategy()
    if selected_strategy.strategy_key != "engineering_stage":
        raise ValueError("Phase-4 benchmark requires engineering_stage strategy")
    if selected_strategy.strategy_version != 1:
        raise ValueError("Phase-4 benchmark requires engineering_stage.v1")

    results = tuple(
        _evaluate_case(
            baseline,
            case=case,
            targets=targets,
            config=config,
            strategy=selected_strategy,
        )
        for baseline in BenchmarkBaseline
        for case in cases
    )

    overall = {
        baseline.value: _metrics(
            tuple(item for item in results if item.baseline is baseline)
        )
        for baseline in BenchmarkBaseline
    }
    categories = sorted({case.category for case in cases})
    by_category = {
        category: {
            baseline.value: _metrics(
                tuple(
                    item
                    for item in results
                    if item.category == category and item.baseline is baseline
                )
            )
            for baseline in BenchmarkBaseline
        }
        for category in categories
    }
    return RoutingEvaluationReport(
        fixture_id=config.fixture_id,
        fixture_digest=benchmark_fixture_digest(cases),
        source_revision=config.source_revision,
        registry_digest=config.registry_digest,
        strategy_digest=selected_strategy.strategy_digest,
        results=results,
        overall=overall,
        by_category=by_category,
    )


def load_routing_benchmark_fixture(
    path: str | Path,
) -> tuple[str, str, tuple[RoutingBenchmarkCase, ...]]:
    """Load a versioned JSON replay fixture and return ID, source revision and cases."""

    from jarvis.model_routing.models import (
        EvidenceSizeClass,
        LocalityRequirement,
        PrivacyClass,
    )

    fixture_path = Path(path)
    payload: Any = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("routing benchmark fixture must be a JSON object")
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported routing benchmark fixture schema")
    fixture_id = _token(payload.get("fixture_id"), field="fixture_id")
    source_revision = _required_text(
        payload.get("source_revision"),
        field="source_revision",
    )
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("routing benchmark fixture requires cases")

    cases: list[RoutingBenchmarkCase] = []
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict):
            raise TypeError("benchmark case must be an object")
        raw_request = raw_case.get("request")
        raw_observations = raw_case.get("observations")
        if not isinstance(raw_request, dict) or not isinstance(
            raw_observations,
            list,
        ):
            raise TypeError("benchmark case request/observations are invalid")
        request = RoutingRequest(
            routing_request_id=raw_request["routing_request_id"],
            work_id=raw_request["work_id"],
            task_kind=raw_request["task_kind"],
            strategy_key="engineering_stage",
            strategy_version=1,
            required_capabilities=_string_tuple(
                raw_request["required_capabilities"],
                field="required_capabilities",
            ),
            privacy_class=PrivacyClass(raw_request["privacy_class"]),
            locality_requirement=LocalityRequirement(
                raw_request["locality_requirement"]
            ),
            estimated_context_tokens=raw_request["estimated_context_tokens"],
            evidence_size_class=EvidenceSizeClass(raw_request["evidence_size_class"]),
            recent_progress_signals=_string_tuple(
                raw_request.get("recent_progress_signals", []),
                field="recent_progress_signals",
            ),
            recent_failure_signals=_string_tuple(
                raw_request.get("recent_failure_signals", []),
                field="recent_failure_signals",
            ),
            latency_preference=raw_request.get(
                "latency_preference",
                "balanced",
            ),
            cost_preference=raw_request.get("cost_preference", "balanced"),
            change_id=raw_request.get("change_id"),
            stage_key=raw_request.get("stage_key"),
            affinity_key=raw_request.get("affinity_key"),
            routing_features=_json_object(
                raw_request.get("routing_features", {}),
                field="routing_features",
            ),
        )
        observations_list: list[TargetReplayObservation] = []
        for item in raw_observations:
            if not isinstance(item, dict):
                raise TypeError("benchmark observation must be an object")
            observations_list.append(
                TargetReplayObservation(
                    target_id=item["target_id"],
                    invocation_succeeded=item["invocation_succeeded"],
                    structured_output_valid=item["structured_output_valid"],
                    verified_success=item["verified_success"],
                    verifier_reference=item["verifier_reference"],
                    latency_ms=item["latency_ms"],
                    input_tokens=item["input_tokens"],
                    output_tokens=item["output_tokens"],
                    estimated_cost_usd=item["estimated_cost_usd"],
                    failure_class=item.get("failure_class"),
                )
            )
        observations = tuple(observations_list)
        cases.append(
            RoutingBenchmarkCase(
                case_id=raw_case["case_id"],
                category=raw_case["category"],
                expected_role=raw_case["expected_role"],
                request=request,
                observations=observations,
            )
        )

    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("benchmark case IDs must be unique")
    return fixture_id, source_revision, tuple(cases)
