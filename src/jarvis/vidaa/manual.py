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
import time
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
        from pyvidaa import VidaaTV, discover_udp, probe_ip
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
    if not mac:
        # VIDAA-specific UDP discovery can return the TV's MAC when its
        # UPnP HTTP descriptor is temporarily unavailable. Never borrow
        # identity from a different IP or a generic SSDP neighbor.
        discovered = discover_udp(timeout=4.0, retries=2)
        candidate = discovered.get(args.host)
        if candidate is not None and getattr(candidate, "ip", None) == args.host:
            mac = getattr(candidate, "mac", None)
    # UDP discovery sometimes reports a flat 12-character hexadecimal MAC.
    # Normalize this before the strict RFC1918-target + MAC validation.
    if isinstance(mac, str) and re.fullmatch(r"[0-9a-fA-F]{12}", mac):
        mac = ":".join(mac[i : i + 2] for i in range(0, 12, 2))
    # A prior UPnP sighting of protocol 3290 does not make static auth
    # acceptable when the TV temporarily stops answering discovery. Modern
    # authentication requires the MAC; do not let pyvidaa silently downgrade.
    if not mac:
        raise VidaaManualError(
            "TV MAC unavailable: targeted VIDAA UPnP and UDP discovery did not return "
            "a usable MAC. Modern VIDAA auth requires it; do not fall back "
            "to legacy static credentials. Turn on the TV, verify its current "
            "IP, retry 'identify', or supply its verified network MAC via --mac."
        )
    validate_target(args.host, args.port, mac)
    sdk_options: dict[str, Any] = {
        "host": args.host,
        "port": args.port,
        "mac_address": mac,
        "use_dynamic_auth": True,
        "auto_detect_protocol": True,
        "allow_static_auth": False,
        "enable_persistence": args.persist_tokens,
    }
    if getattr(args, "protocol_version", None) == 3290:
        # Owner previously confirmed this exact protocol from the TV's
        # VIDAA-specific descriptor. Avoid slow HTTP retries to unreachable
        # UPnP ports for every command; do not silently guess other versions.
        from pyvidaa import AuthMethod

        sdk_options["auth_method"] = AuthMethod.MODERN
        sdk_options["auto_detect_protocol"] = False
    return VidaaTV(**sdk_options)


