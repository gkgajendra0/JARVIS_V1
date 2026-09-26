"""Bounded read-only discovery for local services.

The broker validates a caller-supplied DiscoveryScope against a reviewed adapter
policy. The initial adapter uses python-zeroconf only for explicit mDNS/DNS-SD
service types; it never enumerates arbitrary service types or performs port scans.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from jarvis.capabilities.discovery import (
    CapabilityDiscoveryError,
    CapabilityDiscoverySource,
)
from jarvis.capabilities.models import (
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import DiscoveryObservation, DiscoveryScope


class DiscoveryBrokerError(RuntimeError):
    """Base error for bounded discovery."""


class DiscoveryPolicyError(DiscoveryBrokerError):
    """A requested scope widens beyond the reviewed adapter policy."""


class DiscoveryResourceUnavailable(DiscoveryBrokerError):
    """The reviewed discovery adapter cannot access its required local resource."""


class DiscoveryAdapterError(DiscoveryBrokerError):
    """A discovery adapter returned malformed or untrusted evidence."""


@dataclass(frozen=True, slots=True)
class DiscoveryAdapterPolicy:
    adapter_id: str
    adapter_version: str
    protocols: tuple[str, ...]
    allowed_service_types: tuple[str, ...]
    allowed_device_types: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ("local.",)
    max_timeout_seconds: float = 10.0
    max_results: int = 32
    max_freshness_seconds: float = 300.0

    def __post_init__(self) -> None:
        adapter_id = str(self.adapter_id).strip().casefold()
        adapter_version = str(self.adapter_version).strip()
        protocols = _tokens(self.protocols)
        services = _tokens(self.allowed_service_types)
        devices = _tokens(self.allowed_device_types)
        domains = _tokens(self.allowed_domains)
        if not adapter_id or not adapter_version:
            raise ValueError("discovery adapter identity/version must not be empty")
        if not protocols:
            raise ValueError("discovery adapter requires an explicit protocol")
        if not services and not devices:
            raise ValueError("discovery adapter requires an explicit service/device set")
        if "mdns" in protocols:
            for service_type in services:
                _validate_mdns_service_type(service_type)
        if self.max_timeout_seconds <= 0 or self.max_timeout_seconds > 30:
            raise ValueError("adapter max_timeout_seconds must be within Phase-5 bounds")
        if self.max_results <= 0 or self.max_results > 64:
            raise ValueError("adapter max_results must be within Phase-5 bounds")
        if self.max_freshness_seconds <= 0:
            raise ValueError("adapter max_freshness_seconds must be positive")
        object.__setattr__(self, "adapter_id", adapter_id)
        object.__setattr__(self, "adapter_version", adapter_version)
        object.__setattr__(self, "protocols", protocols)
        object.__setattr__(self, "allowed_service_types", services)
        object.__setattr__(self, "allowed_device_types", devices)
        object.__setattr__(self, "allowed_domains", domains)
        object.__setattr__(
            self,
            "max_timeout_seconds",
            float(self.max_timeout_seconds),
        )
        object.__setattr__(self, "max_results", int(self.max_results))
        object.__setattr__(
            self,
            "max_freshness_seconds",
            float(self.max_freshness_seconds),
        )


@dataclass(frozen=True, slots=True)
class MdnsServiceRecord:
    service_type: str
    instance_name: str
    server: str
    port: int
    addresses: tuple[str, ...]
    ttl_seconds: float

    def __post_init__(self) -> None:
        service_type = str(self.service_type).strip().casefold()
        instance_name = str(self.instance_name).strip()
        server = str(self.server).strip().casefold()
        if not service_type or not instance_name or not server:
            raise ValueError("mDNS service identity fields must not be empty")
        if self.port <= 0 or self.port > 65535:
            raise ValueError("mDNS service port is invalid")
        addresses: list[str] = []
        for raw in self.addresses:
            address = ipaddress.ip_address(str(raw).strip())
            if not (
                address.is_private
                or address.is_link_local
                or address.is_loopback
            ):
                raise ValueError("mDNS endpoint must remain local/private")
            normalized = address.compressed.casefold()
            if normalized not in addresses:
                addresses.append(normalized)
        if not addresses:
            raise ValueError("mDNS service requires at least one local address")
        if self.ttl_seconds <= 0:
            raise ValueError("mDNS TTL must be positive")
        object.__setattr__(self, "service_type", service_type)
        object.__setattr__(self, "instance_name", instance_name)
        object.__setattr__(self, "server", server)
        object.__setattr__(self, "addresses", tuple(sorted(addresses)))
        object.__setattr__(self, "ttl_seconds", float(self.ttl_seconds))


class DiscoveryAdapter(Protocol):
    adapter_id: str
    adapter_version: str

    def discover(self, scope: DiscoveryScope) -> tuple[DiscoveryObservation, ...]: ...


class MdnsBackend(Protocol):
    def browse(
        self,
        *,
        service_types: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[MdnsServiceRecord, ...]: ...


class ZeroconfMdnsBackend:
    """Production python-zeroconf browse/resolve backend with one global deadline."""

    def browse(
        self,
        *,
        service_types: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[MdnsServiceRecord, ...]:
        try:
            from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
        except ImportError as exc:
            raise DiscoveryResourceUnavailable(
                "python-zeroconf is unavailable"
            ) from exc

        class _Listener(ServiceListener):
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.names: set[tuple[str, str]] = set()

            def add_service(self, zc, service_type: str, name: str) -> None:
                del zc
                with self.lock:
                    self.names.add((service_type.casefold(), name))

            def update_service(self, zc, service_type: str, name: str) -> None:
                self.add_service(zc, service_type, name)

            def remove_service(self, zc, service_type: str, name: str) -> None:
                del zc, service_type, name

            def snapshot(self) -> tuple[tuple[str, str], ...]:
                with self.lock:
                    return tuple(sorted(self.names))

        kwargs: dict[str, object] = {}
        if local_interface is not None:
            try:
                ipaddress.ip_address(local_interface)
            except ValueError as exc:
                raise DiscoveryPolicyError(
                    "mDNS local_interface must be a concrete IP address"
                ) from exc
            kwargs["interfaces"] = [local_interface]

        listener = _Listener()
        deadline = time.monotonic() + timeout_seconds
        try:
            zeroconf = Zeroconf(**kwargs)
        except OSError as exc:
            raise DiscoveryResourceUnavailable(
                "mDNS socket/interface is unavailable"
            ) from exc

        browser = None
        try:
            browser = ServiceBrowser(
                zeroconf,
                list(service_types),
                listener=listener,
            )
            threading.Event().wait(timeout_seconds)
            discovered = listener.snapshot()[:max_results]
            records: list[MdnsServiceRecord] = []
            for service_type, name in discovered:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                timeout_ms = max(1, min(1000, int(remaining * 1000)))
                info = zeroconf.get_service_info(
                    service_type,
                    name,
                    timeout=timeout_ms,
                )
                if info is None or not info.server or not info.port:
                    continue
                addresses = tuple(info.parsed_addresses())
                if not addresses:
                    continue
                ttl = min(
                    float(value)
                    for value in (info.host_ttl, info.other_ttl)
                    if float(value) > 0
                )
                try:
                    record = MdnsServiceRecord(
                        service_type=service_type,
                        instance_name=name,
                        server=info.server,
                        port=int(info.port),
                        addresses=addresses,
                        ttl_seconds=ttl,
                    )
                except ValueError:
                    continue
                records.append(record)
                if len(records) >= max_results:
                    break
            return tuple(records)
        finally:
            if browser is not None:
                browser.cancel()
            zeroconf.close()


class MdnsDnsSdAdapter:
    adapter_id = "mdns_dns_sd.v1"
    adapter_version = "python-zeroconf-0.151.3"

    def __init__(
        self,
        *,
        backend: MdnsBackend | None = None,
        clock=time.time,
        max_freshness_seconds: float = 300.0,
    ) -> None:
        self._backend = backend or ZeroconfMdnsBackend()
        self._clock = clock
        self._max_freshness_seconds = float(max_freshness_seconds)
        if self._max_freshness_seconds <= 0:
            raise ValueError("max_freshness_seconds must be positive")

    def discover(self, scope: DiscoveryScope) -> tuple[DiscoveryObservation, ...]:
        if scope.adapter_id != self.adapter_id:
            raise DiscoveryAdapterError("mDNS adapter received mismatched adapter_id")
        if scope.protocol != "mdns":
            raise DiscoveryAdapterError("mDNS adapter requires protocol=mdns")
        if scope.allowed_device_types:
            raise DiscoveryAdapterError(
                "mDNS v1 accepts explicit DNS-SD service types, not device types"
            )
        if not scope.allowed_service_types:
            raise DiscoveryAdapterError("mDNS v1 requires explicit service types")

        records = self._backend.browse(
            service_types=scope.allowed_service_types,
            local_interface=scope.local_interface,
            timeout_seconds=scope.timeout_seconds,
            max_results=scope.max_results,
        )
        observed = float(self._clock())
        scope_digest = canonical_digest(scope)
        observations: list[DiscoveryObservation] = []
        for record in records[: scope.max_results]:
            if record.service_type not in scope.allowed_service_types:
                raise DiscoveryAdapterError(
                    "mDNS backend returned an out-of-scope service type"
                )
            if scope.target_hints:
                searchable = (
                    record.instance_name + " " + record.server
                ).casefold()
                if not any(
                    hint.casefold() in searchable for hint in scope.target_hints
                ):
                    continue
            identity_digest = canonical_digest(
                {
                    "service_type": record.service_type,
                    "instance_name": record.instance_name,
                }
            )
            endpoints = tuple(
                sorted(
                    f"tcp://{_endpoint_host(address)}:{record.port}"
                    for address in record.addresses
                )
            )
            evidence_digest = canonical_digest(
                {
                    "service_type": record.service_type,
                    "instance_name": record.instance_name,
                    "server": record.server,
                    "port": record.port,
                    "addresses": list(record.addresses),
                    "ttl_seconds": record.ttl_seconds,
                }
            )
            expires = observed + min(
                record.ttl_seconds,
                self._max_freshness_seconds,
            )
            observations.append(
                DiscoveryObservation(
                    observation_id="mdns-observation:"
                    + canonical_digest(
                        {
                            "scope_digest": scope_digest,
                            "identity_digest": identity_digest,
                            "evidence_digest": evidence_digest,
                        }
                    ),
                    scope_id=scope.scope_id,
                    scope_digest=scope_digest,
                    adapter_id=self.adapter_id,
                    adapter_version=self.adapter_version,
                    stable_identity="mdns:" + identity_digest,
                    endpoints=endpoints,
                    observed_at_epoch=observed,
                    expires_at_epoch=expires,
                    evidence_digest=evidence_digest,
                )
            )
        return tuple(sorted(observations, key=lambda item: item.stable_identity))


class DiscoveryBroker:
    """Validate requested discovery scope before calling one trusted read-only adapter."""

    def __init__(
        self,
        *,
        policies: Iterable[DiscoveryAdapterPolicy],
        adapters: Iterable[DiscoveryAdapter],
        clock=time.time,
    ) -> None:
        self._policies: dict[str, DiscoveryAdapterPolicy] = {}
        self._adapters: dict[str, DiscoveryAdapter] = {}
        self._clock = clock
        for policy in policies:
            if policy.adapter_id in self._policies:
                raise ValueError(f"duplicate discovery policy: {policy.adapter_id}")
            self._policies[policy.adapter_id] = policy
        for adapter in adapters:
            adapter_id = str(adapter.adapter_id).strip().casefold()
            if adapter_id in self._adapters:
                raise ValueError(f"duplicate discovery adapter: {adapter_id}")
            self._adapters[adapter_id] = adapter

    def _policy(self, adapter_id: str) -> DiscoveryAdapterPolicy:
        try:
            return self._policies[adapter_id]
        except KeyError as exc:
            raise DiscoveryPolicyError(
                f"unregistered discovery adapter policy: {adapter_id}"
            ) from exc

    def _adapter(self, adapter_id: str) -> DiscoveryAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise DiscoveryResourceUnavailable(
                f"registered discovery adapter is unavailable: {adapter_id}"
            ) from exc

    @staticmethod
    def _validate_scope(
        scope: DiscoveryScope,
        policy: DiscoveryAdapterPolicy,
    ) -> None:
        if scope.protocol not in policy.protocols:
            raise DiscoveryPolicyError("discovery protocol exceeds adapter policy")
        if not set(scope.allowed_service_types).issubset(
            set(policy.allowed_service_types)
        ):
            raise DiscoveryPolicyError(
                "discovery service type exceeds adapter policy"
            )
        if not set(scope.allowed_device_types).issubset(
            set(policy.allowed_device_types)
        ):
            raise DiscoveryPolicyError(
                "discovery device type exceeds adapter policy"
            )
        domain = (scope.local_domain or "local.").strip().casefold()
        if domain not in policy.allowed_domains:
            raise DiscoveryPolicyError("discovery domain exceeds adapter policy")
        if scope.timeout_seconds > policy.max_timeout_seconds:
            raise DiscoveryPolicyError("discovery timeout exceeds adapter policy")
        if scope.max_results > policy.max_results:
            raise DiscoveryPolicyError("discovery result count exceeds adapter policy")

    def discover(self, scope: DiscoveryScope) -> tuple[DiscoveryObservation, ...]:
        policy = self._policy(scope.adapter_id)
        self._validate_scope(scope, policy)
        adapter = self._adapter(scope.adapter_id)
        if adapter.adapter_version != policy.adapter_version:
            raise DiscoveryAdapterError(
                "discovery adapter version does not match reviewed policy"
            )
        observations = adapter.discover(scope)
        if len(observations) > scope.max_results:
            raise DiscoveryAdapterError(
                "discovery adapter exceeded max_results"
            )
        expected_scope_digest = canonical_digest(scope)
        identities: set[str] = set()
        validated: list[DiscoveryObservation] = []
        for observation in observations:
            if observation.adapter_id != scope.adapter_id:
                raise DiscoveryAdapterError(
                    "discovery observation adapter_id mismatch"
                )
            if observation.adapter_version != policy.adapter_version:
                raise DiscoveryAdapterError(
                    "discovery observation adapter_version mismatch"
                )
            if observation.scope_id != scope.scope_id:
                raise DiscoveryAdapterError(
                    "discovery observation scope_id mismatch"
                )
            if observation.scope_digest != expected_scope_digest:
                raise DiscoveryAdapterError(
                    "discovery observation scope digest mismatch"
                )
            if observation.stable_identity in identities:
                raise DiscoveryAdapterError(
                    "duplicate stable identity returned by discovery adapter"
                )
            if (
                observation.expires_at_epoch - observation.observed_at_epoch
                > policy.max_freshness_seconds
            ):
                raise DiscoveryAdapterError(
                    "discovery observation freshness exceeds adapter policy"
                )
            identities.add(observation.stable_identity)
            validated.append(observation)
        return tuple(sorted(validated, key=lambda item: item.stable_identity))

    def fresh(
        self,
        observations: Iterable[DiscoveryObservation],
        *,
        now: float | None = None,
    ) -> tuple[DiscoveryObservation, ...]:
        instant = float(self._clock() if now is None else now)
        return tuple(
            observation
            for observation in observations
            if observation.observed_at_epoch <= instant < observation.expires_at_epoch
        )


class DiscoveryCapabilitySource(CapabilityDiscoverySource):
    """Project bounded observations into the existing catalog as execution-disabled."""

    def __init__(
        self,
        *,
        broker: DiscoveryBroker,
        scope: DiscoveryScope,
    ) -> None:
        self._broker = broker
        self._scope = scope
        self.source_id = f"engineering.discovery:{scope.scope_id}"

    def discover(self) -> DiscoverySnapshot:
        started = time.monotonic()
        try:
            observations = self._broker.discover(self._scope)
        except DiscoveryBrokerError as exc:
            raise CapabilityDiscoveryError(str(exc)) from exc
        descriptors = tuple(
            CapabilityDescriptor.create(
                capability_id=observation.stable_identity,
                source_id=self.source_id,
                kind=CapabilityKind.DISCOVERED_SERVICE,
                name="Discovered local service",
                description=(
                    "Read-only local service observation; execution requires a "
                    "separately registered capability manifest and executor."
                ),
                operations=(),
                metadata={
                    "observation_id": observation.observation_id,
                    "scope_id": observation.scope_id,
                    "scope_digest": observation.scope_digest,
                    "adapter_id": observation.adapter_id,
                    "adapter_version": observation.adapter_version,
                    "endpoints": list(observation.endpoints),
                    "expires_at_epoch": observation.expires_at_epoch,
                    "evidence_digest": observation.evidence_digest,
                },
                execution_enabled=False,
            )
            for observation in observations
        )
        return DiscoverySnapshot(
            source_id=self.source_id,
            state=DiscoveryState.AVAILABLE,
            capabilities=descriptors,
            elapsed_ms=(time.monotonic() - started) * 1000,
        )


DEFAULT_MDNS_POLICY = DiscoveryAdapterPolicy(
    adapter_id=MdnsDnsSdAdapter.adapter_id,
    adapter_version=MdnsDnsSdAdapter.adapter_version,
    protocols=("mdns",),
    allowed_service_types=(
        "_airplay._tcp.local.",
        "_googlecast._tcp.local.",
        "_http._tcp.local.",
        "_https._tcp.local.",
        "_ipp._tcp.local.",
        "_printer._tcp.local.",
        "_raop._tcp.local.",
    ),
    allowed_domains=("local.",),
    max_timeout_seconds=10,
    max_results=32,
    max_freshness_seconds=300,
)


def default_discovery_broker(
    *,
    backend: MdnsBackend | None = None,
    clock=time.time,
) -> DiscoveryBroker:
    adapter = MdnsDnsSdAdapter(
        backend=backend,
        clock=clock,
        max_freshness_seconds=DEFAULT_MDNS_POLICY.max_freshness_seconds,
    )
    return DiscoveryBroker(
        policies=(DEFAULT_MDNS_POLICY,),
        adapters=(adapter,),
        clock=clock,
    )


def _tokens(values: Iterable[str]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(
            str(value).strip().casefold()
            for value in values
            if str(value).strip()
        )
    )
    if any("*" in value for value in normalized):
        raise ValueError("wildcard discovery policy is forbidden")
    return normalized


def _validate_mdns_service_type(value: str) -> None:
    service_type = str(value).strip().casefold()
    if service_type == "_services._dns-sd._udp.local.":
        raise ValueError("DNS-SD service-type enumeration is forbidden")
    if not service_type.startswith("_") or not service_type.endswith(".local."):
        raise ValueError("mDNS service type must be explicit and local")
    if "._tcp." not in service_type and "._udp." not in service_type:
        raise ValueError("mDNS service type must declare TCP or UDP transport")


def _endpoint_host(address: str) -> str:
    parsed = ipaddress.ip_address(address)
    if parsed.version == 6:
        return f"[{parsed.compressed.casefold()}]"
    return parsed.compressed
