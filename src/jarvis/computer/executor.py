"""Local Windows screenshot and input execution for computer-use providers."""

from __future__ import annotations

import importlib
import platform
import time
from typing import Protocol

from .models import ActionExecutionResult, ComputerAction, ScreenFrame


class ComputerExecutorError(RuntimeError):
    pass


class ComputerExecutor(Protocol):
    def capture_screen(self) -> ScreenFrame: ...

    def execute(self, action: ComputerAction) -> ActionExecutionResult: ...


class MssPyAutoGuiExecutor:
    """Small replaceable Windows bridge: MSS capture + PyAutoGUI input.

    Optional dependencies are imported only when the executor is instantiated so
    normal JARVIS startup remains side-effect free when computer use is disabled.
    MSS is loaded before PyAutoGUI to avoid PyScreeze changing process DPI awareness
    before multi-monitor geometry is captured.
    """

    MAX_TYPED_CHARACTERS = 2000
    MAX_WAIT_SECONDS = 5.0

    def __init__(self) -> None:
        if platform.system() != "Windows":
            raise ComputerExecutorError("local computer use currently requires Windows")
        try:
            self._mss_module = importlib.import_module("mss")
            self._pyautogui = importlib.import_module("pyautogui")
            self._cv2 = importlib.import_module("cv2")
            self._numpy = importlib.import_module("numpy")
        except ImportError as exc:
            raise ComputerExecutorError(
                "computer-use extras are required; install jarvis[computer-use]"
            ) from exc

        self._pyautogui.FAILSAFE = True
        self._pyautogui.PAUSE = 0.05

    def _frame_from_grab(
        self,
        grab,
        *,
        left: int,
        top: int,
        width: int,
        height: int,
    ) -> ScreenFrame:
        pixels = self._numpy.asarray(grab)
        ok, encoded = self._cv2.imencode(".png", pixels)
        if not ok:
            raise ComputerExecutorError("failed to encode desktop screenshot as PNG")
        return ScreenFrame(
            png_bytes=encoded.tobytes(),
            left=int(left),
            top=int(top),
            width=int(width),
            height=int(height),
        )

    def capture_screen(self) -> ScreenFrame:
        with self._mss_module.mss() as capture:
            monitor = capture.monitors[0]
            grab = capture.grab(monitor)
        return self._frame_from_grab(
            grab,
            left=int(monitor["left"]),
            top=int(monitor["top"]),
            width=int(monitor["width"]),
            height=int(monitor["height"]),
        )

    def capture_region(
        self,
        *,
        left: int,
        top: int,
        width: int,
        height: int,
    ) -> ScreenFrame:
        """Capture one explicit virtual-desktop region instead of the whole desktop."""

        if width <= 0 or height <= 0:
            raise ComputerExecutorError("capture region dimensions must be positive")
        region = {
            "left": int(left),
            "top": int(top),
            "width": int(width),
            "height": int(height),
        }
        with self._mss_module.mss() as capture:
            grab = capture.grab(region)
        return self._frame_from_grab(grab, **region)

    def execute(self, action: ComputerAction) -> ActionExecutionResult:
        name = action.name
        args = action.arguments

        if name == "click":
            self._pyautogui.click(int(args["x"]), int(args["y"]))
        elif name == "double_click":
            self._pyautogui.doubleClick(int(args["x"]), int(args["y"]))
        elif name == "triple_click":
            self._pyautogui.click(int(args["x"]), int(args["y"]), clicks=3)
        elif name == "middle_click":
            self._pyautogui.click(int(args["x"]), int(args["y"]), button="middle")
        elif name == "right_click":
            self._pyautogui.rightClick(int(args["x"]), int(args["y"]))
        elif name == "mouse_down":
            self._pyautogui.moveTo(int(args["x"]), int(args["y"]))
            self._pyautogui.mouseDown()
        elif name == "mouse_up":
            self._pyautogui.moveTo(int(args["x"]), int(args["y"]))
            self._pyautogui.mouseUp()
        elif name == "move":
            self._pyautogui.moveTo(int(args["x"]), int(args["y"]))
        elif name == "type":
            text = str(args.get("text", ""))
            if len(text) > self.MAX_TYPED_CHARACTERS:
                raise ComputerExecutorError(
                    "computer-use typed text exceeds safe limit"
                )
            self._pyautogui.write(text, interval=0.01)
            if bool(args.get("press_enter", False)):
                self._pyautogui.press("enter")
        elif name == "drag_and_drop":
            self._pyautogui.moveTo(int(args["start_x"]), int(args["start_y"]))
            self._pyautogui.dragTo(
                int(args["end_x"]),
                int(args["end_y"]),
                duration=0.35,
                button="left",
            )
        elif name == "drag_path":
            path = list(args.get("path", []))
            if len(path) < 2:
                raise ComputerExecutorError("drag path requires at least two points")
            first = path[0]
            self._pyautogui.moveTo(int(first["x"]), int(first["y"]))
            self._pyautogui.mouseDown()
            try:
                for point in path[1:]:
                    self._pyautogui.moveTo(
                        int(point["x"]),
                        int(point["y"]),
                        duration=0.05,
                    )
            finally:
                self._pyautogui.mouseUp()
        elif name == "wait":
            seconds = float(args.get("seconds", 1))
            if not 0 <= seconds <= self.MAX_WAIT_SECONDS:
                raise ComputerExecutorError("computer-use wait exceeds safe limit")
            time.sleep(seconds)
        elif name == "press_key":
            self._pyautogui.press(self._normalize_key(str(args["key"])))
        elif name == "key_down":
            self._pyautogui.keyDown(self._normalize_key(str(args["key"])))
        elif name == "key_up":
            self._pyautogui.keyUp(self._normalize_key(str(args["key"])))
        elif name == "hotkey":
            keys = [self._normalize_key(str(key)) for key in args.get("keys", [])]
            if not keys:
                raise ComputerExecutorError("hotkey requires at least one key")
            self._pyautogui.hotkey(*keys)
        elif name == "scroll":
            self._pyautogui.moveTo(int(args["x"]), int(args["y"]))
            direction = str(args.get("direction", "down")).casefold()
            magnitude = max(1, int(args.get("magnitude_in_pixels", 300)))
            clicks = max(1, round(magnitude / 120))
            if direction == "up":
                self._pyautogui.scroll(clicks)
            elif direction == "down":
                self._pyautogui.scroll(-clicks)
            elif direction == "left":
                self._pyautogui.hscroll(-clicks)
            elif direction == "right":
                self._pyautogui.hscroll(clicks)
            else:
                raise ComputerExecutorError(
                    f"unsupported scroll direction: {direction}"
                )
        elif name == "scroll_delta":
            self._pyautogui.moveTo(int(args["x"]), int(args["y"]))
            scroll_y = int(args.get("scroll_y", 0))
            scroll_x = int(args.get("scroll_x", 0))
            if scroll_y:
                clicks_y = max(1, round(abs(scroll_y) / 120))
                self._pyautogui.scroll(-clicks_y if scroll_y > 0 else clicks_y)
            if scroll_x:
                clicks_x = max(1, round(abs(scroll_x) / 120))
                self._pyautogui.hscroll(clicks_x if scroll_x > 0 else -clicks_x)
        elif name == "take_screenshot":
            pass
        else:
            raise ComputerExecutorError(f"unsupported computer action: {name}")

        return ActionExecutionResult(ok=True, detail=f"executed:{name}")

    @staticmethod
    def _normalize_key(value: str) -> str:
        aliases = {
            "control": "ctrl",
            "return": "enter",
            "escape": "esc",
            "command": "win",
            "meta": "win",
        }
        normalized = value.strip().casefold()
        return aliases.get(normalized, normalized)
