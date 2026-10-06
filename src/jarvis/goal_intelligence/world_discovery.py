"""Reviewed local-resource discovery bridges for GICC world resolution."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import DiscoveryObservation, DiscoveryScope
from jarvis.engineering_substrate.discovery import (
    DiscoveryBroker,
    DiscoveryBrokerError,
    default_discovery_broker,
)

from .information import InformationProbeResult, InformationResolutionStrategy
from .models import InformationNeedV1, WorldEntityRefV1
from .world import EntityResolutionState, EntityResolver, canonical_world_entity_type

_MEDIA_MDNS_SERVICE_TYPES = (
    "_airplay._tcp.local.",
    "_googlecast._tcp.local.",
    "_raop._tcp.local.",
)
_MEDIA_SSDP_SERVICE_TYPES = (
    "urn:dial-multiscreen-org:service:dial:1",
    "urn:schemas-upnp-org:device:mediarenderer:1",
)
_ONVIF_CAMERA_DEVICE_TYPES = ("network_video_transmitter",)
_GENERIC_TARGET_WORDS = frozenset(
    {
        "a",
        "an",
        "cam",
        "camera",
        "default",
        "device",
        "display",
        "media",
        "my",
        "player",
        "screen",
        "smart",
        "television",
        "the",
        "tv",
    }
)


def _specific_target_hints(mention: str) -> tuple[str, ...]:
    tokens = [
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_-]*", str(mention))
    ]
    return tuple(
        dict.fromkeys(
            token
            for token in tokens
            if len(token) >= 2 and token not in _GENERIC_TARGET_WORDS
        )
    )[:4]


def _endpoint_host(endpoint: str) -> str | None:
    try:
        parsed = urlparse(str(endpoint).strip())
    except ValueError:
        return None
    host = parsed.hostname
    return None if host is None else host.casefold()


def _observation_entity_type(observation: DiscoveryObservation) -> str:
    if observation.adapter_id == "onvif_ws_discovery.v1":
        return "camera"
    return "media_player"


def _resource_key(observation: DiscoveryObservation) -> str:
    hosts = tuple(
        sorted(
            {
                host
                for endpoint in observation.endpoints
                if (host := _endpoint_host(endpoint)) is not None
            }
        )
    )
    entity_type = _observation_entity_type(observation)
    prefix = "" if entity_type == "media_player" else f"{entity_type}:"
    if hosts:
        return prefix + "host:" + hosts[0]
    return prefix + "identity:" + observation.stable_identity.casefold()


class ReviewedLocalServiceEntityDiscovery:
    """Discover only resource classes covered by existing reviewed local policies."""

    discovery_id = "gicc.reviewed_local_service.v1"

    def __init__(
        self,
        broker: DiscoveryBroker | None = None,
        *,
        timeout_seconds: float = 1.5,
        max_results: int = 16,
    ) -> None:
        self._broker = broker or default_discovery_broker()
        self._timeout_seconds = float(timeout_seconds)
        self._max_results = int(max_results)
        if not 0.25 <= self._timeout_seconds <= 10:
            raise ValueError("GICC discovery timeout must be within reviewed bounds")
        if not 1 <= self._max_results <= 32:
            raise ValueError(
                "GICC discovery max_results must be within reviewed bounds"
            )

    def _scopes(
        self,
        *,
        expected_entity_types: tuple[str, ...],
        target_hints: tuple[str, ...],
    ) -> tuple[DiscoveryScope, ...]:
        expected = {
            canonical_world_entity_type(item)
            for item in expected_entity_types
            if str(item).strip()
        }
        output = []
        if "media_player" in expected:
            for adapter_id, protocol, service_types in (
                ("mdns_dns_sd.v1", "mdns", _MEDIA_MDNS_SERVICE_TYPES),
                ("ssdp_upnp.v1", "ssdp", _MEDIA_SSDP_SERVICE_TYPES),
            ):
                identity = {
                    "discovery_id": self.discovery_id,
                    "adapter_id": adapter_id,
                    "protocol": protocol,
                    "service_types": list(service_types),
                    "target_hints": list(target_hints),
                }
                output.append(
                    DiscoveryScope(
                        scope_id="gicc:" + canonical_digest(identity)[:24],
                        adapter_id=adapter_id,
                        protocol=protocol,
                        allowed_service_types=service_types,
                        allowed_device_types=(),
                        local_domain="local.",
                        target_hints=target_hints,
                        timeout_seconds=self._timeout_seconds,
                        max_results=self._max_results,
                    )
                )

        if "camera" in expected:
            identity = {
                "discovery_id": self.discovery_id,
                "adapter_id": "onvif_ws_discovery.v1",
                "protocol": "ws_discovery",
                "device_types": list(_ONVIF_CAMERA_DEVICE_TYPES),
                "target_hints": list(target_hints),
            }
            output.append(
                DiscoveryScope(
                    scope_id="gicc:" + canonical_digest(identity)[:24],
                    adapter_id="onvif_ws_discovery.v1",
                    protocol="ws_discovery",
                    allowed_service_types=(),
                    allowed_device_types=_ONVIF_CAMERA_DEVICE_TYPES,
                    local_domain="local.",
                    target_hints=target_hints,
                    timeout_seconds=self._timeout_seconds,
                    max_results=self._max_results,
                )
            )
        return tuple(output)

    def _discover_once(
        self,
        *,
        expected_entity_types: tuple[str, ...],
        target_hints: tuple[str, ...],
    ) -> tuple[DiscoveryObservation, ...]:
        observations: dict[str, DiscoveryObservation] = {}
        for scope in self._scopes(
            expected_entity_types=expected_entity_types,
            target_hints=target_hints,
        ):
            try:
                discovered = self._broker.discover(scope)
            except DiscoveryBrokerError:
                continue
            for observation in discovered:
                observations[observation.observation_id] = observation
        return tuple(observations[key] for key in sorted(observations))

    def discover(
        self,
        *,
        mention: str,
        expected_entity_types: tuple[str, ...],
    ) -> tuple[WorldEntityRefV1, ...]:
        expected = tuple(
            sorted(
                {
                    canonical_world_entity_type(item)
                    for item in expected_entity_types
                    if str(item).strip()
                }
            )
        )
        if not ({"media_player", "camera"} & set(expected)):
            return ()

        hints = _specific_target_hints(mention)
        observations = self._discover_once(
            expected_entity_types=expected,
            target_hints=hints,
        )
        if not observations and hints:
            observations = self._discover_once(
                expected_entity_types=expected,
                target_hints=(),
            )
        if not observations:
            return ()

        grouped: dict[str, list[DiscoveryObservation]] = {}
        for observation in observations:
            grouped.setdefault(_resource_key(observation), []).append(observation)

        entities = []
        for resource_key in sorted(grouped):
            group = tuple(
                sorted(
                    grouped[resource_key],
                    key=lambda item: item.observation_id,
                )
            )
            entity_type = _observation_entity_type(group[0])
            if any(
                _observation_entity_type(item) != entity_type for item in group
            ):
                continue
            host_prefix = (
                "host:" if entity_type == "media_player" else f"{entity_type}:host:"
            )
            host = (
                resource_key.removeprefix(host_prefix)
                if resource_key.startswith(host_prefix)
                else None
            )
            identity_digest = canonical_digest(
                {
                    "discovery_id": self.discovery_id,
                    "entity_type": entity_type,
                    "resource_key": resource_key,
                }
            )
            provenance = tuple(
                sorted(
                    {f"discovery:{item.observation_id}" for item in group}
                    | {f"discovery_evidence:{item.evidence_digest}" for item in group}
                )
            )
            label = "camera" if entity_type == "camera" else "media player"
            entities.append(
                WorldEntityRefV1.create(
                    entity_id="entity_discovered_" + identity_digest[:20],
                    entity_type=entity_type,
                    canonical_name=(
                        f"Discovered {label} {host}"
                        if host is not None
                        else f"Discovered {label} {identity_digest[:8]}"
                    ),
                    provenance_refs=provenance,
                )
            )
        return tuple(entities)


class EntityInformationProbe:
    """Resolve entity InformationNeeds from world evidence before owner input."""

    def __init__(
        self,
        resolver: EntityResolver,
        *,
        strategy: InformationResolutionStrategy,
    ) -> None:
        if not isinstance(resolver, EntityResolver):
            raise TypeError("resolver must be EntityResolver")
        if strategy not in {
            InformationResolutionStrategy.WORLD_REGISTRY,
            InformationResolutionStrategy.BOUNDED_LOCAL_DISCOVERY,
        }:
            raise ValueError("unsupported entity information strategy")
        self._resolver = resolver
        self.strategy = strategy

    def resolve(self, need: InformationNeedV1) -> InformationProbeResult:
        if need.answer_schema.get("type") != "entity_id":
            return InformationProbeResult(
                resolution_ref=None,
                reason="information need is not an entity identity",
            )
        entity_type = canonical_world_entity_type(need.answer_schema.get("entity_type"))
        resolution = self._resolver.resolve(
            need.subject,
            expected_entity_types=((entity_type,) if entity_type else ()),
            require_live_binding=False,
            allow_discovery=(
                self.strategy is InformationResolutionStrategy.BOUNDED_LOCAL_DISCOVERY
            ),
        )
        if resolution.state is not EntityResolutionState.RESOLVED:
            return InformationProbeResult(
                resolution_ref=None,
                evidence_refs=resolution.evidence_refs,
                reason=resolution.reason,
            )
        return InformationProbeResult(
            resolution_ref=resolution.entity_id,
            evidence_refs=resolution.evidence_refs,
            reason=resolution.reason,
        )
