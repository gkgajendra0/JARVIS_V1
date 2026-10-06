"""Proactively surface exact EngineeringChange owner gates.

This bridge creates no approval authority.  It only presents the current
artifact-bound gate and places one durable owner-visible delivery on the
existing Work delivery substrate.  GateService + ChangeService remain the
only decision/strong-approval path.
"""

from __future__ import annotations

from jarvis.autonomy.owner_communication import (
    OwnerCommunicationIntentV1,
    OwnerCommunicationKind,
    SupervisorOwnerCommunication,
)
from jarvis.work.models import WorkDeliveryKind

from .coordinator import ChangeCoordinator
from .gates import GateKind, GateService
from .models import ChangeState


def reconcile_owner_change_gates(
    coordinator: ChangeCoordinator,
    *,
    change_ids: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """Present/recover durable owner gates for selected architecture-ready changes."""

    surfaced: list[str] = []
    store = coordinator.store
    gates = GateService(store, verify_owner=lambda *_: False)
    selected_change_ids = (
        store.active_ids()
        if change_ids is None
        else tuple(
            dict.fromkeys(str(item).strip() for item in change_ids if str(item).strip())
        )
    )

    for change_id in selected_change_ids:
        change = store.require(change_id)
        if change.state not in {
            ChangeState.ARCHITECTURE_READY,
            ChangeState.WAITING_OWNER_APPROVAL,
        }:
            continue

        architecture = store.latest_artifact(change_id, "architecture")
        if architecture is None:
            continue

        process = store.process_contract(change.process_key, change.process_version)
        source_stage = process.architecture_source_stage
        stage = store.current_stage_attempt(
            change_id,
            source_stage.stage_key,
        )
        if stage is None:
            continue

        challenge = gates.present(
            change_id,
            GateKind.ARCHITECTURE,
            architecture.artifact_id,
        )
        work = store.work.require(stage.work_id)
        event_key = f"change-gate:{change_id}:{challenge.gate_id}:{architecture.digest}"
        proposal_summary = {
            key: architecture.payload[key]
            for key in (
                "strategy",
                "proposed_capability_id",
                "proposed_package_id",
                "proposed_package_version",
                "allowed_components",
                "allowed_paths",
                "requested_operations",
                "rollback_strategy",
            )
            if key in architecture.payload
        }
        intent = OwnerCommunicationIntentV1.create(
            kind=OwnerCommunicationKind.CHANGE_GATE,
            event_key=event_key,
            summary="Architecture approval is required before development can start.",
            change_id=change_id,
            work_id=work.work_id,
            gate_id=challenge.gate_id,
            artifact_digest=architecture.digest,
            artifact_revision=architecture.revision,
            proposal_summary=proposal_summary,
        )
        owner_message = SupervisorOwnerCommunication.compile(intent)
        assert owner_message is not None
        store.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.CHANGE_GATE,
            message=owner_message.message,
            event_key=owner_message.event_key,
        )
        surfaced.append(challenge.gate_id)

    return tuple(surfaced)
