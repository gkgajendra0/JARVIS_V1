from __future__ import annotations

from jarvis.identity.active_speaker_benchmark_guided import (
    _capture_seconds_from_argv,
    _h_cue_schedule,
    _scenario_readiness_lines,
)


def test_capture_seconds_follow_cli_override() -> None:
    assert _capture_seconds_from_argv([]) == 4.0
    assert _capture_seconds_from_argv(["--seconds", "6"]) == 6.0
    assert _capture_seconds_from_argv(["--seconds=5.5"]) == 5.5


def test_every_scenario_tells_operator_to_wait_for_start_now() -> None:
    for key in "ABCDEFGH":
        text = " ".join(_scenario_readiness_lines(key, 4.0))
        assert "NOT capturing yet" in text
        assert "START NOW" in text
        assert "4.0s" in text


def test_h_cue_schedule_places_a_short_occlusion_in_middle() -> None:
    hide_start, hide_duration = _h_cue_schedule(4.0)

    assert hide_start == 1.65
    assert hide_duration == 0.7
    assert hide_start + hide_duration < 4.0
