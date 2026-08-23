"""Application composition root for JARVIS V1."""

from __future__ import annotations

import logging


LOGGER = logging.getLogger(__name__)


class JarvisApp:
    """Own the minimal, synchronous JARVIS V1 application lifecycle."""

    def __init__(self) -> None:
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        if self._is_running:
            return
        LOGGER.info("JARVIS V1 starting...")
        self._is_running = True
        LOGGER.info("JARVIS V1 ready.")

    def stop(self) -> None:
        if not self._is_running:
            return
        self._is_running = False
        LOGGER.info("JARVIS V1 stopped.")
