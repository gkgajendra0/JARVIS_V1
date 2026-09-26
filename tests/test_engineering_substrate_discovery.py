from __future__ import annotations

from dataclasses import replace

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import CapabilityKind, DiscoveryState
from jarvis.engineering_substrate import DiscoveryScope, canonical_digest
from jarvis.engineering_substrate.discovery import (
    DEFAULT_MDNS_POLICY,
    DiscoveryAdapterError,
    DiscoveryAdapterPolicy,
    DiscoveryBroker,
    DiscoveryCapabilitySource,
    DiscoveryPolicyError,
    MdnsDnsSdAdapter,
    MdnsServiceRecord,
    default_discovery_broker,
)


class FakeMdnsBackend:
    def __init__(self, records: tuple[MdnsServiceRecord, ...]) -> None:
        self.records = records
        self.calls: list[dict[str, object]] = []

    def browse(
        self,
        *,
        service_types: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[MdnsServiceRecord, ...]:
        self.calls.append(
            {
                "service_types": service_types,
                "local_interface": local_interface,
                "timeout_seconds": timeout_seconds,
                "max_results": max_results,
            }
        )
        return self.records[:max_results]


def _record(
    *,
    service_type: str = "_googlecast._tcp.local.",
    instance_name: str = "Living Room._googlecast._tcp.local.",
    address: str = "192.168.1.50",
    ttl_seconds: float = 120,
) -> MdnsServiceRecord:
    return MdnsServiceRecord(
        service_type=service_type,
        instance_name=instance_name,
        server="living-room.local.",
        port=8009,
        addresses=(address,),
        ttl_seconds=ttl_seconds,
    )


def _scope(**overrides: object) -> DiscoveryScope:
    values: dict[str, object] = {
        "scope_id": "scope-media-1",
        "adapter_id": "mdns_dns_sd.v1",
        "protocol": "mdns",
        "allowed_service_types": ("_googlecast._tcp.local.",),
        "allowed_device_types": (),
        "local_domain": "local.",
        "timeout_seconds": 1,
        "max_results": 4,
    }
    values.update(overrides)
    return DiscoveryScope(**values)  # type: ignore[arg-type]


def test_mdns_adapter_builds_digest_bound_local_observation() -> None:
    backend = FakeMdnsBackend((_record(),))
    broker = default_discovery_broker(backend=backend, clock=lambda: 1_000.0)
    scope = _scope()

    observations = broker.discover(scope)

    assert len(observations) == 1
    observation = observations[0]
    assert observation.scope_digest == canonical_digest(scope)
    assert observation.adapter_id == "mdns_dns_sd.v1"
    assert observation.adapter_version == "python-zeroconf-0.151.3"
    assert observation.stable_identity.startswith("mdns:")
    assert observation.endpoints == ("tcp://192.168.1.50:8009",)
    assert observation.observed_at_epoch == 1_000.0
    assert observation.expires_at_epoch == 1_120.0
    assert len(backend.calls) == 1
    assert backend.calls[0]["service_types"] == ("_googlecast._tcp.local.",)


def test_scope_cannot_broaden_to_unregistered_service_type() -> None:
    broker = default_discovery_broker(backend=FakeMdnsBackend(()))

    with pytest.raises(DiscoveryPolicyError, match="service type exceeds"):
        broker.discover(_scope(allowed_service_types=("_ssh._tcp.local.",)))


def test_scope_local_interface_cannot_exceed_registered_policy() -> None:
    broker = default_discovery_broker(backend=FakeMdnsBackend(()))

    with pytest.raises(DiscoveryPolicyError, match="local interface exceeds"):
        broker.discover(_scope(local_interface="192.168.1.25"))


def test_registered_local_interface_is_allowed() -> None:
    backend = FakeMdnsBackend(())
    policy = replace(
        DEFAULT_MDNS_POLICY,
        allowed_interfaces=("192.168.1.25",),
    )
    broker = DiscoveryBroker(
        policies=(policy,),
        adapters=(MdnsDnsSdAdapter(backend=backend),),
    )

    assert broker.discover(_scope(local_interface="192.168.1.25")) == ()
    assert backend.calls[0]["local_interface"] == "192.168.1.25"


def test_scope_timeout_and_result_limit_cannot_exceed_policy() -> None:
    backend = FakeMdnsBackend(())
    broker = default_discovery_broker(backend=backend)

    with pytest.raises(DiscoveryPolicyError, match="timeout exceeds"):
        broker.discover(_scope(timeout_seconds=11))

    with pytest.raises(DiscoveryPolicyError, match="result count exceeds"):
        broker.discover(_scope(max_results=33))


def test_mdns_v1_rejects_device_type_discovery() -> None:
    policy = replace(
        DEFAULT_MDNS_POLICY,
        allowed_device_types=("camera",),
    )
    adapter = MdnsDnsSdAdapter(backend=FakeMdnsBackend(()))
    broker = DiscoveryBroker(policies=(policy,), adapters=(adapter,))

    with pytest.raises(DiscoveryAdapterError, match="not device types"):
        broker.discover(
            _scope(
                allowed_service_types=(),
                allowed_device_types=("camera",),
            )
        )


def test_result_limit_is_enforced_before_projection() -> None:
    records = tuple(
        _record(
            instance_name=f"Cast {index}._googlecast._tcp.local.",
            address=f"192.168.1.{50 + index}",
        )
        for index in range(6)
    )
    backend = FakeMdnsBackend(records)
    broker = default_discovery_broker(backend=backend, clock=lambda: 100.0)

    observations = broker.discover(_scope(max_results=2))

    assert len(observations) == 2
    assert backend.calls[0]["max_results"] == 2


def test_udp_service_preserves_transport_in_endpoint() -> None:
    service_type = "_example._udp.local."
    backend = FakeMdnsBackend(
        (
            _record(
                service_type=service_type,
                instance_name="Example._example._udp.local.",
            ),
        )
    )
    policy = DiscoveryAdapterPolicy(
        adapter_id="mdns_dns_sd.v1",
        adapter_version="python-zeroconf-0.151.3",
        protocols=("mdns",),
        allowed_service_types=(service_type,),
    )
    broker = DiscoveryBroker(
        policies=(policy,),
        adapters=(MdnsDnsSdAdapter(backend=backend, clock=lambda: 100.0),),
        clock=lambda: 100.0,
    )
    scope = _scope(allowed_service_types=(service_type,))

    observations = broker.discover(scope)

    assert observations[0].endpoints == ("udp://192.168.1.50:8009",)


def test_target_hint_only_narrows_results() -> None:
    backend = FakeMdnsBackend(
        (
            _record(instance_name="Living Room._googlecast._tcp.local."),
            _record(
                instance_name="Bedroom._googlecast._tcp.local.",
                address="192.168.1.51",
            ),
        )
    )
    broker = default_discovery_broker(backend=backend, clock=lambda: 100.0)

    observations = broker.discover(_scope(target_hints=("bedroom",)))

    assert len(observations) == 1


def test_freshness_expires_deterministically() -> None:
    broker = default_discovery_broker(
        backend=FakeMdnsBackend((_record(ttl_seconds=5),)),
        clock=lambda: 100.0,
    )
    observations = broker.discover(_scope())

    assert broker.fresh(observations, now=104.9) == observations
    assert broker.fresh(observations, now=105.0) == ()


def test_adapter_cannot_return_out_of_scope_service() -> None:
    backend = FakeMdnsBackend((_record(service_type="_airplay._tcp.local."),))
    broker = default_discovery_broker(backend=backend)

    with pytest.raises(DiscoveryAdapterError, match="out-of-scope"):
        broker.discover(_scope())


def test_public_network_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="local/private"):
        _record(address="8.8.8.8")


