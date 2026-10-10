"""Waiting GICC goals produce owner permission requests, not manual IP work."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.goal_intelligence.models import (
    GoalKind,
    GoalState,
    InformationNeedCategory,
    InformationNeedState,
    InformationNeedV1,
    OwnerGoalV2,
)
from jarvis.goal_intelligence.network_consent import (
    prepare_pending_device_discovery_consent,
)
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.windows_lan_scope import WindowsLanScopePlanner
from jarvis.work.privacy import build_default_work_payload_codec
from jarvis.work.store import SQLiteWorkStore


def _data(
    tmp_path: Path,
    *,
    state=GoalState.WAITING_INFORMATION,
    sources=(
        "world_registry",
        "current_state_observation",
        "bounded_local_discovery",
        "owner_input",
    ),
):
    db = tmp_path / "consent-proposal.sqlite"
    store = GoalStore(
        SQLiteWorkStore(db, payload_codec=build_default_work_payload_codec(db))
    )
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner-session",
            source_turn_id="turn-wants-tv",
            exact_owner_request="JARVIS acquire TV control",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Control my television",
            state=state,
        )
    )
    need = store.create_information_need(
        InformationNeedV1.create(
            goal_id=goal.goal_id,
            category=InformationNeedCategory.MISSING_VALUE,
            subject="my TV",
            required_fact="canonical media_player target",
            why_required="target identity unresolved",
            allowed_resolution_sources=sources,
            answer_schema={"type": "entity_id", "entity_type": "television"},
        )
    )
    return store, goal, need


def _planner(rows=None):
    return WindowsLanScopePlanner(
        platform="win32",
        runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                rows
                if rows is not None
                else [
                    {
                        "InterfaceAlias": "Ethernet",
                        "InterfaceIndex": 4,
                        "IPAddress": "192.168.1.6",
                        "PrefixLength": 24,
                    }
                ]
            ),
        ),
    )


def test_waiting_device_need_generates_exact_permission_proposal(
    tmp_path: Path,
) -> None:
    store, goal, _need = _data(tmp_path)
    before = store.list_information_needs(goal_id=goal.goal_id)
    proposal = prepare_pending_device_discovery_consent(
        store=store,
        goal_id=goal.goal_id,
        session_id="owner-session",
        planner=_planner(),
    )

    assert proposal is not None
    assert proposal.has_valid_fingerprint()
    assert proposal.capability == "network_discovery"
    assert proposal.operation == "enumerate_aep"
    assert proposal.target()["protocol"] == "upnp"
    assert proposal.target()["gicc_goal_id"] == goal.goal_id
    assert proposal.target()["gicc_need_id"] == _need.information_need_id
    assert proposal.target()["address_result_filters"] == ["192.168.1.0/24"]
    assert "all local network interfaces" in proposal.material_summary
    assert store.list_information_needs(goal_id=goal.goal_id) == before


def test_same_consent_proposal_accessible_from_gicc_runtime(
    tmp_path: Path,
) -> None:
    store, goal, _ = _data(tmp_path)
    runtime = GiccApplyRuntime(
        store=store,
        world=object(),
        coordinator=object(),
        dispatcher=object(),
        telemetry=object(),
        capability_runtime=object(),
    )
    proposal = runtime.prepare_network_discovery_consent(
        goal_id=goal.goal_id,
        session_id="owner-session",
        planner=_planner(),
    )
    assert proposal is not None
    assert proposal.capability == "network_discovery"
    assert proposal.parameters()["device_control"] is False


def test_consent_cannot_be_proposed_for_another_session(
    tmp_path: Path,
) -> None:
    store, goal, _ = _data(tmp_path)
    assert (
        prepare_pending_device_discovery_consent(
            store=store,
            goal_id=goal.goal_id,
            session_id="unrelated-session",
            planner=_planner(),
        )
        is None
    )


def test_consent_requires_waiting_information_state(tmp_path: Path) -> None:
    store, goal, _ = _data(tmp_path, state=GoalState.PLANNED)
    assert (
        prepare_pending_device_discovery_consent(
            store=store,
            goal_id=goal.goal_id,
            session_id="owner-session",
            planner=_planner(),
        )
        is None
    )


def test_consent_fails_closed_without_approved_private_lan(tmp_path: Path) -> None:
    store, goal, _ = _data(tmp_path)
    proposal = prepare_pending_device_discovery_consent(
        store=store,
        goal_id=goal.goal_id,
        session_id="owner-session",
        planner=_planner(
            [
                {
                    "InterfaceAlias": "Ethernet",
                    "InterfaceIndex": 4,
                    "IPAddress": "8.8.8.8",
                    "PrefixLength": 24,
                }
            ]
        ),
    )
    assert proposal is None


def test_owner_only_information_cannot_create_scan_consent(tmp_path: Path) -> None:
    db = tmp_path / "owner-only.sqlite"
    store = GoalStore(
        SQLiteWorkStore(db, payload_codec=build_default_work_payload_codec(db))
    )
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner-session",
            source_turn_id="turn-secret",
            exact_owner_request="Help with approval",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Owner decision",
            state=GoalState.WAITING_INFORMATION,
        )
    )
    store.create_information_need(
        InformationNeedV1.create(
            goal_id=goal.goal_id,
            category=InformationNeedCategory.AUTHORIZATION,
            subject="my tv",
            required_fact="owner approval",
            why_required="approval cannot be guessed",
            allowed_resolution_sources=("bounded_local_discovery", "owner_input"),
            answer_schema={"type": "entity_id", "entity_type": "media_player"},
        )
    )
    assert (
        prepare_pending_device_discovery_consent(
            store=store,
            goal_id=goal.goal_id,
            session_id="owner-session",
            planner=_planner(),
        )
        is None
    )


@pytest.mark.parametrize(
    "sources",
    (
        ("world_registry", "current_state_observation", "owner_input"),
        ("world_registry", "bounded_local_discovery", "owner_input"),
    ),
)
def test_no_owner_scan_request_when_need_disallows_required_discovery_strategies(
    tmp_path: Path, sources: tuple[str, ...]
) -> None:
    store, goal, _need = _data(tmp_path, sources=sources)
    assert (
        prepare_pending_device_discovery_consent(
            store=store,
            goal_id=goal.goal_id,
            session_id=goal.source_session_id,
            planner=_planner(),
        )
        is None
    )


def test_cancelled_need_does_not_request_network_permission(tmp_path: Path) -> None:
    """An unresolved goal cannot resurrect permission for a retired need."""

    store, goal, need = _data(tmp_path)
    cancelled = store.update_information_need_state(
        need.information_need_id,
        InformationNeedState.CANCELLED,
        expected_revision=need.revision,
    )
    assert cancelled.state is InformationNeedState.CANCELLED
    assert (
        prepare_pending_device_discovery_consent(
            store=store,
            goal_id=goal.goal_id,
            session_id=goal.source_session_id,
            planner=_planner(),
        )
        is None
    )
