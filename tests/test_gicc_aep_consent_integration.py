"""Owner-governed network-device discovery integration across existing subsystems.

No real network or owner machine is contacted: real GICC/Authority orchestration
runs over synthetic Windows interface and WinRT watcher fixtures. The resulting
AEP claims must remain unverified, not become a physical control capability.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

from tests.test_authority_foundation import LocalPolicy
from tests.test_gicc_passive_windows_neighbors import _backend, _entry, _need
from tests.test_gicc_windows_aep import FakeWatcher, _device

from jarvis.authority import (
    ApprovalMethod,
    ApprovalRequirement,
    ApprovalService,
    AttentionState,
    AuthorityEffect,
    AuthorityService,
    InMemoryAuditEventStore,
    InteractionContext,
    PermitRegistry,
    RiskClassifier,
    TrustTier,
)
from jarvis.goal_intelligence.aep_authority import (
    AepAuthorityExecutionGuard,
    build_aep_consent_proposal,
)
from jarvis.goal_intelligence.local_network import WindowsNeighborInformationProbe
from jarvis.goal_intelligence.windows_aep import WindowsAepIdentityBackend
from jarvis.goal_intelligence.windows_lan_scope import WindowsLanScopePlanner


def test_owner_goal_to_authorized_network_observation_stops_before_control() -> None:
    def passive_os(command, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "IPAddress": "192.168.1.6",
                        "PrefixLength": 24,
                        "InterfaceIndex": 4,
                        "InterfaceAlias": "Ethernet",
                    }
                ]
            ),
        )

    planner = WindowsLanScopePlanner(runner=passive_os, platform="win32")
    scopes = planner.consent_scopes_for("television")
    assert len(scopes) == 2
    assert {scope.protocol for scope in scopes} == {"upnp", "dns_sd"}
    assert all(scope.approved_address_ranges == ("192.168.1.0/24",) for scope in scopes)

    scope = scopes[0]
    proposal = build_aep_consent_proposal(
        scope=scope,
        session_id="owner-session",
    )
    assert "all local network interfaces" in proposal.material_summary
    assert proposal.attributes.external_side_effect
    approvals = ApprovalService()
    audit = InMemoryAuditEventStore()
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=LocalPolicy(),
        approvals=approvals,
        audit_store=audit,
        permits=PermitRegistry(),
    )
    context = InteractionContext(
        session_id="owner-session",
        trust_tier=TrustTier.CORROBORATED_OWNER,
        attention_state=AttentionState.ATTENTIVE,
        actor_unambiguous=True,
    )
    requested = approvals.request(
        proposal,
        session_id="owner-session",
        requirement=ApprovalRequirement.EXPLICIT,
        ttl_seconds=60.0,
    )
    scope = replace(scope, consent_record_id=requested.approval_id)

    watcher = FakeWatcher(rows=(_device(address="192.168.1.10"),))
    decision_without_grant = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=requested.approval_id,
    )
    assert decision_without_grant.effect is AuthorityEffect.DENY
    assert watcher.started == 0

    approvals.grant(
        requested.approval_id,
        proposal=proposal,
        session_id="owner-session",
        method=ApprovalMethod.SPOKEN,
    )
    decision = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=requested.approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None
    guard = AepAuthorityExecutionGuard(
        authority=authority,
        proposal=proposal,
        context=context,
        permit_id=decision.execution_permit.permit_id,
        approval_id=requested.approval_id,
    )
    backend = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=guard,
        watcher_factory=lambda _: watcher,
        clock=lambda: 1000,
    )
    probe = WindowsNeighborInformationProbe(
        _backend([_entry("192.168.1.10", "02-11-22-33-44-55")]),
        aep_backend=backend,
        aep_scopes=(scope,),
    )

    result = probe.resolve(_need("goal_owner_tv"))
    assert not result.resolved
    assert result.resolution_ref is None
    assert any(
        ref.startswith("windows_aep_neighbor_correlated_unverified:")
        for ref in result.evidence_refs
    )
    assert not any(ref.startswith("owner_inventory:") for ref in result.evidence_refs)
    assert watcher.started == watcher.stopped == 1

    # Retrying the same goal does not silently reuse the single permit.
    again = probe.resolve(_need("goal_owner_tv"))
    assert not again.resolved
    assert not any(
        ref.startswith("windows_aep_neighbor_correlated_unverified:")
        for ref in again.evidence_refs
    )
    assert watcher.started == 1
