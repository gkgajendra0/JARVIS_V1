"""No owner IP-entry: passive Windows LAN scope and consent planning."""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from jarvis.goal_intelligence.aep_authority import build_aep_consent_proposal
from jarvis.goal_intelligence.windows_lan_scope import (
    _PASSIVE_SCOPE_SCRIPT,
    WindowsLanScopePlanner,
    _parse_networks,
)


def _row(ip: str, prefix: int = 24, alias: str = "Ethernet", index: int = 4):
    return {
        "IPAddress": ip,
        "PrefixLength": prefix,
        "InterfaceAlias": alias,
        "InterfaceIndex": index,
    }


def _planner(rows, *, platform: str = "win32", calls=None):
    def runner(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(rows),
            stderr="",
        )

    return WindowsLanScopePlanner(runner=runner, platform=platform)


def test_os_derived_media_scopes_do_not_require_owner_ip_entry() -> None:
    calls = []
    planner = _planner([_row("192.168.1.6"), _row("192.168.1.8")], calls=calls)
    scopes = planner.consent_scopes_for("smart_tv")
    assert [scope.protocol for scope in scopes] == ["upnp", "dns_sd"]
    assert all(scope.approved_address_ranges == ("192.168.1.0/24",) for scope in scopes)
    assert all(scope.consent_record_id == "pending_owner_approval" for scope in scopes)
    assert all(scope.all_local_interfaces_authorized for scope in scopes)
    assert all(scope.max_results <= 16 for scope in scopes)
    assert len(calls) == 1
    assert "Get-NetIPAddress" in calls[0][0][-1]
    assert "Get-NetRoute" in calls[0][0][-1]
    assert "Test-NetConnection" not in calls[0][0][-1]
    proposal = build_aep_consent_proposal(scope=scopes[0], session_id="owner-session")
    assert "192.168.1.0/24" in proposal.material_summary
    assert "all local network interfaces" in proposal.material_summary


def test_camera_scopes_are_not_tv_protocols() -> None:
    planner = _planner([_row("10.2.8.50")])
    scopes = planner.consent_scopes_for("webcam")
    assert [scope.protocol for scope in scopes] == ["wsd"]
    assert scopes[0].approved_address_ranges == ("10.2.8.0/24",)
    assert planner.consent_scopes_for("application") == ()


@pytest.mark.parametrize(
    "rows",
    [
        [_row("8.8.8.8")],
        [_row("192.0.0.1")],
        [_row("192.168.1.6", prefix=16)],
        [_row("192.168.1.6", alias="vEthernet (WSL)")],
        [_row("192.168.1.6", alias="")],
        [_row("192.168.1.6", index=0)],
        [_row("172.15.9.6")],
        [_row("192.168.1.6", prefix=31)],
    ],
)
def test_public_virtual_unreviewed_and_overbroad_routes_fail_closed(rows) -> None:
    assert _planner(rows).consent_scopes_for("television") == ()


def test_os_result_is_deterministic_and_deduplicated() -> None:
    rows = [
        _row("192.168.1.6"),
        _row("192.168.1.9"),
        _row("10.2.4.8", index=3, alias="Wi-Fi"),
        _row("10.2.4.8", index=3, alias="Wi-Fi"),
    ]
    a = _parse_networks(json.dumps(rows))
    b = _parse_networks(json.dumps(list(reversed(rows))))
    assert a == b
    assert len(a) == 2
    assert {x.cidr for x in a} == {"192.168.1.0/24", "10.2.4.0/24"}


def test_non_windows_never_runs_powershell_scope_planning() -> None:
    def prohibited(*args, **kwargs):
        raise AssertionError("non-Windows scope must not execute")

    planner = WindowsLanScopePlanner(runner=prohibited, platform="linux")
    assert planner.consent_scopes_for("media_player") == ()


def test_failed_windows_network_inspection_fails_closed() -> None:
    planner = WindowsLanScopePlanner(
        platform="win32",
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="permission refused"
        ),
    )
    assert planner.consent_scopes_for("media_player") == ()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OS network API")
def test_real_windows_os_scope_inspection_sends_no_lan_probe() -> None:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _PASSIVE_SCOPE_SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert isinstance(_parse_networks(result.stdout), tuple)


@pytest.mark.parametrize(
    "failure",
    ("timeout", "malformed-json", "oversized", "missing-result", "missing-stdout"),
)
def test_passive_scope_planner_handles_broken_windows_provider(
    failure: str,
) -> None:
    def runner(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd="powershell.exe", timeout=5)
        if failure == "malformed-json":
            return SimpleNamespace(returncode=0, stdout="{not-json")
        if failure == "oversized":
            return SimpleNamespace(returncode=0, stdout=" " * 33000)
        if failure == "missing-result":
            return None
        return SimpleNamespace(returncode=0)

    planner = WindowsLanScopePlanner(runner=runner, platform="win32")
    assert planner.inspect() == ()
    assert planner.consent_scopes_for("television") == ()
