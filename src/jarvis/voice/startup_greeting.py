"""JARVIS-owned startup greeting selection."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from random import SystemRandom

GreetingChooser = Callable[[Sequence[str]], str]

_RANDOM = SystemRandom()

_MORNING_GREETINGS = (
    "Good morning, sir. JARVIS is online.",
    "Morning, sir. Systems are ready.",
    "Good morning. Everything is up and running, sir.",
    "Good morning, sir. At your service.",
    "All systems are operational. Good morning, sir.",
)

_AFTERNOON_GREETINGS = (
    "Good afternoon, sir. JARVIS is online.",
    "Good afternoon, sir. Systems are operational.",
    "Afternoon, sir. Everything is ready.",
    "Good afternoon. At your service, sir.",
    "All systems are ready. Good afternoon, sir.",
)

_EVENING_GREETINGS = (
    "Good evening, sir. JARVIS is online.",
    "Good evening, sir. Everything appears to be in order.",
    "Evening, sir. Systems are ready.",
    "Good evening. At your service, sir.",
    "All systems are operational. Good evening, sir.",
)

_LATE_NIGHT_GREETINGS = (
    "JARVIS online, sir. Systems are ready.",
    "At your service, sir. Everything is operational.",
    "Online and ready, sir.",
    "All systems are standing by, sir.",
    "JARVIS is online and ready, sir.",
)


def select_startup_greeting(
    now: datetime | None = None,
    *,
    chooser: GreetingChooser | None = None,
) -> str:
    """Return one time-appropriate greeting without requiring model generation."""
    local_now = now if now is not None else datetime.now().astimezone()
    hour = local_now.hour

    if 5 <= hour < 12:
        greetings = _MORNING_GREETINGS
    elif 12 <= hour < 17:
        greetings = _AFTERNOON_GREETINGS
    elif 17 <= hour < 22:
        greetings = _EVENING_GREETINGS
    else:
        greetings = _LATE_NIGHT_GREETINGS

    pick = chooser if chooser is not None else _RANDOM.choice
    return pick(greetings)
