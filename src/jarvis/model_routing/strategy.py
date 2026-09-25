"""Deterministic engineering-stage routing strategy for Phase 4."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from jarvis.model_routing.models import (
    EvidenceSizeClass,
    ModelTarget,
    RoutingRequest,
    RoutingStrategyResult,
)
from jarvis.work.models import WorkStep, WorkStepState


class StrategyNoCandidateError(RuntimeError):
    """Raised when eligible targets cannot satisfy the required route profile."""


@dataclass(frozen=True, slots=True)
class StageRoutingSignals:
    progress_signals: tuple[str, ...]
    failure_signals: tuple[str, ...]
    routing_features: dict[str, int | float | bool | str | None]


_PROVIDER_PRESSURE_STEP_KIND = "provider_pressure"
_PROVIDER_PRESSURE_SIGNALS = frozenset(
    {
        "provider_pressure",
        "rate_limited",
        "quota_exhausted",
        "provider_service_unavailable",
        "provider_timeout",
        "provider_connection_lost",
    }
)
_HEALTHY_PROGRESS = frozenset(
    {
        "healthy_progress",
        "verified_progress",
        "plan_settled",
        "architecture_settled",
        "research_complete",
        "deterministic_follow_through",
    }
)
_CAPABLE_FAILURE_SIGNALS = frozenset(
    {
        "quality_failure",
        "structured_output_invalid",
        "failed_hypothesis",
        "stalled_progress",
        "conflicting_evidence",
        "verification_failure",
    }
)
_STRATEGY_RULES = {
    "strategy": "engineering_stage",
    "version": 1,
    "provider_pressure_affects_difficulty": False,
    "capable_failure_threshold": 2,
    "stalled_cycle_threshold": 2,
    "failed_hypothesis_threshold": 2,
    "evidence_capable": ["large", "heterogeneous"],
    "roles": ["efficient", "capable"],
}
_STRATEGY_DIGEST = hashlib.sha256(
    json.dumps(
        _STRATEGY_RULES,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
).hexdigest()


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _feature_int(request: RoutingRequest, key: str) -> int:
    value = request.routing_features.get(key, 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 0


def _feature_text(request: RoutingRequest, key: str) -> str | None:
    value = request.routing_features.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    return normalized or None


def derive_work_step_signals(
    steps: tuple[WorkStep, ...],
    *,
    limit: int = 12,
) -> StageRoutingSignals:
    """Derive bounded routing signals from canonical WorkStep state only."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    progress: list[str] = []
    failures: list[str] = []
    provider_pressure_count = 0
    quality_failure_count = 0
    structured_output_failure_count = 0
    interrupted_count = 0
    completion_guard_block_count = 0

    for step in steps[-limit:]:
        if not isinstance(step, WorkStep):
            raise TypeError("steps must contain WorkStep values")

        kind = step.kind.strip().casefold()
        if kind == _PROVIDER_PRESSURE_STEP_KIND:
            provider_pressure_count += 1
            continue

        if step.state is WorkStepState.COMPLETED:
            if kind == "completion_guard" and step.observation.get("allowed") is False:
                completion_guard_block_count += 1
                failures.append("completion_guard_blocked")
                continue
            if step.observation.get("verified") is True:
                progress.append("verified_progress")
            else:
                progress.append("step_completed")
            continue

        if step.state is WorkStepState.FAILED:
            failures.append("step_failed")
            if any(
                token in kind
                for token in ("test", "verification", "validate", "quality")
            ):
                quality_failure_count += 1
                failures.append("quality_failure")
            if "structured" in kind or "contract" in kind:
                structured_output_failure_count += 1
                failures.append("structured_output_invalid")
            continue

        if step.state is WorkStepState.INTERRUPTED:
            interrupted_count += 1
            failures.append("step_interrupted")

    features: dict[str, int | float | bool | str | None] = {
        "provider_pressure_count": provider_pressure_count,
        "quality_failure_count": quality_failure_count,
        "structured_output_failure_count": structured_output_failure_count,
        "interrupted_count": interrupted_count,
        "completion_guard_block_count": completion_guard_block_count,
    }
    return StageRoutingSignals(
        progress_signals=_ordered_unique(progress),
        failure_signals=_ordered_unique(failures),
        routing_features=features,
    )


