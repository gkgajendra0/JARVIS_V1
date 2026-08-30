from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol


class SessionSecurityEvent(str, Enum):
    LOCK = "lock"
    DISCONNECT = "disconnect"
    LOGOFF = "logoff"
    USER_SWITCH = "user_switch"
    MANUAL_CLEAR = "manual_clear"


@dataclass(frozen=True, slots=True)
class AuthoritySession:
    session_id: str
    windows_session_id: int | None
    windows_user_sid_hash: str | None
    active_unlocked: bool
    generation: int
    created_at_monotonic: float
    invalidated_at_monotonic: float | None = None
    invalidation_reason: SessionSecurityEvent | None = None


class WindowsSessionProvider(Protocol):
    def current_session(self) -> AuthoritySession: ...


class AuthoritySessionManager:
    def __init__(self) -> None:
        self._generation = 0
        self._current: AuthoritySession | None = None
        self._lock = threading.RLock()

    @property
    def current(self) -> AuthoritySession | None:
        with self._lock:
            return self._current

    def start(
        self,
        *,
        windows_session_id: int | None,
        windows_user_sid_hash: str | None,
        now_monotonic: float | None = None,
    ) -> AuthoritySession:
        with self._lock:
            self._generation += 1
            self._current = AuthoritySession(
                session_id=str(uuid.uuid4()),
                windows_session_id=windows_session_id,
                windows_user_sid_hash=windows_user_sid_hash,
                active_unlocked=True,
                generation=self._generation,
                created_at_monotonic=(
                    time.monotonic()
                    if now_monotonic is None
                    else now_monotonic
                ),
            )
            return self._current

    def invalidate(
        self,
        reason: SessionSecurityEvent,
        *,
        now_monotonic: float | None = None,
    ) -> AuthoritySession | None:
        with self._lock:
            if self._current is None:
                return None
            if not self._current.active_unlocked:
                return self._current
            self._current = replace(
                self._current,
                active_unlocked=False,
                invalidated_at_monotonic=(
                    time.monotonic()
                    if now_monotonic is None
                    else now_monotonic
                ),
                invalidation_reason=reason,
            )
            return self._current
