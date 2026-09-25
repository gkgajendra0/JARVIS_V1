"""Deterministic route selection for bounded background work reasoning."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.ai_provider import (
    credential_environment_name,
    normalize_ai_provider,
    provider_api_key,
    resolve_ai_role_model,
)
from jarvis.model_routing.eligibility import (
    EligibilityPolicy,
    EligibilityRuntimeState,
    NoEligibleTargets,
)
from jarvis.model_routing.models import (
    BenchmarkStatus,
    EligibilitySnapshot,
    EvidenceSizeClass,
    LocalityRequirement,
    ModelLocality,
    ModelTarget,
    PrivacyClass,
    RoutingDecision,
    RoutingRequest,
)
from jarvis.model_routing.registry import (
    ModelAdapterRegistry,
    ModelTargetRegistry,
    RoutingStrategyRegistry,
)
from jarvis.model_routing.store import (
    ModelRoutingStore,
    PersistedRoutingDecision,
    RoutingStoreError,
)
from jarvis.model_routing.strategy import derive_work_step_signals
from jarvis.work.brain import BrainRequest

_WORK_ROUTING_PROVIDERS = ("gemini", "openai")
_WORK_CONTEXT_BUDGET_TOKENS = 32_000


def _digest_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _sha256(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


def reasoning_cycle_key(request: BrainRequest) -> str:
    """Stable key for one canonical WorkReasoner cycle and its DBOS retries."""

    if not isinstance(request, BrainRequest):
        raise TypeError("request must be a BrainRequest")
    last_step_id = request.recent_steps[-1].step_id if request.recent_steps else None
    payload = {
        "work_id": request.work.work_id,
        "work_version": request.work.version,
        "work_state": request.work.state.value,
        "current_step_id": request.work.current_step_id,
        "last_step_id": last_step_id,
        "purpose": request.purpose,
        "allowed_actions": sorted(action.name for action in request.allowed_actions),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return _digest_id("reasoning", encoded)


def _estimated_context_tokens(request: BrainRequest) -> int:
    payload = {
        "request": request.work.request,
        "purpose": request.purpose,
        "actions": [
            {
                "name": action.name,
                "description": action.description,
                "parameter_schema": action.parameter_schema,
            }
            for action in request.allowed_actions
        ],
        "steps": [
            {
                "kind": step.kind,
                "summary": step.summary,
                "input": step.input_data,
                "observation": step.observation,
                "error": step.error,
            }
            for step in request.recent_steps
        ],
        "evidence": list(request.evidence),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return max(1, (len(encoded) + 3) // 4)


def _evidence_size_class(request: BrainRequest) -> EvidenceSizeClass:
    evidence_count = len(request.evidence)
    if evidence_count >= 6:
        return EvidenceSizeClass.HETEROGENEOUS
    estimated = _estimated_context_tokens(request)
    if estimated >= 16_000:
        return EvidenceSizeClass.LARGE
    if estimated >= 4_000:
        return EvidenceSizeClass.MEDIUM
    return EvidenceSizeClass.SMALL


def build_work_routing_request(
    request: BrainRequest,
    *,
    primary_target_id: str,
) -> RoutingRequest:
    """Project one BrainRequest into bounded, non-prompt routing metadata."""

    if not isinstance(request, BrainRequest):
        raise TypeError("request must be a BrainRequest")
    primary = str(primary_target_id).strip().casefold()
    if not primary:
        raise ValueError("primary_target_id must not be empty")

    signals = derive_work_step_signals(request.recent_steps)
    cycle_key = reasoning_cycle_key(request)
    features = dict(signals.routing_features)
    features["affinity_target_id"] = primary

    return RoutingRequest(
        routing_request_id=cycle_key,
        work_id=request.work.work_id,
        task_kind=request.work.work_type.value,
        strategy_key="engineering_stage",
        strategy_version=1,
        required_capabilities=(
            "engineering_reasoning",
            "structured_output",
        ),
        privacy_class=PrivacyClass.STANDARD,
        locality_requirement=LocalityRequirement.ANY,
        estimated_context_tokens=_estimated_context_tokens(request),
        evidence_size_class=_evidence_size_class(request),
        recent_progress_signals=signals.progress_signals,
        recent_failure_signals=signals.failure_signals,
        latency_preference="balanced",
        cost_preference="balanced",
        stage_key=request.work.work_type.value,
        affinity_key=f"work:{request.work.work_id}",
        routing_features=features,
    )


@dataclass(frozen=True, slots=True)
class DefaultWorkTargets:
    registry: ModelTargetRegistry
    primary_target_id: str


def build_default_work_targets(
    *,
    configured_provider: str,
    configured_model: str | None,
    adapter_registry: ModelAdapterRegistry,
) -> DefaultWorkTargets:
    """Build the small approved target pool using existing provider support."""

    primary_provider = normalize_ai_provider(configured_provider)
    targets: list[ModelTarget] = []
    primary_target_id = ""
    for provider in _WORK_ROUTING_PROVIDERS:
        model = resolve_ai_role_model(
            provider,
            "work_orchestration",
            configured_model=configured_model,
        )
        target_id = f"work.{provider}.default"
        if provider == primary_provider:
            primary_target_id = target_id
        targets.append(
            ModelTarget(
                target_id=target_id,
                adapter_id=provider,
                provider_id=provider,
                model_id=model,
                locality=ModelLocality.CLOUD,
                capabilities=(
                    "engineering_reasoning",
                    "structured_output",
                ),
                roles=("efficient", "capable"),
                max_context_tokens=_WORK_CONTEXT_BUDGET_TOKENS,
                supports_structured_output=True,
                supports_tools=False,
                supports_streaming=False,
                latency_class="standard",
                benchmark_status=BenchmarkStatus.ACCEPTED,
                registry_version=1,
                credential_ref=credential_environment_name(provider),
                enabled=True,
            )
        )
    if not primary_target_id:
        raise AssertionError("configured work provider did not produce a primary target")
    return DefaultWorkTargets(
        registry=ModelTargetRegistry(adapter_registry, tuple(targets)),
        primary_target_id=primary_target_id,
    )


class RoutingUnavailableError(RuntimeError):
    def __init__(self, snapshot: EligibilitySnapshot) -> None:
        super().__init__("no eligible model target is available")
        self.snapshot = snapshot


class RoutingProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RoutedSelection:
    request: RoutingRequest
    decision: RoutingDecision
    target: ModelTarget
    eligibility: EligibilitySnapshot
    reused_decision: bool = False


CredentialAvailability = Callable[[ModelTarget], bool]


def _default_credential_availability(target: ModelTarget) -> bool:
    if target.credential_ref is None:
        return True
    try:
        return provider_api_key(target.provider_id) is not None
    except (KeyError, TypeError, ValueError):
        return False


class ModelRouter:
    """Eligibility + strategy + durable decision persistence; never invokes models."""

    def __init__(
        self,
        *,
        target_registry: ModelTargetRegistry,
        adapter_registry: ModelAdapterRegistry,
        strategy_registry: RoutingStrategyRegistry,
        routing_store: ModelRoutingStore,
        eligibility_policy: EligibilityPolicy | None = None,
        credential_available: CredentialAvailability = _default_credential_availability,
        clock: Callable[[], float] = time.time,
        fallback_budget: int = 1,
    ) -> None:
        if fallback_budget < 0:
            raise ValueError("fallback_budget must not be negative")
        self.target_registry = target_registry
        self.adapter_registry = adapter_registry
        self.strategy_registry = strategy_registry
        self.routing_store = routing_store
        self.eligibility_policy = eligibility_policy or EligibilityPolicy()
        self._credential_available = credential_available
        self._clock = clock
        self._fallback_budget = fallback_budget

    def _runtime_state(self, *, now_epoch: float) -> EligibilityRuntimeState:
        credentials: dict[str, bool] = {}
        health = {}
        versions: dict[str, int] = {}

        for target in self.target_registry.all():
            credentials[target.target_id] = bool(self._credential_available(target))
            record = self.routing_store.get_health(target.target_id)
            if record is None:
                continue
            effective = record.effective_state(now_epoch=now_epoch)
            if effective is not record.state:
                recovered = record.recovered(now_epoch=now_epoch)
                try:
                    self.routing_store.save_health(
                        recovered,
                        expected_version=record.version,
                    )
                    record = recovered
                except RoutingStoreError:
                    refreshed = self.routing_store.get_health(target.target_id)
                    if refreshed is not None:
                        record = refreshed
                        effective = record.effective_state(now_epoch=now_epoch)
            health[target.target_id] = effective
            versions[target.target_id] = record.version

        return EligibilityRuntimeState(
            credential_availability=credentials,
            target_health=health,
            target_health_versions=versions,
        )

    def _reused_selection(
        self,
        request: RoutingRequest,
        persisted: PersistedRoutingDecision,
    ) -> RoutedSelection:
        registry_digest = self.target_registry.digest()
        if persisted.registry_digest != registry_digest:
            raise RoutingProvenanceError(
                "persisted routing decision registry digest does not match"
            )
        if (
            persisted.eligibility.policy_digest
            != self.eligibility_policy.policy_digest
        ):
            raise RoutingProvenanceError(
                "persisted routing decision policy digest does not match"
            )
        target = self.target_registry.require(
            persisted.decision.selected_target_id
        )
        return RoutedSelection(
            request=request,
            decision=persisted.decision,
            target=target,
            eligibility=persisted.eligibility,
            reused_decision=True,
        )

    def route(self, request: RoutingRequest) -> RoutedSelection:
        if not isinstance(request, RoutingRequest):
            raise TypeError("request must be a RoutingRequest")

        persisted = self.routing_store.find_decision_by_request(
            request.routing_request_id
        )
        if persisted is not None:
            return self._reused_selection(request, persisted)

        now = float(self._clock())
        eligibility = self.eligibility_policy.evaluate(
            request=request,
            targets=self.target_registry.all(),
            adapter_registry=self.adapter_registry,
            runtime_state=self._runtime_state(now_epoch=now),
            snapshot_id=_digest_id(
                "eligibility",
                request.routing_request_id,
            ),
        )
        if isinstance(eligibility, NoEligibleTargets):
            raise RoutingUnavailableError(eligibility.snapshot)

        strategy = self.strategy_registry.require(
            request.strategy_key,
            request.strategy_version,
        )
        result = strategy.rank(
            request=request,
            eligible_targets=eligibility.targets,
            history=None,
        )
        self.eligibility_policy.validate_strategy_result(
            eligibility=eligibility,
            strategy_result=result,
        )
        if not result.ordered_target_ids:
            raise RoutingUnavailableError(eligibility.snapshot)

        strategy_digest = _sha256(
            getattr(strategy, "strategy_digest", ""),
            field="strategy_digest",
        )
        decision = RoutingDecision(
            decision_id=_digest_id(
                "decision",
                request.routing_request_id,
            ),
            routing_request_id=request.routing_request_id,
            strategy_key=request.strategy_key,
            strategy_version=request.strategy_version,
            strategy_digest=strategy_digest,
            ordered_target_ids=result.ordered_target_ids,
            selected_target_id=result.ordered_target_ids[0],
            reason_codes=result.reason_codes,
            selected_role=result.selected_role,
            fallback_budget=min(
                self._fallback_budget,
                max(0, len(result.ordered_target_ids) - 1),
            ),
            created_at_epoch=now,
        )
        try:
            persisted = self.routing_store.record_decision(
                request=request,
                eligibility=eligibility.snapshot,
                decision=decision,
                registry_digest=self.target_registry.digest(),
            )
        except RoutingStoreError:
            persisted = self.routing_store.find_decision_by_request(
                request.routing_request_id
            )
            if persisted is None:
                raise
            return self._reused_selection(request, persisted)

        return RoutedSelection(
            request=request,
            decision=persisted.decision,
            target=self.target_registry.require(
                persisted.decision.selected_target_id
            ),
            eligibility=persisted.eligibility,
            reused_decision=False,
        )
