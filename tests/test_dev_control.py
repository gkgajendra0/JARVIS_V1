from __future__ import annotations

import pytest

from jarvis.dev_control import parse_explicit_update_decision


@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "YES",
        "yeah",
        "yep",
        "Jarvis yes",
        "yes please",
        "Yes, sir. I will do it.",
        "Jarvis, yes sir, go ahead.",
        "haan",
        "हाँ",
        "हाँ जी, कर दीजिए।",
    ],
)
def test_spoken_update_decision_accepts_explicit_yes(text: str) -> None:
    assert parse_explicit_update_decision(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "no",
        "NO",
        "nope",
        "nah",
        "Jarvis no",
        "no please",
        "No, sir. Leave it.",
        "nahi",
        "नहीं",
    ],
)
def test_spoken_update_decision_accepts_explicit_no(text: str) -> None:
    assert parse_explicit_update_decision(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "",
        "maybe",
        "maybe yes",
        "do it",
        "sure",
        "okay",
        "I guess so",
        "restart later",
        "yes, but no",
        "yes, do not update",
        "yes, don't update",
        "no, actually yes",
    ],
)
def test_spoken_update_decision_rejects_ambiguous_or_conflicting_speech(
    text: str,
) -> None:
    assert parse_explicit_update_decision(text) is None
