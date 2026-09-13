import asyncio
import threading
from types import SimpleNamespace

import pytest

from jarvis.vision.models import BoundingBox
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


def test_saved_windows_profile_can_be_reused_without_ble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    monkeypatch.setattr(
        Pocket3NativeTrackerClient, "_ble_session", fails_after_credentials
    )

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
    monkeypatch.setattr(
        "jarvis.vision.pocket3_recovery.time.sleep", lambda _seconds: None
    )

    client._join_windows_wifi("OsmoPocket3-C36F", "not-a-real-secret")

    assert attempts == 3


def test_a6_waiter_exists_before_fast_reply_can_arrive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    with client._lock:
        client._connected = True

    def immediate_reply_send(
        self: Pocket3NativeTrackerClient,
        *,
        receiver: int,
        flags: int,
        cmd_set: int,
        cmd_id: int,
        payload: bytes,
    ) -> int:
        del receiver, flags, cmd_set, cmd_id, payload
        seq = self._command_seq
        self._command_seq = (self._command_seq + 1) & 0xFFFF
        pending = self._a6_events.get(seq)
        assert pending is not None
        event, holder = pending
        holder.append(b"\x00")
        event.set()
        return seq

    monkeypatch.setattr(
        Pocket3NativeTrackerClient, "_send_command", immediate_reply_send
    )

    assert client.set_target(BoundingBox(0.2, 0.2, 0.6, 0.8)) is True
    assert client._a6_events == {}


def test_close_invalidates_stale_native_tracking_and_wakes_a6_waiters() -> None:
    client = _client()
    waiter = threading.Event()
    with client._lock:
        client._connected = True
        client._tracking_active = True
        client._last_poll_at = 10.0
        client._last_subject_push_at = 10.5
        client._a6_events[123] = (waiter, [])

    client.close()

    status = client.status()
    assert status.connected is False
    assert status.active is False
    assert status.last_poll_at is None
    assert status.last_subject_push_at is None
    assert client._a6_events == {}
    assert waiter.is_set()
