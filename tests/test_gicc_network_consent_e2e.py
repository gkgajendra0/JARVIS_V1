"""Full simulated GICC owner goal -> consent -> discovery -> trusted identity.

No live network packets or machine controls. A system test must not conflate
discovery evidence with device control authority or physical acceptance.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
from tests.test_authority_foundation import LocalPolicy
from tests.test_gicc_network_consent import _data, _planner
from tests.test_gicc_passive_windows_neighbors import _backend
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
from jarvis.goal_intelligence import runtime as gicc_runtime
from jarvis.goal_intelligence.aep_authority import AepAuthorityExecutionGuard
from jarvis.goal_intelligence.information import (
    InformationResolutionState,
    InformationResolutionStrategy,
    InformationResolver,
)
from jarvis.goal_intelligence.local_network import (
    WindowsNeighborInformationProbe,
)
from jarvis.goal_intelligence.models import WorldEntityRefV1
from jarvis.goal_intelligence.network_consent import (
    prepare_pending_device_discovery_consent,
)
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.windows_aep import WindowsAepIdentityBackend
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry
from jarvis.goal_intelligence.world_discovery import EntityInformationProbe


def test_owner_goal_research_and_identity_recovery_use_one_governed_flow(
    tmp_path: Path,
) -> None:
    store, goal, need = _data(tmp_path)
    planner = _planner()
    scopes = planner.consent_scopes_for("television")
    assert scopes

    # GICC autonomously prepares the exact request; the owner still grants it.
    proposal = prepare_pending_device_discovery_consent(
        store=store,
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        planner=planner,
    )
    assert proposal is not None
    assert proposal.has_valid_fingerprint()

    clock = time.monotonic
    approvals = ApprovalService(clock=clock)
    record = approvals.request(
        proposal,
        session_id=goal.source_session_id,
        requirement=ApprovalRequirement.EXPLICIT,
        ttl_seconds=30.0,
    )
    approved_scope = replace(scopes[0], consent_record_id=record.approval_id)
    approvals.grant(
        record.approval_id,
        proposal=proposal,
        session_id=goal.source_session_id,
        method=ApprovalMethod.SPOKEN,
    )
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=LocalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=clock),
        clock=clock,
    )
    context = InteractionContext(
        session_id=goal.source_session_id,
        trust_tier=TrustTier.CORROBORATED_OWNER,
        attention_state=AttentionState.ATTENTIVE,
        actor_unambiguous=True,
    )
    decision = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=record.approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None
    guard = AepAuthorityExecutionGuard(
        authority=authority,
        proposal=proposal,
        context=context,
        permit_id=decision.execution_permit.permit_id,
        approval_id=record.approval_id,
    )

    # OS has NO cached neighbor: the authorized network watcher still gathers
    # an independently observable advertisement, but cannot prove the TV.
    watcher = FakeWatcher(rows=(_device(endpoint_id="candidate-tv"),))
    aep_backend = WindowsAepIdentityBackend(
        platform="win32",
        is_authorized=guard,
        watcher_factory=lambda _: watcher,
        clock=lambda: 1000.0,
    )
    world = WorldRegistry(store)
    entity_resolver = EntityResolver(world)
    resolver = InformationResolver(
        store=store,
        probes=(
            EntityInformationProbe(
                entity_resolver,
                strategy=InformationResolutionStrategy.WORLD_REGISTRY,
            ),
            WindowsNeighborInformationProbe(
                _backend([]),
                aep_backend=aep_backend,
                aep_scopes=(approved_scope,),
            ),
        ),
    )
    first = resolver.resolve(need)
    assert first.state is InformationResolutionState.NEEDS_OWNER
    assert first.need.resolution_ref is None
    assert world.entities() == ()
    assert any(
        item.startswith("windows_aep_discovered_unverified:")
        for item in first.need.evidence_refs
    )
    assert watcher.started == watcher.stopped == 1

    # The same execution permit cannot silently enumerate again.
    second = resolver.resolve(first.need)
    assert second.state is InformationResolutionState.NEEDS_OWNER
    assert second.need.resolution_ref is None
    assert watcher.started == 1

    # A separate independently reviewed owner inventory record finally binds
    # this physical device. No owner network troubleshooting was required.
    tv = world.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Family Television",
            aliases=("my TV",),
            provenance_refs=("owner_inventory:confirmed_family_tv",),
        )
    )
    recovered = resolver.resolve(second.need)
    assert recovered.state is InformationResolutionState.RESOLVED
    assert recovered.need.resolution_ref == tv.entity_id
    assert world.entities() == (tv,)
    assert store.get_information_need(need.information_need_id) == recovered.need
    assert watcher.started == 1


def test_existing_gicc_runtime_executes_exact_approved_discovery_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An owner permit unlocks one same-goal scan without manual diagnostics."""

    store, goal, need = _data(tmp_path)
    planner = _planner()
    scope = planner.consent_scopes_for("television")[0]
    runtime = GiccApplyRuntime(
        store=store,
        world=WorldRegistry(store),
        coordinator=object(),
        dispatcher=object(),
        telemetry=object(),
        capability_runtime=object(),
    )
    proposal = runtime.prepare_network_discovery_consent(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        planner=planner,
    )
    assert proposal is not None

    clock = time.monotonic
    approvals = ApprovalService(clock=clock)
    request = approvals.request(
        proposal,
        session_id=goal.source_session_id,
        requirement=ApprovalRequirement.EXPLICIT,
        ttl_seconds=60.0,
    )
    scope = replace(scope, consent_record_id=request.approval_id)
    approvals.grant(
        request.approval_id,
        proposal=proposal,
        session_id=goal.source_session_id,
        method=ApprovalMethod.SPOKEN,
    )
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=LocalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=clock),
        clock=clock,
    )
    context = InteractionContext(
        session_id=goal.source_session_id,
        trust_tier=TrustTier.CORROBORATED_OWNER,
        attention_state=AttentionState.ATTENTIVE,
        actor_unambiguous=True,
    )
    decision = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=request.approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None
    guard = AepAuthorityExecutionGuard(
        authority=authority,
        proposal=proposal,
        context=context,
        permit_id=decision.execution_permit.permit_id,
        approval_id=request.approval_id,
    )

    watcher = FakeWatcher(rows=(_device(endpoint_id="advertising-tv"),))
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

    # Reject unrelated goals, sessions, and changed LAN scope before any
    # network watcher can start or any one-time permit can be consumed.
    assert guard.binds_information_need(
        goal_id=goal.goal_id, need_id=need.information_need_id
    )
    assert not guard.binds_information_need(
        goal_id=goal.goal_id, need_id="unrelated-information-need"
    )
    assert (
        runtime.apply_approved_network_discovery(
            goal_id=goal.goal_id,
            need_id="unrelated-information-need",
            session_id=goal.source_session_id,
            scope=scope,
            authority_guard=guard,
            planner=planner,
        )
        is None
    )
    assert (
        runtime.apply_approved_network_discovery(
            goal_id=goal.goal_id,
            need_id=need.information_need_id,
            session_id="another-session",
            scope=scope,
            authority_guard=guard,
            planner=planner,
        )
        is None
    )
    assert (
        runtime.apply_approved_network_discovery(
            goal_id=goal.goal_id,
            need_id=need.information_need_id,
            session_id=goal.source_session_id,
            scope=scope,
            authority_guard=guard,
            planner=_planner(
                [
                    {
                        "InterfaceAlias": "Ethernet",
                        "InterfaceIndex": 4,
                        "IPAddress": "192.168.2.6",
                        "PrefixLength": 24,
                    }
                ]
            ),
        )
        is None
    )
    assert watcher.started == 0

    result = runtime.apply_approved_network_discovery(
        goal_id=goal.goal_id,
        need_id=need.information_need_id,
        session_id=goal.source_session_id,
        scope=scope,
        authority_guard=guard,
        planner=planner,
    )
    assert result is not None
    assert result.state is InformationResolutionState.NEEDS_OWNER
    assert result.need.resolution_ref is None
    assert any(
        item.startswith("windows_aep_discovered_unverified:")
        for item in result.need.evidence_refs
    )
    assert watcher.started == watcher.stopped == 1
    assert guard.consumed is True
    assert "windows_aep_authorized_scope_consumed:upnp" in result.need.evidence_refs
    next_proposal = runtime.prepare_network_discovery_consent(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        planner=planner,
    )
    assert next_proposal is not None
    assert next_proposal.target()["protocol"] == "dns_sd"
    wrong_protocol_scope = replace(scope, protocol="dns_sd")
    assert guard.consumed_for(scope) is True
    assert guard.consumed_for(wrong_protocol_scope) is False
    assert guard.binds_scope(wrong_protocol_scope) is False
    assert (
        runtime.apply_approved_network_discovery(
            goal_id=goal.goal_id,
            need_id=need.information_need_id,
            session_id=goal.source_session_id,
            scope=wrong_protocol_scope,
            authority_guard=guard,
            planner=planner,
        )
        is None
    )
    assert (
        "windows_aep_authorized_scope_consumed:dns_sd" not in result.need.evidence_refs
    )
    assert store.get_information_need(need.information_need_id) == result.need
    assert runtime.world.entities() == ()

    # JARVIS can now present a concise device hint instead of requesting
    # raw owner-run PowerShell/IP diagnostics. Nothing is auto-confirmed.
    suggestions = runtime.pending_network_device_suggestions(
        goal_id=goal.goal_id,
        session_id=goal.source_session_id,
        now_epoch=1001,
    )
    assert len(suggestions) == 1
    assert suggestions[0].display_hint == "example media example 4k"
    assert suggestions[0].evidence_ref in result.need.evidence_refs

    # Reconciliation cannot reuse the consumed permit for another LAN query.
    again = runtime.apply_approved_network_discovery(
        goal_id=goal.goal_id,
        need_id=need.information_need_id,
        session_id=goal.source_session_id,
        scope=scope,
        authority_guard=guard,
        planner=planner,
    )
    assert again is not None
    assert watcher.started == 1
    assert again.need.resolution_ref is None
