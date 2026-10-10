"""Offline strong-approval-to-AEP integration; absolutely no real network scan."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_authority_foundation import LocalPolicy
from tests.test_gicc_network_consent import _data, _planner
from tests.test_gicc_windows_aep import FakeWatcher, _device
from tests.test_strong_approval import BoundVerifier

from jarvis.authority import (
    ApprovalService,
    AuthorityService,
    InMemoryAuditEventStore,
    PermitRegistry,
    RiskClassifier,
    StrongApprovalService,
    StrongVerificationStatus,
)
from jarvis.capabilities.authority_bridge import (
    CapabilityAuthorityBroker,
    CapabilityAuthorizationError,
)
from jarvis.goal_intelligence import runtime as gicc_runtime
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.windows_aep import WindowsAepIdentityBackend
from jarvis.goal_intelligence.world import WorldRegistry


@pytest.mark.parametrize("found", [False, True])
def test_real_canonical_authority_binds_one_strong_permitted_scan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    found: bool,
) -> None:
    """The full production composition never creates or trusts a device."""
    store, goal, need = _data(tmp_path)
    approvals = ApprovalService(clock=time.monotonic)
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=LocalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=time.monotonic),
        clock=time.monotonic,
    )
    verifier = BoundVerifier(StrongVerificationStatus.VERIFIED)
    broker = CapabilityAuthorityBroker()
    broker._authority = authority
    broker._approvals = approvals
    broker._strong = StrongApprovalService(approvals=approvals, verifier=verifier)

    runtime = GiccApplyRuntime(
        store=store,
        world=WorldRegistry(store),
        coordinator=object(),
        dispatcher=object(),
        telemetry=object(),
        capability_runtime=SimpleNamespace(
            authorize_network_discovery_proposal=(
                broker.authorize_network_discovery_proposal
            ),
        ),
    )
    watcher = FakeWatcher(rows=(_device(),) if found else ())
    monkeypatch.setattr(
        gicc_runtime,
        "WindowsAepIdentityBackend",
        lambda **kwargs: WindowsAepIdentityBackend(
            platform="win32",
            watcher_factory=lambda _: watcher,
            clock=lambda: 1000.0,
            **kwargs,
        ),
    )
    planner = _planner()
    first = runtime.prepare_network_discovery_consent(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        planner=planner,
    )
    assert first is not None
    assert first.target()["protocol"] == "upnp"
    before = store.get_information_need(need.information_need_id)

    result = runtime.authorize_and_discover_network(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        planner=planner,
    )
    assert result is not None
    assert verifier.calls == 1
    assert watcher.started == watcher.stopped == 1
    assert "windows_aep_authorized_scope_consumed:upnp" in result.need.evidence_refs
    assert result.need.resolution_ref is None
    assert result.need.revision > before.revision
    assert runtime.world.entities() == ()
    next_proposal = runtime.prepare_network_discovery_consent(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        planner=planner,
    )
    assert next_proposal is not None
    assert next_proposal.target()["protocol"] == "dns_sd"
    hints = runtime.pending_network_device_suggestions(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    )
    assert len(hints) == int(found)
    assert all(not item.neighbor_correlated for item in hints)

    # Owner cancels the next protocol's strong verification. The first
    # consumed permission cannot authorize that protocol or repeat UPnP.
    broker._strong = StrongApprovalService(
        approvals=approvals,
        verifier=BoundVerifier(StrongVerificationStatus.CANCELED),
    )
    with pytest.raises(CapabilityAuthorizationError, match="not granted"):
        runtime.authorize_and_discover_network(
            goal_id=goal.goal_id,
            session_id=goal.source_session_id,
            planner=planner,
        )
    assert watcher.started == 1
    final = store.get_information_need(need.information_need_id)
    assert final is not None
    assert "windows_aep_authorized_scope_consumed:dns_sd" not in final.evidence_refs
    assert final.resolution_ref is None
