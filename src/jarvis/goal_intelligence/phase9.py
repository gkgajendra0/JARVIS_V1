"""GICC V2 bridge into the existing Phase-9 capability-acquisition lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from jarvis.capability_acquisition.admission import (
    CapabilityAcquisitionAdmission,
    CapabilityAcquisitionAdmissionDisposition,
)
from jarvis.capability_acquisition.lineage import (
    CapabilityAcquisitionLineageError,
    verify_capability_acquisition_completion,
)
from jarvis.capability_acquisition.models import OwnerCapabilityGoalV1
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.engineering_change import (
    ChangeArtifact,
    ChangeState,
    ChangeStore,
    EngineeringChange,
)
from jarvis.engineering_substrate.canonical import canonical_digest

from .capability_graph import CapabilityGapAnalysis, CapabilityGraphResolver
from .models import (
    CapabilityGapState,
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    ContinuationState,
    GoalContinuationV1,
    GoalKind,
    OwnerGoalV2,
)
from .monitoring import GICC_MONITOR_EVENT_CONTRACT
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

    def find_by_source(
        self,
        source_session_id: str,
        source_turn_id: str,
        process_key: str,
    ) -> EngineeringChange | None: ...


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
    monitor_event_contract_required: bool
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
        family = gap.reusable_capability_family
        observation_family = (
            ".observe" in family
            or ".perceive" in family
            or family.startswith(("vision.", "camera."))
        )
        monitor_event_required = bool(
            goal.goal_kind is GoalKind.MONITORING and observation_family
        )
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
            "monitor_event_contract_required": monitor_event_required,
        }
        digest = canonical_digest(payload)
        return cls(
            request_id=f"phase9_gicc_{digest[:20]}",
            motivating_goal_id=goal.goal_id,
            gap_id=gap.gap_id,
            reusable_capability_family=gap.reusable_capability_family,
            minimum_required_operations=tuple(gap.minimum_required_operations),
            target_entity_type=gap.target_entity_type,
            target_entity_id=gap.target_entity_id,
            owner_source_session_id=goal.source_session_id,
            owner_source_turn_id=goal.source_turn_id,
            bridge_source_session_id=f"gicc:{goal.goal_id}",
            bridge_source_turn_id=f"gap:{gap.gap_id}",
            monitor_event_contract_required=monitor_event_required,
            digest=digest,
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
            "monitor_event_contract_required": self.monitor_event_contract_required,
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
        if self.monitor_event_contract_required:
            hints.append(f"monitor_event_contract:{GICC_MONITOR_EVENT_CONTRACT}")
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


def migrate_legacy_phase9_gap_links(
    *,
    goal_store: GoalStore,
    change_store: ChangeStore,
    dry_run: bool = False,
    limit: int = 10_000,
) -> tuple[str, ...]:
    """Append exact v2 lineage for durable v1 GICC links without rewriting history."""

    if not isinstance(goal_store, GoalStore):
        raise TypeError("goal_store must be GoalStore")
    if not isinstance(change_store, ChangeStore):
        raise TypeError("change_store must be ChangeStore")
    if not isinstance(dry_run, bool):
        raise TypeError("dry_run must be bool")
    if type(limit) is not int or limit <= 0:
        raise ValueError("limit must be a positive integer")

    migrated: list[str] = []
    changes = change_store.list_by_states(
        tuple(ChangeState),
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        limit=limit,
    )
    for change in changes:
        link = change_store.latest_artifact(
            change.change_id,
            "gicc_capability_gap_link",
        )
        if link is None or link.payload.get("schema") != "gicc_phase9_gap_link.v1":
            continue

        goal_id = str(link.payload.get("motivating_goal_id") or "").strip()
        gap_id = str(link.payload.get("gap_id") or "").strip()
        goal = goal_store.get_goal(goal_id)
        gap = goal_store.get_gap(gap_id)
        if goal is None or gap is None:
            raise GoalStoreConflict(
                "legacy Phase-9 link no longer resolves to its exact goal/gap"
            )
        request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
        expected_legacy = {
            "request_id": request.request_id,
            "request_digest": request.digest,
            "motivating_goal_id": request.motivating_goal_id,
            "gap_id": request.gap_id,
            "reusable_capability_family": request.reusable_capability_family,
            "minimum_required_operations": list(request.minimum_required_operations),
            "target_entity_type": request.target_entity_type,
            "target_entity_id": request.target_entity_id,
            "owner_source_session_id": request.owner_source_session_id,
            "owner_source_turn_id": request.owner_source_turn_id,
        }
        for key, expected in expected_legacy.items():
            if link.payload.get(key) != expected:
                raise GoalStoreConflict(
                    f"legacy Phase-9 link field {key} drifted from canonical goal/gap"
                )
        if (
            change.source_session_id != request.bridge_source_session_id
            or change.source_turn_id != request.bridge_source_turn_id
        ):
            raise GoalStoreConflict(
                "legacy Phase-9 EngineeringChange source identity drifted"
            )

        source_stage_key = (
            OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
        )
        source_stages = sorted(
            (
                item
                for item in change_store.list_stages(change.change_id)
                if item.stage_key == source_stage_key
            ),
            key=lambda item: item.attempt,
        )
        if not source_stages or source_stages[0].attempt != 1:
            raise GoalStoreConflict(
                "legacy Phase-9 link has no original acquisition stage"
            )
        acquisition_work_id = source_stages[0].work_id
        goal_artifact = change_store.latest_artifact(
            change.change_id,
            "capability_goal",
        )
        admission_artifact = change_store.latest_artifact(
            change.change_id,
            "capability_acquisition_admission",
        )
        if goal_artifact is None or admission_artifact is None:
            raise GoalStoreConflict(
                "legacy Phase-9 link is missing canonical admission provenance"
            )
        phase9_goal = request.to_v1(owner_goal_created_at=goal.created_at)
        payload = {
            "schema": "gicc_phase9_gap_link.v2",
            "request_id": request.request_id,
            "request_digest": request.digest,
            "motivating_goal_id": request.motivating_goal_id,
            "gap_id": request.gap_id,
            "phase9_goal_id": phase9_goal.goal_id,
            "phase9_goal_digest": phase9_goal.digest,
            "engineering_change_id": change.change_id,
            "acquisition_work_id": acquisition_work_id,
            "goal_artifact_id": goal_artifact.artifact_id,
            "admission_artifact_id": admission_artifact.artifact_id,
            "admission_disposition": (
                CapabilityAcquisitionAdmissionDisposition.ENGINEERING_CHANGE.value
            ),
            "reusable_capability_family": request.reusable_capability_family,
            "minimum_required_operations": list(request.minimum_required_operations),
            "target_entity_type": request.target_entity_type,
            "target_entity_id": request.target_entity_id,
            "owner_source_session_id": request.owner_source_session_id,
            "owner_source_turn_id": request.owner_source_turn_id,
            "bridge_source_session_id": request.bridge_source_session_id,
            "bridge_source_turn_id": request.bridge_source_turn_id,
            "monitor_event_contract_required": request.monitor_event_contract_required,
            "monitor_event_contract": (
                GICC_MONITOR_EVENT_CONTRACT
                if request.monitor_event_contract_required
                else None
            ),
        }
        migrated.append(change.change_id)
        if not dry_run:
            change_store.add_artifact(
                change.change_id,
                kind="gicc_capability_gap_link",
                payload=payload,
            )

    return tuple(migrated)


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
            or not callable(getattr(change_store, "find_by_source", None))
        ):
            raise TypeError(
                "change_store must provide artifact persistence and source lookup"
            )
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
                "schema": "gicc_phase9_gap_link.v2",
                "request_id": request.request_id,
                "request_digest": request.digest,
                "motivating_goal_id": request.motivating_goal_id,
                "gap_id": request.gap_id,
                "phase9_goal_id": phase9_goal.goal_id,
                "phase9_goal_digest": phase9_goal.digest,
                "engineering_change_id": admission.change.change_id,
                "acquisition_work_id": admission.acquisition_work_id,
                "goal_artifact_id": admission.goal_artifact_id,
                "admission_artifact_id": admission.admission_artifact_id,
                "admission_disposition": admission.disposition.value,
                "reusable_capability_family": request.reusable_capability_family,
                "minimum_required_operations": list(
                    request.minimum_required_operations
                ),
                "target_entity_type": request.target_entity_type,
                "target_entity_id": request.target_entity_id,
                "owner_source_session_id": request.owner_source_session_id,
                "owner_source_turn_id": request.owner_source_turn_id,
                "bridge_source_session_id": request.bridge_source_session_id,
                "bridge_source_turn_id": request.bridge_source_turn_id,
                "monitor_event_contract_required": (
                    request.monitor_event_contract_required
                ),
                "monitor_event_contract": (
                    GICC_MONITOR_EVENT_CONTRACT
                    if request.monitor_event_contract_required
                    else None
                ),
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

            target_hints = [f"entity_type:{request.target_entity_type}"]
            target_entity = (
                None
                if request.target_entity_id is None
                else self._goals.get_entity(request.target_entity_id)
            )
            target_payload: dict[str, object] = {
                "schema": "gicc_target_context.v1",
                "motivating_goal_id": request.motivating_goal_id,
                "gap_id": request.gap_id,
                "target_entity_type": request.target_entity_type,
                "target_entity_id": request.target_entity_id,
                "canonical_name": (
                    None if target_entity is None else target_entity.canonical_name
                ),
                "aliases": (
                    [] if target_entity is None else list(target_entity.aliases)
                ),
                "provenance_refs": (
                    [] if target_entity is None else list(target_entity.provenance_refs)
                ),
                "target_hints": target_hints,
            }
            if target_entity is not None:
                target_payload["target_hints"] = [
                    *target_hints,
                    f"entity_name:{target_entity.canonical_name}",
                ]
            current_target = self._changes.latest_artifact(
                admission.change.change_id,
                "gicc_target_context",
            )
            if current_target is None or current_target.payload != target_payload:
                self._changes.add_artifact(
                    admission.change.change_id,
                    kind="gicc_target_context",
                    payload=target_payload,
                )
        return Phase9GapAdmission(
            request=request,
            phase9_goal=phase9_goal,
            admission=admission,
        )

    def completion_verified(
        self,
        *,
        gap: CapabilityGapV1,
        goal: OwnerGoalV2,
    ) -> bool:
        """Prove that this exact GICC gap produced the currently accepted capability."""

        request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
        change = self._changes.find_by_source(
            request.bridge_source_session_id,
            request.bridge_source_turn_id,
            OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        )
        if change is None:
            # No EngineeringChange is the canonical Phase-9 reuse path. This method
            # is called only after GICC has re-read capability truth and found the
            # semantic gap absent, so there is no newly produced package generation
            # that requires lineage binding.
            return True
        try:
            lineage = verify_capability_acquisition_completion(
                self._changes,
                change_id=change.change_id,
                motivating_goal_id=goal.goal_id,
                gap_id=gap.gap_id,
                request_id=request.request_id,
                request_digest=request.digest,
            )
        except CapabilityAcquisitionLineageError:
            return False
        return lineage is not None


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
        goal = self._store.get_goal(request.motivating_goal_id)
        analysis = self._resolver.analyze(
            graph,
            self._context.current(),
            persist_gaps=False,
            monitoring_goal=bool(
                goal is not None and goal.goal_kind is GoalKind.MONITORING
            ),
        )
        still_missing = {gap.gap_id: gap for gap in analysis.gaps}
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
                raise GoalStoreError(f"unknown continuation_id: {continuation_id}")
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
