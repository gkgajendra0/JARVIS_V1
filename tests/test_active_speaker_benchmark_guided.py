from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.identity import active_speaker_benchmark_guided as guided
from jarvis.identity.active_speaker_benchmark_guided import (
    _capture_seconds_from_argv,
    _focused_output_path,
    _guided_capture_factory,
    _h_cue_schedule,
    _scenario_readiness_lines,
    _selected_scenarios_from_argv,
)


def test_capture_seconds_follow_cli_override() -> None:
    assert _capture_seconds_from_argv([]) == 4.0
    assert _capture_seconds_from_argv(["--seconds", "6"]) == 6.0
    assert _capture_seconds_from_argv(["--seconds=5.5"]) == 5.5


def test_every_scenario_tells_operator_to_wait_for_start_now() -> None:
    for key in "ABCDEFGH":
        text = " ".join(_scenario_readiness_lines(key, 4.0))
        assert "NOT capturing yet" in text
        assert "validate the fresh OWNER context" in text
        assert "START NOW" in text
        assert "4.0s" in text


def test_h_cue_schedule_places_a_short_occlusion_in_middle() -> None:
    hide_start, hide_duration = _h_cue_schedule(4.0)

    assert hide_start == 1.65
    assert hide_duration == 0.7
    assert hide_start + hide_duration < 4.0


def test_selected_scenarios_filters_wrapper_argument_and_preserves_order() -> None:
    scenarios, cleaned, focused = _selected_scenarios_from_argv(
        ["--seconds", "5", "--scenarios", "H,A,D", "--device", "cuda"]
    )

    assert focused is True
    assert [scenario.key for scenario in scenarios] == ["A", "D", "H"]
    assert cleaned == ["--seconds", "5", "--device", "cuda"]
    assert _focused_output_path(scenarios).name == "step3b11_lr_asd_bakeoff_ADH.json"


def test_selected_scenarios_rejects_unknown_keys() -> None:
    with pytest.raises(ValueError, match="valid keys are A-H"):
        _selected_scenarios_from_argv(["--scenarios=A,Z"])


@pytest.mark.asyncio
async def test_countdown_runs_immediately_before_real_capture(monkeypatch) -> None:
    events: list[str] = []

    async def fake_countdown() -> None:
        events.append("countdown")

    async def fake_capture(spec, **kwargs):
        del spec, kwargs
        events.append("capture")
        return "turn"

    monkeypatch.setattr(guided, "_run_countdown", fake_countdown)
    wrapped = _guided_capture_factory(fake_capture, duration_seconds=4.0)

    result = await wrapped(SimpleNamespace(key="A"))

    assert result == "turn"
    assert events == ["countdown", "capture"]
