"""Proactively surface exact EngineeringChange owner gates.

This bridge creates no approval authority.  It only presents the current
artifact-bound gate and places one durable owner-visible delivery on the
existing Work delivery substrate.  GateService + ChangeService remain the
only decision/strong-approval path.
"""

from __future__ import annotations

import json

from jarvis.work.models import WorkDeliveryKind

from .coordinator import ChangeCoordinator
from .gates import GateKind, GateService
from .models import ChangeState


def _architecture_review_message(
    *,
    change_id: str,
    gate_id: str,
    revision: int,
    digest: str,
    payload: dict[str, object],
) -> str:
    summary = {
        key: payload[key]
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
        if key in payload
    }
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    return (
        f"EngineeringChange {change_id} has completed architecture revision "
        f"{revision} and requires your approval before development can start. "
        f"Proposal: {rendered}. Artifact SHA-256: {digest}. "
        f"To approve, say 'approve {gate_id}'. To reject it, say "
        f"'reject {gate_id}'."
    )


def reconcile_owner_change_gates(coordinator: ChangeCoordinator) -> tuple[str, ...]:
    """Present/recover durable owner gates for active architecture-ready changes."""

    surfaced: list[str] = []
    store = coordinator.store
    gates = GateService(store, verify_owner=lambda *_: False)

    for change_id in store.active_ids():
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
        stage = next(
            (
                item
                for item in store.list_stages(change_id)
                if item.stage_key == source_stage.stage_key
            ),
            None,
        )
        if stage is None:
            continue

        challenge = gates.present(
            change_id,
            GateKind.ARCHITECTURE,
            architecture.artifact_id,
        )
        work = store.work.require(stage.work_id)
        store.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.CHANGE_GATE,
            message=_architecture_review_message(
                change_id=change_id,
                gate_id=challenge.gate_id,
                revision=architecture.revision,
                digest=architecture.digest,
                payload=architecture.payload,
            ),
            event_key=(
                f"change-gate:{change_id}:{challenge.gate_id}:{architecture.digest}"
            ),
        )
        surfaced.append(challenge.gate_id)

    return tuple(surfaced)
