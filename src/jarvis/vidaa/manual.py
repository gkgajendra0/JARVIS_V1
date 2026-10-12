"""Manual, owner-initiated VIDAA control, independent of autonomous acquisition.

Run with: python -m jarvis.vidaa.manual --host 192.168.1.10 probe

An open TCP port is not a verified TV. MQTT commands are not proof of an
observable TV effect. The operator must confirm that effect separately.
"""

from __future__ import annotations

import argparse
import contextlib
import getpass
import ipaddress
import json
import re
import socket
import sys
from collections.abc import Callable
from typing import Any

TV_PORT = 36669
LAN_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
REMOTE_KEYS = {
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
    "ok": "KEY_OK",
    "back": "KEY_BACK",
    "home": "KEY_HOME",
    "menu": "KEY_MENU",
    "volume-up": "KEY_VOLUME_UP",
    "volume-down": "KEY_VOLUME_DOWN",
    "mute": "KEY_MUTE",
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSE",
    "stop": "KEY_STOP",
}


class VidaaManualError(RuntimeError):
    """Known manual VIDAA operation failure."""


def validate_target(host: str, port: int, mac: str | None) -> None:
    """Reject non-RFC1918 destinations, preventing arbitrary remote connections."""
    try:
        address = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError as exc:
        raise VidaaManualError("Host must be a literal private IPv4 address") from exc
    if not any(address in network for network in LAN_NETWORKS):
        raise VidaaManualError("TV target must be on a private RFC1918 LAN")
    if not 1 <= port <= 65535:
        raise VidaaManualError("Invalid TCP port")
    if mac and not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise VidaaManualError("MAC must use AA:BB:CC:DD:EE:FF format")


def new_client(args: argparse.Namespace) -> Any:
    """Lazy import: production JARVIS does not require the optional SDK."""
    try:
        from pyvidaa import VidaaTV, probe_ip
    except ImportError as exc:
        raise VidaaManualError(
            "Optional dependency unavailable: install pyvidaa in the active venv"
        ) from exc
    mac = args.mac
    if mac is None:
        # Modern VIDAA (including observed protocol 3290) requires the TV MAC
        # for dynamic MQTT credentials. Use only a targeted, matching descriptor.
        device = probe_ip(args.host, timeout=3.0)
        if device is not None and getattr(device, "ip", None) == args.host:
            mac = getattr(device, "mac", None)
            protocol = getattr(device, "protocol_version", None)
            if not mac and protocol and int(protocol) >= 3000:
                raise VidaaManualError(
                    "Modern VIDAA protocol discovered without a MAC address; "
                    "provide the TV network-interface MAC via --mac"
                )
    validate_target(args.host, args.port, mac)
    return VidaaTV(
        host=args.host,
        port=args.port,
        mac_address=mac,
        auto_detect_protocol=True,
        enable_persistence=args.persist_tokens,
    )


