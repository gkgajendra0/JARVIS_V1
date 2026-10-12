"""Trace one original owner goal through consented discovery into Phase 9.

A real Authority permit permits observation only; owner-reviewed inventory is
separate evidence. This test must not claim pairing, activation, or TV control.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from pathlib import Path

from tests.test_authority_foundation import LocalPolicy
from tests.test_capability_acquisition_owner_flow_hardening import (
    _Backend,
    _empty_context,
    _QueueStructuredClient,
)
from tests.test_gicc_network_consent import _planner
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
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.goal_intelligence import runtime as gicc_runtime
from jarvis.goal_intelligence.aep_authority import AepAuthorityExecutionGuard
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.information import (
    InformationResolutionState,
    InformationResolutionStrategy,
    InformationResolver,
)
from jarvis.goal_intelligence.interpretation import (
    GoalInterpreter,
    ShadowEntityCandidate,
    ShadowGoalInterpretationOutput,
)
from jarvis.goal_intelligence.models import GoalKind
from jarvis.goal_intelligence.phase9 import Phase9GoalBridge
from jarvis.goal_intelligence.requirements import (
    CapabilityRequirementProposal,
    CapabilityRequirementProposalSet,
    RequirementDeriver,
)
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.windows_aep import WindowsAepIdentityBackend
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry
from jarvis.goal_intelligence.world_discovery import EntityInformationProbe
from jarvis.work.store import SQLiteWorkStore


def test_one_owner_goal_survives_approved_discovery_then_enters_phase9(
    tmp_path: Path, monkeypatch
) -> None:
    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    store = GoalStore(work)
    changes = ChangeStore(work, processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,))
    backend = _Backend()
    context = _empty_context()
    phase9 = Phase9GoalBridge(
        coordinator=CapabilityAcquisitionCoordinator(
            changes=ChangeCoordinator(changes, backend),
            context_provider=context,
        ),
        change_store=changes,
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )

    conversation = ConversationSession(session_id="owner-session")
    conversation.start()
    turn = conversation.accept_turn(
        ConversationRole.USER, "JARVIS, acquire control of my TV."
    )
    world = WorldRegistry(store)
    entities = EntityResolver(world)
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(
            client=_QueueStructuredClient(
                ShadowGoalInterpretationOutput(
                    actionable=True,
                    desired_outcome="Control my television.",
                    goal_kind=GoalKind.ONE_SHOT,
                    candidate_entities=[
                        ShadowEntityCandidate(
                            mention="my TV",
                            proposed_type="media_player",
                            evidence_turn_ids=[turn.turn_id],
                        )
                    ],
                    candidate_completion_predicates=["tv_responded"],
                    evidence_turn_ids=[turn.turn_id],
                )
            )
        ),
        entity_resolver=entities,
        information_resolver=InformationResolver(
            store=store,
            probes=(
                EntityInformationProbe(
                    entities,
                    strategy=InformationResolutionStrategy.WORLD_REGISTRY,
                ),
            ),
        ),
        requirement_deriver=RequirementDeriver(
            client=_QueueStructuredClient(
                CapabilityRequirementProposalSet(
                    requirements=[
                        CapabilityRequirementProposal(
                            semantic_capability="media_player.control",
                            operation="send_remote_key",
                            target_entity_id=None,
                            target_entity_type="media_player",
                            expected_postconditions=["tv_responded"],
                            reason="Use a separately confirmed owner TV.",
                        )
                    ]
                )
            )
        ),
        capability_context=context,
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=phase9,
    )
    initial = asyncio.run(coordinator.pursue(conversation=conversation, turn=turn))
    assert initial.disposition is GoalIntakeDisposition.WAITING_INFORMATION
    assert initial.goal is not None
    goal_id = initial.goal.goal_id
    assert world.entities() == ()
    needs = store.list_information_needs(goal_id=goal_id)
    assert len(needs) == 1
    need = needs[0]

    runtime = GiccApplyRuntime(
        store=store,
        world=world,
        coordinator=coordinator,
        dispatcher=object(),
        telemetry=object(),
        capability_runtime=object(),
    )
    planner = _planner()
    proposal = runtime.prepare_network_discovery_consent(
        goal_id=goal_id,
        session_id=conversation.session_id,
        planner=planner,
    )
    assert proposal is not None
    assert proposal.target()["gicc_need_id"] == need.information_need_id
    assert proposal.has_valid_fingerprint()

    approvals = ApprovalService(clock=time.monotonic)
    owner_record = approvals.request(
        proposal,
        session_id=conversation.session_id,
        requirement=ApprovalRequirement.EXPLICIT,
        ttl_seconds=60.0,
    )
    approvals.grant(
        owner_record.approval_id,
        proposal=proposal,
        session_id=conversation.session_id,
        method=ApprovalMethod.SPOKEN,
    )
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=LocalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(clock=time.monotonic),
        clock=time.monotonic,
    )
    interaction = InteractionContext(
        session_id=conversation.session_id,
        trust_tier=TrustTier.CORROBORATED_OWNER,
        attention_state=AttentionState.ATTENTIVE,
        actor_unambiguous=True,
    )
    decision = authority.evaluate(
        proposal=proposal,
        context=interaction,
        approval_id=owner_record.approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None
    guard = AepAuthorityExecutionGuard(
        authority=authority,
        proposal=proposal,
        context=interaction,
        permit_id=decision.execution_permit.permit_id,
        approval_id=owner_record.approval_id,
    )
    scope = replace(
        planner.consent_scopes_for("television")[0],
        consent_record_id=owner_record.approval_id,
    )
    watcher = FakeWatcher(rows=(_device(endpoint_id="unverified-tv"),))
    monkeypatch.setattr(
        gicc_runtime,
        "WindowsAepIdentityBackend",
        lambda **kw: WindowsAepIdentityBackend(
            platform="win32",
            watcher_factory=lambda _: watcher,
            clock=time.time,
            **kw,
        ),
    )
    observed = runtime.apply_approved_network_discovery(
        goal_id=goal_id,
        need_id=need.information_need_id,
        session_id=conversation.session_id,
        scope=scope,
        authority_guard=guard,
        planner=planner,
    )
    assert observed is not None
    assert observed.state is InformationResolutionState.NEEDS_OWNER
    assert observed.need.resolution_ref is None
    assert watcher.started == watcher.stopped == 1
    assert world.entities() == ()
    assert runtime.pending_network_device_suggestions(
        goal_id=goal_id,
        session_id=conversation.session_id,
        now_epoch=int(time.time()),
    )
    assert not runtime.apply_approved_network_discovery(
        goal_id="other-goal",
        need_id=need.information_need_id,
        session_id=conversation.session_id,
        scope=scope,
        authority_guard=guard,
        planner=planner,
    )

    # A fresh, unique unverified hint is never enough. The owner separately
    # confirms the identity; no static future target ID is provided to GICC.
    tv = runtime.confirm_owner_discovered_device(
        goal_id=goal_id,
        information_need_id=need.information_need_id,
        session_id=conversation.session_id,
        owner_turn_id="owner-explicit-tv-identity-confirmation",
    )
    assert tv is not None
    assert tv.entity_id.startswith("owner_confirmed_network:")
    assert world.bindings(entity_id=tv.entity_id) == ()
    resumed = asyncio.run(coordinator.continue_goal(goal_id, retry_information=True))
    assert resumed.disposition is GoalIntakeDisposition.WAITING_CAPABILITY
    assert resumed.goal is not None
    assert resumed.goal.goal_id == goal_id
    assert resumed.goal.exact_owner_request == turn.text
    assert resumed.goal.referenced_entity_ids == (tv.entity_id,)
    assert (
        store.get_information_need(need.information_need_id).resolution_ref
        == tv.entity_id
    )
    assert len(resumed.phase9_admissions) == 1
    change = resumed.phase9_admissions[0].admission.change
    assert change is not None
    assert changes.latest_artifact(change.change_id, "gicc_target_context") is not None
    assert backend.submissions
    assert world.entities() == (tv,)
    # The same original goal must remain blocked throughout Phase-9 build,
    # activation and external acceptance until durable lineage is completed.
    # These are intentionally SYNTHETIC downstream artifacts: they verify
    # the cross-lifecycle contracts, not execution on real owner hardware.
    from tests.test_gicc_phase9_bridge import (
        FakeAdmitter,
        LineageArtifacts,
        _install_current_external_pass,
        _install_current_lineage,
    )

    admission = resumed.phase9_admissions[0]
    goal_after_discovery = store.get_goal(goal_id)
    gap = store.get_gap(admission.request.gap_id)
    assert goal_after_discovery is not None
    assert gap is not None
    assert admission.request.target_entity_id == tv.entity_id
    assert not phase9.completion_verified(gap=gap, goal=goal_after_discovery)

    synthetic = LineageArtifacts()
    _install_current_lineage(
        synthetic,
        request=admission.request,
        goal=goal_after_discovery,
        gap=gap,
    )
    synthetic_bridge = Phase9GoalBridge(
        coordinator=FakeAdmitter(),
        change_store=synthetic,
        goal_store=store,
        source_revision_provider=lambda: "a" * 40,
    )
    assert not synthetic_bridge.completion_verified(gap=gap, goal=goal_after_discovery)
    _install_current_external_pass(synthetic)
    assert synthetic_bridge.completion_verified(gap=gap, goal=goal_after_discovery)
    # Even complete synthetic acquisition acceptance must not mark the
    # actual original TV goal PLAYBACK-COMPLETED or change its request.
    durable_goal = store.get_goal(goal_id)
    assert durable_goal is not None
    assert durable_goal.exact_owner_request == turn.text
    assert durable_goal.goal_id == goal_id
    assert durable_goal.state == goal_after_discovery.state
    assert world.bindings(entity_id=tv.entity_id) == ()

    # Real device pairing, live effect, actual release/promotion and verified
    # original-goal completion remain owner-machine acceptance gates.
