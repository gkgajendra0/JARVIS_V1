"""Read-only software observation reconnaissance for owner-paired VIDAA TVs.

VIDAA MQTT state and device metadata are NOT screenshots, an accessibility
tree, current focus, or evidence of video playback.

Two bounded checks of documented older VIDAA ports 9226 and 9222 can
find possible developer-inspection services. It does not turn on debugging,
retrieve DOM or screenshots, or assume commercial apps are inspectable.
"""

from __future__ import annotations

import ipaddress
import json
import socket
from collections.abc import Callable
from typing import Any

INSPECTOR_PORT = 9226
ALTERNATE_INSPECTOR_PORT = 9222
DOCUMENTED_INSPECTOR_PORTS = frozenset((INSPECTOR_PORT, ALTERNATE_INSPECTOR_PORT))
MAX_HTTP_RESPONSE = 8192

# Never publish raw device identifiers, serial numbers, certificate materials,
# arbitrary JSON payloads or app account data in diagnostic output.
TV_INFO_FIELDS = frozenset(("brand", "chipplatform", "fake_sleep", "uVersion"))
DEVICE_INFO_FIELDS = frozenset(("model_name", "tv_version", "country"))
CAPABILITY_FIELDS = frozenset(("resolution", "softwareVersion"))
STATE_FIELDS = frozenset(("statetype", "source"))


def _safe_field_names(payload: Any, allowlist: frozenset[str]) -> list[str]:
    if not isinstance(payload, dict):
        return []
    return sorted(key for key in allowlist if key in payload)


def _safe_state_value(payload: Any, name: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(name)
    if not isinstance(value, str) or not 1 <= len(value) <= 48:
        return None
    if not all(char.isascii() and (char.isalnum() or char in "_-") for char in value):
        return None
    return value


def _read_metadata(
    client: Any, method_name: str, fields: frozenset[str]
) -> dict[str, Any]:
    method = getattr(client, method_name, None)
    if not callable(method):
        return {"status": "sdk_method_not_available", "available_fields": []}
    try:
        response = method(timeout=2.0)
    except Exception:  # noqa: BLE001 - avoid logging SDK errors with identifiers
        return {"status": "request_failed", "available_fields": []}
    if not isinstance(response, dict):
        return {"status": "no_structured_response", "available_fields": []}
    result: dict[str, Any] = {
        "status": "metadata_received",
        "available_fields": _safe_field_names(response, fields),
    }
    if method_name == "get_state":
        result["state_type"] = _safe_state_value(response, "statetype")
        result["state_source"] = _safe_state_value(response, "source")
    return result


def probe_legacy_inspector(
    host: str,
    *,
    port: int = INSPECTOR_PORT,
    connector: Callable[..., Any] = socket.create_connection,
) -> dict[str, Any]:
    """Make one bounded read-only request to a known legacy debug port.

    No port range scan, debug enablement, authentication bypass, URL redirect,
    JS execution, inspection of page content, or leaking of response bodies.
    """
    if port not in DOCUMENTED_INSPECTOR_PORTS:
        raise ValueError("Only documented VIDAA inspector ports are permitted")
    address = ipaddress.IPv4Address(host)
    if not address.is_private or address.is_loopback or address.is_link_local:
        raise ValueError("Inspector probe requires private non-loopback IPv4")

    sock = None
    try:
        sock = connector((host, port), timeout=0.8)
        sock.settimeout(0.8)
        request = (
            f"GET /json/version HTTP/1.1\r\nHost: {host}:{port}\r\n"
            "Accept: application/json\r\nConnection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(request)
        response = sock.recv(MAX_HTTP_RESPONSE)
    except (OSError, TimeoutError):
        return {
            "port": port,
            "result": "unreachable_or_no_response",
            "inspector_confirmed": False,
        }
    finally:
        if sock is not None:
            sock.close()

    if b"\r\n\r\n" not in response:
        result = "tcp_open_non_http_or_incomplete_response"
    else:
        headers, payload = response.split(b"\r\n\r\n", 1)
        result = "http_service_unidentified"
        if headers.startswith((b"HTTP/1.1 200 ", b"HTTP/1.0 200 ")):
            try:
                doc = json.loads(payload)
            except (UnicodeDecodeError, json.JSONDecodeError):
                doc = None
            if isinstance(doc, dict) and (
                isinstance(doc.get("Browser"), str)
                and isinstance(doc.get("Protocol-Version"), str)
            ):
                result = "cdp_version_endpoint_detected"

    return {
        "port": port,
        "result": result,
        "inspector_confirmed": result == "cdp_version_endpoint_detected",
    }


def observe_software(
    client: Any,
    host: str,
    *,
    inspector_probe: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Inventory available software signals, without claiming screen visibility."""
    state = _read_metadata(client, "get_state", STATE_FIELDS)
    tv_info = _read_metadata(client, "get_tv_info", TV_INFO_FIELDS)
    device_info = _read_metadata(client, "get_device_info", DEVICE_INFO_FIELDS)
    capability = _read_metadata(client, "get_capability", CAPABILITY_FIELDS)

    try:
        inspector = (inspector_probe or probe_legacy_inspector)(host)
    except (OSError, TimeoutError, ValueError):
        inspector = {
            "port": INSPECTOR_PORT,
            "result": "probe_failed",
            "inspector_confirmed": False,
        }

    # VIDAA's older developer guide lists both 9226 and 9222 depending
    # on chipset. Neither is guaranteed on the owner's newer VIDAA U7.6.
    # Don't touch the LAN for offline tests that injected their boundary.
    if inspector_probe is not None:
        alternate = {
            "port": ALTERNATE_INSPECTOR_PORT,
            "result": "not_probed_injected_boundary",
            "inspector_confirmed": False,
        }
    elif inspector.get("inspector_confirmed"):
        alternate = {
            "port": ALTERNATE_INSPECTOR_PORT,
            "result": "not_needed_primary_inspector_detected",
            "inspector_confirmed": False,
        }
    else:
        try:
            alternate = probe_legacy_inspector(
                host, port=ALTERNATE_INSPECTOR_PORT
            )
        except (OSError, TimeoutError, ValueError):
            alternate = {
                "port": ALTERNATE_INSPECTOR_PORT,
                "result": "probe_failed",
                "inspector_confirmed": False,
            }

    return {
        "outcome": "software_observation_probe_complete",
        "signal_inventory": {
            "tv_state": state,
            "tv_info": tv_info,
            "device_info": device_info,
            "capability": capability,
        },
        "legacy_developer_inspector": inspector,
        "alternate_legacy_inspector": alternate,
        "screen_observation": {
            "screenshot": "not_observed",
            "ui_tree": "not_observed",
            "focused_element": "not_observed",
            "movie_playback": "not_observed",
        },
        "software_ui_navigation_ready": False,
        "scope": (
            "Read-only observation discovery, not a screenshot or DOM capture. "
            "A reachable inspector endpoint would require separate app-specific "
            "compatibility and owner-authorized read-only inspection."
        ),
    }
