from jarvis.autonomy.owner_communication import (
    OwnerCommunicationIntentV1,
    OwnerCommunicationKind,
    SupervisorOwnerCommunication,
)


def test_internal_nonterminal_failure_is_not_owner_visible() -> None:
    intent = OwnerCommunicationIntentV1.create(
        kind=OwnerCommunicationKind.FAILURE,
        event_key="failure:provider-overload",
        summary="Research provider is temporarily overloaded.",
        system_outcome_kind="retryable",
        terminal=False,
        work_id="work-research",
        technical_detail="ChatGPTPlanHTTPError 503 provider_overload",
    )

    assert SupervisorOwnerCommunication.compile(intent) is None


def test_internal_blocker_is_not_owner_visible_without_owner_action() -> None:
    intent = OwnerCommunicationIntentV1.create(
        kind=OwnerCommunicationKind.BLOCKER,
        event_key="blocker:resource",
        summary="Waiting for provider capacity.",
        system_outcome_kind="temporary_resource",
        owner_action_required=False,
        work_id="work-research",
    )

    assert SupervisorOwnerCommunication.compile(intent) is None


def test_owner_blocker_is_rendered_without_technical_detail() -> None:
    intent = OwnerCommunicationIntentV1.create(
        kind=OwnerCommunicationKind.BLOCKER,
        event_key="blocker:credential",
        summary="Please unlock the reviewed credential so I can continue.",
        system_outcome_kind="needs_owner",
        owner_action_required=True,
        work_id="work-research",
        technical_detail="secret_scope=tv.remote internal_work_id=work-research",
    )

    message = SupervisorOwnerCommunication.compile(intent)

    assert message is not None
    assert message.owner_action_required is True
    assert "Please unlock the reviewed credential" in message.message
    assert "secret_scope" not in message.message
    assert "work-research" not in message.message


def test_change_gate_message_preserves_exact_authority_binding() -> None:
    intent = OwnerCommunicationIntentV1.create(
        kind=OwnerCommunicationKind.CHANGE_GATE,
        event_key="change-gate:change-1:gate-1:digest",
        summary="Architecture approval is required.",
        change_id="change-1",
        work_id="work-1",
        gate_id="gate-1",
        artifact_digest="a" * 64,
        artifact_revision=2,
        proposal_summary={
            "strategy": "vidaa_mqtt_tls",
            "requested_operations": ["power", "play"],
        },
        technical_detail="internal change state WAITING_OWNER_APPROVAL",
    )

    first = SupervisorOwnerCommunication.compile(intent)
    second = SupervisorOwnerCommunication.compile(intent)

    assert first is not None
    assert first == second
    assert first.event_key == intent.event_key
    assert "approve gate-1" in first.message
    assert "reject gate-1" in first.message
    assert "a" * 64 in first.message
    assert "Revision 2" in first.message
    assert "WAITING_OWNER_APPROVAL" not in first.message
    assert "change-1" not in first.message
    assert "work-1" not in first.message


def test_terminal_failure_is_owner_visible_as_system_failure() -> None:
    intent = OwnerCommunicationIntentV1.create(
        kind=OwnerCommunicationKind.FAILURE,
        event_key="failure:terminal",
        summary="the approved implementation cannot satisfy the required safety contract.",
        system_outcome_kind="terminal",
        terminal=True,
        goal_id="goal-1",
        technical_detail="InvariantFailure code=E_INTERNAL",
    )

    message = SupervisorOwnerCommunication.compile(intent)

    assert message is not None
    assert "can't continue with this objective" in message.message
    assert "InvariantFailure" not in message.message
    assert "E_INTERNAL" not in message.message
