"""Native Windows capability executors for the JARVIS Hands H1 slice."""

from __future__ import annotations

import asyncio
import platform
import re
import time
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)
from jarvis.computer.structured_windows import (
    AllowlistedWindowsLauncher,
    StructuredWindowsError,
    WinAppCliBackend,
)

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)
_MAX_CLIPBOARD_CHARS = 10_000
_MAX_WINDOWS = 100


class NativeWindowsError(RuntimeError):
    """Raised when a bounded native Windows adapter cannot complete."""


def _contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def _execution_enabled() -> bool:
    return platform.system() == "Windows"


def _approval_preview(text: str, *, limit: int = 120) -> str:
    compact = " ".join(str(text).split())
    preview = compact if len(compact) <= limit else compact[: limit - 3] + "..."
    return f"{preview!r} ({len(str(text))} chars)"


def _audio_summary(operation: str, params: dict[str, Any]) -> str:
    if operation == "set_master_volume":
        return f"Set Windows master volume to {float(params['percent']):g}%"
    if operation == "mute_master_volume":
        return "Mute Windows master output"
    if operation == "unmute_master_volume":
        return "Unmute Windows master output"
    return "Read Windows master volume and mute state"


def _media_summary(operation: str) -> str:
    labels = {
        "get_current_media": "Read current Windows media session and metadata",
        "play_media": "Resume the current Windows media session",
        "pause_media": "Pause the current Windows media session",
        "toggle_media_playback": "Toggle play/pause for the current Windows media session",
        "next_media": "Skip to next item in the current Windows media session",
        "previous_media": "Return to previous item in the current Windows media session",
        "stop_media": "Stop the current Windows media session",
    }
    return labels[operation]


def _clipboard_summary(operation: str, params: dict[str, Any]) -> str:
    if operation == "set_clipboard_text":
        return f"Set Windows clipboard text to {_approval_preview(str(params['text']))}"
    if operation == "clear_clipboard":
        return "Clear Windows clipboard contents"
    return "Read bounded Unicode text from the Windows clipboard"


def _window_summary(operation: str, params: dict[str, Any]) -> str:
    if operation == "list_windows":
        return "List visible top-level Windows application windows"
    app = str(params["app"])
    labels = {
        "focus_window": "Focus",
        "maximize_window": "Maximize",
        "minimize_window": "Minimize",
        "restore_window": "Restore",
        "move_window_to_next_monitor": "Move to next monitor",
    }
    return f"{labels[operation]} Windows app window: {app}"


def _result(
    prepared: PreparedCapability,
    status: CapabilityStatus,
    started: float,
    *,
    data: dict[str, Any] | None = None,
    reason: str | None = None,
    provenance: tuple[str, ...] = (),
) -> CapabilityResult:
    return CapabilityResult(
        status=status,
        capability_key=prepared.request.capability_key,
        operation=prepared.request.operation,
        data=data or {},
        reason=reason,
        elapsed_ms=(time.monotonic() - started) * 1000.0,
        provenance=provenance,
    )


class AudioBackend(Protocol):
    def state(self) -> dict[str, Any]: ...

    def set_volume(self, percent: float) -> None: ...

    def set_mute(self, muted: bool) -> None: ...


class PycawAudioBackend:
    """Windows Core Audio adapter through the mature pycaw library."""

    @staticmethod
    def _device():
        try:
            from pycaw.pycaw import AudioUtilities
        except ImportError as exc:
            raise NativeWindowsError(
                "Windows audio support requires the jarvis[windows-hands] extra"
            ) from exc
        return AudioUtilities.GetSpeakers()

    def state(self) -> dict[str, Any]:
        device = self._device()
        endpoint = device.EndpointVolume
        return {
            "device": str(device.FriendlyName),
            "volume_percent": round(
                float(endpoint.GetMasterVolumeLevelScalar()) * 100.0, 1
            ),
            "muted": bool(endpoint.GetMute()),
        }

    def set_volume(self, percent: float) -> None:
        endpoint = self._device().EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(float(percent) / 100.0, None)

    def set_mute(self, muted: bool) -> None:
        self._device().EndpointVolume.SetMute(bool(muted), None)


