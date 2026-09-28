"""Bounded SSDP/UPnP discovery adapter for the Phase-5 DiscoveryBroker.

This module deliberately implements only the small SSDP M-SEARCH transport needed by
JARVIS discovery policy. It does not fetch device descriptions, issue UPnP actions,
enumerate ssdp:all, scan ports, or grant execution authority.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import DiscoveryObservation, DiscoveryScope
from jarvis.engineering_substrate.discovery import (
    DiscoveryAdapterError,
    DiscoveryAdapterPolicy,
    DiscoveryResourceUnavailable,
)

_SSDP_ADDRESS = ("239.255.255.250", 1900)
_MAX_DATAGRAM_BYTES = 65_507
_MAX_CACHE_SECONDS = 300.0
_CACHE_MAX_AGE = re.compile(r"(?:^|,)\\s*max-age\\s*=\\s*([0-9]+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class SsdpServiceRecord:
    search_target: str
    usn: str
    sender_address: str
    location: str | None
    server: str | None
    max_age_seconds: float

    def __post_init__(self) -> None:
        target = str(self.search_target).strip().casefold()
        usn = str(self.usn).strip()
        address = ipaddress.ip_address(str(self.sender_address).strip())
        if not target or not usn:
            raise ValueError("SSDP record requires search target and USN")
        if not (address.is_private or address.is_link_local or address.is_loopback):
            raise ValueError(
                "SSDP response must originate from a local/private address"
            )
        if self.max_age_seconds <= 0:
            raise ValueError("SSDP max-age must be positive")
        location = None if self.location is None else str(self.location).strip()
        if location:
            parsed = urlparse(location)
            if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
                raise ValueError("SSDP LOCATION must be an HTTP(S) URL")
            try:
                host = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                if not parsed.hostname.casefold().endswith(".local"):
                    location = None
            else:
                if not (host.is_private or host.is_link_local or host.is_loopback):
                    location = None
        object.__setattr__(self, "search_target", target)
        object.__setattr__(self, "sender_address", address.compressed.casefold())
        object.__setattr__(self, "location", location)
        object.__setattr__(
            self,
            "server",
            None if self.server is None else str(self.server).strip() or None,
        )
        object.__setattr__(
            self,
            "max_age_seconds",
            min(float(self.max_age_seconds), _MAX_CACHE_SECONDS),
        )


class SsdpBackend(Protocol):
    def search(
        self,
        *,
        search_targets: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[SsdpServiceRecord, ...]: ...


def _parse_headers(payload: bytes) -> dict[str, str]:
    if not payload or len(payload) > _MAX_DATAGRAM_BYTES:
        raise DiscoveryAdapterError("SSDP response size is invalid")
    text = payload.decode("iso-8859-1")
    lines = text.replace("\\r\\n", "\\n").split("\\n")
    if not lines or not lines[0].strip().casefold().startswith("http/1.1 200"):
        raise DiscoveryAdapterError("SSDP response status line is invalid")
    result: dict[str, str] = {}
    for line in lines[1:]:
        if not line.strip() or ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.strip().casefold()
        if not key or key in result:
            continue
        result[key] = value.strip()
    return result


def _max_age(cache_control: str | None) -> float:
    if cache_control:
        match = _CACHE_MAX_AGE.search(cache_control)
        if match is not None:
            return max(1.0, min(float(match.group(1)), _MAX_CACHE_SECONDS))
    return 60.0


class SocketSsdpBackend:
    """Small standards-based SSDP M-SEARCH transport with one bounded deadline."""

    def search(
        self,
        *,
        search_targets: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[SsdpServiceRecord, ...]:
        if not search_targets:
            return ()
        if any(target.casefold() == "ssdp:all" for target in search_targets):
            raise DiscoveryAdapterError("SSDP all-target enumeration is forbidden")
        interface = None
        if local_interface is not None:
            address = ipaddress.ip_address(local_interface)
            if address.version != 4:
                raise DiscoveryAdapterError("SSDP v1 requires an IPv4 local interface")
            interface = address.compressed

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if interface is not None:
                sock.bind((interface, 0))
                sock.setsockopt(
                    socket.IPPROTO_IP,
                    socket.IP_MULTICAST_IF,
                    socket.inet_aton(interface),
                )
            else:
                sock.bind(("", 0))
        except OSError as exc:
            raise DiscoveryResourceUnavailable(
                "SSDP socket/interface is unavailable"
            ) from exc

        deadline = time.monotonic() + timeout_seconds
        records: dict[tuple[str, str], SsdpServiceRecord] = {}
        target_set = set(search_targets)
        try:
            for target in search_targets:
                request = (
                    "M-SEARCH * HTTP/1.1\\r\\n"
                    f"HOST: {_SSDP_ADDRESS[0]}:{_SSDP_ADDRESS[1]}\\r\\n"
                    'MAN: "ssdp:discover"\\r\\n'
                    "MX: 1\\r\\n"
                    f"ST: {target}\\r\\n"
                    "\\r\\n"
                ).encode("ascii")
                sock.sendto(request, _SSDP_ADDRESS)

            while len(records) < max_results:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(min(0.25, remaining))
                try:
                    payload, sender = sock.recvfrom(_MAX_DATAGRAM_BYTES)
                except socket.timeout:
                    continue
                except OSError as exc:
                    raise DiscoveryResourceUnavailable("SSDP receive failed") from exc
                try:
                    sender_ip = ipaddress.ip_address(sender[0])
                except ValueError:
                    continue
                if not (
                    sender_ip.is_private
                    or sender_ip.is_link_local
                    or sender_ip.is_loopback
                ):
                    continue
                try:
                    headers = _parse_headers(payload)
                except DiscoveryAdapterError:
                    continue
                target = str(headers.get("st") or "").strip().casefold()
                if target not in target_set:
                    continue
                usn = str(headers.get("usn") or "").strip()
                if not usn:
                    continue
                try:
                    record = SsdpServiceRecord(
                        search_target=target,
                        usn=usn,
                        sender_address=sender_ip.compressed,
                        location=headers.get("location"),
                        server=headers.get("server"),
                        max_age_seconds=_max_age(headers.get("cache-control")),
                    )
                except ValueError:
                    continue
                records[(record.usn.casefold(), record.search_target)] = record
            return tuple(
                records[key]
                for key in sorted(records, key=lambda item: (item[0], item[1]))
            )
        finally:
            sock.close()


class SsdpUpnpAdapter:
    adapter_id = "ssdp_upnp.v1"
    adapter_version = "stdlib-ssdp-1"

    def __init__(
        self,
        *,
        backend: SsdpBackend | None = None,
        clock=time.time,
        max_freshness_seconds: float = _MAX_CACHE_SECONDS,
    ) -> None:
        self._backend = backend or SocketSsdpBackend()
        self._clock = clock
        self._max_freshness_seconds = float(max_freshness_seconds)

    def discover(self, scope: DiscoveryScope) -> tuple[DiscoveryObservation, ...]:
        if scope.adapter_id != self.adapter_id or scope.protocol != "ssdp":
            raise DiscoveryAdapterError("SSDP adapter received mismatched scope")
        if scope.allowed_device_types:
            raise DiscoveryAdapterError(
                "SSDP v1 accepts explicit search targets, not device-type enumeration"
            )
        targets = tuple(item.casefold() for item in scope.allowed_service_types)
        if not targets or "ssdp:all" in targets:
            raise DiscoveryAdapterError(
                "SSDP v1 requires explicit non-enumerating search targets"
            )
        records = self._backend.search(
            search_targets=targets,
            local_interface=scope.local_interface,
            timeout_seconds=scope.timeout_seconds,
            max_results=scope.max_results,
        )
        observed = float(self._clock())
        scope_digest = canonical_digest(scope)
        observations: list[DiscoveryObservation] = []
        hints = tuple(item.casefold() for item in scope.target_hints)
        for record in records[: scope.max_results]:
            if record.search_target not in targets:
                raise DiscoveryAdapterError(
                    "SSDP backend returned an out-of-scope search target"
                )
            searchable = " ".join(
                item
                for item in (
                    record.usn,
                    record.server or "",
                    record.location or "",
                    record.sender_address,
                )
                if item
            ).casefold()
            if hints and not any(hint in searchable for hint in hints):
                continue
            identity_digest = canonical_digest(
                {"usn": record.usn, "search_target": record.search_target}
            )
            endpoints = [f"udp://{record.sender_address}:{_SSDP_ADDRESS[1]}"]
            if record.location is not None:
                endpoints.append(record.location)
            evidence_digest = canonical_digest(
                {
                    "search_target": record.search_target,
                    "usn": record.usn,
                    "sender_address": record.sender_address,
                    "location": record.location,
                    "server": record.server,
                    "max_age_seconds": record.max_age_seconds,
                }
            )
            observations.append(
                DiscoveryObservation(
                    observation_id="ssdp-observation:"
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
                    stable_identity="ssdp:" + identity_digest,
                    endpoints=tuple(sorted(endpoints)),
                    observed_at_epoch=observed,
                    expires_at_epoch=observed
                    + min(record.max_age_seconds, self._max_freshness_seconds),
                    evidence_digest=evidence_digest,
                )
            )
        return tuple(sorted(observations, key=lambda item: item.stable_identity))


DEFAULT_SSDP_POLICY = DiscoveryAdapterPolicy(
    adapter_id=SsdpUpnpAdapter.adapter_id,
    adapter_version=SsdpUpnpAdapter.adapter_version,
    protocols=("ssdp",),
    allowed_service_types=(
        "upnp:rootdevice",
        "urn:dial-multiscreen-org:service:dial:1",
        "urn:schemas-upnp-org:device:mediarenderer:1",
        "urn:schemas-upnp-org:device:mediaserver:1",
    ),
    allowed_domains=("local.",),
    max_timeout_seconds=10,
    max_results=32,
    max_freshness_seconds=300,
)
