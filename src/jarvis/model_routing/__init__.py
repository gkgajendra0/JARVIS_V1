"""Provider/model-neutral routing substrate for JARVIS background engineering work.

The package facade is intentionally lazy. Routing submodules depend on canonical work
models, while the work engine consumes routing blockers. Eagerly importing the whole
graph here makes otherwise valid leaf imports depend on import order.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "EligibilityPolicy": "jarvis.model_routing.eligibility",
    "EligibilityReason": "jarvis.model_routing.eligibility",
    "EligibilityResult": "jarvis.model_routing.eligibility",
    "EligibilityRuntimeState": "jarvis.model_routing.eligibility",
    "EligibleTargets": "jarvis.model_routing.eligibility",
    "IneligibleStrategyTargetError": "jarvis.model_routing.eligibility",
    "NoEligibleTargets": "jarvis.model_routing.eligibility",
    "TargetHealthEligibility": "jarvis.model_routing.eligibility",
    "BenchmarkBaseline": "jarvis.model_routing.evaluation",
    "RoutingBenchmarkCase": "jarvis.model_routing.evaluation",
    "RoutingCaseEvaluation": "jarvis.model_routing.evaluation",
    "RoutingEvaluationConfig": "jarvis.model_routing.evaluation",
    "RoutingEvaluationMetrics": "jarvis.model_routing.evaluation",
    "RoutingEvaluationReport": "jarvis.model_routing.evaluation",
    "TargetReplayObservation": "jarvis.model_routing.evaluation",
    "benchmark_fixture_digest": "jarvis.model_routing.evaluation",
    "evaluate_routing_replay": "jarvis.model_routing.evaluation",
    "load_routing_benchmark_fixture": "jarvis.model_routing.evaluation",
    "HealthAction": "jarvis.model_routing.health",
    "HealthMutation": "jarvis.model_routing.health",
    "TargetHealthRecord": "jarvis.model_routing.health",
    "apply_provider_failure": "jarvis.model_routing.health",
    "ModelInvocationContext": "jarvis.model_routing.invoker",
    "ModelInvoker": "jarvis.model_routing.invoker",
    "StructuredOutputModelAdapter": "jarvis.model_routing.invoker",
    "build_default_model_adapter_registry": "jarvis.model_routing.invoker",
    "BenchmarkStatus": "jarvis.model_routing.models",
    "CostProfile": "jarvis.model_routing.models",
    "EligibilitySnapshot": "jarvis.model_routing.models",
    "EvidenceSizeClass": "jarvis.model_routing.models",
    "LocalityRequirement": "jarvis.model_routing.models",
    "ModelLocality": "jarvis.model_routing.models",
    "ModelTarget": "jarvis.model_routing.models",
    "PrivacyClass": "jarvis.model_routing.models",
    "ResponseContractResult": "jarvis.model_routing.models",
    "RoutingAttempt": "jarvis.model_routing.models",
    "RoutingAttemptKind": "jarvis.model_routing.models",
    "RoutingDecision": "jarvis.model_routing.models",
    "RoutingOutcome": "jarvis.model_routing.models",
    "RoutingRequest": "jarvis.model_routing.models",
    "RoutingStrategyResult": "jarvis.model_routing.models",
    "TargetExclusion": "jarvis.model_routing.models",
    "DuplicateRegistrationError": "jarvis.model_routing.registry",
    "ModelAdapter": "jarvis.model_routing.registry",
    "ModelAdapterRegistry": "jarvis.model_routing.registry",
    "ModelTargetRegistry": "jarvis.model_routing.registry",
    "RoutingRegistryError": "jarvis.model_routing.registry",
    "RoutingStrategy": "jarvis.model_routing.registry",
    "RoutingStrategyRegistry": "jarvis.model_routing.registry",
    "UnknownModelAdapterError": "jarvis.model_routing.registry",
    "UnknownModelTargetError": "jarvis.model_routing.registry",
    "UnknownRoutingStrategyError": "jarvis.model_routing.registry",
    "DefaultWorkTargets": "jarvis.model_routing.router",
    "ModelRouter": "jarvis.model_routing.router",
    "RoutedSelection": "jarvis.model_routing.router",
    "RoutingProvenanceError": "jarvis.model_routing.router",
    "RoutingResourceBlocked": "jarvis.model_routing.router",
    "RoutingUnavailableError": "jarvis.model_routing.router",
    "build_default_work_targets": "jarvis.model_routing.router",
    "build_work_routing_request": "jarvis.model_routing.router",
    "reasoning_cycle_key": "jarvis.model_routing.router",
    "RoutingStatus": "jarvis.model_routing.status",
    "RoutingStatusReader": "jarvis.model_routing.status",
    "VerificationStatus": "jarvis.model_routing.status",
    "ModelRoutingStore": "jarvis.model_routing.store",
    "PersistedRoutingDecision": "jarvis.model_routing.store",
    "RoutingStoreError": "jarvis.model_routing.store",
    "EngineeringStageStrategy": "jarvis.model_routing.strategy",
    "StageRoutingSignals": "jarvis.model_routing.strategy",
    "StrategyNoCandidateError": "jarvis.model_routing.strategy",
    "derive_work_step_signals": "jarvis.model_routing.strategy",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_path), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *_EXPORTS))
