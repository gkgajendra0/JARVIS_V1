from __future__ import annotations

import logging
import time
from collections.abc import Callable

from livekit import rtc

from jarvis.voice.audio import SessionAudioInput

LOGGER = logging.getLogger(__name__)


class ObservedSessionAudioInput(SessionAudioInput):
    """Tee accepted canonical session frames to one cheap memory-only observer."""

    def __init__(
        self,
        observer: Callable[[rtc.AudioFrame, float], None],
        *,
        capacity_frames: int = 1_000,
    ) -> None:
        super().__init__(capacity_frames=capacity_frames)
        self._observer = observer

    def push_frame(
        self,
        frame: rtc.AudioFrame,
        *,
        observed_at_monotonic: float | None = None,
    ) -> bool:
        observed_at = (
            time.monotonic() if observed_at_monotonic is None else observed_at_monotonic
        )

        if observed_at < 0:
            raise ValueError("audio observation timestamp must be non-negative")

        accepted = super().push_frame(
            frame,
            observed_at_monotonic=observed_at,
        )

        if not accepted:
            return False

        try:
            self._observer(frame, observed_at)
        except Exception:
            LOGGER.exception(
                "Passive session-audio observer failed; conversation audio continues"
            )

        return True
