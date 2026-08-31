from __future__ import annotations

import logging
from collections.abc import Callable

from livekit import rtc

from jarvis.voice.audio import SessionAudioInput

LOGGER = logging.getLogger(__name__)


class ObservedSessionAudioInput(SessionAudioInput):
    """Tee accepted canonical session frames to one cheap memory-only observer."""

    def __init__(
        self,
        observer: Callable[[rtc.AudioFrame], None],
        *,
        capacity_frames: int = 1_000,
    ) -> None:
        super().__init__(capacity_frames=capacity_frames)
        self._observer = observer

    def push_frame(self, frame: rtc.AudioFrame) -> bool:
        accepted = super().push_frame(frame)
        if not accepted:
            return False
        try:
            self._observer(frame)
        except Exception:
            LOGGER.exception(
                "Passive session-audio observer failed; conversation audio continues"
            )
        return True
