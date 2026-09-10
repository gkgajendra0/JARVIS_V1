from __future__ import annotations

import pytest
from pydantic import ValidationError

from jarvis.hands.contracts import (
    build_action_response_model,
    materialize_planner_response,
    validate_contract_coverage,
)
from jarvis.hands.registry import HandsCapabilityRegistry


def test_typed_contracts_cover_every_canonical_hands_operation() -> None:
    operations = {item.operation for item in HandsCapabilityRegistry.default().operations}
    validate_contract_coverage(operations)


def test_dynamic_planner_schema_only_accepts_shortlisted_operations() -> None:
    response_model = build_action_response_model(("open_app", "set_master_volume"))

    accepted = response_model.model_validate(
        {
            "actions": [
                {
                    "operation": "open_app",
                    "parameters": {"app": "Apple Music"},
                    "evidence": "Open Apple Music",
                }
            ],
            "goal_complete": False,
        }
    )
    turn = materialize_planner_response(accepted)
    assert turn.action is not None
    assert turn.action.operation == "open_app"

    with pytest.raises(ValidationError):
        response_model.model_validate(
            {
                "actions": [
                    {
                        "operation": "shutdown_workstation",
                        "parameters": {},
                        "evidence": "Open Apple Music",
                    }
                ]
            }
        )


def test_typed_volume_schema_rejects_out_of_range_or_extra_arguments() -> None:
    response_model = build_action_response_model(("set_master_volume",))

    with pytest.raises(ValidationError):
        response_model.model_validate(
            {
                "actions": [
                    {
                        "operation": "set_master_volume",
                        "parameters": {"percent": 140},
                        "evidence": "set it to 140",
                    }
                ]
            }
        )

    with pytest.raises(ValidationError):
        response_model.model_validate(
            {
                "actions": [
                    {
                        "operation": "set_master_volume",
                        "parameters": {"percent": 30, "shell": "cmd.exe"},
                        "evidence": "set volume to 30",
                    }
                ]
            }
        )


def test_planner_completion_and_clarification_are_mutually_exclusive() -> None:
    response_model = build_action_response_model(("open_app",))
    complete = response_model.model_validate({"actions": [], "goal_complete": True})
    assert materialize_planner_response(complete).goal_complete is True

    clarification = response_model.model_validate(
        {"actions": [], "clarification_question": "Which application?"}
    )
    assert (
        materialize_planner_response(clarification).clarification_question
        == "Which application?"
    )
