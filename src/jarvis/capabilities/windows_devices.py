"""Windows display, Bluetooth and power/session Hands capabilities."""

from __future__ import annotations

import asyncio
import ctypes
import platform
import time
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol, TypeVar

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityRequest,
    CapabilityResult,
    CapabilityStatus,
)


_T = TypeVar("_T")


class WindowsDeviceValidationError(ValueError):
    pass


def _windows_enabled() -> bool:
    return platform.system() == "Windows"


def _run_async(factory: Callable[[], Coroutine[Any, Any, _T]]) -> _T:
    """Run a WinRT coroutine from synchronous capability code.

    Capability executors are synchronous, but production voice runs them while an
    asyncio event loop is already active. Creating a fresh loop in that thread via
    asyncio.run() is illegal, so use a short-lived worker thread in that case. The
    coroutine is created inside the worker to keep WinRT objects on the same thread.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-winrt") as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


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


class DisplayBackend(Protocol):
    def list_monitors(self) -> list[dict[str, Any]]: ...

    def get_brightness(self, display: str | None = None) -> list[int]: ...

    def set_brightness(self, percent: int, display: str | None = None) -> list[int]: ...


class ScreenBrightnessBackend:
    @staticmethod
    def _module():
        try:
            import screen_brightness_control as sbc
        except ImportError as exc:
            raise WindowsDeviceValidationError(
                "display brightness requires the jarvis[device-hands] extra"
            ) from exc
        return sbc

    def list_monitors(self) -> list[dict[str, Any]]:
        sbc = self._module()
        result: list[dict[str, Any]] = []
        for item in sbc.list_monitors_info(allow_duplicates=False):
            result.append(
                {
                    "name": str(item.get("name") or ""),
                    "model": str(item.get("model") or ""),
                    "serial": str(item.get("serial") or ""),
                    "manufacturer": str(item.get("manufacturer") or ""),
                    "method": getattr(
                        item.get("method"), "__name__", str(item.get("method") or "")
                    ),
                }
            )
        return result

    def get_brightness(self, display: str | None = None) -> list[int]:
        values = self._module().get_brightness(display=display)
        return [int(value) for value in values]

    def set_brightness(self, percent: int, display: str | None = None) -> list[int]:
        sbc = self._module()
        sbc.set_brightness(percent, display=display)
        return self.get_brightness(display)


class DisplayControlExecutor:
    capability_key = "system:display"
    operations = ("get_display_brightness", "list_displays", "set_display_brightness")

    def __init__(self, backend: DisplayBackend | None = None) -> None:
        self._backend = backend or ScreenBrightnessBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="display",
            source_id="system",
            kind=CapabilityKind.NATIVE_API,
            name="Windows display control",
            description="Monitor inventory and hardware-supported brightness control.",
            operations=list(self.operations),
            metadata={
                "backend": "screen-brightness-control",
                "hardware_dependent": True,
            },
            execution_enabled=_windows_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise WindowsDeviceValidationError("unsupported display operation")
        params: dict[str, Any] = {}
        display = str(request.parameters.get("display") or "").strip()
        if display:
            if len(display) > 200:
                raise WindowsDeviceValidationError("display name exceeds bounded limit")
            params["display"] = display
        if request.operation == "set_display_brightness":
            percent = int(request.parameters.get("percent"))
            if not 0 <= percent <= 100:
                raise WindowsDeviceValidationError(
                    "brightness percent must be between 0 and 100"
                )
            params["percent"] = percent
            attributes = ActionAttributes(reversible_local_change=True)
            summary = f"Set display brightness to {percent}%"
        else:
            attributes = ActionAttributes(private_read=True)
            summary = "Read Windows monitor/brightness state"
        return PreparedCapability(
            request=request,
            target={
                "domain": "system.display",
                "display": params.get("display", "default/all"),
            },
            parameters=params,
            material_summary=summary,
            attributes=attributes,
            execution_payload=params,
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            operation = prepared.request.operation
            display = prepared.execution_payload.get("display")
            if operation == "list_displays":
                data = {
                    "displays": self._backend.list_monitors(),
                    "verification_passed": True,
                }
            elif operation == "get_display_brightness":
                data = {
                    "brightness": self._backend.get_brightness(display),
                    "verification_passed": True,
                }
            else:
                percent = int(prepared.execution_payload["percent"])
                values = self._backend.set_brightness(percent, display)
                verified = bool(values) and all(
                    abs(value - percent) <= 2 for value in values
                )
                if not verified:
                    return _result(
                        prepared,
                        CapabilityStatus.FAILED,
                        started,
                        data={"brightness": values, "verification_passed": False},
                        reason="post-action brightness verification failed",
                        provenance=("screen-brightness-control",),
                    )
                data = {"brightness": values, "verification_passed": True}
        except Exception as exc:  # noqa: BLE001 - executor boundary contains OS/backend faults
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("screen-brightness-control",),
            )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED,
            started,
            data=data,
            provenance=("screen-brightness-control",),
        )


class BluetoothBackend(Protocol):
    def list_devices(self) -> list[dict[str, Any]]: ...

    def pair(self, name: str) -> dict[str, Any]: ...

    def unpair(self, name: str) -> dict[str, Any]: ...


class WinRtBluetoothBackend:
    @staticmethod
    async def _devices():
        try:
            from winrt.windows.devices.bluetooth import BluetoothDevice
            from winrt.windows.devices.enumeration import DeviceInformation
        except ImportError as exc:
            raise WindowsDeviceValidationError(
                "Bluetooth Hands requires the jarvis[device-hands] extra"
            ) from exc
        selector = BluetoothDevice.get_device_selector()
        return list(await DeviceInformation.find_all_async(selector))

    @classmethod
    async def _find_unique(cls, name: str):
        devices = await cls._devices()
        needle = name.strip().casefold()
        matches = [
            item for item in devices if str(item.name).strip().casefold() == needle
        ]
        if not matches:
            raise WindowsDeviceValidationError(f"Bluetooth device not found: {name}")
        if len(matches) != 1:
            raise WindowsDeviceValidationError("Bluetooth device name is ambiguous")
        return matches[0]

    def list_devices(self) -> list[dict[str, Any]]:
        async def run():
            result = []
            for item in await self._devices():
                pairing = item.pairing
                result.append(
                    {
                        "name": str(item.name),
                        "id": str(item.id),
                        "is_paired": bool(pairing.is_paired),
                        "can_pair": bool(pairing.can_pair),
                    }
                )
            return result

        return _run_async(run)

    def pair(self, name: str) -> dict[str, Any]:
        async def run():
            item = await self._find_unique(name)
            if item.pairing.is_paired:
                return {
                    "name": str(item.name),
                    "is_paired": True,
                    "already_paired": True,
                }
            if not item.pairing.can_pair:
                raise WindowsDeviceValidationError(
                    "device reports that it cannot be paired"
                )
            result = await item.pairing.pair_async()
            status = str(getattr(result.status, "name", result.status)).casefold()
            refreshed = await self._find_unique(name)
            return {
                "name": str(refreshed.name),
                "is_paired": bool(refreshed.pairing.is_paired),
                "pairing_status": status,
            }

        return _run_async(run)

    def unpair(self, name: str) -> dict[str, Any]:
        async def run():
            item = await self._find_unique(name)
            if not item.pairing.is_paired:
                return {
                    "name": str(item.name),
                    "is_paired": False,
                    "already_unpaired": True,
                }
            result = await item.pairing.unpair_async()
            status = str(getattr(result.status, "name", result.status)).casefold()
            refreshed = await self._find_unique(name)
            return {
                "name": str(refreshed.name),
                "is_paired": bool(refreshed.pairing.is_paired),
                "unpairing_status": status,
            }

        return _run_async(run)


class BluetoothControlExecutor:
    capability_key = "device:bluetooth"
    operations = (
        "list_bluetooth_devices",
        "pair_bluetooth_device",
        "unpair_bluetooth_device",
    )

    def __init__(self, backend: BluetoothBackend | None = None) -> None:
        self._backend = backend or WinRtBluetoothBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="bluetooth",
            source_id="device",
            kind=CapabilityKind.NATIVE_API,
            name="Windows Bluetooth device control",
            description="Enumerate and pair/unpair uniquely named Bluetooth devices via WinRT.",
            operations=list(self.operations),
            metadata={"backend": "Windows.Devices.Enumeration/Bluetooth"},
            execution_enabled=_windows_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise WindowsDeviceValidationError("unsupported Bluetooth operation")
        params: dict[str, Any] = {}
        if request.operation == "list_bluetooth_devices":
            attributes = ActionAttributes(private_read=True)
            summary = "List discoverable Windows Bluetooth devices and pairing state"
        else:
            name = str(request.parameters.get("name") or "").strip()
            if not name or len(name) > 200:
                raise WindowsDeviceValidationError(
                    "Bluetooth mutation requires a bounded device name"
                )
            params["name"] = name
            attributes = ActionAttributes(persistent_write=True)
            summary = f"{request.operation.replace('_', ' ')}: {name}"
        return PreparedCapability(
            request=request,
            target={"domain": "device.bluetooth", **params},
            parameters=params,
            material_summary=summary,
            attributes=attributes,
            execution_payload=params,
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        try:
            if prepared.request.operation == "list_bluetooth_devices":
                data = {
                    "devices": self._backend.list_devices(),
                    "verification_passed": True,
                }
            elif prepared.request.operation == "pair_bluetooth_device":
                data = self._backend.pair(str(prepared.execution_payload["name"]))
                data["verification_passed"] = bool(data.get("is_paired"))
            else:
                data = self._backend.unpair(str(prepared.execution_payload["name"]))
                data["verification_passed"] = not bool(data.get("is_paired"))
            if not data["verification_passed"]:
                return _result(
                    prepared,
                    CapabilityStatus.FAILED,
                    started,
                    data=data,
                    reason="Bluetooth post-action verification failed",
                    provenance=("Windows WinRT device enumeration/pairing",),
                )
        except Exception as exc:  # noqa: BLE001 - executor boundary contains OS/backend faults
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("Windows WinRT device enumeration/pairing",),
            )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED,
            started,
            data=data,
            provenance=("Windows WinRT device enumeration/pairing",),
        )


class PowerBackend(Protocol):
    def lock(self) -> bool: ...

    def sleep(self) -> bool: ...

    def sign_out(self) -> bool: ...

    def restart(self) -> bool: ...

    def shutdown(self) -> bool: ...


class Win32PowerBackend:
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
        return bool(ctypes.windll.user32.ExitWindowsEx(0x00000008, 0))


class PowerSessionExecutor:
    capability_key = "system:power_session"
    operations = (
        "lock_workstation",
        "restart_workstation",
        "shutdown_workstation",
        "sign_out",
        "sleep_workstation",
    )

    def __init__(self, backend: PowerBackend | None = None) -> None:
        self._backend = backend or Win32PowerBackend()
        self.descriptor = CapabilityDescriptor.create(
            capability_id="power_session",
            source_id="system",
            kind=CapabilityKind.NATIVE_API,
            name="Windows power/session control",
            description="Native workstation lock, sleep, sign-out, restart and shutdown requests.",
            operations=list(self.operations),
            metadata={"backend": "Win32 User32/PowrProf", "shell": False},
            execution_enabled=_windows_enabled() or backend is not None,
        )

    def prepare(self, request: CapabilityRequest) -> PreparedCapability:
        if request.operation not in self.operations:
            raise WindowsDeviceValidationError("unsupported power/session operation")
        critical = request.operation != "lock_workstation"
        attributes = (
            ActionAttributes(executable_or_system_change=True)
            if critical
            else ActionAttributes(reversible_local_change=True)
        )
        return PreparedCapability(
            request=request,
            target={"domain": "system.power_session", "machine": "local"},
            parameters={},
            material_summary=request.operation.replace("_", " ").title(),
            attributes=attributes,
            execution_payload={},
        )

    def execute(self, prepared: PreparedCapability) -> CapabilityResult:
        started = time.monotonic()
        method = {
            "lock_workstation": self._backend.lock,
            "sleep_workstation": self._backend.sleep,
            "sign_out": self._backend.sign_out,
            "restart_workstation": self._backend.restart,
            "shutdown_workstation": self._backend.shutdown,
        }[prepared.request.operation]
        try:
            initiated = bool(method())
        except Exception as exc:  # noqa: BLE001 - executor boundary contains OS/backend faults
            return _result(
                prepared,
                CapabilityStatus.UNAVAILABLE,
                started,
                reason=str(exc),
                provenance=("native Windows power/session API",),
            )
        return _result(
            prepared,
            CapabilityStatus.SUCCEEDED if initiated else CapabilityStatus.FAILED,
            started,
            data={"request_initiated": initiated, "verification_passed": initiated},
            reason=None
            if initiated
            else "Windows rejected the requested power/session action",
            provenance=("native Windows power/session API",),
        )
