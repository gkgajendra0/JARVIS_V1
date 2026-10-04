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
from jarvis.chatgpt_plan import (
    CHATGPT_PLAN_PROVIDER_ID,
    CHATGPT_PLAN_RESOURCE,
    CHATGPT_PLAN_TARGET_ID,
)
from jarvis.model_routing.eligibility import (
    EligibilityPolicy,
    EligibilityRuntimeState,
    NoEligibleTargets,
)
from jarvis.model_routing.models import (
    BenchmarkStatus,
    CostProfile,
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
from jarvis.work.context import WorkContextMode

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
    pack = request.context_pack
    use_pack = request.context_mode is WorkContextMode.APPLY and pack is not None
    steps = (
        pack.recent_steps_payload()
        if use_pack
        else [
            {
                "kind": step.kind,
                "summary": step.summary,
                "input": step.input_data,
                "observation": step.observation,
                "error": step.error,
            }
            for step in request.recent_steps
        ]
    )
    evidence = list(pack.evidence) if use_pack else list(request.evidence)
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
        "steps": steps,
        "evidence": evidence,
    }
    if use_pack:
        payload["history_manifest"] = pack.history_manifest_payload()
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    )
    return max(1, (len(encoded) + 3) // 4)


def _evidence_size_class(request: BrainRequest) -> EvidenceSizeClass:
    evidence_count = (
        len(request.context_pack.evidence)
        if request.context_mode is WorkContextMode.APPLY
        and request.context_pack is not None
        else len(request.evidence)
    )
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
    if primary == CHATGPT_PLAN_TARGET_ID:
        cycle_key = _digest_id(
            "reasoning_plan",
            f"{cycle_key}|{CHATGPT_PLAN_TARGET_ID}",
        )
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


def _paid_work_target(
    provider: str,
    *,
    configured_model: str | None,
) -> ModelTarget:
    model = resolve_ai_role_model(
        provider,
        "work_orchestration",
        configured_model=configured_model,
    )
    return ModelTarget(
        target_id=f"work.{provider}.default",
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


def build_default_work_targets(
    *,
    configured_provider: str,
    configured_model: str | None,
    adapter_registry: ModelAdapterRegistry,
    chatgpt_plan_enabled: bool = False,
    chatgpt_plan_model: str | None = None,
    chatgpt_plan_available_models: tuple[str, ...] = (),
    paid_fallback_enabled: bool = False,
) -> DefaultWorkTargets:
    """Build the approved Work pool.

    Legacy mode is byte-for-byte compatible with the Phase-4 two-provider pool.
    When ChatGPT-plan usage is explicitly enabled, the subscription-backed target
    becomes primary. A configured paid provider is included only when the owner has
    explicitly enabled paid fallback. The C5 Ollama target intentionally remains
    outside this durable pool.
    """

    primary_provider = normalize_ai_provider(configured_provider)
    if not chatgpt_plan_enabled:
        targets = tuple(
            _paid_work_target(provider, configured_model=configured_model)
            for provider in _WORK_ROUTING_PROVIDERS
        )
        return DefaultWorkTargets(
            registry=ModelTargetRegistry(adapter_registry, targets),
            primary_target_id=f"work.{primary_provider}.default",
        )

    plan_model = str(chatgpt_plan_model or "").strip()
    if not plan_model:
        raise ValueError(
            "chatgpt_plan_model is required when ChatGPT-plan routing is enabled"
        )

    available = {
        str(model).strip().casefold()
        for model in chatgpt_plan_available_models
        if str(model).strip()
    }

    def _first_available(*models: str) -> str | None:
        if not available:
            return None
        for candidate in models:
            if candidate.casefold() in available:
                return candidate
        return None

    # Prefer the cheapest sufficient subscription-backed models when the
    # connected account exposes them. If catalog discovery is unavailable we
    # preserve the previously configured single-model behavior rather than
    # guessing model access.
    efficient_model = _first_available("gpt-6-luna", "gpt-5.6-luna")
    capable_model = _first_available(
        "gpt-6.1-sol",
        "gpt-6-sol",
        "gpt-5.6-sol",
    )
    frontier_model = _first_available("gpt-6-astra")

    def _plan_target(
        *,
        target_id: str,
        model_id: str,
        roles: tuple[str, ...],
    ) -> ModelTarget:
        return ModelTarget(
            target_id=target_id,
            adapter_id=CHATGPT_PLAN_PROVIDER_ID,
            provider_id=CHATGPT_PLAN_PROVIDER_ID,
            model_id=model_id,
            locality=ModelLocality.CLOUD,
            capabilities=(
                "engineering_reasoning",
                "structured_output",
            ),
            roles=roles,
            max_context_tokens=_WORK_CONTEXT_BUDGET_TOKENS,
            supports_structured_output=True,
            supports_tools=False,
            supports_streaming=True,
            latency_class="standard",
            benchmark_status=BenchmarkStatus.ACCEPTED,
            registry_version=1,
            endpoint_ref=CHATGPT_PLAN_RESOURCE,
            credential_ref=None,
            cost_profile=CostProfile(
                profile_id="chatgpt-plan-subscription-2026-10",
                version=1,
                effective_from_epoch=0.0,
                input_usd_per_million_tokens=0.0,
                output_usd_per_million_tokens=0.0,
            ),
            enabled=True,
        )

    plan_targets: list[ModelTarget] = []
    primary_target_id = CHATGPT_PLAN_TARGET_ID

    if efficient_model is not None:
        plan_targets.append(
            _plan_target(
                target_id=CHATGPT_PLAN_TARGET_ID,
                model_id=efficient_model,
                roles=("efficient",),
            )
        )
    if capable_model is not None and capable_model != efficient_model:
        capable_target_id = f"{CHATGPT_PLAN_TARGET_ID}.capable"
        if not plan_targets:
            primary_target_id = capable_target_id
        plan_targets.append(
            _plan_target(
                target_id=capable_target_id,
                model_id=capable_model,
                roles=("capable",),
            )
        )
    if frontier_model is not None and frontier_model not in {
        efficient_model,
        capable_model,
    }:
        frontier_target_id = f"{CHATGPT_PLAN_TARGET_ID}.frontier"
        if not plan_targets:
            primary_target_id = frontier_target_id
        plan_targets.append(
            _plan_target(
                target_id=frontier_target_id,
                model_id=frontier_model,
                roles=("frontier",),
            )
        )

    if not plan_targets:
        plan_targets.append(
            _plan_target(
                target_id=CHATGPT_PLAN_TARGET_ID,
                model_id=plan_model,
                roles=("efficient", "capable"),
            )
        )
        primary_target_id = CHATGPT_PLAN_TARGET_ID

    targets: tuple[ModelTarget, ...] = tuple(plan_targets)
    if paid_fallback_enabled:
        paid_fallback = _paid_work_target(
            primary_provider,
            configured_model=configured_model,
        )
        targets = (*targets, paid_fallback)
    return DefaultWorkTargets(
        registry=ModelTargetRegistry(adapter_registry, targets),
        primary_target_id=primary_target_id,
    )


class RoutingUnavailableError(RuntimeError):
    def __init__(self, snapshot: EligibilitySnapshot) -> None:
        super().__init__("no eligible model target is available")
        self.snapshot = snapshot


class RoutingProvenanceError(RuntimeError):
    pass


class RoutingResourceBlocked(RuntimeError):
    """All approved targets for one durable routing lineage are unavailable."""

    def __init__(
        self,
        *,
        reason: str,
        decision_id: str | None = None,
        routing_request_id: str | None = None,
        retry_after_seconds: float = 30.0,
    ) -> None:
        normalized_decision = str(decision_id or "").strip() or None
        normalized_request = str(routing_request_id or "").strip() or None
        normalized_reason = str(reason).strip()
        if normalized_decision is None and normalized_request is None:
            raise ValueError("routing blocker requires decision or request lineage")
        if not normalized_reason:
            raise ValueError("routing blocker requires reason")
        if retry_after_seconds <= 0:
            raise ValueError("routing blocker retry delay must be positive")
        super().__init__(normalized_reason)
        self.decision_id = normalized_decision
        self.routing_request_id = normalized_request
        self.reason = normalized_reason
        self.retry_after_seconds = float(retry_after_seconds)
        lineage = normalized_decision or normalized_request
        self.blocker_key = f"routing-resource:{lineage}"


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
            # Expiry only makes the target eligible for one probe. It must not
            # erase the failure streak: only a successful provider invocation may
            # reset consecutive_failures via _mark_target_recovered().
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
        if persisted.eligibility.policy_digest != self.eligibility_policy.policy_digest:
            raise RoutingProvenanceError(
                "persisted routing decision policy digest does not match"
            )
        target = self.target_registry.require(persisted.decision.selected_target_id)
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
            target=self.target_registry.require(persisted.decision.selected_target_id),
            eligibility=persisted.eligibility,
            reused_decision=False,
        )
