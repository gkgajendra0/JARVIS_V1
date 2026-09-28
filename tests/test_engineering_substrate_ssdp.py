from __future__ import annotations

import pytest

from jarvis.engineering_substrate.contracts import DiscoveryScope
from jarvis.engineering_substrate.discovery import DiscoveryBroker
from jarvis.engineering_substrate.discovery_ssdp import (
    DEFAULT_SSDP_POLICY,
    SsdpServiceRecord,
    SsdpUpnpAdapter,
)


class FakeSsdpBackend:
    def __init__(self) -> None:
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        return (
            SsdpServiceRecord(
                search_target="upnp:rootdevice",
                usn="uuid:device-1::upnp:rootdevice",
                sender_address="192.168.1.7",
                location="http://192.168.1.7:8008/description.xml",
                server="test-device/1.0 upnp/1.1",
                max_age_seconds=120,
            ),
        )


def test_ssdp_adapter_projects_bounded_local_observation() -> None:
    backend = FakeSsdpBackend()
    adapter = SsdpUpnpAdapter(backend=backend, clock=lambda: 1000.0)
    broker = DiscoveryBroker(
        policies=(DEFAULT_SSDP_POLICY,),
        adapters=(adapter,),
        clock=lambda: 1000.0,
    )
    scope = DiscoveryScope(
        scope_id="scope.ssdp.test",
        adapter_id=SsdpUpnpAdapter.adapter_id,
        protocol="ssdp",
        allowed_service_types=("upnp:rootdevice",),
        allowed_device_types=(),
        local_domain="local.",
        timeout_seconds=1.0,
        max_results=4,
    )

    observations = broker.discover(scope)

    assert len(observations) == 1
    observed = observations[0]
    assert observed.adapter_id == "ssdp_upnp.v1"
    assert "http://192.168.1.7:8008/description.xml" in observed.endpoints
    assert observed.expires_at_epoch == 1120.0
    assert backend.calls[0]["search_targets"] == ("upnp:rootdevice",)


def test_ssdp_policy_rejects_all_target_enumeration() -> None:
    backend = FakeSsdpBackend()
    adapter = SsdpUpnpAdapter(backend=backend)
    broker = DiscoveryBroker(
        policies=(DEFAULT_SSDP_POLICY,),
        adapters=(adapter,),
    )
    scope = DiscoveryScope(
        scope_id="scope.ssdp.all",
        adapter_id=SsdpUpnpAdapter.adapter_id,
        protocol="ssdp",
        allowed_service_types=("ssdp:all",),
        allowed_device_types=(),
        local_domain="local.",
    )

    with pytest.raises(Exception, match="service type exceeds adapter policy"):
        broker.discover(scope)


def test_ssdp_record_drops_public_location_metadata() -> None:
    record = SsdpServiceRecord(
        search_target="upnp:rootdevice",
        usn="uuid:device-2::upnp:rootdevice",
        sender_address="192.168.1.8",
        location="https://8.8.8.8/device.xml",
        server=None,
        max_age_seconds=60,
    )

    assert record.location is None
