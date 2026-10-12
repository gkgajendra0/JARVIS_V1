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
from jarvis.work.models import WorkDeliveryKind, WorkState

from .coordinator import ChangeCoordinator
from .gates import GateKind, GateService
from .models import ChangeConflict, ChangeState


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
                "device_scopes",
                "network_scopes",
                "discovery_scopes",
                "semantic_capability_contract",
                "owner_acceptance_contract_ids",
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


def reconcile_owner_acceptance_gates(
    coordinator: ChangeCoordinator,
    *,
    change_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Present/recover exact verified acceptance gates without granting approval."""

    store = coordinator.store
    gates = GateService(store, verify_owner=lambda *_: False)
    surfaced: list[str] = []

    for change_id in tuple(
        dict.fromkeys(str(item).strip() for item in change_ids if str(item).strip())
    ):
        change = store.require(change_id)
        if change.state not in {
            ChangeState.VERIFYING,
            ChangeState.WAITING_OWNER_ACCEPTANCE,
        }:
            continue

        process = store.process_contract(change.process_key, change.process_version)
        stage = store.current_stage_attempt(
            change_id,
            process.development_stage.stage_key,
        )
        if stage is None:
            raise ChangeConflict("verification has no current development stage")
        work = store.work.require(stage.work_id)
        result = work.result
        if (
            work.state is not WorkState.COMPLETED
            or not isinstance(result.get("verification"), dict)
            or result["verification"].get("passed") is not True
            or not result.get("commit")
            or not result.get("branch")
        ):
            raise ChangeConflict("canonical development has no verified commit")

        payload = {"work_id": stage.work_id, "result": result}
        artifact = store.latest_artifact(change_id, "acceptance")
        if artifact is None or artifact.payload != payload:
            artifact = store.add_artifact(
                change_id,
                kind="acceptance",
                payload=payload,
            )

        challenge = gates.present(
            change_id,
            GateKind.ACCEPTANCE,
            artifact.artifact_id,
        )
        intent = OwnerCommunicationIntentV1.create(
            kind=OwnerCommunicationKind.CHANGE_GATE,
            event_key=(
                f"change-gate:{change_id}:{challenge.gate_id}:{artifact.digest}"
            ),
            summary="Acceptance approval is required for the verified candidate.",
            change_id=change_id,
            work_id=work.work_id,
            gate_id=challenge.gate_id,
            artifact_digest=artifact.digest,
            artifact_revision=artifact.revision,
            proposal_summary={
                "review_kind": "acceptance",
                "branch": result["branch"],
                "commit": result["commit"],
                "sandbox": result["verification"].get("sandbox"),
            },
        )
        owner_message = SupervisorOwnerCommunication.compile(intent)
        if owner_message is None:
            raise ChangeConflict("Supervisor suppressed required acceptance gate")
        store.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.CHANGE_GATE,
            message=owner_message.message,
            event_key=owner_message.event_key,
        )
        surfaced.append(challenge.gate_id)

    return tuple(surfaced)


def reconcile_owner_promotion_attention(
    coordinator: ChangeCoordinator,
    *,
    change_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Surface promotion preparation or the exact promotion gate to the owner."""

    store = coordinator.store
    gates = GateService(store, verify_owner=lambda *_: False)
    surfaced: list[str] = []

    for change_id in tuple(
        dict.fromkeys(str(item).strip() for item in change_ids if str(item).strip())
    ):
        change = store.require(change_id)
        if change.state not in {
            ChangeState.READY_FOR_PROMOTION,
            ChangeState.WAITING_PROMOTION_APPROVAL,
        }:
            continue
        process = store.process_contract(change.process_key, change.process_version)
        stage = store.current_stage_attempt(
            change_id,
            process.development_stage.stage_key,
        )
        if stage is None:
            raise ChangeConflict("promotion has no current development stage")
        work = store.work.require(stage.work_id)
        promotion = store.latest_artifact(change_id, "promotion")

        if promotion is None:
            intent = OwnerCommunicationIntentV1.create(
                kind=OwnerCommunicationKind.OWNER_INPUT,
                event_key=f"promotion-preparation:{change_id}:{work.work_id}",
                summary=(
                    "The verified candidate is ready for promotion review. Preparing "
                    "the exact GitHub PR/CI evidence requires your presence and strong "
                    "local verification for the short-lived GitHub credential lease."
                ),
                owner_action_required=True,
                change_id=change_id,
                work_id=work.work_id,
                system_outcome_kind="needs_owner",
                technical_detail="promotion preparation requires strong owner verification",
            )
            owner_message = SupervisorOwnerCommunication.compile(intent)
            if owner_message is None:
                raise ChangeConflict(
                    "Supervisor suppressed required promotion preparation request"
                )
            store.work.enqueue_delivery(
                work=work,
                kind=WorkDeliveryKind.OWNER_INPUT,
                message=owner_message.message,
                event_key=owner_message.event_key,
            )
            continue

        from jarvis.promotion.models import PromotionEvidenceV1

        try:
            evidence = PromotionEvidenceV1.from_payload(promotion.payload)
        except (TypeError, ValueError) as exc:
            raise ChangeConflict("exact Phase-7 promotion evidence is invalid") from exc

        challenge = gates.present(
            change_id,
            GateKind.PROMOTION,
            promotion.artifact_id,
        )
        intent = OwnerCommunicationIntentV1.create(
            kind=OwnerCommunicationKind.CHANGE_GATE,
            event_key=(
                f"change-gate:{change_id}:{challenge.gate_id}:{promotion.digest}"
            ),
            summary=(
                "Promotion approval is required for the exact verified release "
                "evidence; the gate itself is not an execution permit."
            ),
            change_id=change_id,
            work_id=work.work_id,
            gate_id=challenge.gate_id,
            artifact_digest=promotion.digest,
            artifact_revision=promotion.revision,
            proposal_summary={
                "review_kind": "promotion",
                "pr_number": evidence.pr_number,
                "candidate_head_sha": evidence.candidate_head_sha,
                "tested_merge_sha": evidence.tested_merge_sha,
                "evidence_digest": evidence.digest,
            },
        )
        owner_message = SupervisorOwnerCommunication.compile(intent)
        if owner_message is None:
            raise ChangeConflict("Supervisor suppressed required promotion gate")
        store.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.CHANGE_GATE,
            message=owner_message.message,
            event_key=owner_message.event_key,
        )
        surfaced.append(challenge.gate_id)

    return tuple(surfaced)


