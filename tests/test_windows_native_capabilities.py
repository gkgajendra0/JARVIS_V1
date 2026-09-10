from __future__ import annotations

import pytest

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus
from jarvis.capabilities.windows_native import (
    AppLifecycleExecutor,
    ClipboardExecutor,
    MediaPlaybackExecutor,
    PycawAudioBackend,
    SystemAudioExecutor,
    WindowManagementExecutor,
    WindowSnapshot,
)


class _FakeEndpointVolume:
    def __init__(self) -> None:
        self.scalar = 0.5
        self.muted = False

    def GetMasterVolumeLevelScalar(self):
        return self.scalar

    def SetMasterVolumeLevelScalar(self, value, _context):
        self.scalar = float(value)

    def GetMute(self):
        return self.muted

    def SetMute(self, muted, _context):
        self.muted = bool(muted)


class _FakeAudioDevice:
    def __init__(self) -> None:
        self.FriendlyName = "Fake speakers"
        self.EndpointVolume = _FakeEndpointVolume()


class _ContractPycawBackend(PycawAudioBackend):
    device = _FakeAudioDevice()

    @staticmethod
    def _device():
        return _ContractPycawBackend.device


def test_pycaw_backend_uses_endpoint_scalar_contract_not_audio_device_convenience_property() -> (
    None
):
    backend = _ContractPycawBackend()

    assert backend.state()["volume_percent"] == 50.0
    backend.set_volume(30.0)
    assert backend.state()["volume_percent"] == 30.0


class FakeAudio:
    def __init__(self) -> None:
        self.percent = 50.0
        self.muted = False

    def state(self):
        return {
            "device": "fake",
            "volume_percent": self.percent,
            "muted": self.muted,
        }

    def set_volume(self, percent: float) -> None:
        self.percent = percent

    def set_mute(self, muted: bool) -> None:
        self.muted = muted


class FakeMedia:
    def __init__(self) -> None:
        self.status = "playing"
        self.action = None

    def current(self):
        return {
            "playback_status": self.status,
            "title": "Song",
            "artist": "Artist",
        }

    def control(self, action: str) -> bool:
        self.action = action
        if action == "pause":
            self.status = "paused"
        elif action == "play":
            self.status = "playing"
        elif action == "stop":
            self.status = "stopped"
        return True


class FakeClipboard:
    def __init__(self) -> None:
        self.text = ""

    def get_text(self) -> str:
        return self.text

    def set_text(self, text: str) -> None:
        self.text = text

    def clear(self) -> None:
        self.text = ""


class FakeWindows:
    def __init__(self) -> None:
        self.state = WindowSnapshot(
            hwnd=1,
            title="Notepad",
            process="notepad.exe",
            rect=(0, 0, 800, 600),
            visible=True,
            iconic=False,
            zoomed=False,
            foreground=False,
        )

    def list_windows(self):
        return [self.state]

    def snapshot(self, app: str):
        del app
        return self.state

    def focus(self, app: str):
        del app
        self.state = WindowSnapshot(**{**self.state.__dict__, "foreground": True})
        return self.state

    def show(self, app: str, state: str):
        del app
        values = self.state.payload()
        values.pop("hwnd")
        values.pop("rect")
        values.pop("visible")
        values.pop("foreground")
        self.state = WindowSnapshot(
            hwnd=1,
            title="Notepad",
            process="notepad.exe",
            rect=(0, 0, 800, 600),
            visible=True,
            iconic=state == "minimize",
            zoomed=state == "maximize",
            foreground=False,
        )
        return self.state

    def move_next_monitor(self, app: str):
        del app
        return {
            "window": self.state.payload(),
            "from_monitor_index": 0,
            "to_monitor_index": 1,
        }


class FakeAppLifecycle:
    def open(self, app: str):
        return {"app": app, "launched": True, "running": True}


def request(executor, operation: str, parameters: dict | None = None):
    return CapabilityRequest(
        session_id="session-1",
        capability_key=executor.capability_key,
        operation=operation,
        parameters=parameters or {},
    )


def test_audio_read_is_routine_but_mutation_is_reversible() -> None:
    executor = SystemAudioExecutor(FakeAudio())

    read = executor.prepare(request(executor, "get_master_volume"))
    mutation = executor.prepare(request(executor, "set_master_volume", {"percent": 25}))

    assert read.attributes == ActionAttributes()
    assert mutation.attributes.reversible_local_change is True
    assert mutation.material_summary == "Set Windows master volume to 25%"


def test_audio_set_verifies_final_volume() -> None:
    backend = FakeAudio()
    executor = SystemAudioExecutor(backend)
    prepared = executor.prepare(request(executor, "set_master_volume", {"percent": 25}))

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["state"]["volume_percent"] == 25
    assert result.data["verification_passed"] is True


def test_audio_rejects_invalid_percent() -> None:
    executor = SystemAudioExecutor(FakeAudio())

    with pytest.raises(ValueError, match="between 0 and 100"):
        executor.prepare(request(executor, "set_master_volume", {"percent": 110}))


