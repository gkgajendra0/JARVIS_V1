import pytest

from jarvis.vision.pocket3_native import Pocket3NativeConfig, _transport_header
from jarvis.vision.pocket3_recovery import ResilientPocket3NativeTrackerClient


def _client() -> ResilientPocket3NativeTrackerClient:
    return ResilientPocket3NativeTrackerClient(
        Pocket3NativeConfig(ble_name="OsmoPocket3-C36F")
    )


def test_native_status_exposes_last_transport_receive_time() -> None:
    client = _client()

    assert client.status().last_transport_rx_at is None


def test_valid_inbound_transport_updates_receive_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr("jarvis.vision.pocket3_recovery.time.monotonic", lambda: 42.0)
    packet = _transport_header(0x03, 0, 0x1234, 0x2000)

    client._ingest_transport(packet)

    assert client.status().last_transport_rx_at == 42.0


def test_close_clears_transport_receive_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client()
    monkeypatch.setattr("jarvis.vision.pocket3_recovery.time.monotonic", lambda: 42.0)
    packet = _transport_header(0x03, 0, 0x1234, 0x2000)
    client._ingest_transport(packet)
    assert client.status().last_transport_rx_at == 42.0

    client.close()

    assert client.status().last_transport_rx_at is None
