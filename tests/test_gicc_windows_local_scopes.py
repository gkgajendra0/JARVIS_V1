"""OS-derived local network scope is only a proposal, never a scan grant."""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from jarvis.goal_intelligence.local_network_scopes import (
    WindowsLocalSubnetObserver,
    _parse_subnets,
    _WINDOWS_SUBNET_SCRIPT,
)


def _address(
    ip: str,
    *,
    prefix: int = 24,
    index: int = 4,
    alias: str = "Ethernet",
):
    return {
        "IPAddress": ip,
        "PrefixLength": prefix,
        "InterfaceIndex": index,
        "InterfaceAlias": alias,
    }


def test_only_default_routed_narrow_private_subnets_become_review_hints() -> None:
    rows = [
        _address("192.168.1.6"),
        _address("192.168.1.8"),  # same network; deduplicate
        _address("172.16.12.22", prefix=24, alias="Wi-Fi"),
        _address("10.10.0.2", prefix=16),  # wider than reviewed result cap
        _address("8.8.8.8"),
        _address("169.254.10.12"),
        _address("192.0.0.12"),
        _address("192.168.1.10", alias="vEthernet (WSL)"),
        _address("192.168.2.3", alias="Loopback"),
        _address("192.168.3.3", index=0),
        _address("192.168.4.5", prefix=36),
        _address("192.168.5.5", alias=""),
        _address("bad"),
    ]
    result = _parse_subnets(json.dumps(rows))
    assert tuple(row.cidr for row in result) == (
        "172.16.12.0/24",
        "192.168.1.0/24",
    )
    assert all(row.interface_alias in {"Ethernet", "Wi-Fi"} for row in result)


def test_single_object_and_empty_network_config_are_safe() -> None:
    assert _parse_subnets(json.dumps(_address("10.1.2.3"))) == (
        _parse_subnets(json.dumps([_address("10.1.2.3")]))[0],
    )
    assert _parse_subnets("[]") == ()
    assert _parse_subnets("null") == ()
    assert _parse_subnets("") == ()


def test_windows_observation_is_fixed_read_only_os_query() -> None:
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([_address("192.168.1.6")]),
        )

    rows = WindowsLocalSubnetObserver(
        platform="win32",
        runner=runner,
    ).observe()
    assert tuple(row.cidr for row in rows) == ("192.168.1.0/24",)
    assert calls[0][0][0].casefold() == "powershell.exe"
    assert "-NoProfile" in calls[0][0]
    assert calls[0][1]["timeout"] == 4
    assert calls[0][1]["check"] is False
    script = calls[0][0][-1]
    assert "Get-NetRoute" in script
    assert "Get-NetIPAddress" in script
    assert "Test-NetConnection" not in script
    assert "Invoke-WebRequest" not in script
    assert "Set-Net" not in script


def test_non_windows_never_executes_network_inspection() -> None:
    def denied(*args, **kwargs):
        raise AssertionError("unexpected Windows call on Linux")

    assert WindowsLocalSubnetObserver(
        runner=denied, platform="linux"
    ).observe() == ()


@pytest.mark.parametrize(
    "problem",
    ["failed", "timeout", "bad-json", "too-large", "missing-result"],
)
def test_windows_scope_inspection_fail_closed(problem: str) -> None:
    def runner(*_args, **_kwargs):
        if problem == "timeout":
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=4)
        if problem == "failed":
            return SimpleNamespace(returncode=1, stdout="[]")
        if problem == "bad-json":
            return SimpleNamespace(returncode=0, stdout="{broken")
        if problem == "too-large":
            return SimpleNamespace(returncode=0, stdout=" " * 70000)
        return None

    assert WindowsLocalSubnetObserver(
        runner=runner, platform="win32"
    ).observe() == ()


@pytest.mark.skipif(sys.platform != "win32", reason="requires real Windows")
def test_actual_windows_subnet_script_runs_without_starting_discovery() -> None:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _WINDOWS_SUBNET_SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert isinstance(_parse_subnets(result.stdout), tuple)
