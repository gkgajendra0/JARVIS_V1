from __future__ import annotations

import pytest

from jarvis.engineering_substrate import DiscoveryScope, canonical_digest
from jarvis.engineering_substrate.discovery import (
    DiscoveryAdapterError,
    DiscoveryPolicyError,
    default_discovery_broker,
)
from jarvis.engineering_substrate.discovery_onvif import OnvifDeviceRecord


class FakeOnvifBackend:
    def __init__(self, records: tuple[OnvifDeviceRecord, ...]) -> None:
        self.records = records
        self.calls: list[dict[str, object]] = []

    def probe(
        self,
        *,
        device_types: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[OnvifDeviceRecord, ...]:
        self.calls.append(
            {
                "device_types": device_types,
                "local_interface": local_interface,
                "timeout_seconds": timeout_seconds,
                "max_results": max_results,
            }
        )
        return self.records[:max_results]


def _record(
    *,
    address: str = "192.168.1.70",
    endpoint_reference: str = "urn:uuid:hardening-camera",
    scopes: tuple[str, ...] = (
        "onvif://www.onvif.org/type/NetworkVideoTransmitter",
        "onvif://www.onvif.org/name/MainGateCamera",
    ),
) -> OnvifDeviceRecord:
    return OnvifDeviceRecord(
        endpoint_reference=endpoint_reference,
        sender_address=address,
        xaddrs=(f"http://{address}/onvif/device_service",),
        types=("dn:NetworkVideoTransmitter",),
        scopes=scopes,
    )


def _scope(**overrides: object) -> DiscoveryScope:
    values: dict[str, object] = {
        "scope_id": "scope-onvif-camera-1",
        "adapter_id": "onvif_ws_discovery.v1",
        "protocol": "ws_discovery",
        "allowed_service_types": (),
        "allowed_device_types": ("network_video_transmitter",),
        "local_domain": "local.",
        "timeout_seconds": 1,
        "max_results": 4,
    }
    values.update(overrides)
    return DiscoveryScope(**values)  # type: ignore[arg-type]


def test_onvif_adapter_builds_digest_bound_local_observation() -> None:
    backend = FakeOnvifBackend((_record(),))
    broker = default_discovery_broker(
        onvif_backend=backend,
        clock=lambda: 1_000.0,
    )
    scope = _scope()

    observations = broker.discover(scope)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.scope_digest == canonical_digest(scope)
    assert observation.adapter_id == "onvif_ws_discovery.v1"
    assert observation.adapter_version == "stdlib-onvif-wsd-1"
    assert observation.stable_identity.startswith("onvif:")
    assert observation.endpoints == ("http://192.168.1.70/onvif/device_service",)
    assert observation.observed_at_epoch == 1_000.0
    assert observation.expires_at_epoch == 1_060.0
    assert backend.calls == [
        {
            "device_types": ("network_video_transmitter",),
            "local_interface": None,
            "timeout_seconds": 1.0,
            "max_results": 4,
        }
    ]


def test_onvif_policy_refuses_unreviewed_device_type() -> None:
    broker = default_discovery_broker(onvif_backend=FakeOnvifBackend(()))

    with pytest.raises(DiscoveryPolicyError, match="device type exceeds"):
        broker.discover(
            _scope(
                allowed_device_types=("door_controller",),
            )
        )


def test_onvif_adapter_refuses_service_type_enumeration() -> None:
    broker = default_discovery_broker(onvif_backend=FakeOnvifBackend(()))

    with pytest.raises(DiscoveryPolicyError, match="service type exceeds"):
        broker.discover(
            _scope(
                allowed_service_types=("urn:anything",),
            )
        )


def test_onvif_target_hint_only_narrows_results() -> None:
    backend = FakeOnvifBackend(
        (
            _record(
                endpoint_reference="urn:uuid:main-gate",
                address="192.168.1.70",
                scopes=(
                    "onvif://www.onvif.org/type/NetworkVideoTransmitter",
                    "onvif://www.onvif.org/name/MainGateCamera",
                ),
            ),
            _record(
                endpoint_reference="urn:uuid:garage",
                address="192.168.1.71",
                scopes=(
                    "onvif://www.onvif.org/type/NetworkVideoTransmitter",
                    "onvif://www.onvif.org/name/GarageCamera",
                ),
            ),
        )
    )
    broker = default_discovery_broker(
        onvif_backend=backend,
        clock=lambda: 100.0,
    )

    observations = broker.discover(_scope(target_hints=("maingate",)))

    assert len(observations) == 1
    assert observations[0].endpoints == (
        "http://192.168.1.70/onvif/device_service",
    )


def test_onvif_record_rejects_public_device_service() -> None:
    with pytest.raises(ValueError, match="local/private device-service"):
        OnvifDeviceRecord(
            endpoint_reference="urn:uuid:public-camera",
            sender_address="192.168.1.70",
            xaddrs=("http://8.8.8.8/onvif/device_service",),
            types=("dn:NetworkVideoTransmitter",),
            scopes=("onvif://www.onvif.org/type/NetworkVideoTransmitter",),
        )


def test_onvif_record_rejects_non_camera_device() -> None:
    with pytest.raises(ValueError, match="not a network video transmitter"):
        OnvifDeviceRecord(
            endpoint_reference="urn:uuid:door-controller",
            sender_address="192.168.1.72",
            xaddrs=("http://192.168.1.72/onvif/device_service",),
            types=("tds:Device",),
            scopes=("onvif://www.onvif.org/type/DoorController",),
        )


def test_onvif_adapter_rejects_broadened_device_enumeration() -> None:
    class BroadBroker:
        def probe(self, **kwargs):
            del kwargs
            return ()

    from jarvis.engineering_substrate.discovery_onvif import OnvifWsDiscoveryAdapter

    adapter = OnvifWsDiscoveryAdapter(backend=BroadBroker())

    with pytest.raises(DiscoveryAdapterError, match="explicit"):
        adapter.discover(
            _scope(
                allowed_device_types=("network_video_transmitter", "device"),
            )
        )
