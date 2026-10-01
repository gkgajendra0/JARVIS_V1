import logging

import pytest

from jarvis.goal_intelligence.telemetry import (
    CapturingGiccTelemetry,
    GiccTelemetry,
)


def test_capturing_telemetry_accepts_ids_digests_and_reason_codes() -> None:
    telemetry = CapturingGiccTelemetry()

    telemetry.emit(
        "gicc_goal_admitted",
        goal_id="goal_123",
        goal_digest="a" * 64,
        goal_kind="one_shot",
        reason_code="accepted",
    )

    assert telemetry.events == [
        {
            "event": "gicc_goal_admitted",
            "goal_digest": "a" * 64,
            "goal_id": "goal_123",
            "goal_kind": "one_shot",
            "reason_code": "accepted",
        }
    ]


@pytest.mark.parametrize(
    "field",
    (
        "owner_request",
        "exact_owner_request",
        "raw_request",
        "prompt",
        "password",
        "secret",
        "token",
        "parameters",
        "payload",
        "data",
    ),
)
def test_telemetry_rejects_raw_or_secret_bearing_field_names(field: str) -> None:
    telemetry = CapturingGiccTelemetry()

    with pytest.raises(ValueError, match="forbidden"):
        telemetry.emit(
            "gicc_goal_admitted",
            **{field: "must-not-be-logged"},
        )


def test_request_identifier_is_allowed_but_request_content_is_not() -> None:
    telemetry = CapturingGiccTelemetry()

    telemetry.emit(
        "gicc_phase9_linked",
        request_id="phase9_gicc_123",
        request_digest="b" * 64,
    )

    assert telemetry.events[0]["request_id"] == "phase9_gicc_123"
    assert telemetry.events[0]["request_digest"] == "b" * 64


def test_logging_sink_emits_one_json_event_line(caplog) -> None:
    logger = logging.getLogger("jarvis.gicc.telemetry.acceptance-test")
    telemetry = GiccTelemetry(logger)

    with caplog.at_level(logging.INFO, logger=logger.name):
        telemetry.emit(
            "gicc_postcondition_verified",
            goal_id="goal_123",
            plan_id="plan_123",
            verified=True,
            reason_code="verified",
        )

    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert message.startswith("GICC_EVENT ")
    assert '"event":"gicc_postcondition_verified"' in message
    assert '"verified":true' in message
