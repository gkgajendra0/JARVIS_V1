"""Operator guidance for the Step 3B.11 active-speaker bake-off.

This module deliberately wraps the diagnostic runner instead of changing its
measurement logic.  It adds an explicit READY -> COUNTDOWN -> CAPTURE protocol so
human actions start at a reproducible point in every A-H trial.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from jarvis.identity import active_speaker_benchmark as benchmark

_COUNTDOWN_SECONDS = 3
_DEFAULT_CAPTURE_SECONDS = 4.0


def _capture_seconds_from_argv(argv: Sequence[str]) -> float:
    for index, value in enumerate(argv):
        if value.startswith("--seconds="):
            try:
                return float(value.split("=", 1)[1])
            except ValueError:
                return _DEFAULT_CAPTURE_SECONDS
        if value == "--seconds" and index + 1 < len(argv):
            try:
                return float(argv[index + 1])
            except ValueError:
                return _DEFAULT_CAPTURE_SECONDS
    return _DEFAULT_CAPTURE_SECONDS


def _scenario_readiness_lines(key: str, duration_seconds: float) -> tuple[str, ...]:
    duration = f"{duration_seconds:.1f}s"
    common = (
        "READY PHASE: this scenario is NOT capturing yet.",
        "Arrange the complete scene first. Do not start the test action yet.",
        (
            "Press Enter only when everything is positioned and ready. Then you get "
            f"a {_COUNTDOWN_SECONDS}-second countdown."
        ),
        f"Begin only at >>> START NOW <<< and stop at >>> STOP NOW <<< ({duration}).",
    )
    actions = {
        "A": "A: Stay visible and silent while preparing. On START NOW, speak naturally and keep speaking.",
        "B": "B: Stay visible and silent. Have TV/off-camera speech paused and ready; start it on START NOW.",
        "C": "C: Stay visible and silent. Do nothing on START NOW; JARVIS playback is automatic.",
        "D": "D: Stay visible and silent. Have your recorded voice ready on the phone; press play on START NOW.",
        "E": "E: You and the other person must already be visible. Other person stays silent; YOU speak on START NOW.",
        "F": "F: You and the other person must already be visible. YOU stay silent; OTHER person speaks on START NOW.",
        "G": "G: Keep both speech sources ready. On START NOW, you and the other/TV speech overlap together.",
        "H": "H: Start speaking on START NOW and keep speaking continuously. Follow the HIDE/SHOW cues printed during capture.",
    }
    return common + (actions[key],)


def _h_cue_schedule(duration_seconds: float) -> tuple[float, float]:
    hide_duration = min(0.8, max(0.6, duration_seconds * 0.175))
    hide_start = max(0.1, (duration_seconds - hide_duration) / 2.0)
    return hide_start, hide_duration


def _print_stop_cue(duration_seconds: float) -> None:
    time.sleep(duration_seconds)
    print("\n  >>> STOP NOW — CAPTURE WINDOW ENDED <<<", flush=True)


def _print_h_timed_cues(duration_seconds: float) -> None:
    hide_start, hide_duration = _h_cue_schedule(duration_seconds)
    time.sleep(hide_start)
    print("\n  >>> HIDE YOUR HEAD NOW — KEEP SPEAKING <<<", flush=True)
    time.sleep(hide_duration)
    print("\n  >>> SHOW YOUR HEAD AGAIN — KEEP SPEAKING <<<", flush=True)
    remaining = max(0.0, duration_seconds - hide_start - hide_duration)
    time.sleep(remaining)
    print("\n  >>> STOP NOW — CAPTURE WINDOW ENDED <<<", flush=True)


def _run_countdown() -> None:
    print()
    print("  Get ready. Do NOT start yet.", flush=True)
    for remaining in range(_COUNTDOWN_SECONDS, 0, -1):
        print(f"  {remaining}...", flush=True)
        time.sleep(1.0)


def _guided_input_factory(
    original_input: Callable[[str], str],
    *,
    duration_seconds: float,
) -> Callable[[str], str]:
    scenario_index = 0

    def guided_input(prompt: str = "") -> str:
        nonlocal scenario_index
        if "Enter=run" not in prompt:
            return original_input(prompt)

        if scenario_index >= len(benchmark.SCENARIOS):
            return original_input(prompt)

        spec = benchmark.SCENARIOS[scenario_index]
        print()
        for line in _scenario_readiness_lines(spec.key, duration_seconds):
            print(f"  {line}")
        response = original_input("  READY? Enter=start countdown, s=skip, q=finish > ")
        normalized = response.strip().casefold()
        scenario_index += 1
        if normalized in {"s", "skip", "q", "quit", "exit"}:
            return response

        _run_countdown()
        print(
            f"  >>> START NOW — CAPTURE IS LIVE ({duration_seconds:.1f}s) <<<",
            flush=True,
        )
        if spec.key == "C":
            print(
                "  Stay silent and visible; JARVIS playback/capture is automatic."
            )
        elif spec.key == "H":
            threading.Thread(
                target=_print_h_timed_cues,
                args=(duration_seconds,),
                name="jarvis-step3b11-h-cues",
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=_print_stop_cue,
                args=(duration_seconds,),
                name=f"jarvis-step3b11-{spec.key}-stop-cue",
                daemon=True,
            ).start()
        return response

    return guided_input


def main() -> None:
    """Run the existing bake-off with deterministic operator-facing trial cues."""
    duration_seconds = _capture_seconds_from_argv(sys.argv[1:])
    original_input: Any = benchmark.__dict__.get("input")
    had_module_input = "input" in benchmark.__dict__
    benchmark.input = _guided_input_factory(input, duration_seconds=duration_seconds)  # type: ignore[attr-defined]
    try:
        benchmark.main()
    finally:
        if had_module_input:
            benchmark.input = original_input  # type: ignore[attr-defined]
        else:
            benchmark.__dict__.pop("input", None)


if __name__ == "__main__":
    main()
