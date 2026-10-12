"""OS-only TV discovery diagnostics cannot send network packets."""

from __future__ import annotations

from types import SimpleNamespace

from jarvis.goal_intelligence.local_network import PassiveNeighborV1
from jarvis.goal_intelligence.passive_network_diagnostics import (
    inspect_passive_media_network,
)
from jarvis.goal_intelligence.windows_lan_scope import PassiveLanScopeV1


def test_cached_neighbors_and_winrt_readiness_are_passive_and_scope_filtered() -> None:
    calls = []

    class Planner:
        def inspect(self):
            calls.append("read_interfaces")
            return (PassiveLanScopeV1(cidr="192.168.1.0/24", interface_index=4),)

    class Neighbors:
        def observe(self):
            calls.append("read_neighbor_cache")
            return (
                (
                    PassiveNeighborV1(
                        ip_address="192.168.1.10",
                        mac_address="00-11-22-33-44-55",
                        state="reachable",
                        interface_index=4,
                    ),
                    PassiveNeighborV1(
                        ip_address="192.168.1.25",
                        mac_address="00-11-22-33-44-66",
                        state="stale",
                        interface_index=7,
                    ),
                    PassiveNeighborV1(
                        ip_address="192.168.2.70",
                        mac_address="00-11-22-33-44-77",
                        state="reachable",
                        interface_index=4,
                    ),
                ),
                1,
            )

    def load(module):
        assert module == "winrt.windows.devices.enumeration"
        calls.append("import_module")
        return SimpleNamespace(
            DeviceInformation=SimpleNamespace(
                create_watcher_with_kind_aqs_filter_and_additional_properties=lambda *a: (
                    None
                )
            ),
            DeviceInformationKind=SimpleNamespace(ASSOCIATION_ENDPOINT=1),
        )

    result = inspect_passive_media_network(
        platform="win32",
        planner=Planner(),
        neighbors=Neighbors(),
        load_module=load,
    )
    assert result["state"] == "passive_inspection_completed"
    assert result["winrt_backend"] == "loadable"
    assert result["network_probe_performed"] is False
    assert result["cached_neighbor_candidates"] == [
        {
            "address": "192.168.1.10",
            "neighbor_state": "reachable",
            "verified_tv_identity": False,
        }
    ]
    assert calls == ["import_module", "read_interfaces", "read_neighbor_cache"]


def test_blocked_winrt_import_is_reported_without_scanning() -> None:
    def blocked(_name):
        raise OSError("System application control denied native projection")

    result = inspect_passive_media_network(
        platform="win32",
        planner=SimpleNamespace(inspect=lambda: ()),
        neighbors=SimpleNamespace(observe=lambda: ((), 1)),
        load_module=blocked,
    )
    assert result["winrt_backend"] == "unavailable"
    assert result["cached_neighbor_candidates"] == []
    assert result["network_probe_performed"] is False


def test_nonwindows_never_calls_passive_windows_backends() -> None:
    def forbidden():
        raise AssertionError("No Windows access permitted")

    result = inspect_passive_media_network(
        platform="linux",
        planner=SimpleNamespace(inspect=forbidden),
        neighbors=SimpleNamespace(observe=forbidden),
        load_module=lambda _name: forbidden(),
    )
    assert result["state"] == "not_windows"
    assert result["winrt_backend"] == "not_applicable"
    assert result["network_probe_performed"] is False
