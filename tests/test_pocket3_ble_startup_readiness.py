import asyncio
import inspect
from types import SimpleNamespace

import pytest

from jarvis.identity.owner_context import OwnerContextState
from jarvis.vision import pocket3_native
from jarvis.vision.native_owner_tracking import (
    NativeOwnerTrackingConfig,
    NativeOwnerTrackingObserver,
)
from jarvis.vision.pocket3_native import Pocket3NativeConfig, Pocket3NativeTrackerClient
from jarvis.vision.pocket3_recovery import (
    Pocket3RecoveryConfig,
    ResilientPocket3NativeTrackerClient,
)


def test_native_config_rejects_non_positive_ble_ready_timeout() -> None:
    with pytest.raises(ValueError, match="ble_ready_timeout_seconds"):
        Pocket3NativeConfig(ble_ready_timeout_seconds=0.0)


def test_pairing_waits_for_real_protocol_readiness_and_service_settle() -> None:
    source = inspect.getsource(Pocket3NativeTrackerClient._ble_session)

    subscribe = source.index("await client.start_notify(_FFF4, notification_handler)")
    readiness = source.index('stage="protocol readiness"')
    service_settle = source.index('stage="service settle"')
    session_wake = source.index('payload=b"\\x04\\x00"')
    pair_arm = source.index('await client.write_gatt_char(_FFF4, b"\\x01\\x00"')
    pairing = source.index("await self._send_pair_auth_until_confirmed(")

    assert subscribe < readiness < service_settle < session_wake < pair_arm < pairing


def test_ble_event_wait_unwinds_promptly_on_shutdown() -> None:
    client = Pocket3NativeTrackerClient(Pocket3NativeConfig())

    async def run() -> None:
        event = asyncio.Event()
        client._stop.set()
        with pytest.raises(RuntimeError, match="stopped during JARVIS shutdown"):
            await client._wait_for_ble_event(
                event,
                timeout=10.0,
                stage="test wait",
            )

    asyncio.run(run())


def test_ble_service_settle_unwinds_promptly_on_shutdown() -> None:
    client = Pocket3NativeTrackerClient(Pocket3NativeConfig())

    async def run() -> None:
        client._stop.set()
        with pytest.raises(RuntimeError, match="stopped during JARVIS shutdown"):
            await client._wait_for_ble_settle(10.0, stage="test settle")

    asyncio.run(run())


class _FakeGattClient:
    def __init__(
        self,
        pair_event: asyncio.Event,
        pair_request_seen_event: asyncio.Event,
        *,
        confirm_on_auth_attempt: int | None = None,
        request_seen_on_auth_attempt: int | None = None,
        owner_approval_delay_seconds: float = 0.0,
    ) -> None:
        self.pair_event = pair_event
        self.pair_request_seen_event = pair_request_seen_event
        self.confirm_on_auth_attempt = confirm_on_auth_attempt
        self.request_seen_on_auth_attempt = request_seen_on_auth_attempt
        self.owner_approval_delay_seconds = owner_approval_delay_seconds
        self.auth_sequences: list[int] = []

    async def write_gatt_char(
        self,
        _characteristic: str,
        data: bytes,
        response: bool = False,
    ) -> None:
        del response
        if len(data) < 13 or data[9:11] != bytes((0x07, 0x45)):
            return
        self.auth_sequences.append(int.from_bytes(data[6:8], "little"))
        attempt = len(self.auth_sequences)
        if self.confirm_on_auth_attempt == attempt:
            self.pair_event.set()
        if self.request_seen_on_auth_attempt == attempt:
            self.pair_request_seen_event.set()
            asyncio.get_running_loop().call_later(
                self.owner_approval_delay_seconds,
                self.pair_event.set,
            )