def reconcile_owner_lifecycle_activation_requests(
    coordinator: ChangeCoordinator,
    *,
    change_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Re-surface exact lifecycle activation authority without activating anything."""

    store = coordinator.store
    event_keys: list[str] = []
    for change_id in tuple(
        dict.fromkeys(str(item).strip() for item in change_ids if str(item).strip())
    ):
        proposal = store.latest_artifact(change_id, "capability_lifecycle_proposal")
        if proposal is None or proposal.payload.get("authority_required") is not True:
            continue
        admission_id = str(proposal.payload.get("admission_artifact_id") or "").strip()
        admission_digest = str(
            proposal.payload.get("admission_artifact_digest") or ""
        ).strip()
        if not admission_id or not admission_digest:
            continue

        activations = [
            item
            for item in store.list_artifacts(change_id)
            if item.kind == "capability_lifecycle_activation"
            and item.payload.get("admission_artifact_id") == admission_id
            and item.payload.get("admission_artifact_digest") == admission_digest
            and item.payload.get("effective_enabled") is True
        ]
        activation = (
            None
            if not activations
            else max(activations, key=lambda item: (item.revision, item.artifact_id))
        )
        disabled_after = False
        if activation is not None:
            candidate_id = str(
                activation.payload.get("candidate_artifact_id") or ""
            ).strip()
            candidate_digest = str(
                activation.payload.get("candidate_artifact_digest") or ""
            ).strip()
            disabled_after = any(
                item.kind == "capability_lifecycle_disable"
                and item.payload.get("candidate_artifact_id") == candidate_id
                and item.payload.get("candidate_artifact_digest") == candidate_digest
                and item.payload.get("effective_enabled") is False
                and item.created_at >= activation.created_at
                for item in store.list_artifacts(change_id)
            )
        if activation is not None and not disabled_after:
            continue

        change = store.require(change_id)
        process = store.process_contract(change.process_key, change.process_version)
        stage = store.current_stage_attempt(
            change_id,
            process.development_stage.stage_key,
        )
        if stage is None:
            continue
        work = store.work.require(stage.work_id)
        event_key = f"phase9-lifecycle:{change_id}:{proposal.digest}"
        intent = OwnerCommunicationIntentV1.create(
            kind=OwnerCommunicationKind.OWNER_INPUT,
            event_key=event_key,
            summary=(
                "The acquired capability is ready and remains disabled until you "
                "explicitly activate it. Say 'activate the acquired capability' "
                "to continue."
            ),
            owner_action_required=True,
            change_id=change_id,
            work_id=work.work_id,
            system_outcome_kind="needs_owner",
            technical_detail="explicit lifecycle activation authority required",
        )
        owner_message = SupervisorOwnerCommunication.compile(intent)
        if owner_message is None:
            raise ChangeConflict(
                "Supervisor suppressed required lifecycle activation request"
            )
        store.work.enqueue_delivery(
            work=work,
            kind=WorkDeliveryKind.OWNER_INPUT,
            message=owner_message.message,
            event_key=owner_message.event_key,
        )
        event_keys.append(event_key)
    return tuple(event_keys)