def execute(
    args: argparse.Namespace,
    *,
    client_factory: Callable[[argparse.Namespace], Any] | None = None,
    pin_reader: Callable[[str], str] | None = None,
    socket_connector: Callable[..., Any] | None = None,
    device_probe: Callable[..., Any] | None = None,
    cert_resolver: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Execute one explicitly requested action with test-injectable boundaries."""
    validate_target(args.host, args.port, args.mac)
    if args.command == "probe":
        connector = socket_connector or socket.create_connection
        try:
            sock = connector((args.host, args.port), timeout=3.0)
            sock.close()
        except OSError:
            return {
                "outcome": "tcp_unreachable",
                "host": args.host,
                "port": args.port,
                "tv_verified": False,
            }
        return {
            "outcome": "tcp_reachable_only",
            "host": args.host,
            "port": args.port,
            "tv_verified": False,
        }

    if args.command == "identify":
        if device_probe is None:
            try:
                from pyvidaa import probe_ip
            except ImportError as exc:
                raise VidaaManualError("Install pyvidaa in the active venv") from exc
            device_probe = probe_ip
        device = device_probe(args.host, timeout=3.0)
        if device is None:
            return {
                "outcome": "vidaa_upnp_not_observed",
                "host": args.host,
                "tv_verified": False,
                "note": "No UPnP response does not prove this is not a TV.",
            }
        return {
            "outcome": "vidaa_upnp_candidate",
            "host": args.host,
            "name": getattr(device, "name", None),
            "model": getattr(device, "model", None),
            "brand": getattr(device, "brand", None),
            "protocol_version": getattr(device, "protocol_version", None),
            "mac_available": bool(getattr(device, "mac", None)),
            "tv_verified": False,
            "control_verified": False,
        }

    if args.command == "certs":
        if cert_resolver is None:
            try:
                from pyvidaa.certs import resolve_client_certs
            except ImportError as exc:
                raise VidaaManualError("Install pyvidaa in the active venv") from exc
            cert_resolver = resolve_client_certs
        found = cert_resolver() is not None
        return {
            "outcome": "client_certificate_pair_present"
            if found
            else "client_certificate_pair_missing",
            "tls_files_found": found,
            "tls_handshake_verified": False,
            "help": (
                "See pyvidaa README: Obtaining the client certificate."
                if not found
                else "File presence does not prove TV TLS authentication."
            ),
        }

    client = (client_factory or new_client)(args)
    try:
        if not client.connect(timeout=10.0):
            if cert_resolver is None:
                try:
                    from pyvidaa.certs import resolve_client_certs
                except ImportError:
                    resolve_client_certs = None
                cert_resolver = resolve_client_certs
            if cert_resolver is not None:
                certs = cert_resolver()
                if certs is None:
                    raise VidaaManualError(
                        "VIDAA connection failed with no client cert/key installed. "
                        "Modern firmware may require mutual TLS. Run 'certs' and "
                        "see the pyvidaa README for obtaining the client certificate."
                    )
            raise VidaaManualError(
                "VIDAA client did not connect; check protocol, TV settings and power"
            )
        if args.command == "pair":
            if client.start_pairing() is False:
                raise VidaaManualError(
                    "TV rejected the pairing request; no PIN expected"
                )
            reader = pin_reader or getpass.getpass
            pin = reader("PIN displayed on TV (not echoed): ").strip()
            if not re.fullmatch(r"\d{4,8}", pin):
                raise VidaaManualError("PIN must be 4-8 digits")
            if client.authenticate(pin) is not True:
                raise VidaaManualError("TV pairing was not confirmed by the SDK")
            return {
                "outcome": "sdk_pairing_acknowledged",
                "tv_effect_verified": False,
                "tokens_persisted_by_sdk": args.persist_tokens,
            }
        if args.command == "status":
            state = client.get_state()
            volume = client.get_volume()
            return {
                "outcome": "status_response" if state is not None else "no_state",
                "state": state,
                "volume": volume,
                "tv_effect_verified": False,
            }
        if args.command == "apps":
            apps = client.get_apps()
            names = [
                str(app["name"])
                for app in (apps or [])
                if isinstance(app, dict) and app.get("name")
            ]
            return {
                "outcome": "apps_response" if apps is not None else "no_apps",
                "apps": names,
                "tv_effect_verified": False,
            }
        if args.command == "key":
            code = REMOTE_KEYS[args.key]
            result = client.send_key(code)
            if result is False:
                raise VidaaManualError("SDK rejected the remote key command")
            return {
                "outcome": "key_submitted_unverified",
                "key": code,
                "tv_effect_verified": False,
            }
        if args.command == "launch":
            apps = client.get_apps() or []
            matches = [
                str(app["name"])
                for app in apps
                if isinstance(app, dict)
                and str(app.get("name") or "").casefold() == args.app.casefold()
            ]
            if not matches:
                raise VidaaManualError(
                    "App not confirmed in TV app list. Run 'apps' first."
                )
            result = client.launch_app(matches[0])
            if result is False:
                raise VidaaManualError("SDK rejected app-launch request")
            return {
                "outcome": "launch_submitted_unverified",
                "app": matches[0],
                "tv_effect_verified": False,
            }
        raise VidaaManualError("Unsupported action")
    finally:
        with contextlib.suppress(OSError):
            client.disconnect()


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Explicit manual Hisense VIDAA test; never autonomous discovery."
    )
    parser.add_argument("--host", required=True, help="Known candidate private IPv4")
    parser.add_argument("--port", type=int, default=TV_PORT)
    parser.add_argument("--mac", help="Optional verified TV MAC address")
    parser.add_argument(
        "--persist-tokens",
        action="store_true",
        help="Opt in to pyvidaa SDK's local token persistence",
    )
    actions = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "identify", "certs", "pair", "status", "apps"):
        actions.add_parser(name)
    key = actions.add_parser("key")
    key.add_argument("key", choices=sorted(REMOTE_KEYS))
    launch = actions.add_parser("launch")
    launch.add_argument("app", help="Exact app name returned by 'apps'")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(argv)
    try:
        result = execute(args)
    except VidaaManualError as exc:
        print(json.dumps({"outcome": "blocked", "reason": str(exc)}))
        return 2
    except Exception as exc:  # noqa: BLE001 - sanitize opaque SDK failures
        # Raw SDK errors may contain authentication material; print only the type.
        print(json.dumps({"outcome": "sdk_error", "error_type": type(exc).__name__}))
        return 3
    print(json.dumps(result, default=str))
    return 2 if result["outcome"] in {"tcp_unreachable", "no_state"} else 0


if __name__ == "__main__":
    sys.exit(main())