class SystemAudioExecutor:
    capability_key = "system:audio"
    operations = (
        "get_master_volume",
        "mute_master_volume",
        "set_master_volume",
        "unmute_master_volume",
    )

    def __init__(self, backend: AudioBackend | None = None) -> None:
        self._backend = backend or PycawAudioBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="audio",
            source_id="system",
            kind=CapabilityKind.NATIVE_API,
            name="Windows system audio",
            description="Native Windows master-volume and mute control through Core Audio.",
            operations=list(self.operations),
            metadata={"backend": "pycaw / Windows Core Audio"},
            execution_enabled=_execution_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise ValueError("unsupported system audio operation")
        params: dict[str, Any] = {}
        attributes = ActionAttributes()
        if request.operation == "set_master_volume":
            percent = float(request.parameters.get("percent"))
            if not 0.0 <= percent <= 100.0:
                raise ValueError("volume percent must be between 0 and 100")
            params["percent"] = percent
            attributes = ActionAttributes(reversible_local_change=True)
        elif request.operation in {"mute_master_volume", "unmute_master_volume"}:
            attributes = ActionAttributes(reversible_local_change=True)
        return PreparedCapability(
            request=request,
            target={"device": "default_output", "domain": "system.audio"},
            parameters=params,
            material_summary=_audio_summary(request.operation, params),
            attributes=attributes,
            execution_payload=params,
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            operation = prepared.request.operation
            if operation == "set_master_volume":
                self._backend.set_volume(float(prepared.execution_payload["percent"]))
            elif operation == "mute_master_volume":
                self._backend.set_mute(True)
            elif operation == "unmute_master_volume":
                self._backend.set_mute(False)
            state = self._backend.state()
        except (NativeWindowsError, OSError, RuntimeError) as exc:
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("Windows Core Audio via pycaw",),
            )

        verified = True
        if operation == "set_master_volume":
            verified = (
                abs(
                    float(state["volume_percent"])
                    - float(prepared.execution_payload["percent"])
                )
                <= 1.0
            )
        elif operation == "mute_master_volume":
            verified = bool(state["muted"])
        elif operation == "unmute_master_volume":
            verified = not bool(state["muted"])
        if not verified:
            return _result(
                prepared,
                CapabilityStatus.FAILED,
                started,
                data={"state": state, "verification_passed": False},
                reason="post-action audio verification failed",
                provenance=("Windows Core Audio via pycaw",),
            )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED,
            started,
            data={"state": state, "verification_passed": True},
            provenance=("Windows Core Audio via pycaw",),
        )


class MediaBackend(Protocol):
    def current(self) -> dict[str, Any]: ...

    def control(self, action: str) -> bool: ...


class WinRtMediaBackend:
    """Global Windows media-session adapter through modular PyWinRT bindings."""

    @staticmethod
    async def _manager():
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager,
            )
        except ImportError as exc:
            raise NativeWindowsError(
                "Windows media support requires the jarvis[windows-hands] extra"
            ) from exc
        return await GlobalSystemMediaTransportControlsSessionManager.request_async()

    @classmethod
    async def _session(cls):
        manager = await cls._manager()
        session = manager.get_current_session()
        if session is None:
            raise NativeWindowsError("no active Windows media session is available")
        return session

    @staticmethod
    def _playback_status(session) -> str:
        info = session.get_playback_info()
        value = info.playback_status
        return str(getattr(value, "name", value)).casefold()

    @classmethod
    async def _current_async(cls) -> dict[str, Any]:
        session = await cls._session()
        props = await session.try_get_media_properties_async()
        return {
            "source_app_user_model_id": str(session.source_app_user_model_id),
            "playback_status": cls._playback_status(session),
            "title": str(getattr(props, "title", "") or ""),
            "artist": str(getattr(props, "artist", "") or ""),
            "album_title": str(getattr(props, "album_title", "") or ""),
        }

    @classmethod
    async def _control_async(cls, action: str) -> bool:
        session = await cls._session()
        method_name = {
            "play": "try_play_async",
            "pause": "try_pause_async",
            "toggle": "try_toggle_play_pause_async",
            "next": "try_skip_next_async",
            "previous": "try_skip_previous_async",
            "stop": "try_stop_async",
        }.get(action)
        if method_name is None:
            raise NativeWindowsError(f"unsupported media action: {action}")
        return bool(await getattr(session, method_name)())

    def current(self) -> dict[str, Any]:
        return asyncio.run(self._current_async())

    def control(self, action: str) -> bool:
        return asyncio.run(self._control_async(action))