def test_media_read_is_private_and_pause_is_reversible() -> None:
    executor = MediaPlaybackExecutor(FakeMedia())

    read = executor.prepare(request(executor, "get_current_media"))
    pause = executor.prepare(request(executor, "pause_media"))

    assert read.attributes.private_read is True
    assert pause.attributes.reversible_local_change is True
    assert pause.material_summary == "Pause the current Windows media session"


def test_media_pause_verifies_playback_state() -> None:
    backend = FakeMedia()
    executor = MediaPlaybackExecutor(backend)

    result = executor.execute(executor.prepare(request(executor, "pause_media")))

    assert result.status is CapabilityStatus.SUCCEEDED
    assert backend.action == "pause"
    assert "paused" in result.data["state"]["playback_status"]


def test_clipboard_set_is_verified() -> None:
    executor = ClipboardExecutor(FakeClipboard())
    prepared = executor.prepare(
        request(executor, "set_clipboard_text", {"text": "BMW service tomorrow"})
    )

    result = executor.execute(prepared)

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["text"] == "BMW service tomorrow"
    assert result.data["verification_passed"] is True
    assert "BMW service tomorrow" in prepared.material_summary
    assert "20 chars" in prepared.material_summary


def test_clipboard_blocks_credential_like_text_before_execution() -> None:
    executor = ClipboardExecutor(FakeClipboard())

    with pytest.raises(ValueError, match="credential-like"):
        executor.prepare(
            request(
                executor,
                "set_clipboard_text",
                {"text": "sk-abcdefghijklmnopqrstuvwxyz123456"},
            )
        )


def test_window_management_verifies_monitor_move() -> None:
    executor = WindowManagementExecutor(FakeWindows())
    prepared = executor.prepare(
        request(executor, "move_window_to_next_monitor", {"app": "notepad"})
    )

    result = executor.execute(prepared)

    assert prepared.attributes.reversible_local_change is True
    assert (
        prepared.material_summary == "Move to next monitor Windows app window: notepad"
    )
    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["from_monitor_index"] == 0
    assert result.data["to_monitor_index"] == 1


def test_list_windows_is_private_read() -> None:
    executor = WindowManagementExecutor(FakeWindows())

    prepared = executor.prepare(request(executor, "list_windows"))
    result = executor.execute(prepared)

    assert prepared.attributes.private_read is True
    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["windows"][0]["title"] == "Notepad"


def test_app_lifecycle_uses_allowlist_and_verifies_running() -> None:
    executor = AppLifecycleExecutor(FakeAppLifecycle())
    prepared = executor.prepare(request(executor, "open_app", {"app": "notepad"}))

    result = executor.execute(prepared)

    assert prepared.attributes.reversible_local_change is True
    assert prepared.material_summary == "Open approved Windows application: notepad"
    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["running"] is True


def test_app_lifecycle_rejects_unapproved_application() -> None:
    executor = AppLifecycleExecutor(FakeAppLifecycle())

    with pytest.raises(ValueError, match="not approved"):
        executor.prepare(request(executor, "open_app", {"app": "powershell"}))


def test_pywin32_window_snapshot_uses_get_window_placement_not_iszoomed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from jarvis.capabilities.windows_native import PyWin32WindowBackend

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def name(self) -> str:
            return "CalculatorApp.exe"

    class FakePsutil:
        class Error(Exception):
            pass

        Process = FakeProcess

    class FakeWin32Con:
        SW_SHOWMINIMIZED = 2
        SW_SHOWMAXIMIZED = 3

    class FakeWin32Gui:
        @staticmethod
        def GetForegroundWindow() -> int:
            return 99

        @staticmethod
        def EnumWindows(callback, extra) -> None:
            callback(99, extra)

        @staticmethod
        def IsWindowVisible(hwnd: int) -> bool:
            return hwnd == 99

        @staticmethod
        def GetWindowText(hwnd: int) -> str:
            return "Calculator" if hwnd == 99 else ""

        @staticmethod
        def GetWindowRect(hwnd: int):
            assert hwnd == 99
            return (0, 0, 800, 600)

        @staticmethod
        def GetWindowPlacement(hwnd: int):
            assert hwnd == 99
            return (0, FakeWin32Con.SW_SHOWMAXIMIZED, (0, 0), (0, 0), (0, 0, 800, 600))

    class FakeWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(hwnd: int):
            assert hwnd == 99
            return (1, 1234)

    backend = PyWin32WindowBackend()
    monkeypatch.setattr(
        backend,
        "_modules",
        lambda: (
            FakePsutil,
            object(),
            FakeWin32Con,
            FakeWin32Gui,
            FakeWin32Process,
        ),
    )

    windows = backend.list_windows()

    assert len(windows) == 1
    assert windows[0].title == "Calculator"
    assert windows[0].iconic is False
    assert windows[0].zoomed is True
    assert windows[0].foreground is True
