"""Read-only Windows LAN scope hints for owner-reviewed active discovery.

This module reads existing NIC/address/route configuration. It never sends
network packets and NEVER grants AEP multicast discovery authority. Active
Windows AEP enumeration may query every local adapter even if only one
result subnet was selected; the owner consent summary must disclose this.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_ALLOWED = tuple(
    ipaddress.IPv4Network(cidr)
    for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
_MAX_NETWORKS = 8
_MAX_OUTPUT_BYTES = 65536

# Fixed script with no external interpolation, no active probes, no writes.
_WINDOWS_SUBNET_SCRIPT = r"""
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
$addresses = @(
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
        $indexes -contains $_.InterfaceIndex -and
        $_.AddressState -eq 'Preferred' -and
        $_.InterfaceAlias -notmatch '^(vEthernet|Loopback)'
    } |
    Select-Object -First 32 -Property InterfaceIndex,InterfaceAlias,IPAddress,PrefixLength
)
ConvertTo-Json -InputObject $addresses -Compress -Depth 3
"""


@dataclass(frozen=True, slots=True)
class WindowsLocalSubnetV1:
    """Result-filter suggestion only; not an approved scan scope."""

    cidr: str
    interface_index: int
    interface_alias: str


def _parse_subnets(raw: str) -> tuple[WindowsLocalSubnetV1, ...]:
    if not raw.strip():
        return ()
    value: Any = json.loads(raw)
    if value is None:
        return ()
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return ()

    results: dict[str, WindowsLocalSubnetV1] = {}
    for row in value[:32]:
        if not isinstance(row, dict):
            continue
        try:
            ip = ipaddress.IPv4Address(str(row.get("IPAddress") or ""))
            prefix_length = int(row.get("PrefixLength"))
            index = int(row.get("InterfaceIndex"))
            alias = str(row.get("InterfaceAlias") or "").strip()
            if not 20 <= prefix_length <= 32 or index <= 0:
                continue
            if not alias or alias.casefold().startswith(("vethernet", "loopback")):
                continue
            network = ipaddress.IPv4Network(
                f"{ip}/{prefix_length}", strict=False
            )
            if not any(network.subnet_of(parent) for parent in _ALLOWED):
                continue
            results[str(network)] = WindowsLocalSubnetV1(
                cidr=str(network),
                interface_index=index,
                interface_alias=alias[:128],
            )
        except (ValueError, TypeError):
            continue

    ordered = sorted(
        results.values(),
        key=lambda item: (
            int(ipaddress.IPv4Network(item.cidr).network_address),
            -ipaddress.IPv4Network(item.cidr).prefixlen,
        ),
    )
    return tuple(ordered[:_MAX_NETWORKS])


class WindowsLocalSubnetObserver:
    """No-scan, no-authorization Windows NIC/route inspector."""

    def __init__(
        self,
        *,
        runner: Callable[..., Any] = subprocess.run,
        platform: str | None = None,
    ) -> None:
        self._runner = runner
        self._platform = sys.platform if platform is None else platform

    def observe(self) -> tuple[WindowsLocalSubnetV1, ...]:
        if self._platform != "win32":
            return ()
        try:
            proc = self._runner(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    _WINDOWS_SUBNET_SCRIPT,
                ],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
            if proc.returncode != 0:
                return ()
            raw = str(proc.stdout or "")
            if len(raw.encode("utf-8")) > _MAX_OUTPUT_BYTES:
                return ()
            return _parse_subnets(raw)
        except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
            return ()