class MediaPlaybackExecutor:
    capability_key = "media:playback"
    operations = (
        "get_current_media",
        "next_media",
        "pause_media",
        "play_media",
        "previous_media",
        "stop_media",
        "toggle_media_playback",
    )
    _ACTIONS: ClassVar[dict[str, str]] = {
        "next_media": "next",
        "pause_media": "pause",
        "play_media": "play",
        "previous_media": "previous",
        "stop_media": "stop",
        "toggle_media_playback": "toggle",
    }

    def __init__(self, backend: MediaBackend | None = None) -> None:
        self._backend = backend or WinRtMediaBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="playback",
            source_id="media",
            kind=CapabilityKind.NATIVE_API,
            name="Windows media playback",
            description="Control and inspect the current Global System Media session.",
            operations=list(self.operations),
            metadata={"backend": "Windows.Media.Control via PyWinRT"},
            execution_enabled=_execution_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise ValueError("unsupported media playback operation")
        attributes = (
            ActionAttributes(private_read=True)
            if request.operation == "get_current_media"
            else ActionAttributes(reversible_local_change=True)
        )
        return PreparedCapability(
            request=request,
            target={"session": "current", "domain": "media.playback"},
            parameters={},
            material_summary=_media_summary(request.operation),
            attributes=attributes,
            execution_payload={},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            operation = prepared.request.operation
            accepted = True
            if operation != "get_current_media":
                accepted = self._backend.control(self._ACTIONS[operation])
            state = self._backend.current()
        except (NativeWindowsError, OSError, RuntimeError) as exc:
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("Windows Global System Media Transport Controls",),
            )
        if not accepted:
            return _result(
                prepared,
                CapabilityStatus.FAILED,
                started,
                data={"state": state, "verification_passed": False},
                reason="Windows media session rejected the requested control",
                provenance=("Windows Global System Media Transport Controls",),
            )
        expected = {
            "pause_media": "paused",
            "play_media": "playing",
            "stop_media": "stopped",
        }.get(operation)
        status = str(state.get("playback_status", "")).casefold()
        verified = expected is None or expected in status
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED if verified else CapabilityStatus.FAILED,
            started,
            data={"state": state, "verification_passed": verified},
            reason=None if verified else "post-action media verification failed",
            provenance=("Windows Global System Media Transport Controls",),
        )


class ClipboardBackend(Protocol):
    def get_text(self) -> str: ...

    def set_text(self, text: str) -> None: ...

    def clear(self) -> None: ...


class PyWin32ClipboardBackend:
    @staticmethod
    def _module():
        try:
            import win32clipboard
        except ImportError as exc:
            raise NativeWindowsError(
                "Windows clipboard support requires the jarvis[windows-hands] extra"
            ) from exc
        return win32clipboard

    def get_text(self) -> str:
        api = self._module()
        api.OpenClipboard()
        try:
            if not api.IsClipboardFormatAvailable(api.CF_UNICODETEXT):
                return ""
            return str(api.GetClipboardData(api.CF_UNICODETEXT))
        finally:
            api.CloseClipboard()

    def set_text(self, text: str) -> None:
        api = self._module()
        api.OpenClipboard()
        try:
            api.EmptyClipboard()
            api.SetClipboardText(text, api.CF_UNICODETEXT)
        finally:
            api.CloseClipboard()

    def clear(self) -> None:
        api = self._module()
        api.OpenClipboard()
        try:
            api.EmptyClipboard()
        finally:
            api.CloseClipboard()


