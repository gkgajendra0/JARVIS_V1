"""Read-only Windows media-network diagnostics: no packets, sockets or pairing.

Network addresses come only from cached Windows neighbor rows and current
passive OS interface configuration. WinRT readiness loads its Python projection
but never creates/starts a DeviceWatcher. No observation establishes TV identity.
"""

from __future__ import annotations

import importlib
import ipaddress
import sys
from collections.abc import Callable
from typing import Any

from .local_network import WindowsPassiveNeighborBackend
from .windows_lan_scope import WindowsLanScopePlanner


def inspect_passive_media_network(
    *,
    platform: str | None = None,
    planner: WindowsLanScopePlanner | None = None,
    neighbors: WindowsPassiveNeighborBackend | None = None,
    load_module: Callable[[str], Any] = importlib.import_module,
) -> dict[str, object]:
    """Inspect the local OS cache and WinRT dependency without network traffic."""

    os_name = sys.platform if platform is None else platform
    if os_name != "win32":
        return {
            "state": "not_windows",
            "winrt_backend": "not_applicable",
            "cached_neighbor_candidates": [],
            "network_probe_performed": False,
        }
    try:
        module = load_module("winrt.windows.devices.enumeration")
        device = getattr(module, "DeviceInformation", None)
        kind = getattr(module, "DeviceInformationKind", None)
        winrt_state = (
            "loadable"
            if device is not None
            and kind is not None
            and callable(
                getattr(
                    device,
                    "create_watcher_with_kind_aqs_filter_and_additional_properties",
                    None,
                )
            )
            else "missing_api"
        )
    except (ImportError, OSError, RuntimeError, AttributeError):
        winrt_state = "unavailable"

    cached: list[dict[str, object]] = []
    try:
        current_scopes = (planner or WindowsLanScopePlanner()).inspect()
        rows, _observed_at = (neighbors or WindowsPassiveNeighborBackend()).observe()
        allowed = tuple(
            (ipaddress.IPv4Network(scope.cidr), scope.interface_index)
            for scope in current_scopes
        )
        for row in rows:
            address = ipaddress.IPv4Address(row.ip_address)
            if not any(
                address in network and row.interface_index == interface_index
                for network, interface_index in allowed
            ):
                continue
            cached.append(
                {
                    "address": row.ip_address,
                    "neighbor_state": row.state,
                    "verified_tv_identity": False,
                }
            )
            if len(cached) >= 16:
                break
    except (OSError, ValueError, TypeError, AttributeError):
        cached = []

    return {
        "state": "passive_inspection_completed",
        "winrt_backend": winrt_state,
        "cached_neighbor_candidates": cached,
        "network_probe_performed": False,
    }
