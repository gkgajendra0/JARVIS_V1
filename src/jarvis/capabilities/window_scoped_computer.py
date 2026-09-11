"""Window-scoped containment for provider-backed JARVIS computer use.

The provider sees only the target application's current top-level window. Mouse
coordinates are accepted only inside the exact HWND/rectangle that produced the most
recent screenshot, and keyboard input is allowed only while that target remains the
foreground window. This turns screenshot Computer Use into an application-scoped
fallback rather than whole-desktop authority.
"""

from __future__ import annotations

from typing import Protocol

from jarvis.capabilities.windows_focus import PollingForegroundWindowBackend
from jarvis.capabilities.windows_native import WindowSnapshot
from jarvis.computer.executor import (
    ComputerExecutorError,
    MssPyAutoGuiExecutor,
)
from jarvis.computer.models import (
    ActionExecutionResult,
    ComputerAction,
    ScreenFrame,
)

_COORDINATE_ACTIONS = frozenset(
    {
        "click",
        "double_click",
        "triple_click",
        "middle_click",
        "right_click",
        "mouse_down",
        "mouse_up",
        "move",
        "scroll",
        "scroll_delta",
    }
)
_KEYBOARD_ACTIONS = frozenset(
    {"type", "press_key", "key_down", "key_up", "hotkey"}
)
_ALLOWED_ACTIONS = _COORDINATE_ACTIONS | _KEYBOARD_ACTIONS | frozenset(
    {"drag_and_drop", "drag_path", "take_screenshot", "wait"}
)
_GLOBAL_KEYS = frozenset({"win", "windows", "command", "meta"})


class RegionalComputerExecutor(Protocol):
    def capture_region(
        self,
        *,
        left: int,
        top: int,
        width: int,
        height: int,
    ) -> ScreenFrame: ...

    def execute(self, action: ComputerAction) -> ActionExecutionResult: ...