class ClipboardExecutor:
    capability_key = "system:clipboard"
    operations = ("clear_clipboard", "get_clipboard_text", "set_clipboard_text")

    def __init__(self, backend: ClipboardBackend | None = None) -> None:
        self._backend = backend or PyWin32ClipboardBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="clipboard",
            source_id="system",
            kind=CapabilityKind.NATIVE_API,
            name="Windows clipboard",
            description="Bounded Unicode clipboard reads and reversible clipboard writes.",
            operations=list(self.operations),
            metadata={"backend": "Win32 clipboard via pywin32"},
            execution_enabled=_execution_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise ValueError("unsupported clipboard operation")
        params: dict[str, Any] = {}
        attributes = ActionAttributes(reversible_local_change=True)
        if request.operation == "get_clipboard_text":
            attributes = ActionAttributes(private_read=True)
        elif request.operation == "set_clipboard_text":
            text = str(request.parameters.get("text", ""))
            if not text or len(text) > _MAX_CLIPBOARD_CHARS:
                raise ValueError(
                    "clipboard text must be non-empty and at most 10000 chars"
                )
            if _contains_secret(text):
                raise ValueError(
                    "credential-like text cannot be placed on the clipboard"
                )
            params["text"] = text
        return PreparedCapability(
            request=request,
            target={"clipboard": "windows", "format": "unicode_text"},
            parameters=params,
            material_summary=_clipboard_summary(request.operation, params),
            attributes=attributes,
            execution_payload=params,
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            operation = prepared.request.operation
            if operation == "set_clipboard_text":
                self._backend.set_text(str(prepared.execution_payload["text"]))
            elif operation == "clear_clipboard":
                self._backend.clear()
            text = self._backend.get_text()
        except (NativeWindowsError, OSError, RuntimeError) as exc:
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("Win32 clipboard via pywin32",),
            )
        if _contains_secret(text):
            return _result(
                prepared,
                CapabilityStatus.DENIED,
                started,
                reason="clipboard contains credential-like content and was withheld",
                provenance=("Win32 clipboard via pywin32",),
            )
        expected = str(prepared.execution_payload.get("text", ""))
        verified = (
            text == expected
            if operation == "set_clipboard_text"
            else text == ""
            if operation == "clear_clipboard"
            else True
        )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED if verified else CapabilityStatus.FAILED,
            started,
            data={"text": text, "verification_passed": verified},
            reason=None if verified else "post-action clipboard verification failed",
            provenance=("Win32 clipboard via pywin32",),
        )


@dataclass(frozen=True, slots=True)
class WindowSnapshot:
    hwnd: int
    title: str
    process: str
    rect: tuple[int, int, int, int]
    visible: bool
    iconic: bool
    zoomed: bool
    foreground: bool

    def payload(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "process": self.process,
            "rect": list(self.rect),
            "visible": self.visible,
            "iconic": self.iconic,
            "zoomed": self.zoomed,
            "foreground": self.foreground,
        }


class WindowBackend(Protocol):
    def list_windows(self) -> list[WindowSnapshot]: ...

    def snapshot(self, app: str) -> WindowSnapshot: ...

    def focus(self, app: str) -> WindowSnapshot: ...

    def show(self, app: str, state: str) -> WindowSnapshot: ...

    def move_next_monitor(self, app: str) -> dict[str, Any]: ...


