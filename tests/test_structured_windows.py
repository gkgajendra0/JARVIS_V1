from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from jarvis.computer.structured_windows import (
    AllowlistedWindowsLauncher,
    StructuredWindowsError,
    WinAppCliBackend,
)


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.01
        return self.value


def test_winapp_status_uses_json_and_never_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"app":"Notepad"}',
            stderr="",
        )

    backend = WinAppCliBackend(
        executable=r"C:\Tools\winapp.exe",
        runner=runner,
        monotonic=Clock(),
    )
    result = backend.status("notepad")

    assert result.payload["app"] == "Notepad"
    assert calls[0][0] == [
        r"C:\Tools\winapp.exe",
        "ui",
        "status",
        "-a",
        "notepad",
        "--json",
    ]
    assert calls[0][1]["shell"] is False


def test_wait_until_running_polls_until_winapp_attaches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    responses = [
        subprocess.CompletedProcess(["x"], 1, stdout='{"error":"no app"}', stderr=""),
        subprocess.CompletedProcess(["x"], 0, stdout='{"app":"Notepad"}', stderr=""),
    ]

    def runner(command, **kwargs):
        return responses.pop(0)

    backend = WinAppCliBackend(
        executable="winapp.exe",
        runner=runner,
        sleeper=lambda _: None,
        monotonic=Clock(),
    )

    result = backend.wait_until_running(
        "notepad",
        timeout_seconds=2.0,
        poll_seconds=0.05,
    )

    assert result.payload["app"] == "Notepad"


def test_send_text_is_bounded_and_targets_winapp_send_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}', stderr="")

    backend = WinAppCliBackend(
        executable="winapp.exe",
        runner=runner,
        monotonic=Clock(),
    )
    backend.send_text(
        "notepad",
        "hello world",
        target_selector="Text editor",
    )

    assert calls[0] == [
        "winapp.exe",
        "ui",
        "send-keys",
        "hello world",
        "--verbatim",
        "--via",
        "send-input",
        "--target",
        "Text editor",
        "-a",
        "notepad",
        "--json",
    ]

    with pytest.raises(ValueError, match="exceeds structured automation limit"):
        backend.send_text("notepad", "x" * 501)


def test_winapp_error_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")

    def runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout='{"error":"not found"}',
            stderr="",
        )

    backend = WinAppCliBackend(
        executable="winapp.exe",
        runner=runner,
        monotonic=Clock(),
    )

    with pytest.raises(StructuredWindowsError, match="winapp get_value failed"):
        backend.get_value("notepad", "Text editor")


def test_launcher_allows_only_explicit_app_map(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    calls = []

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(pid=1234)

    launcher = AllowlistedWindowsLauncher(
        popen=popen,
        monotonic=Clock(),
    )
    result = launcher.launch("notepad")

    assert result.payload["pid"] == 1234
    assert calls[0][0] == ["notepad.exe"]
    assert calls[0][1]["shell"] is False

    with pytest.raises(StructuredWindowsError, match="not allow-listed"):
        launcher.launch("powershell")
