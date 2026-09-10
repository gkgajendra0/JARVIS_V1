from __future__ import annotations

import asyncio

from jarvis.authority.risk import RiskClassifier
from jarvis.authority.types import RiskClass
from jarvis.capabilities.models import CapabilityRequest, CapabilityStatus
from jarvis.capabilities.windows_devices import (
    BluetoothControlExecutor,
    DisplayControlExecutor,
    PowerSessionExecutor,
    WinRtBluetoothBackend,
)


class FakeDisplay:
    def __init__(self) -> None:
        self.value = 50

    def list_monitors(self):
        return [{"name": "Display 1", "model": "Fake"}]

    def get_brightness(self, display=None):
        del display
        return [self.value]

    def set_brightness(self, percent: int, display=None):
        del display
        self.value = percent
        return [self.value]


class FakeBluetooth:
    def __init__(self) -> None:
        self.paired = False

    def list_devices(self):
        return [
            {
                "name": "Headphones",
                "id": "1",
                "is_paired": self.paired,
                "can_pair": True,
            }
        ]

    def pair(self, name: str):
        self.paired = True
        return {"name": name, "is_paired": True}

    def unpair(self, name: str):
        self.paired = False
        return {"name": name, "is_paired": False}


class FakePower:
    def lock(self):
        return True

    def sleep(self):
        return True

    def sign_out(self):
        return True

    def restart(self):
        return True

    def shutdown(self):
        return True


def request(executor, operation: str, parameters: dict | None = None):
    return CapabilityRequest(
        session_id="device-test",
        capability_key=executor.capability_key,
        operation=operation,
        parameters=parameters or {},
    )


def test_display_brightness_is_reversible_and_verified() -> None:
    executor = DisplayControlExecutor(FakeDisplay())
    prepared = executor.prepare(
        request(executor, "set_display_brightness", {"percent": 35})
    )

    assert prepared.attributes.reversible_local_change is True
    result = executor.execute(prepared)
    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["brightness"] == [35]
    assert result.data["verification_passed"] is True


def test_bluetooth_pairing_is_persistent_and_verified() -> None:
    backend = FakeBluetooth()
    executor = BluetoothControlExecutor(backend)
    prepared = executor.prepare(
        request(executor, "pair_bluetooth_device", {"name": "Headphones"})
    )

    assert prepared.attributes.persistent_write is True
    assert (
        RiskClassifier().classify(prepared.attributes).risk_class
        is RiskClass.PERSISTENT_OR_EXTERNAL
    )
    result = executor.execute(prepared)
    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data["is_paired"] is True
    assert result.data["verification_passed"] is True


def test_winrt_bluetooth_uses_named_aqs_overload() -> None:
    calls: list[str] = []

    class BluetoothDevice:
        @staticmethod
        def get_device_selector() -> str:
            return "bluetooth-aqs"

    class DeviceInformation:
        @staticmethod
        async def find_all_async_aqs_filter(selector: str):
            calls.append(selector)
            return ["device"]

        @staticmethod
        async def find_all_async(*_args):
            raise AssertionError("zero-argument projection overload must not be used")

    result = asyncio.run(
        WinRtBluetoothBackend._enumerate_with_aqs(
            BluetoothDevice,
            DeviceInformation,
        )
    )

    assert result == ["device"]
    assert calls == ["bluetooth-aqs"]


def test_bluetooth_listing_is_private_read() -> None:
    executor = BluetoothControlExecutor(FakeBluetooth())
    prepared = executor.prepare(request(executor, "list_bluetooth_devices"))
    assert prepared.attributes.private_read is True


def test_winrt_bluetooth_listing_bridges_running_event_loop(monkeypatch) -> None:
    class Pairing:
        is_paired = True
        can_pair = False

    class Device:
        name = "Headphones"
        id = "device-1"
        pairing = Pairing()

    async def fake_devices():
        return [Device()]

    monkeypatch.setattr(WinRtBluetoothBackend, "_devices", staticmethod(fake_devices))

    async def invoke():
        return WinRtBluetoothBackend().list_devices()

    devices = asyncio.run(invoke())

    assert devices == [
        {
            "name": "Headphones",
            "id": "device-1",
            "is_paired": True,
            "can_pair": False,
        }
    ]


def test_power_lock_is_reversible_but_shutdown_is_critical() -> None:
    executor = PowerSessionExecutor(FakePower())
    lock = executor.prepare(request(executor, "lock_workstation"))
    shutdown = executor.prepare(request(executor, "shutdown_workstation"))

    assert lock.attributes.reversible_local_change is True
    assert (
        RiskClassifier().classify(shutdown.attributes).risk_class is RiskClass.CRITICAL
    )


def test_power_backend_result_is_reported_as_initiated_not_final_state() -> None:
    executor = PowerSessionExecutor(FakePower())
    result = executor.execute(
        executor.prepare(request(executor, "restart_workstation"))
    )

    assert result.status is CapabilityStatus.SUCCEEDED
    assert result.data == {"request_initiated": True, "verification_passed": True}