def test_discovery_projection_is_always_execution_disabled() -> None:
    backend = FakeMdnsBackend((_record(),))
    broker = default_discovery_broker(backend=backend, clock=lambda: 100.0)
    source = DiscoveryCapabilitySource(broker=broker, scope=_scope())
    catalog = CapabilityResolver((source,)).refresh()

    assert catalog.sources[0].state is DiscoveryState.AVAILABLE
    assert len(catalog.capabilities) == 1
    capability = catalog.capabilities[0]
    assert capability.kind is CapabilityKind.DISCOVERED_SERVICE
    assert capability.execution_enabled is False
    assert capability.operations == ()
    assert capability.metadata()["adapter_id"] == "mdns_dns_sd.v1"


def test_malformed_observation_scope_digest_is_rejected() -> None:
    base = default_discovery_broker(
        backend=FakeMdnsBackend((_record(),)),
        clock=lambda: 100.0,
    )
    valid = base.discover(_scope())[0]

    class BadAdapter:
        adapter_id = "mdns_dns_sd.v1"
        adapter_version = "python-zeroconf-0.151.3"

        def discover(self, scope: DiscoveryScope):
            return (replace(valid, scope_digest="f" * 64),)

    broker = DiscoveryBroker(
        policies=(DEFAULT_MDNS_POLICY,),
        adapters=(BadAdapter(),),
    )

    with pytest.raises(DiscoveryAdapterError, match="scope digest mismatch"):
        broker.discover(_scope())


def test_policy_requires_explicit_non_wildcard_targets() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        DiscoveryAdapterPolicy(
            adapter_id="bad.v1",
            adapter_version="1",
            protocols=("mdns",),
            allowed_service_types=("*",),
        )
