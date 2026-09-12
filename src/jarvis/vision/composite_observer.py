"""Small observer composition helper for the integrated vision service."""

from __future__ import annotations

from collections.abc import Iterable

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.observer import VisionObserver
from jarvis.vision.runtime import VisionSnapshot


class CompositeVisionObserver:
    """Fan one frame/snapshot pair out to multiple independent observers."""

    def __init__(self, observers: Iterable[VisionObserver]) -> None:
        self._observers = tuple(observers)

    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        for observer in self._observers:
            observer.observe(frame, snapshot)

    def close(self) -> None:
        first_error: Exception | None = None
        for observer in reversed(self._observers):
            try:
                observer.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
