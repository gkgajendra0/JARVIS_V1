"""Passive Windows LAN scope planning for owner-approved network discovery.

Do not make the owner type IP addresses or CIDRs. Read local interface facts
without transmitting packets and construct permission *proposals* only.
Discovery, pairing and device control have separate Authority contracts.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .windows_aep import ReviewedAepScopeV1
from .world import canonical_world_entity_type

_MAX_BYTES = 32_768
_RFC1918 = tuple(
    ipaddress.IPv4Network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)

# Enumerates existing OS network configuration; does not query any LAN device.
_PASSIVE_SCOPE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$indices = @(
    Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
    Where-Object {
        $_.NextHop -ne '0.0.0.0' -and
        $_.InterfaceAlias -notmatch '^(vEthernet|Loopback)'
    } |
    Select-Object -ExpandProperty InterfaceIndex -Unique
)
$addresses = @(
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $indices -contains $_.InterfaceIndex -and
        $_.InterfaceAlias -notmatch '^(vEthernet|Loopback)' -and
        $_.AddressState -eq 'Preferred'
    } |
    Select-Object -First 16 -Property InterfaceAlias,InterfaceIndex,IPAddress,PrefixLength
)
ConvertTo-Json -InputObject $addresses -Compress -Depth 3
"""


@dataclass(frozen=True, slots=True)
class PassiveLanScopeV1:
    cidr: str
    interface_index: int


def _parse_networks(output: str) -> tuple[PassiveLanScopeV1, ...]:
    raw: Any = json.loads(output) if output.strip() else []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return ()
    networks: set[tuple[str, int]] = set()
    for row in raw[:16]:
        if not isinstance(row, dict):
            continue
        try:
            address = ipaddress.IPv4Address(str(row.get("IPAddress") or ""))
            prefix = int(row.get("PrefixLength"))
            index = int(row.get("InterfaceIndex"))
            alias = str(row.get("InterfaceAlias") or "").strip()
            network = ipaddress.IPv4Network((address, prefix), strict=False)
        except (ValueError, TypeError):
            continue
        if (
            index <= 0
            or not alias
            or alias.casefold().startswith(("vethernet", "loopback"))
            or not 20 <= prefix <= 30
            or not any(network.subnet_of(private) for private in _RFC1918)
        ):
            continue
        networks.add((str(network), index))
    return tuple(
        PassiveLanScopeV1(cidr=cidr, interface_index=index)
        for cidr, index in sorted(networks, key=lambda item: (item[0], item[1]))
    )[:8]


class WindowsLanScopePlanner:
    """Local OS introspection only; cannot authorize or start AEP discovery."""

    def __init__(
        self,
        *,
        runner: Callable[..., Any] = subprocess.run,
        platform: str | None = None,
    ) -> None:
        self._runner = runner
        self._platform = sys.platform if platform is None else platform

    def inspect(self) -> tuple[PassiveLanScopeV1, ...]:
        if self._platform != "win32":
            return ()
        try:
            result = self._runner(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    _PASSIVE_SCOPE_SCRIPT,
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                return ()
            output = str(result.stdout or "")
            if len(output.encode("utf-8")) > _MAX_BYTES:
                return ()
            return _parse_networks(output)
        except (
            AttributeError,
            TypeError,
            OSError,
            ValueError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ):
            return ()

    def consent_scopes_for(
        self, requested_entity_type: str
    ) -> tuple[ReviewedAepScopeV1, ...]:
        kind = canonical_world_entity_type(requested_entity_type)
        if kind == "media_player":
            protocols = ("upnp", "dns_sd")
        elif kind == "camera":
            protocols = ("wsd",)
        else:
            return ()
        networks = self.inspect()
        if not networks:
            return ()
        cidrs = tuple(sorted({item.cidr for item in networks}))
        if len(cidrs) > 8:
            return ()
        # Placeholder is not a grant. Owner and Authority must bind a real
        # approval_id / execution permit before any WinRT watcher can start.
        return tuple(
            ReviewedAepScopeV1(
                protocol=protocol,
                approved_address_ranges=cidrs,
                consent_record_id="pending_owner_approval",
                all_local_interfaces_authorized=True,
                timeout_seconds=1.5,
                max_results=16,
            )
            for protocol in protocols
        )
