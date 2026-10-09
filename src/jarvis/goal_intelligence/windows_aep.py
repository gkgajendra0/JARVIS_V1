"""Bounded Windows AssociationEndpoint (AEP) identity observations.

Unlike Get-NetNeighbor, WinRT AEP enumeration CAN send network discovery
traffic. There is deliberately no default authority for this adapter. A
trusted owner-permission checker must approve the exact scope and explicitly
cover protocol discovery over all Windows network interfaces.

Results are unverified identity *candidates*: not WorldEntityRef, trusted
manufacturer attestations, credentials, pairing or device control authority.
"""

from __future__ import annotations

import ipaddress
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from jarvis.engineering_substrate.canonical import canonical_digest

_PROTOCOLS = {
    "upnp": "0e261de4-12f0-46e6-91ba-428607ccef64",
    "dns_sd": "4526e8c1-8aac-4153-9b16-55e86ada0e54",
    "wsd": "782232aa-a2f9-4993-971b-aedc551346b0",
}
_PROPERTIES = (
    "System.Devices.Aep.DeviceAddress",
    "System.Devices.Aep.IsPresent",
    "System.Devices.Aep.ProtocolId",
    "System.Devices.Aep.Manufacturer",
    "System.Devices.Aep.ModelName",
    "System.Devices.Aep.Category",
)
_RFC1918 = tuple(
    ipaddress.IPv4Network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


@dataclass(frozen=True, slots=True)
class ReviewedAepScopeV1:
    """Scope whose consent is verified by an independent permission system."""

    protocol: str
    approved_address_ranges: tuple[str, ...]
    consent_record_id: str
    all_local_interfaces_authorized: bool
    timeout_seconds: float = 1.5
    max_results: int = 16

    def __post_init__(self) -> None:
        if self.protocol not in _PROTOCOLS:
            raise ValueError("AEP protocol is not reviewed")
        if not self.consent_record_id.strip():
            raise ValueError("AEP requires a nonempty consent record reference")
        if self.all_local_interfaces_authorized is not True:
            raise ValueError(
                "AEP Windows queries cannot guarantee a single interface; "
                "explicit all-local-interface permission is required"
            )
        if not 0.25 <= self.timeout_seconds <= 2.5:
            raise ValueError("AEP timeout is outside reviewed bounds")
        if not 1 <= self.max_results <= 16:
            raise ValueError("AEP result limit is outside reviewed bounds")
        if not self.approved_address_ranges:
            raise ValueError("AEP requires approved local address ranges")
        networks = []
        for cidr in self.approved_address_ranges:
            network = ipaddress.ip_network(cidr, strict=True)
            if (
                not isinstance(network, ipaddress.IPv4Network)
                or not any(network.subnet_of(private) for private in _RFC1918)
                or network.prefixlen < 20
            ):
                raise ValueError("AEP address range must be bounded RFC1918 IPv4")
            networks.append(network)
        if len(networks) > 8:
            raise ValueError("too many authorized AEP address ranges")


@dataclass(frozen=True, slots=True)
class AepIdentityCandidateV1:
    """Windows-provided metadata, not a verified device or protocol grant."""

    endpoint_id: str
    address: str
    protocol: str
    name: str
    manufacturer: str
    model: str
    observed_at_epoch: int

    @property
    def evidence_ref(self) -> str:
        digest = canonical_digest(
            {
                "endpoint_id": self.endpoint_id,
                "address": self.address,
                "protocol": self.protocol,
                "name": self.name,
                "manufacturer": self.manufacturer,
                "model": self.model,
                "observed_at_epoch": self.observed_at_epoch,
            }
        )
        return "windows_aep_unverified:" + digest


def _valid_address(raw: object, scope: ReviewedAepScopeV1) -> str | None:
    try:
        address = ipaddress.IPv4Address(str(raw).strip())
    except (ValueError, TypeError):
        return None
    if not any(
        address in ipaddress.IPv4Network(cidr) for cidr in scope.approved_address_ranges
    ):
        return None
    return str(address)


def _normalize_protocol(raw: object) -> str | None:
    try:
        return str(UUID(str(raw).strip().strip("{}")))
    except (ValueError, TypeError, AttributeError):
        return None


def _candidate_from_device(
    device: object, scope: ReviewedAepScopeV1, at_epoch: int
) -> AepIdentityCandidateV1 | None:
    try:
        properties = device.properties
        # "Paired" or a cached record is not sufficient. Absence fails closed.
        if properties.get("System.Devices.Aep.IsPresent") is not True:
            return None
        protocol = _normalize_protocol(properties.get("System.Devices.Aep.ProtocolId"))
        if protocol != _PROTOCOLS[scope.protocol]:
            return None
        address = _valid_address(
            properties.get("System.Devices.Aep.DeviceAddress"), scope
        )
        identity = str(device.id or "").strip()
        if address is None or not identity or len(identity) > 512:
            return None
        return AepIdentityCandidateV1(
            endpoint_id=identity,
            address=address,
            protocol=scope.protocol,
            name=str(device.name or "").strip()[:128],
            manufacturer=str(
                properties.get("System.Devices.Aep.Manufacturer") or ""
            ).strip()[:128],
            model=str(properties.get("System.Devices.Aep.ModelName") or "").strip()[
                :128
            ],
            observed_at_epoch=at_epoch,
        )
    except (AttributeError, TypeError, ValueError):
        return None


def _winrt_watcher_factory(scope: ReviewedAepScopeV1) -> object:
    """Uses a protocol-specific selector, never an unfiltered CreateWatcher."""

    from winrt.windows.devices.enumeration import (
        DeviceInformation,
        DeviceInformationKind,
    )

    protocol = _PROTOCOLS[scope.protocol]
    aqs = f'System.Devices.Aep.ProtocolId:="{{{protocol}}}"'
    return (
        DeviceInformation.create_watcher_with_kind_aqs_filter_and_additional_properties(
            aqs,
            _PROPERTIES,
            DeviceInformationKind.ASSOCIATION_ENDPOINT,
        )
    )


class WindowsAepIdentityBackend:
    """Explicitly authorized, time-bounded network identity enumeration."""

    def __init__(
        self,
        *,
        is_authorized: Callable[[ReviewedAepScopeV1], bool] | None = None,
        watcher_factory: Callable[
            [ReviewedAepScopeV1], object
        ] = _winrt_watcher_factory,
        platform: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._authorized = is_authorized
        self._watcher_factory = watcher_factory
        self._platform = sys.platform if platform is None else platform
        self._clock = clock

    def observe(self, scope: ReviewedAepScopeV1) -> tuple[AepIdentityCandidateV1, ...]:
        if not isinstance(scope, ReviewedAepScopeV1):
            raise TypeError("AEP requires a reviewed scope")
        if self._platform != "win32" or self._authorized is None:
            return ()
        try:
            if self._authorized(scope) is not True:
                return ()
        except Exception:  # noqa: BLE001 - fail closed for any authority failure
            # A failing authorization service must not authorize a scan.
            return ()

        try:
            watcher = self._watcher_factory(scope)
        except (ImportError, AttributeError, OSError, RuntimeError):
            return ()

        at_epoch = int(self._clock())
        finished = threading.Event()
        lock = threading.Lock()
        candidates: dict[str, AepIdentityCandidateV1] = {}
        aborted = False
        closed = False

        def added(_sender: object, device: object) -> None:
            nonlocal aborted
            candidate = _candidate_from_device(device, scope, at_epoch)
            if candidate is None:
                return
            with lock:
                if closed or aborted:
                    return
                existing = candidates.get(candidate.endpoint_id)
                if existing is not None and existing != candidate:
                    aborted = True  # duplicate identity with conflicting metadata
                    finished.set()
                elif candidate.endpoint_id not in candidates:
                    if len(candidates) >= scope.max_results:
                        aborted = True  # overlimit means incomplete enumeration
                        finished.set()
                    else:
                        candidates[candidate.endpoint_id] = candidate

        def removed(_sender: object, update: object) -> None:
            try:
                endpoint_id = str(update.id or "").strip()
            except (AttributeError, TypeError):
                return
            with lock:
                candidates.pop(endpoint_id, None)

        def completed(_sender: object, _args: object) -> None:
            finished.set()

        tokens: list[tuple[str, object]] = []
        started = False
        try:
            for kind, handler in (
                ("added", added),
                ("removed", removed),
                ("enumeration_completed", completed),
            ):
                token = getattr(watcher, f"add_{kind}")(handler)
                tokens.append((kind, token))
            watcher.start()
            started = True
            # On timeout discard incomplete snapshots, not just late records.
            if not finished.wait(scope.timeout_seconds):
                return ()
            with lock:
                if aborted:
                    return ()
                result = tuple(
                    sorted(candidates.values(), key=lambda item: item.endpoint_id)
                )
            return result
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            return ()
        finally:
            with lock:
                closed = True
            if started:
                try:
                    watcher.stop()
                except (OSError, RuntimeError, ValueError):
                    pass
            for kind, token in reversed(tokens):
                try:
                    getattr(watcher, f"remove_{kind}")(token)
                except (AttributeError, OSError, RuntimeError, ValueError):
                    pass
