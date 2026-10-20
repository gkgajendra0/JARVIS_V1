"""Hidden WTS notifications retain security transitions between boundary reads.

The message-only window registers NOTIFY_FOR_THIS_SESSION; no window is shown.
API contract: https://learn.microsoft.com/windows/win32/termserv/wm-wtssession-change
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import uuid
from collections.abc import Callable
from typing import Protocol

from .session import WindowsSessionUnavailable

_WM_WTSSESSION_CHANGE = 0x02B1
_WM_BARRIER = 0x8001
_WM_CLOSE = 0x0010
LOGGER = logging.getLogger(__name__)


class SessionNotificationWindow(Protocol):
    def run(
        self, on_ready: Callable, on_change: Callable, on_barrier: Callable
    ) -> None: ...
    def post_barrier(self, ticket: int) -> None: ...
    def request_close(self) -> None: ...


class _WindowsSessionWindow:
    """ctypes-only Win32 registration and message pump, owned by its thread."""

    def __init__(self) -> None:
        self._user32 = None
        self._hwnd = None
        self._closing = threading.Event()

    def run(self, on_ready, on_change, on_barrier) -> None:
        if sys.platform != "win32":
            raise WindowsSessionUnavailable("WTS notifications require Windows")
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        wndproc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        class WindowClass(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", wndproc),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostQuitMessage.restype = None
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        wts.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
        wts.WTSRegisterSessionNotification.restype = wintypes.BOOL
        wts.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]
        wts.WTSUnRegisterSessionNotification.restype = wintypes.BOOL
        callback_failed = False

        @wndproc
        def dispatch(hwnd, message, wparam, lparam):
            nonlocal callback_failed
            try:
                if message == _WM_WTSSESSION_CHANGE:
                    on_change(int(wparam), int(lparam))
                    return 0
                if message == _WM_BARRIER:
                    on_barrier(int(wparam))
                    return 0
                if message == _WM_CLOSE:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, message, wparam, lparam)
            except Exception:  # noqa: BLE001 - exceptions cannot cross native callback ABI
                callback_failed = True
                user32.PostQuitMessage(1)
                return 0

        name = f"JarvisSessionEvents-{uuid.uuid4().hex}"
        instance = kernel32.GetModuleHandleW(None)
        window_class = WindowClass(
            lpfnWndProc=dispatch, hInstance=instance, lpszClassName=name
        )
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            raise WindowsSessionUnavailable("WTS window class registration failed")
        registered = False
        try:
            # HWND_MESSAGE (-3) has no visible surface or desktop z-order.
            self._hwnd = user32.CreateWindowExW(
                0,
                name,
                "",
                0,
                0,
                0,
                0,
                0,
                wintypes.HWND(-3),
                None,
                instance,
                None,
            )
            self._user32 = user32
            if not self._hwnd:
                raise WindowsSessionUnavailable(
                    "WTS notification window creation failed"
                )
            if not wts.WTSRegisterSessionNotification(self._hwnd, 0):
                raise WindowsSessionUnavailable("WTS notification registration failed")
            registered = True
            on_ready()
            if self._closing.is_set():
                user32.PostQuitMessage(0)
            message = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise WindowsSessionUnavailable("WTS message pump failed")
                if result == 0:
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            if callback_failed:
                raise WindowsSessionUnavailable("WTS notification callback failed")
        finally:
            if registered:
                wts.WTSUnRegisterSessionNotification(self._hwnd)
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
            self._hwnd = None
            user32.UnregisterClassW(name, instance)

    def _post(self, message: int, value: int = 0) -> None:
        if self._user32 is None or self._hwnd is None:
            raise WindowsSessionUnavailable("WTS notification window is unavailable")
        if not self._user32.PostMessageW(self._hwnd, message, value, 0):
            raise WindowsSessionUnavailable("WTS notification message failed")

    def post_barrier(self, ticket: int) -> None:
        self._post(_WM_BARRIER, ticket)

    def request_close(self) -> None:
        self._closing.set()
        if self._hwnd is not None:
            self._post(_WM_CLOSE)


class WindowsSessionEventMonitor:
    """Lazily own one listener; missing readiness/health permanently fails closed."""

    def __init__(
        self,
        *,
        window_factory: Callable[[], SessionNotificationWindow] = _WindowsSessionWindow,
        timeout_seconds: float = 2.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("session-event timeout must be positive")
        self._window_factory = window_factory
        self._timeout = timeout_seconds
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._window: SessionNotificationWindow | None = None
        self._closed = False
        self._failed = False
        self._healthy = False
        self._epoch = 1
        self._next_ticket = 0
        self._barriers: dict[int, threading.Event] = {}

    def _registered(self) -> None:
        with self._lock:
            self._healthy = not self._closed and not self._failed
            self._ready.set()

    def _changed(self, reason: int, session_id: int) -> None:
        with self._lock:
            self._epoch += 1

    def _acknowledge(self, ticket: int) -> None:
        with self._lock:
            pending = self._barriers.get(ticket)
            if pending is not None:
                pending.set()

    def _run(self) -> None:
        try:
            window = self._window_factory()
            with self._lock:
                self._window = window
                if self._closed:
                    return
            window.run(self._registered, self._changed, self._acknowledge)
        except Exception as exc:  # noqa: BLE001 - listener failures always revoke continuity
            LOGGER.warning(
                "Windows session listener unavailable | failure_class=%s",
                type(exc).__name__,
            )
        finally:
            with self._lock:
                self._healthy = False
                self._failed = True
                self._ready.set()
                for pending in self._barriers.values():
                    pending.set()

    def _require_healthy(self) -> None:
        if self._closed or self._failed or not self._healthy:
            raise WindowsSessionUnavailable("WTS session continuity is unavailable")

    def generation(self) -> int:
        with self._lock:
            if self._closed or self._failed:
                raise WindowsSessionUnavailable("WTS session continuity is unavailable")
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._run, name="jarvis-wts-events", daemon=True
                )
                self._thread.start()
        if not self._ready.wait(self._timeout):
            with self._lock:
                self._failed = True
            raise WindowsSessionUnavailable("WTS session listener readiness timed out")
        with self._lock:
            self._require_healthy()
            self._next_ticket += 1
            ticket = self._next_ticket
            pending = threading.Event()
            self._barriers[ticket] = pending
            window = self._window
        try:
            # Queue a barrier after earlier WTS events; an alive but stalled
            # listener cannot provide an old generation as fresh evidence.
            assert window is not None
            window.post_barrier(ticket)
            if not pending.wait(self._timeout):
                raise WindowsSessionUnavailable(
                    "WTS session listener is not responsive"
                )
            with self._lock:
                self._require_healthy()
                return self._epoch
        except Exception as exc:
            with self._lock:
                self._failed = True
            raise WindowsSessionUnavailable(
                "WTS session continuity is unavailable"
            ) from exc
        finally:
            with self._lock:
                self._barriers.pop(ticket, None)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._healthy = False
            window, thread = self._window, self._thread
        if window is not None and thread is not None and thread.is_alive():
            try:
                window.request_close()
            except WindowsSessionUnavailable:
                # A concurrently exiting pump may already have destroyed HWND.
                LOGGER.debug("Windows session window already unavailable during close")
        if thread is not None:
            thread.join(self._timeout)
            if thread.is_alive():
                raise WindowsSessionUnavailable("WTS session listener did not stop")
