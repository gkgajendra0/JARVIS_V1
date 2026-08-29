from __future__ import annotations

import pytest

from jarvis.dev_control import parse_explicit_update_decision


@pytest.mark.parametrize(
    "text",
    ["yes", "YES", "yeah", "yep", "Jarvis yes", "yes please", "haan", "हाँ"],
)
def test_spoken_update_decision_accepts_explicit_yes(text: str) -> None:
    assert parse_explicit_update_decision(text) is True


@pytest.mark.parametrize(
    "text",
    ["no", "NO", "nope", "nah", "Jarvis no", "no please", "nahi", "नहीं"],
)
def test_spoken_update_decision_accepts_explicit_no(text: str) -> None:
    assert parse_explicit_update_decision(text) is False


@pytest.mark.parametrize(
    "text",
    ["", "maybe", "do it", "sure", "okay", "I guess so", "restart later"],
)
def test_spoken_update_decision_rejects_ambiguous_speech(text: str) -> None:
    assert parse_explicit_update_decision(text) is None
