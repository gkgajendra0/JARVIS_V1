from types import SimpleNamespace

import pytest

from jarvis.voice.hands_fast_path import canonicalize_fast_parameters
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator


@pytest.mark.parametrize("operation", ["open_app", "close_app"])
def test_app_name_fast_hint_normalizes_to_typed_app_field(operation: str) -> None:
    assert canonicalize_fast_parameters(
        operation,
        {"app_name": "Apple Music"},
    ) == {"app": "Apple Music"}


def test_app_name_fast_hint_rejects_conflicting_canonical_value() -> None:
    with pytest.raises(ValueError, match="conflicting fast-path parameters"):
        canonicalize_fast_parameters(
            "close_app",
            {"app": "Calculator", "app_name": "Apple Music"},
        )


def test_visual_fallback_candidate_is_added_once_for_structured_ui_stagnation() -> None:
    structured = SimpleNamespace(operation="execute_windows_plan")
    visual = SimpleNamespace(operation="execute_visual_desktop_task")
    route_groups = (
        SimpleNamespace(key="app_ui", operations=(structured,)),
        SimpleNamespace(key="visual_fallback", operations=(visual,)),
    )

    candidates = VoiceHandsOrchestrator._with_visual_candidate(
        (structured,),
        route_groups,
    )
    assert tuple(item.operation for item in candidates) == (
        "execute_windows_plan",
        "execute_visual_desktop_task",
    )

    unchanged = VoiceHandsOrchestrator._with_visual_candidate(
        candidates,
        route_groups,
    )
    assert unchanged == candidates