def _run_pair_auth(
    monkeypatch: pytest.MonkeyPatch,
    *,
    confirm_on_auth_attempt: int | None = None,
    request_seen_on_auth_attempt: int | None = None,
    owner_approval_delay_seconds: float = 0.0,
) -> list[int]:
    monkeypatch.setattr(pocket3_native, "_BLE_PAIR_AUTH_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(pocket3_native, "_BLE_PAIR_CONFIRM_TIMEOUT_SECONDS", 0.08)
    client = Pocket3NativeTrackerClient(Pocket3NativeConfig())

    async def run() -> list[int]:
        pair_event = asyncio.Event()
        pair_request_seen_event = asyncio.Event()
        fake = _FakeGattClient(
            pair_event,
            pair_request_seen_event,
            confirm_on_auth_attempt=confirm_on_auth_attempt,
            request_seen_on_auth_attempt=request_seen_on_auth_attempt,
            owner_approval_delay_seconds=owner_approval_delay_seconds,
        )
        await client._send_pair_auth_until_confirmed(
            fake,
            pair_event,
            pair_request_seen_event,
        )
        return fake.auth_sequences

    return asyncio.run(run())


def test_pair_auth_stops_after_first_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequences = _run_pair_auth(monkeypatch, confirm_on_auth_attempt=1)

    assert sequences == [0x8092]


def test_pair_auth_retries_dropped_first_write_with_new_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequences = _run_pair_auth(monkeypatch, confirm_on_auth_attempt=2)

    assert sequences == [0x8092, 0x8093]


def test_pair_auth_does_not_retransmit_after_camera_requests_owner_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sequences = _run_pair_auth(
        monkeypatch,
        request_seen_on_auth_attempt=1,
        owner_approval_delay_seconds=0.02,
    )

    assert sequences == [0x8092]


def test_pair_auth_failure_is_bounded_to_three_no_response_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pocket3_native, "_BLE_PAIR_AUTH_RETRY_SECONDS", 0.005)
    monkeypatch.setattr(pocket3_native, "_BLE_PAIR_CONFIRM_TIMEOUT_SECONDS", 0.03)
    client = Pocket3NativeTrackerClient(Pocket3NativeConfig())

    async def run() -> list[int]:
        pair_event = asyncio.Event()
        pair_request_seen_event = asyncio.Event()
        fake = _FakeGattClient(pair_event, pair_request_seen_event)
        with pytest.raises(TimeoutError, match="pairing confirmation timed out"):
            await client._send_pair_auth_until_confirmed(
                fake,
                pair_event,
                pair_request_seen_event,
            )
        return fake.auth_sequences

    assert asyncio.run(run()) == [0x8092, 0x8093, 0x8094]


def test_recovery_default_keeps_ble_retry_batch_bounded() -> None:
    assert Pocket3RecoveryConfig().ble_attempts == 2


def test_ble_retry_loop_does_not_restart_after_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ResilientPocket3NativeTrackerClient(
        Pocket3NativeConfig(),
        Pocket3RecoveryConfig(
            ble_attempts=5,
            ble_retry_pause_seconds=0.001,
        ),
    )
    attempts = 0

    async def stopped_ble_session(_self: Pocket3NativeTrackerClient) -> None:
        nonlocal attempts
        attempts += 1
        client._stop.set()
        raise RuntimeError("shutdown")

    monkeypatch.setattr(Pocket3NativeTrackerClient, "_ble_session", stopped_ble_session)

    with pytest.raises(RuntimeError, match="shutdown"):
        asyncio.run(client._ble_session())

    assert attempts == 1


class _FailingNativeClient:
    def __init__(self) -> None:
        self.connected = False
        self.starts = 0
        self.closed = False

    def start(self) -> None:
        self.starts += 1
        raise RuntimeError("BLE provisioning failed")

    def close(self) -> None:
        self.closed = True


def test_reconnect_backoff_begins_when_failed_attempt_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = OwnerContextState()
    client = _FailingNativeClient()
    observer = NativeOwnerTrackingObserver(
        owner_context=owner,
        client=client,  # type: ignore[arg-type]
        config=NativeOwnerTrackingConfig(reconnect_backoff_seconds=5.0),
    )
    monkeypatch.setattr(
        "jarvis.vision.native_owner_tracking.time.monotonic",
        lambda: 100.0,
    )

    observer.observe(
        SimpleNamespace(captured_at=10.0),  # type: ignore[arg-type]
        SimpleNamespace(tracks=()),  # type: ignore[arg-type]
    )

    assert client.starts == 1
    assert observer._last_connect_attempt_at == 100.0
    assert observer._reconnect_due(104.99) is False
    assert observer._reconnect_due(105.0) is True

    observer.close()
    assert client.closed is True
