"""Owner-presence policy for Windows workstation lock and return wake.

JARVIS may decide when the interactive workstation should be locked, but it does
not become a Windows logon authority.  Unlock remains owned by Winlogon and the
configured Windows credential provider (for example Windows Hello).
"""

from __future__ import annotations

import ctypes
import logging
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from jarvis.vision.owner_reacquisition import ReacquisitionState

LOGGER = logging.getLogger(__name__)

_ES_DISPLAY_REQUIRED = 0x00000002


class WorkstationPresenceAction(str, Enum):
    NONE = "none"
    LOCK_WORKSTATION = "lock_workstation"
    WAKE_DISPLAY = "wake_display"


class WorkstationControl(Protocol):
    def lock(self) -> bool: ...

    def wake_display(self) -> bool: ...


class WindowsWorkstationControl:
    """Small Win32 boundary used by the owner-presence policy."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows workstation control requires Windows")

    def lock(self) -> bool:
        result = ctypes.windll.user32.LockWorkStation()
        return bool(result)

    def wake_display(self) -> bool:
        # A one-shot ES_DISPLAY_REQUIRED request resets the display idle timer and
        # forces the display on. It does not authenticate or unlock the session.
        result = ctypes.windll.kernel32.SetThreadExecutionState(_ES_DISPLAY_REQUIRED)
        return bool(result)


@dataclass(frozen=True, slots=True)
class OwnerWorkstationPresenceConfig:
    lock_after_loss_seconds: float = 5.0
    lock_retry_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.lock_after_loss_seconds <= 0:
            raise ValueError("lock_after_loss_seconds must be positive")
        if self.lock_retry_seconds <= 0:
            raise ValueError("lock_retry_seconds must be positive")


class OwnerWorkstationPresenceController:
    """Lock after confirmed owner departure; wake after confirmed owner return.

    Safety invariants:
    - JARVIS must first have observed a healthy native lock *and* a live OWNER.
    - Native loss alone is insufficient; the live OWNER must also be absent.
    - Short occlusions are absorbed by a grace period.
    - JARVIS never supplies or injects a Windows credential.
    - Return wake occurs only after JARVIS itself initiated the lock cycle and a
      live OWNER is again bound to a healthy native tracking lock.
    """

    def __init__(
        self,
        workstation: WorkstationControl,
        config: OwnerWorkstationPresenceConfig | None = None,
    ) -> None:
        self.workstation = workstation
        self.config = config or OwnerWorkstationPresenceConfig()
        self._ever_confirmed_owner_lock = False
        self._absence_started_at: float | None = None
        self._auto_lock_issued = False
        self._return_wake_issued = False
        self._last_lock_attempt_at: float | None = None

    @property
    def auto_lock_issued(self) -> bool:
        return self._auto_lock_issued

    def reset(self) -> None:
        self._ever_confirmed_owner_lock = False
        self._absence_started_at = None
        self._auto_lock_issued = False
        self._return_wake_issued = False
        self._last_lock_attempt_at = None

    def observe(
        self,
        *,
        now: float,
        tracking_state: ReacquisitionState,
        owner_present: bool,
    ) -> WorkstationPresenceAction:
        if now < 0:
            raise ValueError("now must be non-negative")

        if tracking_state is ReacquisitionState.LOCKED and owner_present:
            self._ever_confirmed_owner_lock = True
            self._absence_started_at = None
            self._last_lock_attempt_at = None
            if self._auto_lock_issued and not self._return_wake_issued:
                self._return_wake_issued = True
                if self.workstation.wake_display():
                    LOGGER.info(
                        "OWNER returned after JARVIS auto-lock; display wake requested. "
                        "Windows Hello/Winlogon remains responsible for unlock"
                    )
                    self._complete_cycle()
                    return WorkstationPresenceAction.WAKE_DISPLAY
                LOGGER.warning(
                    "OWNER returned after JARVIS auto-lock but display wake request failed"
                )
            return WorkstationPresenceAction.NONE

        if self._auto_lock_issued:
            return WorkstationPresenceAction.NONE

        should_count_absence = (
            self._ever_confirmed_owner_lock
            and tracking_state is ReacquisitionState.REACQUIRING
            and not owner_present
        )
        if not should_count_absence:
            self._absence_started_at = None
            self._last_lock_attempt_at = None
            return WorkstationPresenceAction.NONE

        if self._absence_started_at is None:
            self._absence_started_at = now
            return WorkstationPresenceAction.NONE

        if now - self._absence_started_at < self.config.lock_after_loss_seconds:
            return WorkstationPresenceAction.NONE

        if not self._lock_retry_due(now):
            return WorkstationPresenceAction.NONE

        self._last_lock_attempt_at = now
        if not self.workstation.lock():
            LOGGER.warning("JARVIS owner-presence workstation lock request failed")
            return WorkstationPresenceAction.NONE

        self._auto_lock_issued = True
        self._return_wake_issued = False
        LOGGER.info(
            "JARVIS locked the workstation after %.1fs of confirmed OWNER absence",
            now - self._absence_started_at,
        )
        return WorkstationPresenceAction.LOCK_WORKSTATION

    def _lock_retry_due(self, now: float) -> bool:
        attempted_at = self._last_lock_attempt_at
        return (
            attempted_at is None or now - attempted_at >= self.config.lock_retry_seconds
        )

    def _complete_cycle(self) -> None:
        self._auto_lock_issued = False
        self._return_wake_issued = False
        self._absence_started_at = None
        self._last_lock_attempt_at = None
