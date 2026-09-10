from __future__ import annotations

from pathlib import Path


WINDOWS_NATIVE = Path("src/jarvis/capabilities/windows_native.py")
TESTS = Path("tests/test_windows_native_capabilities.py")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one anchor in {path}, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    WINDOWS_NATIVE,
    '''            windows.append(
                WindowSnapshot(
                    hwnd=int(hwnd),
                    title=title,
                    process=process,
                    rect=tuple(int(value) for value in win32gui.GetWindowRect(hwnd)),
                    visible=True,
                    iconic=bool(win32gui.IsIconic(hwnd)),
                    zoomed=bool(win32gui.IsZoomed(hwnd)),
                    foreground=int(hwnd) == foreground,
                )
            )
''',
    '''            placement = win32gui.GetWindowPlacement(hwnd)
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
''',
)

replace_once(
    WINDOWS_NATIVE,
    '''    def list_windows(self) -> list[WindowSnapshot]:
        psutil, _, _, win32gui, win32process = self._modules()
''',
    '''    def list_windows(self) -> list[WindowSnapshot]:
        psutil, _, win32con, win32gui, win32process = self._modules()
''',
)

TEST_APPEND = r'''


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
'''

text = TESTS.read_text(encoding="utf-8")
if "test_pywin32_window_snapshot_uses_get_window_placement_not_iszoomed" in text:
    raise SystemExit("regression test already exists")
TESTS.write_text(text.rstrip() + TEST_APPEND + "\n", encoding="utf-8")

print("Applied pywin32 GetWindowPlacement compatibility fix and regression test")
