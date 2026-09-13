import asyncio
from types import SimpleNamespace

import pytest

from jarvis.vision.pocket3_native import Pocket3NativeConfig, Pocket3NativeTrackerClient
from jarvis.vision.pocket3_recovery import (
    Pocket3RecoveryConfig,
    ResilientPocket3NativeTrackerClient,
)


def _client(**recovery_overrides: object) -> ResilientPocket3NativeTrackerClient:
    return ResilientPocket3NativeTrackerClient(
        Pocket3NativeConfig(ble_name="OsmoPocket3-C36F"),
        Pocket3RecoveryConfig(**recovery_overrides),
    )


def test_recovery_config_rejects_non_positive_attempt_counts() -> None:
    with pytest.raises(ValueError, match="ble_attempts"):
        Pocket3RecoveryConfig(ble_attempts=0)
    with pytest.raises(ValueError, match="wifi_join_attempts"):
        Pocket3RecoveryConfig(wifi_join_attempts=0)


def test_saved_windows_profile_can_be_reused_without_ble(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(saved_wifi_wait_seconds=1.0)
    monkeypatch.setattr(
        "jarvis.vision.pocket3_recovery.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        client,
        "_wlan_status",
        lambda: (
            "State                  : connected\n"
            "SSID                   : OsmoPocket3-C36F\n"
        ),
    )

    assert client._join_saved_windows_wifi("OsmoPocket3-C36F") is True


def test_missing_saved_windows_profile_falls_back_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(saved_wifi_wait_seconds=1.0)
    monkeypatch.setattr(
        "jarvis.vision.pocket3_recovery.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )

    assert client._join_saved_windows_wifi("OsmoPocket3-C36F") is False


def test_ble_provisioning_retries_transient_discovery_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        ble_attempts=3,
        ble_retry_pause_seconds=0.001,
    )
    attempts = 0

    async def flaky_ble_session(_self: Pocket3NativeTrackerClient) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient BLE discovery miss")

    monkeypatch.setattr(Pocket3NativeTrackerClient, "_ble_session", flaky_ble_session)

    asyncio.run(client._ble_session())

    assert attempts == 3


def test_ble_does_not_retry_after_credentials_were_delivered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        ble_attempts=3,
        ble_retry_pause_seconds=0.001,
    )
    attempts = 0

    async def fails_after_credentials(_self: Pocket3NativeTrackerClient) -> None:
        nonlocal attempts
        attempts += 1
        client._credentials_ready.set()
        raise RuntimeError("BLE keepalive dropped after provisioning")

    monkeypatch.setattr(Pocket3NativeTrackerClient, "_ble_session", fails_after_credentials)

    with pytest.raises(RuntimeError, match="keepalive"):
        asyncio.run(client._ble_session())

    assert attempts == 1


def test_wifi_association_retries_instead_of_failing_one_shot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(
        wifi_join_attempts=3,
        wifi_retry_pause_seconds=0.001,
    )
    attempts = 0

    monkeypatch.setattr(client, "_wlan_status", lambda: "State : disconnected")

    def flaky_join(
        _self: Pocket3NativeTrackerClient,
        _ssid: str,
        _password: str,
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TimeoutError("association pending")

    monkeypatch.setattr(Pocket3NativeTrackerClient, "_join_windows_wifi", flaky_join)
    monkeypatch.setattr("jarvis.vision.pocket3_recovery.time.sleep", lambda _seconds: None)

    client._join_windows_wifi("OsmoPocket3-C36F", "not-a-real-secret")

    assert attempts == 3
