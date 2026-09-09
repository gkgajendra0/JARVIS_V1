from __future__ import annotations

import pytest

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus
from jarvis.capabilities.windows_native import (
    AppLifecycleExecutor,
    ClipboardExecutor,
    MediaPlaybackExecutor,
    SystemAudioExecutor,
    WindowManagementExecutor,
    WindowSnapshot,
)


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
        self.state = WindowSnapshot(
            **{**self.state.__dict__, "foreground": True}
        )
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
    mutation = executor.prepare(
        request(executor, "set_master_volume", {"percent": 25})
    )

    assert read.attributes == ActionAttributes()
    assert mutation.attributes.reversible_local_change is True


def test_audio_set_verifies_final_volume() -> None:
    backend = FakeAudio()
    executor = SystemAudioExecutor(backend)
    prepared = executor.prepare(
        request(executor, "set_master_volume", {"percent": 25})
    )

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
    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["running"] is True


def test_app_lifecycle_rejects_unapproved_application() -> None:
    executor = AppLifecycleExecutor(FakeAppLifecycle())

    with pytest.raises(ValueError, match="not approved"):
        executor.prepare(request(executor, "open_app", {"app": "powershell"}))
