"""Phase-10A autonomous operations control-plane contracts and persistence."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "jarvis.autonomy.models",
        (
            "AUTONOMY_CONTRACT_SCHEMA_VERSION",
            "ActionCandidateV1",
            "ActionKind",
            "AttentionStatus",
            "AutonomyBudgetPolicyV1",
            "AutonomyDispatchLinkV1",
            "AutonomyFindingEventV1",
            "AutonomyFindingV1",
            "AutonomyOutcomeRecordV1",
            "CandidateDisposition",
            "DesiredStateStatus",
            "DesiredStateV1",
            "DispatchIntentV1",
            "FindingStatus",
            "ObjectiveOrigin",
            "ObjectiveStatus",
            "ObjectiveV1",
            "OwnerAttentionEventV1",
            "OwnerAttentionItemV1",
            "ReconcileRunV1",
            "ReconcileStatus",
            "ReconcileTrigger",
            "StabilizationPolicyV1",
            "candidate_id_for",
            "contract_digest",
            "deterministic_id",
            "finding_id_for",
        ),
    ),
    (
        "jarvis.autonomy.mode",
        ("AutonomyMode",),
    ),
    (
        "jarvis.autonomy.attention",
        (
            "AttentionDeliveryAttemptV1",
            "OwnerAttentionAdmissionV1",
            "OwnerAttentionDeliveryAdapter",
            "OwnerAttentionManager",
            "OwnerAttentionTransport",
            "attention_fingerprint_for",
        ),
    ),
    (
        "jarvis.autonomy.budgets",
        (
            "BUDGET_DIMENSION_NEW_WORK",
            "BUDGET_DIMENSION_OWNER_NOTIFICATION",
            "BUDGET_DIMENSION_PROVIDER_MODEL_WORK",
            "BUDGET_DIMENSION_REPEAT_DISPATCH",
            "AutonomyBudgetEvaluator",
            "AutonomyBudgetLedger",
            "AutonomyBudgetWindowV1",
            "BudgetAssessmentV1",
            "BudgetUsageV1",
        ),
    ),
    (
        "jarvis.autonomy.portfolio",
        (
            "PortfolioInputV1",
            "PortfolioPrioritizer",
            "PrioritizedCandidateV1",
            "PriorityFactorsV1",
        ),
    ),
    (
        "jarvis.autonomy.dispatch",
        (
            "AutonomyDispatchConfigV1",
            "AutonomyDispatchResultV1",
            "AutonomyDispatchService",
            "CapabilityReconciliationControllerV1",
            "ChangeCoordinatorDispatchBridge",
            "ControllerDispatchReceiptV1",
            "DispatchBridgeRegistrationV1",
            "DispatchBridgeRegistry",
            "DuplicateDispatchBridgeError",
            "DuplicateExistingControllerError",
            "ExistingController",
            "ExistingControllerRegistry",
            "WorkOrchestratorDispatchBridge",
            "capability_reconciliation_registration",
        ),
    ),
    (
        "jarvis.autonomy.findings",
        (
            "FindingLifecycleManager",
            "FindingLifecycleResultV1",
        ),
    ),
    (
        "jarvis.autonomy.resolution",
        (
            "ActionResolutionResultV1",
            "ActionResolutionService",
            "ActionResolver",
            "ActionResolverRegistry",
            "ActionResponseSpecV1",
            "DuplicateActionResolverError",
            "LeastPowerfulActionResolverV1",
            "UnknownActionResolverError",
            "build_default_action_resolver_registry",
        ),
    ),
    (
        "jarvis.autonomy.rules",
        (
            "CapabilityEffectiveStateRuleV1",
            "ComponentHealthRuleV1",
            "DesiredStateEvaluationStatus",
            "DesiredStateEvaluationV1",
            "DesiredStateEvaluator",
            "DesiredStateRule",
            "DesiredStateRuleRegistry",
            "DesiredStateStabilizer",
            "DuplicateDesiredStateRuleError",
            "DurableWorkRuleV1",
            "ObjectiveCompletionV1",
            "RawDesiredStateEvaluationV1",
            "StabilizationResultV1",
            "StabilizationStateV1",
            "UnknownDesiredStateRuleError",
            "aggregate_objective_completion",
            "build_default_desired_state_rule_registry",
            "dispatch_cooldown_until",
            "within_numeric_tolerance",
        ),
    ),
    (
        "jarvis.autonomy.system_state",
        (
            "SYSTEM_STATE_PRODUCER_VERSION",
            "SYSTEM_STATE_SCHEMA_VERSION",
            "DuplicateSystemStateSourceError",
            "SystemStateAggregator",
            "SystemStateFactV1",
            "SystemStateReadRequestV1",
            "SystemStateSnapshotV1",
            "SystemStateSource",
            "SystemStateSourceErrorV1",
            "SystemStateSourceRegistry",
            "SystemStateSourceResultV1",
            "SystemStateSourceStatus",
            "SystemStateTargetV1",
        ),
    ),
    (
        "jarvis.autonomy.sources",
        (
            "CapabilityStateSource",
            "EngineeringChangeSource",
            "IncidentSource",
            "ModelProviderStateSource",
            "ProductionObservationSource",
            "ResourceStateSource",
            "SelfModelHealthSource",
            "WorkPortfolioSource",
        ),
    ),
    (
        "jarvis.autonomy.store",
        (
            "AUTONOMY_SCHEMA_CHECKSUM",
            "AUTONOMY_SCHEMA_VERSION",
            "AutonomyConflictError",
            "AutonomyIntegrityError",
            "AutonomyStore",
            "AutonomyStoreError",
        ),
    ),
)

_EXPORTS = {
    name: module_name for module_name, names in _EXPORT_GROUPS for name in names
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
