"""Passive Windows network-neighbor observations for GICC information gathering.

A cached ARP/neighbor entry only says that Windows has seen an IP/MAC pair.
It does NOT identify a product, authorize a probe, prove online reachability,
or constitute evidence that a control protocol/operation works.

The fixed PowerShell command only reads locally cached OS information. It does
not emit packets, attempt DNS, scan ports, authenticate or modify device state.
"""

from __future__ import annotations

import ipaddress
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jarvis.engineering_substrate.canonical import canonical_digest

from .information import InformationProbeResult, InformationResolutionStrategy
from .models import InformationNeedV1
from .world import canonical_world_entity_type
from .windows_aep import ReviewedAepScopeV1, WindowsAepIdentityBackend

_MAX_ROWS = 16
_MAX_OUTPUT_BYTES = 65536
_LOCAL_IPV4_NETWORKS = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)
_MAC_RE = re.compile(r"^[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}$", re.IGNORECASE)

# All strings are constants, not interpolated owner/model/network parameters.
_WINDOWS_NEIGHBORS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$indexes = @(
    Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Where-Object {
        $_.NextHop -ne '0.0.0.0' -and
        $_.InterfaceAlias -notmatch '^(vEthernet|Loopback)' -and
        $_.InterfaceIndex -gt 0
    } |
    Select-Object -ExpandProperty InterfaceIndex -Unique
)
$neighbors = @(
    Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $indexes -contains $_.InterfaceIndex -and
        $_.State -in @('Reachable','Stale','Delay','Probe')
    } |
    Select-Object -First 32 -Property InterfaceAlias,InterfaceIndex,IPAddress,LinkLayerAddress,@{Name='State';Expression={$_.State.ToString()}}
)
ConvertTo-Json -InputObject $neighbors -Compress -Depth 3
"""


@dataclass(frozen=True, slots=True)
class PassiveNeighborV1:
    """OS-cached, unverified observation; intentionally not a WorldEntityRef."""

    ip_address: str
    mac_address: str
    state: str
    interface_index: int

    @property
    def evidence_ref(self) -> str:
        return (
            "windows_neighbor_unverified:"
            f"{self.ip_address}:{self.mac_address}:{self.state}"
        )


def _parse_rows(raw: str) -> tuple[PassiveNeighborV1, ...]:
    if not raw.strip():
        return ()
    data: Any = json.loads(raw)
    if data is None:
        return ()
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return ()
    results: dict[tuple[str, str], PassiveNeighborV1] = {}
    for row in data[:32]:
        if not isinstance(row, dict):
            continue
        try:
            ip = ipaddress.IPv4Address(str(row.get("IPAddress") or ""))
            mac = str(row.get("LinkLayerAddress") or "").strip().lower()
            state = str(row.get("State") or "").strip().lower()
            idx = int(row.get("InterfaceIndex"))
            alias = str(row.get("InterfaceAlias") or "").strip()
        except (ValueError, TypeError):
            continue
        # Never treat cache entries on loopback, multicast, public or
        # non-physical interfaces as candidates for local device identity.
        if not any(ip in subnet for subnet in _LOCAL_IPV4_NETWORKS):
            continue
        if not alias or alias.casefold().startswith(("vethernet", "loopback")):
            continue
        if not _MAC_RE.fullmatch(mac) or idx < 1:
            continue
        if state not in {"reachable", "stale", "delay", "probe"}:
            continue
        item = PassiveNeighborV1(
            ip_address=str(ip),
            mac_address=mac.replace(":", "-"),
            state=state,
            interface_index=idx,
        )
        results[(item.ip_address, item.mac_address)] = item
    ordered = sorted(
        results.values(),
        key=lambda item: (
            int(ipaddress.IPv4Address(item.ip_address)),
            item.mac_address,
        ),
    )
    return tuple(ordered[:_MAX_ROWS])


class WindowsPassiveNeighborBackend:
    """Bounded, read-only OS-cache query; no network-probing privileges."""

    def __init__(
        self,
        *,
        runner: Callable[..., Any] = subprocess.run,
        platform: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._runner = runner
        self._platform = sys.platform if platform is None else platform
        self._clock = clock

    def observe(self) -> tuple[tuple[PassiveNeighborV1, ...], int]:
        collected_at = int(self._clock())
        if self._platform != "win32":
            return (), collected_at
        try:
            process = self._runner(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    _WINDOWS_NEIGHBORS_SCRIPT,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if process.returncode != 0:
                return (), collected_at
            data = str(process.stdout or "")
            if len(data.encode("utf-8")) > _MAX_OUTPUT_BYTES:
                return (), collected_at
            return _parse_rows(data), collected_at
        except (OSError, ValueError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return (), collected_at


class WindowsNeighborInformationProbe:
    """Expose passive candidates to GICC; NEVER claim entity identity."""

    strategy = InformationResolutionStrategy.CURRENT_STATE_OBSERVATION

    def __init__(
        self,
        backend: WindowsPassiveNeighborBackend | None = None,
        *,
        aep_backend: WindowsAepIdentityBackend | None = None,
        aep_scopes: tuple[ReviewedAepScopeV1, ...] = (),
    ) -> None:
        self._backend = backend or WindowsPassiveNeighborBackend()
        # Network enumeration is active; never create an implicit AEP grant.
        if aep_scopes and aep_backend is None:
            raise ValueError("AEP scopes require a separately authorized backend")
        self._aep_backend = aep_backend
        self._aep_scopes = tuple(aep_scopes)

    def resolve(self, need: InformationNeedV1) -> InformationProbeResult:
        if need.answer_schema.get("type") != "entity_id":
            return InformationProbeResult(resolution_ref=None)
        target_type = canonical_world_entity_type(need.answer_schema.get("entity_type"))
        if target_type not in {
            "media_player",
            "camera",
            "computer",
            "display",
            "speaker",
            "printer",
        }:
            return InformationProbeResult(resolution_ref=None)
        observations, at_epoch = self._backend.observe()
        if not observations:
            return InformationProbeResult(
                resolution_ref=None,
                reason="no passive Windows network neighbors verified",
            )
        evidence = [
            f"windows_neighbor_cache_observed:{at_epoch:012d}:"
            + canonical_digest({"rows": [r.evidence_ref for r in observations]}),
            *(row.evidence_ref for row in observations),
        ]
        # Optional WinRT AEP discovery is only possible with independently
        # reviewed scopes and a trusted authorization checker. Match its
        # metadata to an OS-observed IP, but NEVER bind a world entity or
        # candidate capability from these observations by themselves.
        if self._aep_backend is not None and self._aep_scopes:
            neighbors = {row.ip_address for row in observations}
            matched: dict[str, list] = {}
            for scope in self._aep_scopes:
                for candidate in self._aep_backend.observe(scope):
                    if candidate.address in neighbors:
                        matched.setdefault(candidate.address, []).append(candidate)
            for address, group in sorted(matched.items()):
                vendors = {
                    value.manufacturer.casefold()
                    for value in group
                    if value.manufacturer.strip()
                }
                models = {
                    value.model.casefold() for value in group if value.model.strip()
                }
                if len(vendors) > 1 or len(models) > 1:
                    continue  # disagreeing identity advertisements
                evidence.extend(
                    f"windows_aep_neighbor_correlated_unverified:{address}:"
                    + item.evidence_ref
                    for item in sorted(
                        group, key=lambda value: (value.protocol, value.endpoint_id)
                    )
                )
        return InformationProbeResult(
            resolution_ref=None,
            evidence_refs=tuple(evidence),
            reason=(
                "Windows network candidates only: name and model advertisements "
                "are unverified; no device type, control protocol, pairing or "
                "execution authority established"
            ),
        )
