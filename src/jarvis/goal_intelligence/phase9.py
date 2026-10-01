"""GICC V2 bridge into the existing Phase-9 capability-acquisition lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from jarvis.capability_acquisition.admission import CapabilityAcquisitionAdmission
from jarvis.capability_acquisition.models import OwnerCapabilityGoalV1
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.engineering_change import ChangeArtifact
from jarvis.engineering_substrate.canonical import canonical_digest

from .capability_graph import CapabilityGapAnalysis, CapabilityGraphResolver
from .models import (
    CapabilityGapState,
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    ContinuationState,
    GoalContinuationV1,
    OwnerGoalV2,
)
from .store import GoalStore, GoalStoreConflict, GoalStoreError


class CapabilityCatalogRefresher(Protocol):
    def __call__(self) -> object: ...


class CapabilityAcquisitionAdmitter(Protocol):
    def admit(
        self,
        goal: OwnerCapabilityGoalV1,
        *,
        source_revision: str,
    ) -> CapabilityAcquisitionAdmission: ...


class Phase9ChangeArtifactStore(Protocol):
    def latest_artifact(
        self,
        change_id: str,
        kind: str,
    ) -> ChangeArtifact | None: ...

    def add_artifact(
        self,
        change_id: str,
        *,
        kind: str,
        payload: dict[str, object],
    ) -> ChangeArtifact: ...


@dataclass(frozen=True, slots=True)
class Phase9AcquisitionRequestV2:
    request_id: str
    motivating_goal_id: str
    gap_id: str
    reusable_capability_family: str
    minimum_required_operations: tuple[str, ...]
    target_entity_type: str
    target_entity_id: str | None
    owner_source_session_id: str
    owner_source_turn_id: str
    bridge_source_session_id: str
    bridge_source_turn_id: str
    digest: str

    @classmethod
    def create(
        cls,
        *,
        gap: CapabilityGapV1,
        goal: OwnerGoalV2,
    ) -> Phase9AcquisitionRequestV2:
        if not isinstance(gap, CapabilityGapV1):
            raise TypeError("gap must be CapabilityGapV1")
        if not isinstance(goal, OwnerGoalV2):
            raise TypeError("goal must be OwnerGoalV2")
        if gap.goal_id != goal.goal_id or gap.motivating_goal_id != goal.goal_id:
            raise ValueError("gap does not belong to the motivating owner goal")
        payload = {
            "motivating_goal_id": goal.goal_id,
            "gap_id": gap.gap_id,
            "reusable_capability_family": gap.reusable_capability_family,
            "minimum_required_operations": list(gap.minimum_required_operations),
            "target_entity_type": gap.target_entity_type,
            "target_entity_id": gap.target_entity_id,
            "owner_source_session_id": goal.source_session_id,
            "owner_source_turn_id": goal.source_turn_id,
            "bridge_source_session_id": f"gicc:{goal.goal_id}",
            "bridge_source_turn_id": f"gap:{gap.gap_id}",
        }
        digest = canonical_digest(payload)
        return cls(
            request_id=f"phase9_gicc_{digest[:20]}",
            digest=digest,
            **payload,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "motivating_goal_id": self.motivating_goal_id,
            "gap_id": self.gap_id,
            "reusable_capability_family": self.reusable_capability_family,
            "minimum_required_operations": list(self.minimum_required_operations),
            "target_entity_type": self.target_entity_type,
            "target_entity_id": self.target_entity_id,
            "owner_source_session_id": self.owner_source_session_id,
            "owner_source_turn_id": self.owner_source_turn_id,
            "bridge_source_session_id": self.bridge_source_session_id,
            "bridge_source_turn_id": self.bridge_source_turn_id,
        }

    def __post_init__(self) -> None:
        if self.request_id != f"phase9_gicc_{self.digest[:20]}":
            raise ValueError("request_id must derive from digest")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("Phase9AcquisitionRequestV2 digest mismatch")

    def to_v1(self, *, owner_goal_created_at: str) -> OwnerCapabilityGoalV1:
        created = datetime.fromisoformat(owner_goal_created_at)
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError("owner goal created_at must be timezone-aware")
        hints = [f"entity_type:{self.target_entity_type}"]
        if self.target_entity_id is not None:
            hints.append(f"entity_id:{self.target_entity_id}")
        operation_text = ", ".join(self.minimum_required_operations)
        request = (
            f"Acquire reusable capability {self.reusable_capability_family}; "
            f"minimum operations: {operation_text}; "
            f"target type: {self.target_entity_type}."
        )
        return OwnerCapabilityGoalV1.create(
            request=request,
            requested_capability=self.reusable_capability_family,
            required_operations=self.minimum_required_operations,
            target_hints=tuple(hints),
            source_session_id=self.bridge_source_session_id,
            source_turn_id=self.bridge_source_turn_id,
            now_epoch=created.timestamp(),
        )


@dataclass(frozen=True, slots=True)
class Phase9GapAdmission:
    request: Phase9AcquisitionRequestV2
    phase9_goal: OwnerCapabilityGoalV1
    admission: CapabilityAcquisitionAdmission


@dataclass(frozen=True, slots=True)
class Phase9GapRecheck:
    request: Phase9AcquisitionRequestV2
    analysis: CapabilityGapAnalysis
    gap_satisfied: bool
    continuation: GoalContinuationV1 | None


class Phase9GoalBridge:
    """Translate reusable GICC gaps into the existing governed Phase-9 machinery."""

    def __init__(
        self,
        *,
        coordinator: CapabilityAcquisitionAdmitter,
        change_store: Phase9ChangeArtifactStore,
        goal_store: GoalStore,
        source_revision_provider: Callable[[], str],
    ) -> None:
        if not callable(getattr(coordinator, "admit", None)):
            raise TypeError("coordinator must provide admit()")
        if (
            not callable(getattr(change_store, "latest_artifact", None))
            or not callable(getattr(change_store, "add_artifact", None))
        ):
            raise TypeError("change_store must provide artifact persistence")
        if not isinstance(goal_store, GoalStore):
            raise TypeError("goal_store must be GoalStore")
        if not callable(source_revision_provider):
            raise TypeError("source_revision_provider must be callable")
        self._coordinator = coordinator
        self._changes = change_store
        self._goals = goal_store
        self._source_revision_provider = source_revision_provider

    def admit_gap(
        self,
        gap: CapabilityGapV1,
        goal: OwnerGoalV2,
    ) -> Phase9GapAdmission:
        request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
        phase9_goal = request.to_v1(owner_goal_created_at=goal.created_at)
        admission = self._coordinator.admit(
            phase9_goal,
            source_revision=self._source_revision_provider(),
        )
        if admission.change is not None:
            payload = {
                "schema": "gicc_phase9_gap_link.v1",
                "request_id": request.request_id,
                "request_digest": request.digest,
                "motivating_goal_id": request.motivating_goal_id,
                "gap_id": request.gap_id,
                "reusable_capability_family": request.reusable_capability_family,
                "minimum_required_operations": list(
                    request.minimum_required_operations
                ),
                "target_entity_type": request.target_entity_type,
                "target_entity_id": request.target_entity_id,
                "owner_source_session_id": request.owner_source_session_id,
                "owner_source_turn_id": request.owner_source_turn_id,
            }
            latest = self._changes.latest_artifact(
                admission.change.change_id,
                "gicc_capability_gap_link",
            )
            if latest is None:
                self._changes.add_artifact(
                    admission.change.change_id,
                    kind="gicc_capability_gap_link",
                    payload=payload,
                )
            elif latest.payload != payload:
                raise GoalStoreConflict(
                    "Phase-9 change is already linked to a different GICC gap"
                )
        return Phase9GapAdmission(
            request=request,
            phase9_goal=phase9_goal,
            admission=admission,
        )


class Phase9GoalContinuationVerifier:
    """Resume only after refreshed canonical capability truth satisfies the gap."""

    def __init__(
        self,
        *,
        goal_store: GoalStore,
        graph_resolver: CapabilityGraphResolver,
        context_provider: AcquisitionContextProvider,
        refresh_capability_catalog: CapabilityCatalogRefresher,
    ) -> None:
        if not isinstance(goal_store, GoalStore):
            raise TypeError("goal_store must be GoalStore")
        if not isinstance(graph_resolver, CapabilityGraphResolver):
            raise TypeError("graph_resolver must be CapabilityGraphResolver")
        if not callable(refresh_capability_catalog):
            raise TypeError("refresh_capability_catalog must be callable")
        self._store = goal_store
        self._resolver = graph_resolver
        self._context = context_provider
        self._refresh = refresh_capability_catalog

    def recheck(
        self,
        *,
        request: Phase9AcquisitionRequestV2,
        graph: CapabilityRequirementGraphV1,
        continuation_id: str | None = None,
    ) -> Phase9GapRecheck:
        if request.motivating_goal_id != graph.goal_id:
            raise ValueError("Phase-9 gap request does not belong to requirement graph")
        existing_gap = self._store.get_gap(request.gap_id)
        if existing_gap is None:
            raise GoalStoreError(f"unknown capability gap: {request.gap_id}")
        if (
            existing_gap.goal_id != request.motivating_goal_id
            or existing_gap.reusable_capability_family
            != request.reusable_capability_family
            or existing_gap.minimum_required_operations
            != request.minimum_required_operations
        ):
            raise GoalStoreConflict("Phase-9 completion does not match exact GICC gap")

        self._refresh()
        analysis = self._resolver.analyze(
            graph,
            self._context.current(),
            persist_gaps=False,
        )
        still_missing = {
            gap.gap_id: gap
            for gap in analysis.gaps
        }
        if request.gap_id in still_missing:
            return Phase9GapRecheck(
                request=request,
                analysis=analysis,
                gap_satisfied=False,
                continuation=None,
            )

        if existing_gap.state is not CapabilityGapState.SATISFIED:
            existing_gap = self._store.update_gap_state(
                existing_gap.gap_id,
                CapabilityGapState.SATISFIED,
                expected_revision=existing_gap.revision,
            )

        continuation = None
        if continuation_id is not None:
            continuation = self._store.get_continuation(continuation_id)
            if continuation is None:
                raise GoalStoreError(
                    f"unknown continuation_id: {continuation_id}"
                )
            if (
                continuation.goal_id != request.motivating_goal_id
                or continuation.blocked_by_id != request.gap_id
            ):
                raise GoalStoreConflict(
                    "continuation is not blocked by the exact completed GICC gap"
                )
            if continuation.state is not ContinuationState.RESUMED:
                continuation = self._store.resume_continuation(
                    continuation.continuation_id,
                    expected_revision=continuation.revision,
                )

        return Phase9GapRecheck(
            request=request,
            analysis=analysis,
            gap_satisfied=True,
            continuation=continuation,
        )