class EngineeringStageStrategy:
    """Explainable v1 strategy using stage/progress facts, never provider pressure."""

    strategy_key = "engineering_stage"
    strategy_version = 1
    strategy_digest = _STRATEGY_DIGEST

    def rank(
        self,
        *,
        request: RoutingRequest,
        eligible_targets: tuple[ModelTarget, ...],
        history: object | None = None,
    ) -> RoutingStrategyResult:
        del history
        if not isinstance(request, RoutingRequest):
            raise TypeError("request must be a RoutingRequest")
        if not eligible_targets:
            raise StrategyNoCandidateError("no eligible targets supplied to strategy")
        if any(not isinstance(target, ModelTarget) for target in eligible_targets):
            raise TypeError("eligible_targets must contain ModelTarget values")

        meaningful_failures = tuple(
            signal
            for signal in request.recent_failure_signals
            if signal not in _PROVIDER_PRESSURE_SIGNALS
        )
        progress = set(request.recent_progress_signals)
        healthy_progress = bool(progress.intersection(_HEALTHY_PROGRESS))

        quality_failures = _feature_int(request, "quality_failure_count")
        structured_failures = _feature_int(
            request,
            "structured_output_failure_count",
        )
        failed_hypotheses = _feature_int(request, "failed_hypothesis_count")
        stalled_cycles = _feature_int(request, "stalled_cycle_count")
        conflict_count = _feature_int(request, "conflicting_evidence_count")

        reasons: list[str] = []
        capable_required = False

        if quality_failures >= 2:
            capable_required = True
            reasons.append("repeated_quality_failure")
        if structured_failures >= 2:
            capable_required = True
            reasons.append("repeated_structured_output_failure")
        if failed_hypotheses >= 2:
            capable_required = True
            reasons.append("multiple_failed_hypotheses")
        if stalled_cycles >= 2:
            capable_required = True
            reasons.append("stalled_progress")
        if conflict_count > 0:
            capable_required = True
            reasons.append("conflicting_evidence")
        if set(meaningful_failures).intersection(_CAPABLE_FAILURE_SIGNALS):
            capable_required = True
            reasons.append("quality_or_reasoning_failure")
        if request.evidence_size_class in {
            EvidenceSizeClass.LARGE,
            EvidenceSizeClass.HETEROGENEOUS,
        }:
            capable_required = True
            reasons.append("evidence_complexity")

        diagnostic_unknown = (
            request.task_kind in {"diagnostics", "unknown_diagnostic", "incident"}
            and not healthy_progress
            and "plan_settled" not in progress
        )
        if diagnostic_unknown:
            capable_required = True
            reasons.append("unknown_diagnostic")

        preferred_role = "capable" if capable_required else "efficient"
        if not capable_required:
            if healthy_progress:
                reasons.append("healthy_progress")
            elif progress.intersection({"plan_settled", "architecture_settled"}):
                reasons.append("settled_work")
            else:
                reasons.append("routine_work")

        efficient = sorted(
            (
                target
                for target in eligible_targets
                if "efficient" in target.roles
            ),
            key=lambda target: target.target_id,
        )
        capable = sorted(
            (
                target
                for target in eligible_targets
                if "capable" in target.roles
            ),
            key=lambda target: target.target_id,
        )

        if capable_required:
            candidates = capable
            if not candidates:
                raise StrategyNoCandidateError(
                    "capable route required but no capable target is eligible"
                )
        else:
            candidates = list(efficient)
            seen = {target.target_id for target in candidates}
            candidates.extend(
                target for target in capable if target.target_id not in seen
            )
            if not candidates:
                raise StrategyNoCandidateError(
                    "no efficient or capable target is eligible"
                )
            if not efficient:
                reasons.append("efficient_unavailable_capable_fallback")

        affinity_target_id = _feature_text(request, "affinity_target_id")
        hold_affinity = False
        if request.affinity_key and affinity_target_id is not None:
            for index, target in enumerate(candidates):
                if target.target_id == affinity_target_id:
                    candidates.insert(0, candidates.pop(index))
                    hold_affinity = True
                    reasons.append("affinity_hold")
                    break

        return RoutingStrategyResult(
            ordered_target_ids=tuple(target.target_id for target in candidates),
            reason_codes=_ordered_unique(reasons),
            selected_role=preferred_role,
            hold_affinity=hold_affinity,
            affinity_target_id=(
                affinity_target_id if hold_affinity else None
            ),
        )
