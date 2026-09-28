"""Bounded read-only Phase-10 outcome sources over existing canonical stores."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_registry.compatibility import CapabilityCompatibilityEvaluator
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.engineering_change.models import ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.incidents.store import SqliteIncidentStore
from jarvis.promotion.models import PromotionAttemptState
from jarvis.promotion.store import PromotionStore

from .adapters import (
    CapabilityAcquisitionOutcomeAdapter,
    CapabilityCompatibilityOutcomeAdapter,
    EngineeringOutcomeAdapterError,
    PromotionOutcomeAdapter,
    RepairOutcomeAdapter,
)
from .models import EngineeringOutcomeV1


@dataclass(frozen=True, slots=True)
class EngineeringOutcomeSourceScan:
    source_id: str
    outcomes: tuple[EngineeringOutcomeV1, ...]
    errors: tuple[str, ...]


class EngineeringOutcomeSource(Protocol):
    source_id: str

    def scan(
        self,
        *,
        limit: int,
        observed_at_epoch: float,
    ) -> EngineeringOutcomeSourceScan: ...


def _limit(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("outcome source scan limit must be positive")
    return value


class PromotionOutcomeSource:
    source_id = "promotion"

    def __init__(self, store: PromotionStore) -> None:
        if not isinstance(store, PromotionStore):
            raise TypeError("store must be PromotionStore")
        self._store = store
        self._adapter = PromotionOutcomeAdapter(store.changes)

    def scan(
        self,
        *,
        limit: int,
        observed_at_epoch: float,
    ) -> EngineeringOutcomeSourceScan:
        del observed_at_epoch
        attempts = self._store.list_by_states(
            (
                PromotionAttemptState.COMPLETED,
                PromotionAttemptState.ROLLED_BACK,
                PromotionAttemptState.FAILED,
                PromotionAttemptState.BLOCKED,
                PromotionAttemptState.STALE,
            ),
            limit=_limit(limit),
        )
        outcomes: list[EngineeringOutcomeV1] = []
        errors: list[str] = []
        for attempt in attempts:
            try:
                outcomes.append(self._adapter.normalize(attempt))
            except EngineeringOutcomeAdapterError as exc:
                errors.append(f"{attempt.attempt_id}:{exc}")
        return EngineeringOutcomeSourceScan(
            source_id=self.source_id,
            outcomes=tuple(outcomes),
            errors=tuple(errors),
        )


class RepairOutcomeSource:
    source_id = "repair"

    def __init__(self, store: SqliteIncidentStore) -> None:
        if not isinstance(store, SqliteIncidentStore):
            raise TypeError("store must be SqliteIncidentStore")
        self._store = store
        self._adapter = RepairOutcomeAdapter()

    def scan(
        self,
        *,
        limit: int,
        observed_at_epoch: float,
    ) -> EngineeringOutcomeSourceScan:
        del observed_at_epoch
        attempts = self._store.list_terminal_repair_attempts(limit=_limit(limit))
        outcomes: list[EngineeringOutcomeV1] = []
        errors: list[str] = []
        for attempt in attempts:
            try:
                outcomes.append(self._adapter.normalize(attempt))
            except EngineeringOutcomeAdapterError as exc:
                errors.append(f"{attempt.attempt_id}:{exc}")
        return EngineeringOutcomeSourceScan(
            source_id=self.source_id,
            outcomes=tuple(outcomes),
            errors=tuple(errors),
        )


class CapabilityAcquisitionOutcomeSource:
    source_id = "capability_acquisition"

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        self._store = store
        self._adapter = CapabilityAcquisitionOutcomeAdapter(store)

    def scan(
        self,
        *,
        limit: int,
        observed_at_epoch: float,
    ) -> EngineeringOutcomeSourceScan:
        del observed_at_epoch
        changes = self._store.list_by_states(
            (
                ChangeState.CLOSED,
                ChangeState.ROLLED_BACK,
                ChangeState.FAILED,
                ChangeState.BLOCKED_EXTERNAL,
                ChangeState.REJECTED,
            ),
            process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
            limit=_limit(limit),
        )
        outcomes: list[EngineeringOutcomeV1] = []
        errors: list[str] = []
        for change in changes:
            try:
                outcomes.append(self._adapter.normalize(change))
            except EngineeringOutcomeAdapterError as exc:
                errors.append(f"{change.change_id}:{exc}")
        return EngineeringOutcomeSourceScan(
            source_id=self.source_id,
            outcomes=tuple(outcomes),
            errors=tuple(errors),
        )


class CapabilityCompatibilityOutcomeSource:
    source_id = "capability_compatibility"

    def __init__(
        self,
        store: CapabilityRegistryStore,
        evaluator: CapabilityCompatibilityEvaluator,
    ) -> None:
        if not isinstance(store, CapabilityRegistryStore):
            raise TypeError("store must be CapabilityRegistryStore")
        if not isinstance(evaluator, CapabilityCompatibilityEvaluator):
            raise TypeError("evaluator must be CapabilityCompatibilityEvaluator")
        self._store = store
        self._evaluator = evaluator
        self._adapter = CapabilityCompatibilityOutcomeAdapter()

    def scan(
        self,
        *,
        limit: int,
        observed_at_epoch: float,
    ) -> EngineeringOutcomeSourceScan:
        bounded = _limit(limit)
        outcomes: list[EngineeringOutcomeV1] = []
        errors: list[str] = []
        selected = tuple(
            state for state in self._store.list_registry() if state.has_selection
        )[:bounded]
        for state in selected:
            package = self._store.get_package(
                state.selected_package_id or "",
                state.selected_package_version or "",
            )
            if package is None:
                errors.append(f"{state.capability_id}:selected_package_missing")
                continue
            try:
                report = self._evaluator.evaluate(package)
                outcomes.append(
                    self._adapter.normalize(
                        report,
                        observed_at_epoch=observed_at_epoch,
                    )
                )
            except (EngineeringOutcomeAdapterError, ValueError) as exc:
                errors.append(f"{state.capability_id}:{exc}")
        return EngineeringOutcomeSourceScan(
            source_id=self.source_id,
            outcomes=tuple(outcomes),
            errors=tuple(errors),
        )
