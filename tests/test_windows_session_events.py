from __future__ import annotations

import ctypes
import queue
import threading

import pytest

from jarvis.authority.session import WindowsSessionUnavailable
from jarvis.authority.windows_session_events import (
    WindowsSessionEventMonitor,
    _WindowsSessionWindow,
)


class QueueSessionWindow:
    """Offline stand-in for only the Win32 registration/message-loop boundary."""

    def __init__(self, *, register=True, acknowledge=True):
        self.register = register
        self.acknowledge = acknowledge
        self.messages = queue.Queue()
        self.stopped = threading.Event()

    def run(self, on_ready, on_change, on_barrier):
        try:
            if self.register:
                on_ready()
            while True:
                kind, value = self.messages.get(timeout=2.0)
                if kind == "close":
                    return
                if kind == "failure":
                    raise OSError("controlled listener failure")
                if kind == "security":
                    on_change(value, 1)
                if kind == "barrier" and self.acknowledge:
                    on_barrier(value)
        finally:
            self.stopped.set()

    def post_barrier(self, ticket):
        self.messages.put(("barrier", ticket))

    def request_close(self):
        self.messages.put(("close", None))


def test_security_events_retain_lock_unlock_between_snapshot_reads():
    window = QueueSessionWindow()
    monitor = WindowsSessionEventMonitor(window_factory=lambda: window)
    try:
        first = monitor.generation()
        window.messages.put(("security", 7))  # WTS_SESSION_LOCK
        window.messages.put(("security", 8))  # WTS_SESSION_UNLOCK
        assert monitor.generation() == first + 2
    finally:
        monitor.close()
    assert window.stopped.is_set()


@pytest.mark.parametrize("event", [1, 2, 3, 4, 5, 6, 9, 15])
def test_every_session_change_advances_security_continuity(event):
    window = QueueSessionWindow()
    monitor = WindowsSessionEventMonitor(window_factory=lambda: window)
    try:
        before = monitor.generation()
        window.messages.put(("security", event))
        assert monitor.generation() == before + 1
    finally:
        monitor.close()


@pytest.mark.parametrize("failure", ["not_ready", "not_pumping", "crashed"])
def test_missing_or_unhealthy_listener_cannot_supply_continuity(failure):
    window = QueueSessionWindow(
        register=failure != "not_ready", acknowledge=failure != "not_pumping"
    )
    monitor = WindowsSessionEventMonitor(
        window_factory=lambda: window,
        timeout_seconds=0.05,
    )
    try:
        if failure == "crashed":
            monitor.generation()
            window.messages.put(("failure", None))
        with pytest.raises(WindowsSessionUnavailable):
            monitor.generation()
        # A late registration or queue acknowledgement must not restore trust.
        window.register = window.acknowledge = True
        with pytest.raises(WindowsSessionUnavailable):
            monitor.generation()
    finally:
        monitor.close()
    assert window.stopped.is_set()


def test_close_is_idempotent_and_never_restarts_listener():
    window = QueueSessionWindow()
    monitor = WindowsSessionEventMonitor(window_factory=lambda: window)
    monitor.generation()
    monitor.close()
    monitor.close()
    assert window.stopped.is_set()
    with pytest.raises(WindowsSessionUnavailable):
        monitor.generation()


def test_close_before_start_does_not_create_a_window():
    def forbidden_window():
        pytest.fail("closed monitor created a window")

    monitor = WindowsSessionEventMonitor(window_factory=forbidden_window)
    monitor.close()
    with pytest.raises(WindowsSessionUnavailable):
        monitor.generation()


class NativeFunction:
    def __init__(self, implementation):
        self.implementation = implementation

    def __call__(self, *arguments):
        return self.implementation(*arguments)


def test_native_window_is_message_only_and_unregisters_before_destruction(monkeypatch):
    calls = []
    callback = None
    observed_changes = []
    barriers = []

    def register(window_class):
        nonlocal callback
        callback = window_class._obj.lpfnWndProc
        return 1

    def create(*arguments):
        assert arguments[0] == arguments[3] == 0  # no visible window styles
        assert arguments[8].value == ctypes.c_void_p(-3).value  # HWND_MESSAGE
        calls.append("create_hidden_window")
        return 2

    def receive(*_arguments):
        callback(2, 0x02B1, 7, 1)
        callback(2, 0x02B1, 8, 1)
        callback(2, 0x8001, 42, 0)
        return 0

    def record(name, result=1):
        def invoke(*_arguments):
            calls.append(name)
            return result

        return NativeFunction(invoke)

    user = type("FakeUser32", (), {})()
    for name in (
        "DefWindowProcW",
        "PostMessageW",
        "TranslateMessage",
        "DispatchMessageW",
        "PostQuitMessage",
    ):
        setattr(user, name, record(name))
    user.RegisterClassW = NativeFunction(register)
    user.CreateWindowExW = NativeFunction(create)
    user.GetMessageW = NativeFunction(receive)
    user.DestroyWindow = record("destroy_window")
    user.UnregisterClassW = record("unregister_class")
    kernel = type(
        "FakeKernel32", (), {"GetModuleHandleW": NativeFunction(lambda _: 1)}
    )()
    wts = type("FakeWts", (), {})()

    def subscribe(hwnd, flags):
        assert hwnd == 2 and flags == 0  # NOTIFY_FOR_THIS_SESSION
        calls.append("register_wts")
        return 1

    wts.WTSRegisterSessionNotification = NativeFunction(subscribe)
    wts.WTSUnRegisterSessionNotification = record("unregister_wts")
    libraries = {"user32": user, "kernel32": kernel, "wtsapi32": wts}
    monkeypatch.setattr("jarvis.authority.windows_session_events.sys.platform", "win32")
    monkeypatch.setattr(
        ctypes, "WinDLL", lambda name, **_: libraries[name], raising=False
    )
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    window = _WindowsSessionWindow()
    window.run(
        lambda: calls.append("ready"),
        lambda reason, session: observed_changes.append((reason, session)),
        barriers.append,
    )
    assert observed_changes == [(7, 1), (8, 1)]
    assert barriers == [42]
    assert calls == [
        "create_hidden_window",
        "register_wts",
        "ready",
        "unregister_wts",
        "destroy_window",
        "unregister_class",
    ]