class PyWin32WindowBackend:
    @staticmethod
    def _modules():
        try:
            import psutil
            import win32api
            import win32con
            import win32gui
            import win32process
        except ImportError as exc:
            raise NativeWindowsError(
                "Windows window support requires the jarvis[windows-hands] extra"
            ) from exc
        return psutil, win32api, win32con, win32gui, win32process

    def list_windows(self) -> list[WindowSnapshot]:
        psutil, _, win32con, win32gui, win32process = self._modules()
        foreground = int(win32gui.GetForegroundWindow())
        windows: list[WindowSnapshot] = []

        def collect(hwnd: int, _extra: object) -> None:
            if len(windows) >= _MAX_WINDOWS or not win32gui.IsWindowVisible(hwnd):
                return
            title = str(win32gui.GetWindowText(hwnd) or "").strip()
            if not title:
                return
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                process = str(psutil.Process(pid).name())
            except (OSError, psutil.Error):
                process = "unknown"
            placement = win32gui.GetWindowPlacement(hwnd)
            show_cmd = int(placement[1])
            windows.append(
                WindowSnapshot(
                    hwnd=int(hwnd),
                    title=title,
                    process=process,
                    rect=tuple(int(value) for value in win32gui.GetWindowRect(hwnd)),
                    visible=True,
                    iconic=show_cmd == win32con.SW_SHOWMINIMIZED,
                    zoomed=show_cmd == win32con.SW_SHOWMAXIMIZED,
                    foreground=int(hwnd) == foreground,
                )
            )

        win32gui.EnumWindows(collect, None)
        return windows

    def snapshot(self, app: str) -> WindowSnapshot:
        needle = str(app).strip().casefold()
        if not needle:
            raise NativeWindowsError("window target app must not be empty")
        matches = [
            item
            for item in self.list_windows()
            if needle in item.process.casefold() or needle in item.title.casefold()
        ]
        if not matches:
            raise NativeWindowsError(f"no visible window matched application: {app}")
        matches.sort(key=lambda item: (not item.foreground, item.title.casefold()))
        return matches[0]

    def focus(self, app: str) -> WindowSnapshot:
        _, _, win32con, win32gui, _ = self._modules()
        current = self.snapshot(app)
        if current.iconic:
            win32gui.ShowWindow(current.hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(current.hwnd)
        return self.snapshot(app)

    def show(self, app: str, state: str) -> WindowSnapshot:
        _, _, win32con, win32gui, _ = self._modules()
        current = self.snapshot(app)
        command = {
            "maximize": win32con.SW_MAXIMIZE,
            "minimize": win32con.SW_MINIMIZE,
            "restore": win32con.SW_RESTORE,
        }.get(state)
        if command is None:
            raise NativeWindowsError(f"unsupported window state: {state}")
        win32gui.ShowWindow(current.hwnd, command)
        return self.snapshot(app)

    def move_next_monitor(self, app: str) -> dict[str, Any]:
        _, win32api, win32con, win32gui, _ = self._modules()
        current = self.snapshot(app)
        monitors = win32api.EnumDisplayMonitors()
        if len(monitors) < 2:
            raise NativeWindowsError("a second monitor is not available")
        current_monitor = win32api.MonitorFromWindow(
            current.hwnd, win32con.MONITOR_DEFAULTTONEAREST
        )
        handles = [item[0] for item in monitors]
        try:
            source_index = handles.index(current_monitor)
        except ValueError:
            source_index = 0
        target_index = (source_index + 1) % len(monitors)
        source_info = win32api.GetMonitorInfo(handles[source_index])
        target_info = win32api.GetMonitorInfo(handles[target_index])
        sx1, sy1, _sx2, _sy2 = source_info["Work"]
        tx1, ty1, tx2, ty2 = target_info["Work"]
        left, top, right, bottom = current.rect
        width = max(200, min(right - left, tx2 - tx1))
        height = max(120, min(bottom - top, ty2 - ty1))
        rel_x = max(0, left - sx1)
        rel_y = max(0, top - sy1)
        new_left = min(tx2 - width, tx1 + rel_x)
        new_top = min(ty2 - height, ty1 + rel_y)
        win32gui.SetWindowPos(
            current.hwnd,
            0,
            new_left,
            new_top,
            width,
            height,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        moved = self.snapshot(app)
        return {
            "window": moved.payload(),
            "from_monitor_index": source_index,
            "to_monitor_index": target_index,
        }


class WindowManagementExecutor:
    capability_key = "window:management"
    operations = (
        "focus_window",
        "list_windows",
        "maximize_window",
        "minimize_window",
        "move_window_to_next_monitor",
        "restore_window",
    )

    def __init__(self, backend: WindowBackend | None = None) -> None:
        self._backend = backend or PyWin32WindowBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="management",
            source_id="window",
            kind=CapabilityKind.NATIVE_API,
            name="Windows window management",
            description="Native top-level window discovery, focus, state and monitor moves.",
            operations=list(self.operations),
            metadata={"backend": "Win32 window APIs via pywin32"},
            execution_enabled=_execution_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise ValueError("unsupported window management operation")
        params: dict[str, Any] = {}
        attributes = ActionAttributes(private_read=True)
        if request.operation != "list_windows":
            app = str(request.parameters.get("app", "")).strip()
            if not app or len(app) > 100:
                raise ValueError("window action requires a bounded app name")
            params["app"] = app
            attributes = ActionAttributes(reversible_local_change=True)
        return PreparedCapability(
            request=request,
            target={"domain": "window.management", **params},
            parameters=params,
            material_summary=_window_summary(request.operation, params),
            attributes=attributes,
            execution_payload=params,
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            operation = prepared.request.operation
            verified = True
            if operation == "list_windows":
                windows = [item.payload() for item in self._backend.list_windows()]
                data = {"windows": windows, "verification_passed": True}
            else:
                app = str(prepared.execution_payload["app"])
                if operation == "focus_window":
                    state = self._backend.focus(app)
                    verified = state.foreground
                    data = {"window": state.payload(), "verification_passed": verified}
                elif operation == "maximize_window":
                    state = self._backend.show(app, "maximize")
                    verified = state.zoomed
                    data = {"window": state.payload(), "verification_passed": verified}
                elif operation == "minimize_window":
                    state = self._backend.show(app, "minimize")
                    verified = state.iconic
                    data = {"window": state.payload(), "verification_passed": verified}
                elif operation == "restore_window":
                    state = self._backend.show(app, "restore")
                    verified = not state.iconic and not state.zoomed
                    data = {"window": state.payload(), "verification_passed": verified}
                else:
                    data = self._backend.move_next_monitor(app)
                    verified = data["from_monitor_index"] != data["to_monitor_index"]
                    data["verification_passed"] = verified
        except (NativeWindowsError, OSError, RuntimeError) as exc:
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("Win32 window APIs via pywin32",),
            )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED if verified else CapabilityStatus.FAILED,
            started,
            data=data,
            reason=None if verified else "post-action window verification failed",
            provenance=("Win32 window APIs via pywin32",),
        )


class AppLifecycleBackend(Protocol):
    def open(self, app: str) -> dict[str, Any]: ...


class AllowlistedAppLifecycleBackend:
    """Shell-free app launch plus structured running-state verification."""

    def __init__(self) -> None:
        try:
            self._launcher = AllowlistedWindowsLauncher()
            self._ui = WinAppCliBackend()
        except StructuredWindowsError as exc:
            raise NativeWindowsError(str(exc)) from exc

    def open(self, app: str) -> dict[str, Any]:
        status = self._ui.status(app, check=False)
        launched = False
        if int(status.payload.get("exit_code", 1)) != 0:
            launch = self._launcher.launch(app)
            launched = True
            launch_payload = launch.to_payload()
        else:
            launch_payload = None
        ready = self._ui.wait_until_running(app, timeout_seconds=8.0)
        return {
            "app": app,
            "launched": launched,
            "launch": launch_payload,
            "running": int(ready.payload.get("exit_code", 1)) == 0,
        }


class AppLifecycleExecutor:
    capability_key = "app:lifecycle"
    operations = ("open_app",)

    def __init__(self, backend: AppLifecycleBackend | None = None) -> None:
        self._backend = backend
        self.descriptor = CapabilityDescriptor.create(
            capability_id="lifecycle",
            source_id="app",
            kind=CapabilityKind.NATIVE_API,
            name="Approved application lifecycle",
            description="Shell-free launch and running-state verification for approved apps.",
            operations=list(self.operations),
            metadata={
                "approved_apps": list(AllowlistedWindowsLauncher.supported_apps()),
                "raw_shell": False,
            },
            execution_enabled=_execution_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation != "open_app":
            raise ValueError("unsupported application lifecycle operation")
        app = str(request.parameters.get("app", "")).strip().casefold()
        if app not in AllowlistedWindowsLauncher.supported_apps():
            raise ValueError(f"application is not approved for launch: {app}")
        return PreparedCapability(
            request=request,
            target={"app": app, "domain": "app.lifecycle"},
            parameters={"app": app},
            material_summary=f"Open approved Windows application: {app}",
            attributes=ActionAttributes(reversible_local_change=True),
            execution_payload={"app": app},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            backend = self._backend or AllowlistedAppLifecycleBackend()
            data = backend.open(str(prepared.execution_payload["app"]))
            verified = bool(data.get("running"))
            data["verification_passed"] = verified
        except (
            NativeWindowsError,
            StructuredWindowsError,
            OSError,
            RuntimeError,
        ) as exc:
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=(
                    "JARVIS shell-free allowlisted launcher",
                    "Microsoft winapp",
                ),
            )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED if verified else CapabilityStatus.FAILED,
            started,
            data=data,
            reason=None if verified else "application launch verification failed",
            provenance=("JARVIS shell-free allowlisted launcher", "Microsoft winapp"),
        )
