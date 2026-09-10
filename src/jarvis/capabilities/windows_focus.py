"""Reliable foreground-window activation for generic JARVIS Hands.

Windows does not guarantee that foreground state is observable synchronously after
``SetForegroundWindow``. The operating system also owns foreground-stealing policy.
JARVIS therefore requests focus once and polls the actual foreground HWND for a short,
bounded interval instead of treating one immediate snapshot as authoritative.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from jarvis.capabilities.windows_native import (
    PyWin32WindowBackend,
    WindowManagementExecutor,
    WindowSnapshot,
)


class PollingForegroundWindowBackend(PyWin32WindowBackend):
    """Request foreground activation once, then verify eventual Win32 state."""

    def __init__(
        self,
        *,
        verification_timeout_seconds: float = 1.0,
        poll_seconds: float = 0.05,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0.1 <= verification_timeout_seconds <= 3.0:
            raise ValueError("focus verification timeout must be between 0.1 and 3 seconds")
        if not 0.01 <= poll_seconds <= 0.25:
            raise ValueError("focus poll interval must be between 0.01 and 0.25 seconds")
        self._verification_timeout_seconds = float(verification_timeout_seconds)
        self._poll_seconds = float(poll_seconds)
        self._sleeper = sleeper
        self._monotonic = monotonic

    def focus(self, app: str) -> WindowSnapshot:
        _, _, win32con, win32gui, _ = self._modules()
        current = self.snapshot(app)
        if current.iconic:
            win32gui.ShowWindow(current.hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(current.hwnd)

        deadline = self._monotonic() + self._verification_timeout_seconds
        latest = self.snapshot(app)
        while not latest.foreground and self._monotonic() < deadline:
            self._sleeper(self._poll_seconds)
            latest = self.snapshot(app)
        return latest


class ReliableWindowManagementExecutor(WindowManagementExecutor):
    """Production window executor using bounded eventual-state foreground verification."""

    def __init__(self, backend=None) -> None:
        super().__init__(backend or PollingForegroundWindowBackend())