class WindowScopedComputerExecutor:
    """Expose only one installed application's live top-level window to Computer Use."""

    def __init__(
        self,
        app: str,
        *,
        executor: RegionalComputerExecutor | None = None,
        window_backend: PollingForegroundWindowBackend | None = None,
    ) -> None:
        normalized = " ".join(str(app).split())
        if not normalized or len(normalized) > 160:
            raise ValueError("window-scoped computer use requires a bounded app name")
        self._app = normalized
        self._executor = executor or MssPyAutoGuiExecutor()
        self._windows = window_backend or PollingForegroundWindowBackend()
        self._captured_window: WindowSnapshot | None = None

    @property
    def app(self) -> str:
        return self._app

    def _focused_target(self) -> WindowSnapshot:
        current = self._windows.snapshot(self._app)
        if not current.foreground:
            current = self._windows.focus(self._app)
        if not current.foreground:
            raise ComputerExecutorError(
                f"target application did not become foreground: {self._app}"
            )
        if not current.visible or current.iconic:
            raise ComputerExecutorError(
                f"target application is not visibly interactive: {self._app}"
            )
        left, top, right, bottom = current.rect
        if right <= left or bottom <= top:
            raise ComputerExecutorError("target application window has invalid geometry")
        return current

    def capture_screen(self) -> ScreenFrame:
        current = self._focused_target()
        left, top, right, bottom = current.rect
        frame = self._executor.capture_region(
            left=left,
            top=top,
            width=right - left,
            height=bottom - top,
        )
        self._captured_window = current
        return frame

    def _require_same_captured_window(self) -> WindowSnapshot:
        captured = self._captured_window
        if captured is None:
            raise ComputerExecutorError(
                "window-scoped action requires a fresh target-window screenshot"
            )
        current = self._focused_target()
        if current.hwnd != captured.hwnd:
            raise ComputerExecutorError(
                "target application window identity changed after the screenshot"
            )
        if current.rect != captured.rect:
            raise ComputerExecutorError(
                "target application window moved or resized after the screenshot"
            )
        return current

    @staticmethod
    def _point_inside(window: WindowSnapshot, x: int, y: int) -> bool:
        left, top, right, bottom = window.rect
        return left <= x < right and top <= y < bottom

    @classmethod
    def _require_point(
        cls,
        window: WindowSnapshot,
        *,
        x: object,
        y: object,
        label: str,
    ) -> None:
        try:
            resolved_x = int(x)
            resolved_y = int(y)
        except (TypeError, ValueError) as exc:
            raise ComputerExecutorError(
                f"{label} requires integer desktop coordinates"
            ) from exc
        if not cls._point_inside(window, resolved_x, resolved_y):
            raise ComputerExecutorError(
                f"{label} is outside the authorized target application window"
            )

    @classmethod
    def _validate_coordinates(
        cls,
        action: ComputerAction,
        window: WindowSnapshot,
    ) -> None:
        args = action.arguments
        if action.name in _COORDINATE_ACTIONS:
            cls._require_point(
                window,
                x=args.get("x"),
                y=args.get("y"),
                label=action.name,
            )
            return
        if action.name == "drag_and_drop":
            cls._require_point(
                window,
                x=args.get("start_x"),
                y=args.get("start_y"),
                label="drag start",
            )
            cls._require_point(
                window,
                x=args.get("end_x"),
                y=args.get("end_y"),
                label="drag end",
            )
            return
        if action.name == "drag_path":
            path = args.get("path")
            if not isinstance(path, list) or len(path) < 2:
                raise ComputerExecutorError("drag path requires at least two points")
            for index, point in enumerate(path):
                if not isinstance(point, dict):
                    raise ComputerExecutorError("drag path points must be objects")
                cls._require_point(
                    window,
                    x=point.get("x"),
                    y=point.get("y"),
                    label=f"drag path point {index + 1}",
                )

    @staticmethod
    def _normalize_key(value: object) -> str:
        aliases = {
            "control": "ctrl",
            "return": "enter",
            "escape": "esc",
            "command": "win",
            "meta": "win",
            "windows": "win",
        }
        normalized = str(value).strip().casefold()
        return aliases.get(normalized, normalized)

    @classmethod
    def _validate_keyboard(cls, action: ComputerAction) -> None:
        args = action.arguments
        if action.name in {"press_key", "key_down", "key_up"}:
            key = cls._normalize_key(args.get("key"))
            if not key:
                raise ComputerExecutorError("keyboard action requires a key")
            if key in _GLOBAL_KEYS or key == "win":
                raise ComputerExecutorError(
                    "window-scoped computer use cannot invoke the global Windows key"
                )
            return
        if action.name != "hotkey":
            return
        raw_keys = args.get("keys")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise ComputerExecutorError("hotkey requires at least one key")
        keys = [cls._normalize_key(key) for key in raw_keys]
        keyset = set(keys)
        if "win" in keyset:
            raise ComputerExecutorError(
                "window-scoped computer use cannot invoke Windows-key shortcuts"
            )
        if {"alt", "tab"}.issubset(keyset):
            raise ComputerExecutorError(
                "window-scoped computer use cannot switch applications"
            )
        if {"ctrl", "shift", "esc"}.issubset(keyset):
            raise ComputerExecutorError(
                "window-scoped computer use cannot open Task Manager"
            )
        if {"ctrl", "alt", "delete"}.issubset(keyset):
            raise ComputerExecutorError(
                "window-scoped computer use cannot invoke secure-attention shortcuts"
            )

    def execute(self, action: ComputerAction) -> ActionExecutionResult:
        if action.name not in _ALLOWED_ACTIONS:
            raise ComputerExecutorError(
                f"window-scoped computer action is unsupported: {action.name}"
            )
        if action.name == "wait":
            return self._executor.execute(action)

        current = self._require_same_captured_window()
        if action.name in _COORDINATE_ACTIONS or action.name in {
            "drag_and_drop",
            "drag_path",
        }:
            self._validate_coordinates(action, current)
        if action.name in _KEYBOARD_ACTIONS:
            self._validate_keyboard(action)
        return self._executor.execute(action)
