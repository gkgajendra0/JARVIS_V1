from __future__ import annotations

import pytest

from jarvis.computer import hands_smoke


def test_native_dependency_checks_report_missing_extra() -> None:
    checks = hands_smoke._native_dependency_checks(
        finder=lambda name: name != "win32clipboard"
    )

    by_name = {check.name: check for check in checks}
    assert by_name["Native dependency: Windows Core Audio"].ok is True
    missing = by_name["Native dependency: Win32 clipboard"]
    assert missing.ok is False
    assert "jarvis[windows-hands]" in missing.detail


def test_operation_resolution_requires_exactly_one_governed_executor() -> None:
    class FakeRuntime:
        def capability_for_operation(self, operation: str) -> str | None:
            if operation == "pause_media":
                return None
            return f"capability:{operation}"

    checks = hands_smoke._operation_resolution_checks(FakeRuntime())  # type: ignore[arg-type]

    by_name = {check.name: check for check in checks}
    assert by_name["Operation: set_master_volume"].ok is True
    failed = by_name["Operation: pause_media"]
    assert failed.ok is False
    assert "exactly one governed executor" in failed.detail


def test_readiness_payload_is_explicitly_non_mutating() -> None:
    payload = hands_smoke._readiness_payload(
        (
            hands_smoke.ReadinessCheck("OPA", True, "ready"),
            hands_smoke.ReadinessCheck("Hello", True, "ready"),
        )
    )

    assert payload["ok"] is True
    assert payload["read_only"] is True
    assert payload["mutations_performed"] == 0
    assert payload["cloud_model_calls"] == 0


def test_readiness_payload_fails_when_any_check_fails() -> None:
    payload = hands_smoke._readiness_payload(
        (
            hands_smoke.ReadinessCheck("OPA", True, "ready"),
            hands_smoke.ReadinessCheck("Hello", False, "missing"),
        )
    )

    assert payload["ok"] is False


def test_native_core_acceptance_plan_is_bounded_and_explicit() -> None:
    actions = hands_smoke._native_core_actions(30)

    assert [operation for _, operation, _ in actions] == [
        "open_app",
        "maximize_window",
        "set_master_volume",
        "set_clipboard_text",
    ]
    assert actions[0][2] == {"app": "calculator"}
    assert actions[1][2] == {"app": "calculator"}
    assert actions[2][2] == {"percent": 30.0}
    assert actions[3][2] == {"text": hands_smoke._CLIPBOARD_MARKER}


def test_native_core_acceptance_rejects_extreme_volume() -> None:
    with pytest.raises(ValueError, match="between 5 and 80"):
        hands_smoke._native_core_actions(100)


def test_media_transition_plan_restores_common_playback_states() -> None:
    assert hands_smoke._media_transition_plan("playing") == (
        "pause_media",
        "play_media",
    )
    assert hands_smoke._media_transition_plan("paused") == (
        "play_media",
        "pause_media",
    )
    assert hands_smoke._media_transition_plan("stopped") == (
        "play_media",
        "stop_media",
    )
    assert hands_smoke._media_transition_plan("closed") is None