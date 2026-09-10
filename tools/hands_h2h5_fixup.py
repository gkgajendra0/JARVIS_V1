from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected one anchor in {path}, found {count}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_count(path: str, old: str, new: str, *, expected: int) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"expected {expected} anchors in {path}, found {count}")
    file.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "tests/test_local_write_capabilities.py",
    "def test_create_replace_append_text_are_verified(tmp_path: Path) -> None:\n    executor = LocalFileWriteExecutor(roots(tmp_path))",
    "def test_create_replace_append_text_are_verified(tmp_path: Path) -> None:\n    policy = roots(tmp_path)\n    executor = LocalFileWriteExecutor(policy)",
)
replace_once(
    "tests/test_local_write_capabilities.py",
    'assert (roots(tmp_path).root("test") / "note.txt").read_text() == "second + third"',
    'assert (policy.root("test") / "note.txt").read_text() == "second + third"',
)
replace_once(
    "tests/test_windows_control.py",
    'with pytest.raises(ValueError, match="not approved"):\n        executor.prepare(\n            request(\n                {\n                    "app": "powershell",',
    'with pytest.raises(ValueError, match="reserved shell/admin domain"):\n        executor.prepare(\n            request(\n                {\n                    "app": "powershell",',
)
replace_once(
    "tests/test_windows_native_capabilities.py",
    'assert prepared.material_summary == "Open approved Windows application: notepad"',
    'assert prepared.material_summary == "Open Windows application: notepad"',
)
replace_once(
    "tests/test_windows_native_capabilities.py",
    'with pytest.raises(ValueError, match="not approved"):\n        executor.prepare(request(executor, "open_app", {"app": "powershell"}))',
    'with pytest.raises(ValueError, match="reserved shell/admin domain"):\n        executor.prepare(request(executor, "open_app", {"app": "powershell"}))',
)

replace_once(
    "src/jarvis/capabilities/local_writes.py",
    '''        attributes = ActionAttributes(
            persistent_write=True,
            destructive=operation == "trash_path",
        )''',
    '''        destructive = operation == "trash_path" or bool(params.get("overwrite", False))
        attributes = ActionAttributes(
            persistent_write=True,
            destructive=destructive,
        )''',
)
replace_once(
    "src/jarvis/capabilities/local_writes.py",
    '''            if dest.exists() and not overwrite:
                raise LocalWriteValidationError("destination exists and overwrite was not explicit")
            dest.parent.mkdir(parents=True, exist_ok=True)''',
    '''            if dest.exists() and not overwrite:
                raise LocalWriteValidationError("destination exists and overwrite was not explicit")
            if dest.exists() and dest.is_dir() and overwrite:
                raise LocalWriteValidationError(
                    "directory overwrite is blocked; choose a new destination or trash it explicitly"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)''',
)
replace_once(
    "src/jarvis/capabilities/local_writes.py",
    '''            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(source), str(dest))''',
    '''            if dest.exists():
                dest.unlink()
            shutil.move(str(source), str(dest))''',
)

replace_once(
    "src/jarvis/capabilities/browser_playwright.py",
    "        has_click = has_upload = has_download = has_fill = False",
    "        has_click = has_upload = has_download = False",
)
replace_once(
    "src/jarvis/capabilities/browser_playwright.py",
    "                    has_fill = True\n",
    "",
)
replace_once(
    "src/jarvis/capabilities/browser_playwright.py",
    "        except Exception as exc:\n            return CapabilityResult(\n                status=CapabilityStatus.FAILED,",
    "        except Exception as exc:  # noqa: BLE001 - executor boundary contains backend faults\n            return CapabilityResult(\n                status=CapabilityStatus.FAILED,",
)
replace_once(
    "src/jarvis/capabilities/development_git.py",
    "        except Exception as exc:\n            return CapabilityResult(\n                status=CapabilityStatus.FAILED,",
    "        except Exception as exc:  # noqa: BLE001 - executor boundary contains backend faults\n            return CapabilityResult(\n                status=CapabilityStatus.FAILED,",
)
replace_count(
    "src/jarvis/capabilities/windows_devices.py",
    "        except Exception as exc:\n            return _result(",
    "        except Exception as exc:  # noqa: BLE001 - executor boundary contains OS/backend faults\n            return _result(",
    expected=3,
)

replace_once(
    "src/jarvis/capabilities/windows_devices.py",
    '''class Win32PowerBackend:
    def lock(self) -> bool:
        return bool(ctypes.windll.user32.LockWorkStation())

    def sleep(self) -> bool:
        return bool(ctypes.windll.powrprof.SetSuspendState(False, True, False))

    def sign_out(self) -> bool:
        return bool(ctypes.windll.user32.ExitWindowsEx(0x00000000, 0))

    def restart(self) -> bool:
        return bool(ctypes.windll.user32.ExitWindowsEx(0x00000002, 0))

    def shutdown(self) -> bool:
        return bool(ctypes.windll.user32.ExitWindowsEx(0x00000001, 0))''',
    '''class Win32PowerBackend:
    @staticmethod
    def _enable_shutdown_privilege() -> None:
        try:
            import win32api
            import win32con
            import win32security
        except ImportError as exc:
            raise WindowsDeviceValidationError(
                "Windows power/session control requires pywin32"
            ) from exc
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY,
        )
        privilege = win32security.LookupPrivilegeValue(None, "SeShutdownPrivilege")
        win32security.AdjustTokenPrivileges(
            token,
            False,
            [(privilege, win32con.SE_PRIVILEGE_ENABLED)],
        )

    def lock(self) -> bool:
        return bool(ctypes.windll.user32.LockWorkStation())

    def sleep(self) -> bool:
        self._enable_shutdown_privilege()
        return bool(ctypes.windll.powrprof.SetSuspendState(False, False, False))

    def sign_out(self) -> bool:
        return bool(ctypes.windll.user32.ExitWindowsEx(0x00000000, 0))

    def restart(self) -> bool:
        self._enable_shutdown_privilege()
        return bool(ctypes.windll.user32.ExitWindowsEx(0x00000002, 0))

    def shutdown(self) -> bool:
        self._enable_shutdown_privilege()
        return bool(ctypes.windll.user32.ExitWindowsEx(0x00000008, 0))''',
)

replace_once(
    ".github/workflows/code-quality.yml",
    'run: python -m pip install -e ".[dev,phase45d-acceptance]"',
    'run: >-\n          python -m pip install -e\n          ".[dev,phase45d-acceptance,hands-files,hands-documents,browser-hands,development-hands]"',
)
replace_once(
    ".github/workflows/code-quality.yml",
    'run: python -m pip install -e ".[dev,windows-hands]"',
    'run: python -m pip install -e ".[dev,windows-hands,device-hands]"',
)
replace_once(
    ".github/workflows/code-quality.yml",
    '''          import winrt.windows.foundation; import winrt.windows.media.control;
          print('Windows Hands Python dependencies ready')"''',
    '''          import winrt.windows.foundation; import winrt.windows.media.control;
          import winrt.windows.devices.enumeration; import winrt.windows.devices.bluetooth;
          import screen_brightness_control;
          print('Windows Hands Python dependencies ready')"''',
)

print("H2-H5 validation fixup applied")