def run_acceptance(
    client: Any,
    *,
    app_name: str = "JioHotstar",
    observation_reader: Callable[[str], str] = input,
    wait: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """One safe, owner-initiated live TV smoke test with one observation prompt.

    Never switches power off, guesses app navigation, or attempts movie playback.
    MQTT publish success alone is never reported as observable TV control.
    """
    checks: dict[str, str] = {"mqtt_connected": "passed"}
    print("VIDAA acceptance: connected. Watch the TV during this test.", flush=True)

    try:
        installed = client.get_apps()
    except Exception:  # noqa: BLE001 - never expose SDK payloads or tokens
        installed = None
    if not isinstance(installed, list):
        checks["app_inventory"] = "failed"
    else:
        checks["app_inventory"] = "passed"

    matching = [
        app
        for app in (installed or [])
        if isinstance(app, dict)
        and str(app.get("name") or "").casefold() == app_name.casefold()
    ]
    checks["target_app_found"] = "passed" if matching else "failed"

    # The TV should be on already. Each key is a permitted remote action.
    for name, key in (
        ("home", "KEY_HOME"),
        ("volume_up", "KEY_VOLUME_UP"),
        ("volume_down", "KEY_VOLUME_DOWN"),
    ):
        print(f"VIDAA acceptance: {name.replace('_', ' ')}", flush=True)
        try:
            sent = client.send_key(key)
        except Exception:  # noqa: BLE001 - no raw SDK error detail
            sent = False
        checks[name] = "submitted_unverified" if sent is not False else "failed"
        wait(1.0)

    if matching:
        print(f"VIDAA acceptance: launching {app_name}", flush=True)
        # Use the TV-supplied app descriptor to avoid a second slow app-list
        # request in pyvidaa.launch_app().
        app = matching[0]
        payload = {k: app[k] for k in ("appId", "name", "url") if k in app}
        try:
            launched = client.launch_app(payload)
        except Exception:  # noqa: BLE001 - no raw SDK payloads
            launched = False
        checks["app_launch"] = (
            "submitted_unverified" if launched is not False else "failed"
        )
        wait(2.0)
    else:
        checks["app_launch"] = "skipped_target_app_not_found"

    # Reconnect with the same client and persisted credentials. This does not
    # prove handling a changed DHCP IP address or TV wake from standby.
    print("VIDAA acceptance: reconnecting MQTT session", flush=True)
    try:
        client.disconnect()
        reconnected = client.connect(timeout=10.0)
    except Exception:  # noqa: BLE001 - do not expose SDK auth details
        reconnected = False
    checks["mqtt_reconnect"] = "passed" if reconnected else "failed"

    # Ask only once, after displaying all physical effects. The owner observes
    # the TV; do not treat successful publishes as acceptance without this.
    if checks["home"] == "submitted_unverified" and checks["volume_up"] == "submitted_unverified" and checks["volume_down"] == "submitted_unverified" and checks["app_launch"] == "submitted_unverified":
        try:
            observed = observation_reader(
                "Did Home, volume change and JioHotstar launch all work on TV? [y/N]: "
            )
        except (EOFError, KeyboardInterrupt):
            observed = ""
        checks["owner_visual_effects"] = (
            "confirmed" if observed.strip().lower() in ("y", "yes") else "unverified"
        )
    else:
        checks["owner_visual_effects"] = "unverified"

    # Explicitly identify scope gaps rather than inventing passing results.
    checks["movie_search_and_playback"] = "skipped_not_implemented"
    checks["power_on_from_standby"] = "skipped_not_verified"
    checks["dynamic_ip_recovery"] = "skipped_not_verified"
    checks["jarvis_voice_integration"] = "skipped_not_integrated"

    failures = [name for name, value in checks.items() if value == "failed"]
    return {
        "outcome": "acceptance_failed" if failures else "acceptance_completed",
        "checks": checks,
        "failed_checks": failures,
        "physical_tv_verified": checks["owner_visual_effects"] == "confirmed",
        "notes": (
            "One-run smoke test for implemented VIDAA controls; remaining "
            "unimplemented or unverified features are explicitly skipped."
        ),
    }


def execute(
    args: argparse.Namespace,
    *,
    client_factory: Callable[[argparse.Namespace], Any] | None = None,
    pin_reader: Callable[[str], str] | None = None,
    socket_connector: Callable[..., Any] | None = None,
    device_probe: Callable[..., Any] | None = None,
    cert_resolver: Callable[[], Any] | None = None,
    udp_discover: Callable[..., Any] | None = None,
    command_reader: Callable[[str], str] | None = None,
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

    if args.command == "discover":
        if udp_discover is None:
            try:
                from pyvidaa import discover_udp
            except ImportError as exc:
                raise VidaaManualError("Install pyvidaa in the active venv") from exc
            udp_discover = discover_udp
        observed = udp_discover(timeout=4.0, retries=2)
        candidates = []
        for host, device in sorted(observed.items()):
            try:
                validate_target(host, args.port, None)
            except VidaaManualError:
                continue
            candidates.append(
                {
                    "ip": host,
                    "name": getattr(device, "name", None),
                    "model": getattr(device, "model", None),
                    "mac_available": bool(getattr(device, "mac", None)),
                    "matches_requested_host": host == args.host,
                    "tv_verified": False,
                }
            )
        return {
            "outcome": "vidaa_udp_candidates"
            if candidates
            else "no_vidaa_udp_candidates",
            "candidates": candidates[:20],
            "note": "UDP sightings are unverified; confirm the TV's IP before control.",
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
            # pyvidaa exposes the MQTT CONNACK return code separately from
            # socket/TLS failures. Only report non-secret protocol status.
            connack = getattr(client, "_last_connack_rc", None)
            if connack in (4, 5):
                reason = (
                    "bad MQTT username/password"
                    if connack == 4
                    else "MQTT not authorized"
                )
                raise VidaaManualError(
                    f"VIDAA MQTT rejected connection (CONNACK {connack}: {reason}). "
                    "Check the TV clock, dynamically detected TV MAC and "
                    "previously saved authorization. No PIN request was sent."
                )
            if connack is None:
                raise VidaaManualError(
                    "VIDAA connection failed without an observed MQTT CONNACK. "
                    "TCP was previously reachable; TLS handshake, transport "
                    "closure or timeout remain possible. No PIN request was sent."
                )
            raise VidaaManualError(
                f"VIDAA broker refused connection (MQTT CONNACK {connack}). "
                "No PIN request was sent."
            )
        if args.command == "acceptance":
            return run_acceptance(
                client,
                app_name=args.app,
                observation_reader=command_reader or input,
            )
        if args.command == "session":
            # Reuse one authenticated MQTT/TLS connection for fast repeated
            # remote presses. CLI-only, no automatic device actions.
            read = command_reader or input
            submitted = 0
            while True:
                try:
                    command = read("VIDAA remote (home/volume-up/.../exit)> ")
                except (EOFError, KeyboardInterrupt):
                    break
                command = command.strip().lower()
                if command in ("exit", "quit"):
                    break
                if command not in REMOTE_KEYS:
                    print(
                        json.dumps(
                            {
                                "outcome": "invalid_remote_key",
                                "supported": sorted(REMOTE_KEYS),
                            }
                        )
                    )
                    continue
                code = REMOTE_KEYS[command]
                if client.send_key(code) is False:
                    raise VidaaManualError("SDK rejected remote key command")
                submitted += 1
                print(
                    json.dumps(
                        {
                            "outcome": "key_submitted_unverified",
                            "key": code,
                            "tv_effect_verified": False,
                        }
                    )
                )
            return {
                "outcome": "remote_session_ended",
                "keys_submitted": submitted,
                "tv_effect_verified": False,
            }
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
        "--protocol-version",
        type=int,
        choices=(3290,),
        help="Owner-verified VIDAA version; 3290 skips slow UPnP protocol probing",
    )
    parser.add_argument(
        "--persist-tokens",
        action="store_true",
        help="Opt in to pyvidaa SDK's local token persistence",
    )
    actions = parser.add_subparsers(dest="command", required=True)
    for name in (
        "probe",
        "discover",
        "identify",
        "certs",
        "pair",
        "status",
        "apps",
        "session",
    ):
        actions.add_parser(name)
    key = actions.add_parser("key")
    key.add_argument("key", choices=sorted(REMOTE_KEYS))
    launch = actions.add_parser("launch")
    launch.add_argument("app", help="Exact app name returned by 'apps'")
    acceptance = actions.add_parser(
        "acceptance", help="Single-run safe TV smoke test with one visual confirmation"
    )
    acceptance.add_argument(
        "--app", default="JioHotstar", help="Exact installed TV app to launch"
    )
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
    return 2 if result["outcome"] in {"tcp_unreachable", "no_state", "acceptance_failed"} else 0


if __name__ == "__main__":
    sys.exit(main())
