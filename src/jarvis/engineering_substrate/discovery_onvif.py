"""Bounded ONVIF WS-Discovery adapter for local network video devices.

This adapter performs discovery only.  It does not authenticate to a camera, fetch
streams, invoke ONVIF services, scan ports, or grant execution authority.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import uuid
import xml.etree.ElementTree as ET
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

_ONVIF_DISCOVERY_ADDRESS = ("239.255.255.250", 3702)
_MAX_DATAGRAM_BYTES = 65_507
_DEFAULT_FRESHNESS_SECONDS = 60.0
_NETWORK_VIDEO_TRANSMITTER = "network_video_transmitter"

_SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
_WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
_ONVIF_NETWORK = "http://www.onvif.org/ver10/network/wsdl"


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _safe_local_http_url(value: str) -> str | None:
    raw = str(value).strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    try:
        host = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        if not parsed.hostname.casefold().endswith(".local"):
            return None
    else:
        if not (host.is_private or host.is_link_local or host.is_loopback):
            return None
    return raw


@dataclass(frozen=True, slots=True)
class OnvifDeviceRecord:
    endpoint_reference: str
    sender_address: str
    xaddrs: tuple[str, ...]
    types: tuple[str, ...]
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        endpoint = str(self.endpoint_reference).strip()
        sender = ipaddress.ip_address(str(self.sender_address).strip())
        if not endpoint:
            raise ValueError("ONVIF record requires endpoint reference")
        if not (sender.is_private or sender.is_link_local or sender.is_loopback):
            raise ValueError("ONVIF response must originate from a local/private address")
        safe_xaddrs = tuple(
            sorted(
                {
                    safe
                    for item in self.xaddrs
                    if (safe := _safe_local_http_url(item)) is not None
                }
            )
        )
        if not safe_xaddrs:
            raise ValueError("ONVIF record requires a local/private device-service URL")
        types = tuple(sorted({str(item).strip() for item in self.types if str(item).strip()}))
        scopes = tuple(
            sorted({str(item).strip() for item in self.scopes if str(item).strip()})
        )
        searchable = " ".join((*types, *scopes)).casefold()
        if "networkvideotransmitter" not in searchable:
            raise ValueError("ONVIF record is not a network video transmitter")
        object.__setattr__(self, "endpoint_reference", endpoint)
        object.__setattr__(self, "sender_address", sender.compressed.casefold())
        object.__setattr__(self, "xaddrs", safe_xaddrs)
        object.__setattr__(self, "types", types)
        object.__setattr__(self, "scopes", scopes)


class OnvifBackend(Protocol):
    def probe(
        self,
        *,
        device_types: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[OnvifDeviceRecord, ...]: ...


def _probe_message() -> bytes:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<s:Envelope xmlns:s="{_SOAP_ENV}" xmlns:a="{_WSA}" '
        f'xmlns:d="{_WSD}" xmlns:dn="{_ONVIF_NETWORK}">'
        "<s:Header>"
        f"<a:MessageID>{message_id}</a:MessageID>"
        f"<a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>"
        f"<a:Action>{_WSD}/Probe</a:Action>"
        "</s:Header>"
        "<s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types>"
        "</d:Probe></s:Body></s:Envelope>"
    ).encode("utf-8")


def _parse_probe_matches(
    payload: bytes,
    *,
    sender_address: str,
) -> tuple[OnvifDeviceRecord, ...]:
    if not payload or len(payload) > _MAX_DATAGRAM_BYTES:
        raise DiscoveryAdapterError("ONVIF response size is invalid")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DiscoveryAdapterError("ONVIF discovery response XML is invalid") from exc

    records: list[OnvifDeviceRecord] = []
    for match in root.iter():
        if _local_name(match.tag) != "probematch":
            continue
        address = ""
        xaddrs: tuple[str, ...] = ()
        types: tuple[str, ...] = ()
        scopes: tuple[str, ...] = ()
        for node in match.iter():
            name = _local_name(node.tag)
            text = " ".join(str(node.text or "").split())
            if not text:
                continue
            if name == "address" and not address:
                address = text
            elif name == "xaddrs":
                xaddrs = tuple(text.split())
            elif name == "types":
                types = tuple(text.split())
            elif name == "scopes":
                scopes = tuple(text.split())
        try:
            records.append(
                OnvifDeviceRecord(
                    endpoint_reference=address,
                    sender_address=sender_address,
                    xaddrs=xaddrs,
                    types=types,
                    scopes=scopes,
                )
            )
        except ValueError:
            continue
    return tuple(records)


class SocketOnvifBackend:
    """Small standards-based WS-Discovery Probe transport with one deadline."""

    def probe(
        self,
        *,
        device_types: tuple[str, ...],
        local_interface: str | None,
        timeout_seconds: float,
        max_results: int,
    ) -> tuple[OnvifDeviceRecord, ...]:
        if tuple(device_types) != (_NETWORK_VIDEO_TRANSMITTER,):
            raise DiscoveryAdapterError(
                "ONVIF v1 supports only explicit network-video-transmitter discovery"
            )
        interface = None
        if local_interface is not None:
            address = ipaddress.ip_address(local_interface)
            if address.version != 4:
                raise DiscoveryAdapterError(
                    "ONVIF WS-Discovery v1 requires an IPv4 local interface"
                )
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
                "ONVIF WS-Discovery socket/interface is unavailable"
            ) from exc

        records: dict[str, OnvifDeviceRecord] = {}
        deadline = time.monotonic() + timeout_seconds
        try:
            sock.sendto(_probe_message(), _ONVIF_DISCOVERY_ADDRESS)
            while len(records) < max_results:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(min(0.25, remaining))
                try:
                    payload, sender = sock.recvfrom(_MAX_DATAGRAM_BYTES)
                except TimeoutError:
                    continue
                except OSError as exc:
                    raise DiscoveryResourceUnavailable(
                        "ONVIF WS-Discovery receive failed"
                    ) from exc
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
                    found = _parse_probe_matches(
                        payload,
                        sender_address=sender_ip.compressed,
                    )
                except DiscoveryAdapterError:
                    continue
                for record in found:
                    records[record.endpoint_reference.casefold()] = record
                    if len(records) >= max_results:
                        break
            return tuple(records[key] for key in sorted(records))
        finally:
            sock.close()


class OnvifWsDiscoveryAdapter:
    adapter_id = "onvif_ws_discovery.v1"
    adapter_version = "stdlib-onvif-wsd-1"

    def __init__(
        self,
        *,
        backend: OnvifBackend | None = None,
        clock=time.time,
        max_freshness_seconds: float = _DEFAULT_FRESHNESS_SECONDS,
    ) -> None:
        self._backend = backend or SocketOnvifBackend()
        self._clock = clock
        self._max_freshness_seconds = float(max_freshness_seconds)
        if not 0 < self._max_freshness_seconds <= 300:
            raise ValueError("ONVIF discovery freshness must be within 300 seconds")

    def discover(self, scope: DiscoveryScope) -> tuple[DiscoveryObservation, ...]:
        if scope.adapter_id != self.adapter_id or scope.protocol != "ws_discovery":
            raise DiscoveryAdapterError("ONVIF adapter received mismatched scope")
        if scope.allowed_service_types:
            raise DiscoveryAdapterError(
                "ONVIF v1 uses explicit device types, not service-type enumeration"
            )
        device_types = tuple(item.casefold() for item in scope.allowed_device_types)
        if device_types != (_NETWORK_VIDEO_TRANSMITTER,):
            raise DiscoveryAdapterError(
                "ONVIF v1 requires explicit network-video-transmitter device type"
            )

        records = self._backend.probe(
            device_types=device_types,
            local_interface=scope.local_interface,
            timeout_seconds=scope.timeout_seconds,
            max_results=scope.max_results,
        )
        observed = float(self._clock())
        scope_digest = canonical_digest(scope)
        hints = tuple(item.casefold() for item in scope.target_hints)
        observations: list[DiscoveryObservation] = []
        for record in records[: scope.max_results]:
            searchable = " ".join(
                (
                    record.endpoint_reference,
                    record.sender_address,
                    *record.xaddrs,
                    *record.types,
                    *record.scopes,
                )
            ).casefold()
            if hints and not any(hint in searchable for hint in hints):
                continue
            identity_digest = canonical_digest(
                {
                    "endpoint_reference": record.endpoint_reference,
                    "device_type": _NETWORK_VIDEO_TRANSMITTER,
                }
            )
            evidence_digest = canonical_digest(
                {
                    "endpoint_reference": record.endpoint_reference,
                    "sender_address": record.sender_address,
                    "xaddrs": list(record.xaddrs),
                    "types": list(record.types),
                    "scopes": list(record.scopes),
                }
            )
            observations.append(
                DiscoveryObservation(
                    observation_id="onvif-observation:"
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
                    stable_identity="onvif:" + identity_digest,
                    endpoints=record.xaddrs,
                    observed_at_epoch=observed,
                    expires_at_epoch=observed + self._max_freshness_seconds,
                    evidence_digest=evidence_digest,
                )
            )
        return tuple(sorted(observations, key=lambda item: item.stable_identity))


DEFAULT_ONVIF_POLICY = DiscoveryAdapterPolicy(
    adapter_id=OnvifWsDiscoveryAdapter.adapter_id,
    adapter_version=OnvifWsDiscoveryAdapter.adapter_version,
    protocols=("ws_discovery",),
    allowed_service_types=(),
    allowed_device_types=(_NETWORK_VIDEO_TRANSMITTER,),
    allowed_domains=("local.",),
    max_timeout_seconds=10,
    max_results=32,
    max_freshness_seconds=_DEFAULT_FRESHNESS_SECONDS,
)
