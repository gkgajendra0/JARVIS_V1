"""Idempotent owner capability-goal admission into Phase-9 EngineeringChange."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from jarvis.capability_acquisition.artifacts import (
    goal_payload,
    resolution_payload,
)
from jarvis.capability_acquisition.models import (
    AcquisitionStrategy,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.resolver import (
    AcquisitionResolutionResult,
    CapabilityAcquisitionResolver,
)
from jarvis.capability_acquisition.runtime_context import AcquisitionContextProvider
from jarvis.capability_acquisition.source import (
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
)
from jarvis.engineering_change import ChangeArtifact, ChangeState, EngineeringChange
from jarvis.engineering_change.coordinator import ChangeCoordinator

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


class CapabilityAcquisitionAdmissionError(RuntimeError):
    """A capability goal cannot safely enter the Phase-9 workflow."""


class CapabilityAcquisitionAdmissionDisposition(str, Enum):
    EXISTING_READY = "existing_ready"
    EXISTING_LIFECYCLE = "existing_lifecycle"
    ENGINEERING_CHANGE = "engineering_change"


@dataclass(frozen=True, slots=True)
class CapabilityAcquisitionAdmission:
    goal: OwnerCapabilityGoalV1
    disposition: CapabilityAcquisitionAdmissionDisposition
    initial_resolution: AcquisitionResolutionResult
    change: EngineeringChange | None
    goal_artifact_id: str | None
    admission_artifact_id: str | None
    acquisition_work_id: str | None


class CapabilityAcquisitionCoordinator:
    """Reuse current capability truth before creating any engineering work."""

    def __init__(
        self,
        *,
        changes: ChangeCoordinator,
        context_provider: AcquisitionContextProvider,
    ) -> None:
        if not isinstance(changes, ChangeCoordinator):
            raise TypeError("changes must be ChangeCoordinator")
        self._changes = changes
        self._context_provider = context_provider
        self._existing = CapabilityAcquisitionResolver(
            CapabilitySourceRegistry((ExistingCapabilitySourceAdapter(),))
        )

    @staticmethod
    def _persist_if_changed(
        change: EngineeringChange,
        *,
        kind: str,
        payload: dict[str, object],
        coordinator: ChangeCoordinator,
    ) -> ChangeArtifact:
        latest = coordinator.store.latest_artifact(change.change_id, kind)
        if latest is not None and latest.payload == payload:
            return latest
        return coordinator.store.add_artifact(
            change.change_id,
            kind=kind,
            payload=payload,
        )

    @staticmethod
    def _source_revision(value: str) -> str:
        revision = str(value).strip().casefold()
        if _GIT_SHA.fullmatch(revision) is None:
            raise CapabilityAcquisitionAdmissionError(
                "Phase-9 admission requires exact lowercase 40-character source revision"
            )
        return revision

    @staticmethod
    def _reuse_disposition(
        resolution: AcquisitionResolutionResult,
    ) -> CapabilityAcquisitionAdmissionDisposition | None:
        candidate = resolution.selected_candidate
        if candidate is None or candidate.strategy is not AcquisitionStrategy.REUSE:
            return None
        evaluation = resolution.evaluation(candidate.candidate_id)
        reasons = set(evaluation.reason_codes)
        if "existing_package_lifecycle_reuse" in reasons:
            return CapabilityAcquisitionAdmissionDisposition.EXISTING_LIFECYCLE
        if {
            "existing_core_ready",
            "existing_package_effectively_enabled",
        } & reasons:
            return CapabilityAcquisitionAdmissionDisposition.EXISTING_READY
        return None

    def admit(
        self,
        goal: OwnerCapabilityGoalV1,
        *,
        source_revision: str,
    ) -> CapabilityAcquisitionAdmission:
        if not isinstance(goal, OwnerCapabilityGoalV1):
            raise TypeError("goal must be OwnerCapabilityGoalV1")
        revision = self._source_revision(source_revision)
        context = self._context_provider.current()
        initial = self._existing.resolve(goal, context)
        reuse = self._reuse_disposition(initial)
        if reuse is not None:
            return CapabilityAcquisitionAdmission(
                goal=goal,
                disposition=reuse,
                initial_resolution=initial,
                change=None,
                goal_artifact_id=None,
                admission_artifact_id=None,
                acquisition_work_id=None,
            )

        store = self._changes.store
        existing = store.find_by_source(
            goal.source_session_id,
            goal.source_turn_id,
            OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        )
        if existing is not None and existing.state in {
            ChangeState.CLOSED,
            ChangeState.REJECTED,
            ChangeState.FAILED,
            ChangeState.SUPERSEDED,
            ChangeState.ROLLED_BACK,
        }:
            raise CapabilityAcquisitionAdmissionError(
                "terminal capability-acquisition change already owns this owner turn"
            )

        change = store.create(
            request=goal.request,
            process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
            source_session_id=goal.source_session_id,
            source_turn_id=goal.source_turn_id,
        )
        goal_artifact = self._persist_if_changed(
            change,
            kind="capability_goal",
            payload=goal_payload(goal),
            coordinator=self._changes,
        )
        admission_payload = {
            "schema": "capability_acquisition_admission.v1",
            "goal_artifact_id": goal_artifact.artifact_id,
            "goal_artifact_digest": goal_artifact.digest,
            "goal_id": goal.goal_id,
            "goal_digest": goal.digest,
            "source_revision": revision,
            "initial_resolution": resolution_payload(
                candidates=initial.candidates,
                evaluations=initial.evaluations,
                selected_candidate_id=initial.selected_candidate_id,
            ),
        }
        admission_artifact = self._persist_if_changed(
            change,
            kind="capability_acquisition_admission",
            payload=admission_payload,
            coordinator=self._changes,
        )

        change = self._changes.reconcile(change.change_id)
        stage = next(
            (
                item
                for item in store.list_stages(change.change_id)
                if item.stage_key
                == OWNER_CAPABILITY_ACQUISITION_PROCESS.architecture_source_stage.stage_key
            ),
            None,
        )
        if stage is None:
            raise CapabilityAcquisitionAdmissionError(
                "Phase-9 admission created no acquisition WorkItem"
            )
        return CapabilityAcquisitionAdmission(
            goal=goal,
            disposition=CapabilityAcquisitionAdmissionDisposition.ENGINEERING_CHANGE,
            initial_resolution=initial,
            change=change,
            goal_artifact_id=goal_artifact.artifact_id,
            admission_artifact_id=admission_artifact.artifact_id,
            acquisition_work_id=stage.work_id,
        )
