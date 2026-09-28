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
            "AutonomyFindingEventV1",
            "AutonomyFindingV1",
            "AutonomyMode",
            "AutonomyOutcomeRecordV1",
            "CandidateDisposition",
            "DesiredStateStatus",
            "DesiredStateV1",
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
