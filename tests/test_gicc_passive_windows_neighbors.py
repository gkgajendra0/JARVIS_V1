"""Windows passive neighbor discovery is integrated without inventing device identity."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.goal_intelligence.information import (
    InformationResolutionState,
    InformationResolver,
    can_rediscover_information,
)
from jarvis.goal_intelligence.local_network import (
    _WINDOWS_NEIGHBORS_SCRIPT,
    WindowsNeighborInformationProbe,
    WindowsPassiveNeighborBackend,
    _parse_rows,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    GoalState,
    InformationNeedCategory,
    InformationNeedState,
    InformationNeedV1,
    OwnerGoalV2,
)
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.windows_aep import (
    ReviewedAepScopeV1,
    WindowsAepIdentityBackend,
)
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore


def _entry(
    ip: str,
    mac: str,
    state: str = "Stale",
    idx: int = 4,
    alias: str = "Ethernet",
):
    return {
        "IPAddress": ip,
        "LinkLayerAddress": mac,
        "State": state,
        "InterfaceIndex": idx,
        "InterfaceAlias": alias,
    }


def _backend(rows, *, returncode=0, calls=None):
    def runner(command, **kwargs):
        if calls is not None:
            calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=returncode,
            stdout=json.dumps(rows),
            stderr="",
        )

    return WindowsPassiveNeighborBackend(
        runner=runner,
        platform="win32",
        clock=lambda: 1000.0,
    )


def _need(goal_id: str) -> InformationNeedV1:
    return InformationNeedV1.create(
        goal_id=goal_id,
        category=InformationNeedCategory.MISSING_VALUE,
        subject="my TV",
        required_fact="canonical media_player entity",
        why_required="Unverified network neighbors are not a trusted device",
        allowed_resolution_sources=(
            "current_state_observation",
            "owner_input",
        ),
        answer_schema={"type": "entity_id", "entity_type": "television"},
    )


def test_passive_cache_returns_unverified_local_candidates_only() -> None:
    calls = []
    backend = _backend(
        [
            _entry("192.168.1.10", "02-11-22-33-44-55", "Reachable"),
            _entry("192.168.1.1", "94-98-69-73-3D-60"),
            _entry(
                "172.23.63.154",
                "00-15-5D-E4-F3-C9",
                alias="vEthernet (WSL)",
            ),
            _entry("8.8.8.8", "00-11-22-33-44-55"),
            _entry("192.0.0.1", "00-11-22-33-44-56"),
            _entry("172.15.0.2", "00-11-22-33-44-57"),
            _entry("192.168.1.11", "invalid_mac"),
            _entry("192.168.1.12", "AA-BB-CC-DD-EE-02", alias=""),
            _entry("192.168.1.99", "AA-BB-CC-DD-EE-FF", "Permanent"),
            _entry("192.168.1.10", "02-11-22-33-44-55", "Reachable"),
        ],
        calls=calls,
    )
    observations, timestamp = backend.observe()

    assert timestamp == 1000
    assert len(observations) == 2
    assert observations[-1].ip_address == "192.168.1.10"
    assert observations[-1].state == "reachable"
    assert all(
        item.evidence_ref.startswith("windows_neighbor_unverified:")
        for item in observations
    )
    assert calls and calls[0][0][0].casefold() == "powershell.exe"
    assert "-NoProfile" in calls[0][0]
    assert calls[0][1]["timeout"] == 5
    assert "Get-NetNeighbor" in calls[0][0][-1]
    assert "Test-NetConnection" not in calls[0][0][-1]


def test_neighbor_candidate_is_never_reported_as_verified_identity() -> None:
    probe = WindowsNeighborInformationProbe(
        _backend([_entry("192.168.1.10", "02-11-22-33-44-55")])
    )
    result = probe.resolve(_need("goal_tv"))

    assert result.resolution_ref is None
    assert result.resolved is False
    assert "no physical identity" in result.reason
    assert any(
        item.startswith("windows_neighbor_unverified:192.168.1.10:")
        for item in result.evidence_refs
    )
    assert all("entity_discovered_" not in item for item in result.evidence_refs)


def test_only_physical_target_needs_trigger_neighbor_observation() -> None:
    called = []
    probe = WindowsNeighborInformationProbe(_backend([], calls=called))
    need = InformationNeedV1.create(
        goal_id="goal_utility",
        category=InformationNeedCategory.MISSING_VALUE,
        subject="a function",
        required_fact="type of utility",
        why_required="missing specification",
        answer_schema={"type": "entity_id", "entity_type": "software"},
    )
    assert not probe.resolve(need).resolved
    assert called == []


def test_non_windows_cannot_start_passive_windows_collection() -> None:
    def must_not_run(*args, **kwargs):
        raise AssertionError("the runner must not be invoked")

    backend = WindowsPassiveNeighborBackend(
        platform="linux",
        runner=must_not_run,
        clock=lambda: 1000.0,
    )
    assert backend.observe() == ((), 1000)


def test_timeout_or_failed_command_fail_closed_without_unverified_identity() -> None:
    backend = _backend([_entry("192.168.1.10", "02-11-22-33-44-55")], returncode=1)
    assert backend.observe() == ((), 1000)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=5)

    backend = WindowsPassiveNeighborBackend(
        runner=timeout, platform="win32", clock=lambda: 1000
    )
    assert backend.observe() == ((), 1000)


def test_unverified_neighbor_evidence_survives_information_need_restart(
    tmp_path: Path,
) -> None:
    db = tmp_path / "auto-neighbor.sqlite3"
    goal_store = GoalStore(
        SQLiteWorkStore(db, payload_codec=build_default_work_payload_codec(db))
    )
    goal = goal_store.create_goal(
        OwnerGoalV2.create(
            source_session_id="session",
            source_turn_id="turn",
            exact_owner_request="Acquire control of my television",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="My TV is controlled",
            state=GoalState.WAITING_INFORMATION,
        )
    )
    need = goal_store.create_information_need(_need(goal.goal_id))
    information = InformationResolver(
        store=goal_store,
        probes=(
            WindowsNeighborInformationProbe(
                _backend([_entry("192.168.1.10", "02-11-22-33-44-55")])
            ),
        ),
    )

    result = information.resolve(need)
    assert result.state is InformationResolutionState.NEEDS_OWNER
    assert result.need.resolution_ref is None
    assert any(
        item.startswith("windows_neighbor_unverified:192.168.1.10:")
        for item in result.need.evidence_refs
    )
    persisted = goal_store.get_information_need(need.information_need_id)
    assert persisted is not None
    assert persisted.digest == result.need.digest
    assert persisted.evidence_refs == result.need.evidence_refs
    assert goal_store.list_entities() == ()

    # Discovery keeps retrying without finding a verifiable target. Its
    # protected owner record must not grow without bound across restarts.
    current = persisted
    for epoch in range(1001, 1035):
        current = goal_store.update_information_need_state(
            current.information_need_id,
            InformationNeedState.WAITING_FOR_OWNER,
            expected_revision=current.revision,
            evidence_refs=(
                f"windows_neighbor_cache_observed:{epoch:012d}:" + "a" * 64,
            ),
        )
    snapshots = [
        item
        for item in current.evidence_refs
        if item.startswith("windows_neighbor_cache_observed:")
    ]
    assert len(snapshots) == 8
    assert snapshots[-1].startswith("windows_neighbor_cache_observed:000000001034")
    assert goal_store.get_information_need(need.information_need_id) == current


def test_recheck_eligibility_excludes_owner_only_information_and_secrets() -> None:
    assert can_rediscover_information(_need("goal_rediscovery"))

    owner_only = InformationNeedV1.create(
        goal_id="goal_rediscovery",
        category=InformationNeedCategory.MISSING_VALUE,
        subject="owner preference",
        required_fact="preferred format",
        why_required="a personal choice",
        allowed_resolution_sources=("owner_input",),
    )
    assert not can_rediscover_information(owner_only)

    secret = InformationNeedV1.create(
        goal_id="goal_rediscovery",
        category=InformationNeedCategory.OWNER_SECRET,
        subject="private credential",
        required_fact="authorization secret",
        why_required="private authentication",
        allowed_resolution_sources=("world_registry", "secret_flow"),
    )
    assert not can_rediscover_information(secret)


@pytest.mark.parametrize(
    "category",
    [
        InformationNeedCategory.OWNER_PREFERENCE,
        InformationNeedCategory.AUTHORIZATION,
        InformationNeedCategory.SUCCESS_CRITERIA,
        InformationNeedCategory.PHYSICAL_OBSERVATION,
    ],
)
def test_owner_only_boundaries_never_auto_recheck(category) -> None:
    need = InformationNeedV1.create(
        goal_id="goal_safety",
        category=category,
        subject="owner-only decision",
        required_fact="explicit owner response",
        why_required="this fact cannot be inferred from local network cache",
        allowed_resolution_sources=("world_registry", "owner_input"),
    )
    assert not can_rediscover_information(need)


@pytest.mark.skipif(
    sys.platform != "win32", reason="Windows owner OS interface required"
)
def test_windows_powershell_cache_enumeration_is_read_only_and_executable() -> None:
    """Catch a malformed Windows command before asking owner for acceptance."""

    script = _WINDOWS_NEIGHBORS_SCRIPT
    assert "Get-NetNeighbor" in script
    assert "Get-NetRoute" in script
    assert "Test-NetConnection" not in script
    assert "Invoke-WebRequest" not in script
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert isinstance(_parse_rows(result.stdout), tuple)


def test_correlate_authorized_aep_only_with_existing_neighbor_evidence() -> None:
    from tests.test_gicc_windows_aep import FakeWatcher, _device

    scope = ReviewedAepScopeV1(
        protocol="upnp",
        approved_address_ranges=("192.168.1.0/24",),
        consent_record_id="reviewed-fixture",
        all_local_interfaces_authorized=True,
        timeout_seconds=0.25,
    )
    approved = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=lambda value: value == scope,
        watcher_factory=lambda value: FakeWatcher(
            rows=(
                _device(endpoint_id="matched", address="192.168.1.10"),
                _device(endpoint_id="not-in-neighbors", address="192.168.1.22"),
            )
        ),
        clock=lambda: 1000.0,
    )
    neighbor = _backend([_entry("192.168.1.10", "02-11-22-33-44-55")])
    probe = WindowsNeighborInformationProbe(
        neighbor, aep_backend=approved, aep_scopes=(scope,)
    )
    result = probe.resolve(_need("goal_aep"))
    assert not result.resolved
    assert (
        sum(
            item.startswith("windows_aep_neighbor_correlated_unverified:")
            for item in result.evidence_refs
        )
        == 1
    )
    assert any(
        item.startswith("windows_aep_neighbor_correlated_unverified:192.168.1.10:")
        for item in result.evidence_refs
    )


def test_no_aep_backend_or_scope_means_no_active_network_enumeration() -> None:
    class ExplodingBackend:
        def observe(self, scope):
            raise AssertionError("unauthorized active enumeration")

    neighbor = _backend([_entry("192.168.1.10", "02-11-22-33-44-55")])
    result = WindowsNeighborInformationProbe(
        neighbor, aep_backend=ExplodingBackend()
    ).resolve(_need("goal_inactive"))
    assert not any("windows_aep_" in value for value in result.evidence_refs)
    with pytest.raises(ValueError, match="authorized backend"):
        WindowsNeighborInformationProbe(
            neighbor,
            aep_scopes=(
                ReviewedAepScopeV1(
                    protocol="upnp",
                    approved_address_ranges=("192.168.1.0/24",),
                    consent_record_id="missing-checker",
                    all_local_interfaces_authorized=True,
                ),
            ),
        )


def test_conflicting_aep_advertisements_do_not_correlate_as_identity() -> None:
    from tests.test_gicc_windows_aep import FakeWatcher, _device

    scope = ReviewedAepScopeV1(
        protocol="upnp",
        approved_address_ranges=("192.168.1.0/24",),
        consent_record_id="fixture",
        all_local_interfaces_authorized=True,
    )
    aep = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=lambda _: True,
        watcher_factory=lambda _: FakeWatcher(
            rows=(
                _device(endpoint_id="first", manufacturer="Vendor A"),
                _device(endpoint_id="second", manufacturer="Vendor B"),
            )
        ),
    )
    probe = WindowsNeighborInformationProbe(
        _backend([_entry("192.168.1.10", "02-11-22-33-44-55")]),
        aep_backend=aep,
        aep_scopes=(scope,),
    )
    result = probe.resolve(_need("goal_conflict"))
    assert not any("windows_aep_" in ref for ref in result.evidence_refs)


def test_repeated_aep_advertisements_do_not_grow_protected_owner_records(
    tmp_path: Path,
) -> None:
    db = tmp_path / "aep-retention.sqlite"
    store = GoalStore(
        SQLiteWorkStore(db, payload_codec=build_default_work_payload_codec(db))
    )
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="session-aep",
            source_turn_id="turn-aep",
            exact_owner_request="Identify my local device",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Device identity known",
            state=GoalState.WAITING_INFORMATION,
        )
    )
    need = store.create_information_need(_need(goal.goal_id))
    for n in range(48):
        need = store.update_information_need_state(
            need.information_need_id,
            InformationNeedState.WAITING_FOR_OWNER,
            expected_revision=need.revision,
            evidence_refs=(
                "windows_aep_neighbor_correlated_unverified:192.168.1.10:"
                + f"windows_aep_unverified:fixture:{n:04d}",
            ),
        )
    assert (
        sum(
            item.startswith("windows_aep_neighbor_correlated_unverified:")
            for item in need.evidence_refs
        )
        == 32
    )
    assert store.get_information_need(need.information_need_id) == need


def test_approved_aep_can_observe_device_missing_from_neighbor_cache() -> None:
    """A previously invisible LAN device must not need an owner ARP command."""

    from tests.test_gicc_windows_aep import FakeWatcher, _device

    scope = ReviewedAepScopeV1(
        protocol="upnp",
        approved_address_ranges=("192.168.1.0/24",),
        consent_record_id="reviewed-discovery-test",
        all_local_interfaces_authorized=True,
    )
    watcher = FakeWatcher(rows=(_device(endpoint_id="aep-only"),))
    backend = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=lambda candidate: candidate == scope,
        watcher_factory=lambda _: watcher,
        clock=lambda: 1000,
    )
    probe = WindowsNeighborInformationProbe(
        _backend([]), aep_backend=backend, aep_scopes=(scope,)
    )
    result = probe.resolve(_need("goal_newly_discoverable"))
    assert result.resolution_ref is None
    assert any(
        ref.startswith("windows_aep_discovered_unverified:192.168.1.10:")
        for ref in result.evidence_refs
    )
    assert not any(
        ref.startswith("windows_aep_neighbor_correlated_unverified:")
        for ref in result.evidence_refs
    )
    assert watcher.started == watcher.stopped == 1


def test_aep_permission_denial_with_no_neighbors_returns_no_identity() -> None:
    from tests.test_gicc_windows_aep import FakeWatcher, _device

    scope = ReviewedAepScopeV1(
        protocol="upnp",
        approved_address_ranges=("192.168.1.0/24",),
        consent_record_id="not-approved",
        all_local_interfaces_authorized=True,
    )
    watcher = FakeWatcher(rows=(_device(),))
    backend = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=lambda _: False,
        watcher_factory=lambda _: watcher,
    )
    result = WindowsNeighborInformationProbe(
        _backend([]), aep_backend=backend, aep_scopes=(scope,)
    ).resolve(_need("goal_denied"))
    assert result.resolution_ref is None
    assert result.evidence_refs == ()
    assert watcher.started == 0


def test_unmatched_aep_advertisement_research_evidence_is_bounded(
    tmp_path: Path,
) -> None:
    db = tmp_path / "aep-only-retention.sqlite"
    store = GoalStore(
        SQLiteWorkStore(db, payload_codec=build_default_work_payload_codec(db))
    )
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="session-unmatched",
            source_turn_id="turn-unmatched",
            exact_owner_request="Identify any TV on my network",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Identify device",
            state=GoalState.WAITING_INFORMATION,
        )
    )
    need = store.create_information_need(_need(goal.goal_id))
    for i in range(40):
        need = store.update_information_need_state(
            need.information_need_id,
            InformationNeedState.WAITING_FOR_OWNER,
            expected_revision=need.revision,
            evidence_refs=(
                f"windows_aep_discovered_unverified:192.168.1.10:fixture_{i:04d}",
            ),
        )
    assert (
        sum(
            item.startswith("windows_aep_discovered_unverified:")
            for item in need.evidence_refs
        )
        == 32
    )
    assert store.get_information_need(need.information_need_id) == need
