from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
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


class WindowsSessionUnavailable(RuntimeError):
    pass


class _WtsInfoExLevel1(ctypes.Structure):
    _fields_ = [
        ("session_id", ctypes.c_ulong),
        ("session_state", ctypes.c_int),
        ("session_flags", ctypes.c_long),
        ("win_station_name", ctypes.c_wchar * 33),
        ("user_name", ctypes.c_wchar * 21),
        ("domain_name", ctypes.c_wchar * 18),
        ("logon_time", ctypes.c_longlong),
        ("connect_time", ctypes.c_longlong),
        ("disconnect_time", ctypes.c_longlong),
        ("last_input_time", ctypes.c_longlong),
        ("current_time", ctypes.c_longlong),
        ("incoming_bytes", ctypes.c_ulong),
        ("outgoing_bytes", ctypes.c_ulong),
        ("incoming_frames", ctypes.c_ulong),
        ("outgoing_frames", ctypes.c_ulong),
        ("incoming_compressed_bytes", ctypes.c_ulong),
        ("outgoing_compressed_bytes", ctypes.c_ulong),
    ]


class _WtsInfoExData(ctypes.Union):
    _fields_ = [("level1", _WtsInfoExLevel1)]


class _WtsInfoEx(ctypes.Structure):
    _fields_ = [("level", ctypes.c_ulong), ("data", _WtsInfoExData)]


class WindowsWtsSessionProvider:
    """Read the calling process' Windows session and explicit lock state."""

    _WTS_SESSION_INFO_EX = 25
    _WTS_ACTIVE = 0
    _WTS_SESSIONSTATE_UNLOCK = 1

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock

    def current_session(self) -> AuthoritySession:
        if sys.platform != "win32":
            raise WindowsSessionUnavailable(
                "Windows WTS is unavailable on this platform"
            )
        session_id, active_unlocked = self._read_state()
        return AuthoritySession(
            session_id=f"wts:{session_id}",
            windows_session_id=session_id,
            windows_user_sid_hash=None,
            active_unlocked=active_unlocked,
            generation=0,
            created_at_monotonic=self._clock(),
        )

    @classmethod
    def _read_state(cls) -> tuple[int, bool]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

        session_id = ctypes.c_ulong()
        process_id = ctypes.c_ulong(os.getpid())
        kernel32.ProcessIdToSessionId.argtypes = [
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
        ]
        kernel32.ProcessIdToSessionId.restype = ctypes.c_int
        if not kernel32.ProcessIdToSessionId(process_id, ctypes.byref(session_id)):
            raise WindowsSessionUnavailable("ProcessIdToSessionId failed")

        buffer = ctypes.c_void_p()
        bytes_returned = ctypes.c_ulong()
        wtsapi32.WTSQuerySessionInformationW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        wtsapi32.WTSQuerySessionInformationW.restype = ctypes.c_int
        wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
        wtsapi32.WTSFreeMemory.restype = None

        ok = wtsapi32.WTSQuerySessionInformationW(
            None,
            session_id.value,
            cls._WTS_SESSION_INFO_EX,
            ctypes.byref(buffer),
            ctypes.byref(bytes_returned),
        )
        if not ok or not buffer.value:
            raise WindowsSessionUnavailable("WTSQuerySessionInformationW failed")
        try:
            if bytes_returned.value < ctypes.sizeof(_WtsInfoEx):
                raise WindowsSessionUnavailable("WTS session response is truncated")
            info = ctypes.cast(buffer, ctypes.POINTER(_WtsInfoEx)).contents
            if info.level != 1:
                raise WindowsSessionUnavailable("unsupported WTS session info level")
            level1 = info.data.level1
            active_unlocked = (
                level1.session_state == cls._WTS_ACTIVE
                and level1.session_flags == cls._WTS_SESSIONSTATE_UNLOCK
            )
            return session_id.value, active_unlocked
        finally:
            wtsapi32.WTSFreeMemory(buffer)


class WindowsSessionGuard:
    """Detect security-relevant WTS transitions and invalidate JARVIS authority."""

    def __init__(
        self,
        *,
        provider: WindowsSessionProvider,
        on_invalidate: Callable[[str, SessionSecurityEvent], None],
    ) -> None:
        self._provider = provider
        self._on_invalidate = on_invalidate
        self._previous: AuthoritySession | None = None

    def poll(self) -> AuthoritySession:
        current = self._provider.current_session()
        previous = self._previous
        self._previous = current
        if previous is None:
            return current
        if previous.windows_session_id != current.windows_session_id:
            self._on_invalidate(previous.session_id, SessionSecurityEvent.USER_SWITCH)
        elif previous.active_unlocked and not current.active_unlocked:
            self._on_invalidate(previous.session_id, SessionSecurityEvent.LOCK)
        return current


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
                    time.monotonic() if now_monotonic is None else now_monotonic
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
                    time.monotonic() if now_monotonic is None else now_monotonic
                ),
                invalidation_reason=reason,
            )
            return self._current
