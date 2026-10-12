"""VIDAA discovery requires exact fresh Authority; all sightings stay unverified."""

from __future__ import annotations

import pytest

from jarvis.goal_intelligence.device_suggestions import (
    has_consumed_discovery_permit,
    pending_owner_device_suggestions,
)
from jarvis.goal_intelligence.models import InformationNeedState
from jarvis.goal_intelligence.network_consent import (
    prepare_pending_device_discovery_consent,
)
from jarvis.goal_intelligence.vidaa_udp import (
    ReviewedVidaaScopeV1,
    VidaaUdpCandidateV1,
    WindowsVidaaUdpBackend,
    build_vidaa_consent_proposal,
    proposal_vidaa_scope,
)

from test_gicc_network_consent import _data, _planner


def test_scope_is_private_and_exactly_bounded() -> None:
    with pytest.raises(ValueError):
        ReviewedVidaaScopeV1(cidr="8.8.8.0/24", interface_index=4)
    with pytest.raises(ValueError):
        ReviewedVidaaScopeV1(cidr="192.168.1.0/16", interface_index=4)
    with pytest.raises(ValueError):
        ReviewedVidaaScopeV1(cidr="192.168.1.0/24", interface_index=0)
    scope = ReviewedVidaaScopeV1(cidr="192.168.1.0/24", interface_index=4)
    assert scope.broadcast == "192.168.1.255"
    proposal = build_vidaa_consent_proposal(
        scope=scope, session_id="owner-session", goal_id="goal-1", need_id="need-1"
    )
    assert proposal_vidaa_scope(proposal) == scope
    assert proposal.operation == "discover_vidaa_udp"
    assert proposal.parameters()["packet_count"] == 1
    assert proposal.parameters()["device_control"] is False
    assert proposal.parameters()["pairing"] is False
    assert proposal.target()["broadcast_destination"] == "192.168.1.255"


def test_unapproved_or_unavailable_backend_never_opens_socket() -> None:
    scope = ReviewedVidaaScopeV1(cidr="192.168.1.0/24", interface_index=4)
    opens = []

    def prohibited_socket(*args):
        opens.append(args)
        raise AssertionError("permission must precede socket use")

    for checker, platform in ((lambda _scope: False, "win32"), (None, "win32"), (lambda _scope: True, "linux")):
        observed = WindowsVidaaUdpBackend(
            is_authorized=checker, platform=platform, socket_factory=prohibited_socket
        ).observe(scope)
        assert observed == ()
    assert opens == []


def test_authorized_vidaa_udp_emits_one_bounded_packet_and_keeps_only_lan_hints() -> None:
    scope = ReviewedVidaaScopeV1(cidr="192.168.1.0/24", interface_index=4)
    calls = []
    auth = []

    class FakeSocket:
        def __init__(self) -> None:
            self.responses = iter(
                (
                    (b'{"name":"Unrelated device"}', ("192.168.2.20", 36671)),
                    (b'{"devicename":"Hisense TV","model":"U7N","manufacturer":"Hisense"}', ("192.168.1.10", 36671)),
                    (b'{"request":"discover"}', ("192.168.1.11", 36671)),
                )
            )

        def setsockopt(self, *args):
            calls.append(("option", args))

        def bind(self, address):
            calls.append(("bind", address))

        def sendto(self, payload, target):
            calls.append(("send", payload, target))

        def settimeout(self, timeout):
            assert 0 < timeout <= 0.25

        def recvfrom(self, _limit):
            try:
                return next(self.responses)
            except StopIteration:
                raise TimeoutError

        def close(self):
            calls.append(("close",))

    clock = iter((0.0, 0.02, 0.04, 0.06, 2.1))
    backend = WindowsVidaaUdpBackend(
        is_authorized=lambda supplied: auth.append(supplied) or supplied == scope,
        platform="win32",
        socket_factory=lambda *_args: FakeSocket(),
        clock=lambda: next(clock, 3.0),
        epoch=lambda: 1782000000,
    )
    found = backend.observe(scope)
    assert auth == [scope]
    assert len(found) == 1
    assert found[0].address == "192.168.1.10"
    assert found[0].model == "U7N"
    assert sum(row[0] == "send" for row in calls) == 1
    assert ("bind", ("", 36671)) in calls
    assert ("send", b'{"request":"discover"}', ("192.168.1.255", 36671)) in calls
    assert calls[-1] == ("close",)


def test_vidaa_offer_follows_both_consumed_aep_scopes_without_scan(tmp_path) -> None:
    store, goal, need = _data(tmp_path)
    store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(
            "windows_aep_authorized_scope_consumed:upnp",
            "windows_aep_authorized_scope_consumed:dns_sd",
        ),
    )
    offered = prepare_pending_device_discovery_consent(
        store=store, goal_id=goal.goal_id, session_id=goal.source_session_id,
        planner=_planner(),
    )
    assert offered is not None
    assert offered.operation == "discover_vidaa_udp"
    assert offered.target()["gicc_goal_id"] == goal.goal_id
    assert "192.168.1.255:36671" in offered.material_summary
    assert offered.parameters()["pairing"] is False

    current = store.get_information_need(need.information_need_id)
    store.update_information_need_state(
        current.information_need_id,
        current.state,
        expected_revision=current.revision,
        evidence_refs=(
            "windows_vidaa_authorized_scope_consumed:vidaa_udp:192.168.1.0/24",
        ),
    )
    assert prepare_pending_device_discovery_consent(
        store=store, goal_id=goal.goal_id, session_id=goal.source_session_id,
        planner=_planner(),
    ) is None


def test_vidaa_candidate_can_only_be_offered_under_consumed_cidr(tmp_path) -> None:
    store, goal, need = _data(tmp_path)
    candidate = VidaaUdpCandidateV1(
        address="192.168.1.10",
        manufacturer="Hisense",
        model="U7N",
        observed_at_epoch=1782000000,
    )
    store.update_information_need_state(
        need.information_need_id,
        InformationNeedState.WAITING_FOR_OWNER,
        expected_revision=need.revision,
        evidence_refs=(
            candidate.evidence_ref,
            "windows_vidaa_authorized_scope_consumed:vidaa_udp:192.168.1.0/24",
        ),
    )
    hints = pending_owner_device_suggestions(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1782000005,
    )
    assert len(hints) == 1
    assert hints[0].address == "192.168.1.10"
    assert hints[0].protocol == "vidaa_udp"
    assert has_consumed_discovery_permit(
        hints[0].protocol,
        hints[0].address,
        store.get_information_need(need.information_need_id).evidence_refs,
    )
    assert not has_consumed_discovery_permit(
        "vidaa_udp",
        "192.168.2.15",
        store.get_information_need(need.information_need_id).evidence_refs,
    )
    assert not has_consumed_discovery_permit("vidaa_udp", "192.168.1.10", ())
