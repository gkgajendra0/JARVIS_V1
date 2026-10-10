from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.test_gicc_composition import (
    FakePhase9Bridge,
    QueueStructuredClient,
    StaticContext,
    _conversation,
    _store,
)

from jarvis.conversation import ConversationRole
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
    GoalIntelligenceCoordinator,
)
from jarvis.goal_intelligence.interpretation import (
    GoalInterpreter,
    ShadowEntityCandidate,
    ShadowGoalInterpretationOutput,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    GoalState,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeState,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.requirements import (
    CapabilityRequirementProposal,
    CapabilityRequirementProposalSet,
    RequirementDeriver,
)
from jarvis.goal_intelligence.telemetry import CapturingGiccTelemetry
from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry
from jarvis.voice.gicc_tools import GiccAgentTools, build_session_scoped_gicc_tools


@pytest.mark.asyncio
async def test_gicc_voice_clarification_resumes_exact_goal(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    living = registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Living Room TV",
            aliases=("my tv",),
            provenance_refs=("owner_inventory:living_room_tv",),
        )
    )
    registry.register_entity(
        WorldEntityRefV1.create(
            entity_type="media_player",
            canonical_name="Bedroom TV",
            aliases=("my tv",),
            provenance_refs=("owner_inventory:bedroom_tv",),
        )
    )
    conversation, turn = _conversation("Play Transporter on my TV.")
    interpreter = QueueStructuredClient(
        ShadowGoalInterpretationOutput(
            actionable=True,
            desired_outcome="Play Transporter on the selected TV.",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_entities=[
                ShadowEntityCandidate(
                    mention="my TV",
                    proposed_type="media_player",
                    evidence_turn_ids=[turn.turn_id],
                ),
                ShadowEntityCandidate(
                    mention="Transporter",
                    proposed_type="media_content",
                    evidence_turn_ids=[turn.turn_id],
                ),
            ],
            candidate_completion_predicates=["playback_started"],
            evidence_turn_ids=[turn.turn_id],
        )
    )
    requirements = QueueStructuredClient(
        CapabilityRequirementProposalSet(
            requirements=[
                CapabilityRequirementProposal(
                    semantic_capability="media_player.control",
                    operation="play",
                    target_entity_id=living.entity_id,
                    target_entity_type="media_player",
                    expected_postconditions=["playback_started"],
                    reason="Start selected media playback.",
                )
            ]
        )
    )
    telemetry = CapturingGiccTelemetry()
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(client=interpreter),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=requirements),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
        phase9_bridge=FakePhase9Bridge(),
        telemetry=telemetry,
    )
    tools = GiccAgentTools(
        coordinator,
        conversation,
        store,
        telemetry=telemetry,
    )

    admitted = await tools.pursue_owner_goal(None)

    assert admitted["status"] == "waiting_information"
    questions = admitted["questions"]
    assert isinstance(questions, list)
    assert len(questions) == 1
    question = questions[0]
    assert question["interaction_id"]
    labels = {option["label"] for option in question["options"]}
    assert labels == {"Bedroom TV", "Living Room TV"}

    conversation.accept_turn(ConversationRole.USER, "Use the Living Room TV.")
    continued = await tools.resolve_goal_information(
        None,
        interaction_id=str(question["interaction_id"]),
        selected_candidate_value=living.entity_id,
    )

    assert continued["ok"] is True
    assert continued["status"] == "waiting_capability"
    goal = store.get_goal(str(continued["goal_id"]))
    assert goal is not None
    assert living.entity_id in goal.referenced_entity_ids


@pytest.mark.asyncio
async def test_gicc_voice_rejects_candidate_not_bound_to_interaction(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    registry = WorldRegistry(store)
    for name in ("Living Room TV", "Bedroom TV"):
        registry.register_entity(
            WorldEntityRefV1.create(
                entity_type="media_player",
                canonical_name=name,
                aliases=("my tv",),
            )
        )
    conversation, turn = _conversation("Play Transporter on my TV.")
    coordinator = GoalIntelligenceCoordinator(
        store=store,
        interpreter=GoalInterpreter(
            client=QueueStructuredClient(
                ShadowGoalInterpretationOutput(
                    actionable=True,
                    desired_outcome="Play Transporter on my TV.",
                    goal_kind=GoalKind.ONE_SHOT,
                    candidate_entities=[
                        ShadowEntityCandidate(
                            mention="my TV",
                            proposed_type="media_player",
                            evidence_turn_ids=[turn.turn_id],
                        )
                    ],
                    evidence_turn_ids=[turn.turn_id],
                )
            )
        ),
        entity_resolver=EntityResolver(registry),
        requirement_deriver=RequirementDeriver(client=QueueStructuredClient()),
        capability_context=StaticContext(),
        capability_graph_resolver=CapabilityGraphResolver(store=store),
    )
    tools = GiccAgentTools(coordinator, conversation, store)

    admitted = await tools.pursue_owner_goal(None)
    question = admitted["questions"][0]
    conversation.accept_turn(ConversationRole.USER, "Use some other TV.")

    rejected = await tools.resolve_goal_information(
        None,
        interaction_id=str(question["interaction_id"]),
        selected_candidate_value="entity_not_offered",
    )

    assert rejected["ok"] is False
    assert rejected["status"] == "candidate_value_not_allowed"
    need = store.get_information_need(str(question["information_need_id"]))
    assert need is not None
    assert need.state.value == "waiting_for_owner"


class FailingGoalCoordinator(GoalIntelligenceCoordinator):
    def __init__(self) -> None:
        pass

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        raise RuntimeError("synthetic internal requirement failure")


class CompletedExecutionRuntime:
    def __init__(self, result: GoalIntakeResult) -> None:
        self.result = result
        self.pursue_calls = 0

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        self.pursue_calls += 1
        return self.result

    async def continue_goal(self, goal_id: str):
        del goal_id
        return self.result


@pytest.mark.asyncio
async def test_gicc_voice_reports_only_verified_durable_completion(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, turn = _conversation("Open Calculator.")
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id=conversation.session_id,
            source_turn_id=turn.turn_id,
            exact_owner_request=turn.text,
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Calculator is open.",
            completion_predicates=("app_open",),
            state=GoalState.COMPLETED,
            created_at="2026-10-01T18:00:00+00:00",
        )
    )
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.PLAN_READY,
        goal=goal,
    )
    execution = CompletedExecutionRuntime(result)
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=execution,
    )

    payload = await tools.pursue_owner_goal(None)

    assert execution.pursue_calls == 1
    assert payload["status"] == "completed"
    assert payload["verified_completion"] is True
    assert "may acknowledge" in str(payload["truth_note"])


@pytest.mark.asyncio
async def test_gicc_voice_surfaces_sensitive_external_owner_input_without_leak(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, turn = _conversation("Play Transporter on my TV.")
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id=conversation.session_id,
            source_turn_id=turn.turn_id,
            exact_owner_request=turn.text,
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Transporter is playing on my TV.",
            completion_predicates=("playback_started",),
            state=GoalState.EXECUTING,
            created_at="2026-10-01T18:02:00+00:00",
        )
    )
    action = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Play Transporter on the TV.",
        capability_key="package:tv-control",
        operation="play",
        parameters={"title": "Transporter"},
        postcondition_ref="playback_started",
    )
    proposed = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(action,),
        edges=(),
        root_node_ids=(action.node_id,),
        completion_node_ids=(action.node_id,),
        created_at="2026-10-01T18:03:00+00:00",
    )
    waiting = proposed.with_node_state(
        action.node_id,
        PlanNodeState.WAITING,
        plan_state=PlanState.WAITING,
    )
    waiting = store.put_plan(waiting)
    evidence = store.put_plan_node_result(
        plan_id=waiting.plan_id,
        node_id=action.node_id,
        attempt=1,
        status="waiting",
        payload={
            "route": "capability_runtime:owner_input",
            "interaction": {
                "kind": "external_owner_input",
                "input_kind": "pin",
                "prompt": "Enter the TV pairing PIN.",
                "parameter": "pin",
                "sensitive": True,
            },
        },
        created_at="2026-10-01T18:04:00+00:00",
    )
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.PLAN_READY,
        goal=goal,
        plan=waiting,
    )
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=CompletedExecutionRuntime(result),
    )

    payload = await tools.pursue_owner_goal(None)

    assert payload["status"] == "waiting_owner_input"
    assert payload["owner_input"] == {
        "interaction_ref": evidence["result_id"],
        "input_kind": "pin",
        "prompt": "Enter the TV pairing PIN.",
        "parameter": "pin",
        "sensitive": True,
    }
    assert "generic GICC tool argument" in str(payload["truth_note"])
    interaction = evidence["payload"]["interaction"]
    assert "owner_value" not in interaction
    assert "response" not in interaction
    assert "1234" not in str(evidence["payload"])


@pytest.mark.asyncio
async def test_gicc_voice_internal_failure_does_not_invent_device_problem(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, _ = _conversation("Play Interstellar on my TV.")
    telemetry = CapturingGiccTelemetry()
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        telemetry=telemetry,
    )

    result = await tools.pursue_owner_goal(None)

    assert result["ok"] is False
    assert result["status"] == "internal_goal_processing_error"
    assert result["retryable"] is True
    truth_note = str(result["truth_note"])
    assert "internally" in truth_note
    assert "Do not claim a device connectivity failure" in truth_note
    assert any(
        event["event"] == "gicc_goal_processing_error" for event in telemetry.events
    )


@pytest.mark.asyncio
async def test_gicc_voice_status_reads_canonical_objective_projection(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    conversation, _ = _conversation("What is happening with my TV task?")
    payload = {
        "goal_id": "goal_tv",
        "overall_state": "waiting_owner",
        "phase": "waiting_owner_approval",
        "verified_completion": False,
    }
    objective = SimpleNamespace(public_payload=lambda: payload)
    resolver = SimpleNamespace(
        list_active=lambda *, limit: (objective,),
        resolve=lambda goal_id: objective,
    )
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        objective_status=resolver,  # type: ignore[arg-type]
    )

    listed = await tools.list_owner_objectives(None)  # type: ignore[arg-type]
    found = await tools.get_owner_objective_status(
        None,  # type: ignore[arg-type]
        goal_id="goal_tv",
    )

    assert listed["objectives"] == [payload]
    assert found["goal_id"] == "goal_tv"
    assert found["verified_completion"] is False
    assert "Never infer overall completion" in str(listed["truth_note"])


@pytest.mark.asyncio
async def test_gicc_voice_surfaces_bounded_discovery_without_granting_it(
    tmp_path: Path,
) -> None:
    """Owner sees a scope, never an invented permission or trusted TV."""
    from tests.test_gicc_network_consent import _data, _planner

    from jarvis.conversation import ConversationSession
    from jarvis.goal_intelligence.network_consent import (
        prepare_pending_device_discovery_consent,
    )

    store, goal, need = _data(tmp_path)
    conversation = ConversationSession(session_id="owner-session")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Control my TV.")
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.WAITING_INFORMATION,
        goal=goal,
        information_needs=(need,),
    )

    class ReadOnlyDiscoveryRuntime(CompletedExecutionRuntime):
        def __init__(self) -> None:
            super().__init__(result)
            self.consent_reads = 0
            self.suggestion_reads = 0

        def prepare_network_discovery_consent(self, *, goal_id, session_id):
            self.consent_reads += 1
            return prepare_pending_device_discovery_consent(
                store=store,
                goal_id=goal_id,
                session_id=session_id,
                planner=_planner(),
            )

        def pending_network_device_suggestions(self, *, goal_id, session_id):
            self.suggestion_reads += 1
            if goal_id != goal.goal_id or session_id != goal.source_session_id:
                return ()
            return (
                SimpleNamespace(
                    display_hint="Unverified Living Room device",
                    address="192.168.1.15",
                    protocol="upnp",
                    neighbor_correlated=False,
                ),
            )

    runtime = ReadOnlyDiscoveryRuntime()
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=runtime,
    )
    before_need = store.get_information_need(need.information_need_id)
    payload = await tools.pursue_owner_goal(None)

    assert payload["status"] == "waiting_information"
    assert payload["network_discovery"]["state"] == "proposal_only_not_authorized"
    assert payload["network_discovery"]["owner_approval_required"] is True
    assert payload["network_discovery"]["scan_started"] is False
    assert payload["network_discovery"]["protocol"] == "upnp"
    assert (
        payload["network_discovery"]["information_need_id"] == need.information_need_id
    )
    assert "all local network interfaces" in payload["network_discovery"]["summary"]
    assert "has not registered an approval request" in payload["truth_note"]
    # A mock runtime saying it saw a device cannot create a displayable
    # network identity hint without an exact stored approved-scan record.
    assert "unverified_device_hints" not in payload
    assert "device_choice_sets" not in payload
    assert payload["questions"][0]["options"] == []
    assert store.get_information_need(need.information_need_id) == before_need
    assert runtime.consent_reads == runtime.suggestion_reads == 1

    # A proposal with a valid fingerprint is still unusable if it points
    # at a different goal. No pending permission should be advertised.
    from jarvis.goal_intelligence.aep_authority import build_aep_consent_proposal

    class WrongGoalDiscoveryRuntime(ReadOnlyDiscoveryRuntime):
        def prepare_network_discovery_consent(self, *, goal_id, session_id):
            del goal_id
            return build_aep_consent_proposal(
                scope=_planner().consent_scopes_for("media_player")[0],
                session_id=session_id,
                goal_id="other-owner-goal",
                need_id=need.information_need_id,
            )

    mismatched_tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=WrongGoalDiscoveryRuntime(),
    )
    mismatched_payload = await mismatched_tools.pursue_owner_goal(None)
    assert "network_discovery" not in mismatched_payload

    other_conversation = ConversationSession(session_id="unrelated-owner-session")
    other_conversation.start()
    other_conversation.accept_turn(ConversationRole.USER, "Control my TV.")
    other_tools = GiccAgentTools(
        FailingGoalCoordinator(),
        other_conversation,
        store,
        execution_runtime=runtime,
    )
    other_payload = await other_tools.pursue_owner_goal(None)
    assert "network_discovery" not in other_payload
    assert "unverified_device_hints" not in other_payload
    assert runtime.consent_reads == runtime.suggestion_reads == 1


@pytest.mark.asyncio
async def test_gicc_voice_scan_requires_exact_latest_user_consent(
    tmp_path: Path,
) -> None:
    """Voice never turns the original request or generic yes into scan authority."""
    from tests.test_gicc_network_consent import _data, _planner

    from jarvis.conversation import ConversationSession
    from jarvis.goal_intelligence.network_consent import (
        prepare_pending_device_discovery_consent,
    )

    store, goal, need = _data(tmp_path)
    conversation = ConversationSession(session_id="owner-session")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Play my movie on the TV.")
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.WAITING_INFORMATION,
        goal=goal,
        information_needs=(need,),
    )

    class ExactConsentRuntime(CompletedExecutionRuntime):
        def __init__(self) -> None:
            super().__init__(result)
            self.scan_calls = 0
            self.tamper_scope = False

        def prepare_network_discovery_consent(self, *, goal_id, session_id):
            if self.tamper_scope:
                from jarvis.goal_intelligence.aep_authority import (
                    build_aep_consent_proposal,
                )

                return build_aep_consent_proposal(
                    scope=_planner().consent_scopes_for("media_player")[1],
                    session_id=session_id,
                    goal_id=goal_id,
                    need_id=need.information_need_id,
                )
            return prepare_pending_device_discovery_consent(
                store=store,
                goal_id=goal_id,
                session_id=session_id,
                planner=_planner(),
            )

        def authorize_and_discover_network(
            self, *, goal_id, session_id, owner_turn_id, expected_scope_material
        ):
            assert expected_scope_material[1] == "upnp"
            assert owner_turn_id == conversation.turns[-1].turn_id
            assert goal_id == goal.goal_id
            assert session_id == goal.source_session_id
            self.scan_calls += 1
            return SimpleNamespace(need=need)

    runtime = ExactConsentRuntime()
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=runtime,
    )
    initial = await tools.authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert initial["status"] == "explicit_discovery_permission_not_given"
    offer = await tools.pursue_owner_goal(None)
    assert offer["network_discovery"]["protocol"] == "upnp"
    conversation.accept_turn(ConversationRole.USER, "Yes.")
    vague = await tools.authorize_bounded_network_discovery(None, goal_id=goal.goal_id)
    assert vague["status"] == "explicit_discovery_permission_not_given"
    assert runtime.scan_calls == 0

    for denied_text in (
        "I do not approve the network discovery.",
        "I might approve network discovery.",
        "Why should I approve the network discovery?",
        "I approve network discovery only if you ask again.",
        "I revoke my approval of network discovery.",
        "The phrase approve network discovery is not permission.",
    ):
        conversation.accept_turn(ConversationRole.USER, denied_text)
        denied = await tools.authorize_bounded_network_discovery(
            None, goal_id=goal.goal_id
        )
        assert denied["status"] == "explicit_discovery_permission_not_given"
        assert runtime.scan_calls == 0

    conversation.accept_turn(ConversationRole.USER, "I approve the network discovery.")
    not_offered_tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=runtime,
    )
    without_scope = await not_offered_tools.authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert without_scope["status"] == "discovery_scope_not_previously_offered"
    assert runtime.scan_calls == 0
    mismatch = await tools.authorize_bounded_network_discovery(
        None, goal_id="other-goal"
    )
    assert mismatch["status"] == "discovery_goal_not_current_or_not_waiting"
    assert runtime.scan_calls == 0

    # The owner saw the UPnP consent scope; changing it to DNS-SD after
    # the offer must not spend the original approval or launch a scan.
    runtime.tamper_scope = True
    changed = await tools.authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert changed["status"] == "discovery_scope_changed_reoffer_required"
    assert runtime.scan_calls == 0
    runtime.tamper_scope = False

    accepted = await tools.authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert accepted["status"] == "authorized_discovery_observation_recorded"
    assert accepted["verified_device_control"] is False
    assert runtime.scan_calls == 1

    from jarvis.conversation import ConversationSession as NewSession

    another = NewSession(session_id="other-owner-session")
    another.start()
    another.accept_turn(ConversationRole.USER, "I approve the network discovery.")
    other_tools = GiccAgentTools(
        FailingGoalCoordinator(),
        another,
        store,
        execution_runtime=runtime,
    )
    rejected = await other_tools.authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert rejected["status"] == "discovery_goal_not_current_or_not_waiting"
    assert runtime.scan_calls == 1


@pytest.mark.asyncio
async def test_gicc_voice_confirms_only_fresh_explicit_owner_device(
    tmp_path: Path,
) -> None:
    """The model cannot make an unverified network hint a trusted owner TV."""
    import time

    from tests.test_gicc_network_consent import _data
    from tests.test_gicc_owner_device_confirmation import _evidence

    from jarvis.conversation import ConversationSession

    store, goal, need = _data(tmp_path)
    evidence = _evidence(address="192.168.1.10", now=int(time.time()))
    updated = store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(evidence, "windows_aep_authorized_scope_consumed:upnp"),
    )
    conversation = ConversationSession(session_id=goal.source_session_id)
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "My television is missing.")
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.WAITING_INFORMATION,
        goal=goal,
        information_needs=(updated,),
    )

    class ConfirmationRuntime(CompletedExecutionRuntime):
        def __init__(self) -> None:
            super().__init__(result)
            self.confirmations = 0
            self.resumes = 0

        def pending_network_device_suggestions(self, *, goal_id, session_id):
            assert goal_id == goal.goal_id
            assert session_id == goal.source_session_id
            return (
                SimpleNamespace(
                    evidence_ref=evidence,
                    protocol="upnp",
                    display_hint="Unverified TV",
                    address="192.168.1.10",
                    neighbor_correlated=False,
                ),
            )

        def confirm_owner_discovered_device(
            self, *, goal_id, information_need_id, session_id, owner_turn_id
        ):
            assert goal_id == goal.goal_id
            assert information_need_id == need.information_need_id
            assert session_id == goal.source_session_id
            assert owner_turn_id == conversation.turns[-1].turn_id
            self.confirmations += 1
            return WorldEntityRefV1.create(
                entity_type="media_player",
                canonical_name="Owner-confirmed TV",
                aliases=("my tv",),
                provenance_refs=("owner_inventory:test-confirmation",),
            )

        async def continue_goal(self, goal_id, *, retry_information=False):
            assert goal_id == goal.goal_id and retry_information
            self.resumes += 1
            return self.result

    execution = ConfirmationRuntime()
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=execution,
    )
    for unsafe_text in (
        "Yes.",
        "That TV seems familiar.",
        "Do not confirm that the discovered TV is mine.",
        "What if I confirm the discovered TV is mine?",
        "I confirm the discovered device is mine.",
    ):
        conversation.accept_turn(ConversationRole.USER, unsafe_text)
        denied = await tools.confirm_discovered_device_identity(
            None,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
        )
        assert denied["status"] == "explicit_device_identity_confirmation_not_given"
        assert execution.confirmations == 0
    for wrong_kind in (
        "I confirm the discovered camera is mine.",
        "I confirm the discovered TV is my camera.",
    ):
        conversation.accept_turn(ConversationRole.USER, wrong_kind)
        denied = await tools.confirm_discovered_device_identity(
            None,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
        )
        assert denied["status"] == "owner_device_confirmation_type_mismatch"
        assert execution.confirmations == 0

    conversation.accept_turn(
        ConversationRole.USER, "I confirm the discovered TV is mine."
    )
    # A new tool instance has never shown this particular discovery, so a
    # model cannot silently bind it from a guessed device-confirmation phrase.
    fresh_tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=execution,
    )
    unseen = await fresh_tools.confirm_discovered_device_identity(
        None, goal_id=goal.goal_id, information_need_id=need.information_need_id
    )
    assert unseen["status"] == "owner_device_not_previously_offered"
    assert execution.confirmations == 0
    # Explicitly offer the actual single candidate, then require a NEW turn.
    offered = await tools.pursue_owner_goal(None)
    assert (
        offered["device_choice_sets"][0]["options"][0]["display_hint"]
        == "Unverified TV"
    )
    conversation.accept_turn(
        ConversationRole.USER, "I confirm the discovered TV is mine."
    )
    accepted = await tools.confirm_discovered_device_identity(
        None, goal_id=goal.goal_id, information_need_id=need.information_need_id
    )
    assert accepted["owner_inventory_only"] is True
    assert accepted["device_control_verified"] is False
    assert accepted["network_access_verified"] is False
    assert execution.confirmations == execution.resumes == 1


@pytest.mark.asyncio
async def test_gicc_voice_next_protocol_is_disclosed_but_not_automatically_scanned(
    tmp_path: Path,
) -> None:
    """One owner utterance can never recursively scan UPnP and DNS-SD."""
    from tests.test_gicc_network_consent import _data, _planner

    from jarvis.conversation import ConversationSession
    from jarvis.goal_intelligence.network_consent import (
        prepare_pending_device_discovery_consent,
    )

    store, goal, need = _data(tmp_path)
    conversation = ConversationSession(session_id=goal.source_session_id)
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Find my TV.")
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.WAITING_INFORMATION,
        goal=goal,
        information_needs=(need,),
    )

    class SequentialRuntime(CompletedExecutionRuntime):
        def __init__(self) -> None:
            super().__init__(result)
            self.executions = 0

        def authorize_and_discover_network(
            self, *, goal_id, session_id, owner_turn_id, expected_scope_material
        ):
            assert expected_scope_material[1] == (
                "upnp" if self.executions == 0 else "dns_sd"
            )
            assert goal_id == goal.goal_id
            assert session_id == goal.source_session_id
            assert owner_turn_id == conversation.turns[-1].turn_id
            self.executions += 1
            current = store.get_information_need(need.information_need_id)
            updated = store.update_information_need_state(
                current.information_need_id,
                current.state,
                expected_revision=current.revision,
                evidence_refs=(
                    f"windows_aep_authorized_scope_consumed:{expected_scope_material[1]}",
                ),
            )
            return SimpleNamespace(need=updated)

        def pending_network_device_suggestions(self, *, goal_id, session_id):
            # A different waiting device in this owner goal has a suggestion.
            # It must not suppress the next TV-specific discovery scope.
            return (
                SimpleNamespace(
                    evidence_ref="some-other-information-need",
                    display_hint="Another camera",
                    address="192.168.1.12",
                    protocol="upnp",
                ),
            )

        def prepare_network_discovery_consent(self, *, goal_id, session_id):
            return prepare_pending_device_discovery_consent(
                store=store,
                goal_id=goal_id,
                session_id=session_id,
                planner=_planner(),
            )

    runtime = SequentialRuntime()
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=runtime,
    )
    offered = await tools.pursue_owner_goal(None)
    assert offered["network_discovery"]["protocol"] == "upnp"
    conversation.accept_turn(ConversationRole.USER, "I approve the network discovery.")
    payload = await tools.authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert payload["status"] == "authorized_discovery_observation_recorded"
    assert payload["unverified_device_hints"] == []
    assert payload["next_network_discovery"]["protocol"] == "dns_sd"
    assert payload["next_network_discovery"]["owner_approval_required"] is True
    assert payload["next_network_discovery"]["scan_started"] is False
    assert runtime.executions == 1
    # Reusing the same owner turn cannot silently spend the second scope.
    replay = await tools.authorize_bounded_network_discovery(None, goal_id=goal.goal_id)
    assert replay["status"] == "discovery_scope_not_previously_offered"
    assert runtime.executions == 1
    conversation.accept_turn(ConversationRole.USER, "I approve the network discovery.")
    second = await tools.authorize_bounded_network_discovery(None, goal_id=goal.goal_id)
    assert second["status"] == "authorized_discovery_observation_recorded"
    assert runtime.executions == 2
    assert "next_network_discovery" not in second
    assert (
        "windows_aep_authorized_scope_consumed:dns_sd"
        in store.get_information_need(need.information_need_id).evidence_refs
    )


@pytest.mark.asyncio
async def test_gicc_voice_binds_owner_selected_option_to_displayed_set(
    tmp_path: Path,
) -> None:
    """Ambiguous discovered devices require a new exact owner option choice."""
    from tests.test_gicc_network_consent import _data

    from jarvis.conversation import ConversationSession

    store, goal, need = _data(tmp_path)
    updated = store.update_information_need_state(
        need.information_need_id,
        need.state,
        expected_revision=need.revision,
        evidence_refs=(
            "fresh-aep-option-a",
            "fresh-aep-option-b",
            "windows_aep_authorized_scope_consumed:upnp",
        ),
    )
    conversation = ConversationSession(session_id=goal.source_session_id)
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Find my TV.")
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.WAITING_INFORMATION,
        goal=goal,
        information_needs=(updated,),
    )
    options = (
        SimpleNamespace(
            evidence_ref="fresh-aep-option-a",
            display_hint="TV vendor A",
            address="192.168.1.10",
            protocol="upnp",
            neighbor_correlated=False,
        ),
        SimpleNamespace(
            evidence_ref="fresh-aep-option-b",
            display_hint="TV vendor B",
            address="192.168.1.20",
            protocol="upnp",
            neighbor_correlated=False,
        ),
    )

    class OptionsRuntime(CompletedExecutionRuntime):
        def __init__(self) -> None:
            super().__init__(result)
            self.confirmed_ref = None
            self.resumes = 0

        def pending_network_device_suggestions(self, *, goal_id, session_id):
            assert goal_id == goal.goal_id
            assert session_id == goal.source_session_id
            return options

        def confirm_owner_discovered_device(
            self,
            *,
            goal_id,
            information_need_id,
            session_id,
            owner_turn_id,
            selected_evidence_ref,
        ):
            assert goal_id == goal.goal_id
            assert information_need_id == need.information_need_id
            assert session_id == goal.source_session_id
            assert owner_turn_id == conversation.turns[-1].turn_id
            self.confirmed_ref = selected_evidence_ref
            return WorldEntityRefV1.create(
                entity_type="media_player",
                canonical_name="Confirmed TV option B",
                aliases=("my tv",),
                provenance_refs=("owner_inventory:chosen-candidate",),
            )

        async def continue_goal(self, goal_id, *, retry_information=False):
            assert goal_id == goal.goal_id and retry_information
            self.resumes += 1
            return result

    runtime = OptionsRuntime()
    tools = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=runtime,
    )
    offered = await tools.pursue_owner_goal(None)
    choices = offered["device_choice_sets"][0]
    assert choices["information_need_id"] == need.information_need_id
    assert [item["option"] for item in choices["options"]] == [1, 2]
    assert choices["options"][1]["display_hint"] == "TV vendor B"

    conversation.accept_turn(
        ConversationRole.USER, "I confirm the discovered TV option 2 is mine."
    )
    # Another GICC tool instance after restart has never offered this exact
    # choice set, even if a model guesses the digest and candidate evidence.
    restarted = GiccAgentTools(
        FailingGoalCoordinator(),
        conversation,
        store,
        execution_runtime=runtime,
    )
    replayed = await restarted.confirm_discovered_device_identity(
        None,
        goal_id=goal.goal_id,
        information_need_id=need.information_need_id,
        selected_evidence_ref=choices["options"][1]["evidence_ref"],
        displayed_choice_set_digest=choices["digest"],
    )
    assert replayed["status"] == "owner_device_choice_is_not_current"
    assert runtime.confirmed_ref is None
    for wrong_reference, wrong_digest in (
        ("fresh-aep-option-a", choices["digest"]),
        ("fresh-aep-option-b", "stale-choice-set"),
    ):
        rejected = await tools.confirm_discovered_device_identity(
            None,
            goal_id=goal.goal_id,
            information_need_id=need.information_need_id,
            selected_evidence_ref=wrong_reference,
            displayed_choice_set_digest=wrong_digest,
        )
        assert rejected["status"] == "owner_device_choice_is_not_current"
        assert runtime.confirmed_ref is None

    accepted = await tools.confirm_discovered_device_identity(
        None,
        goal_id=goal.goal_id,
        information_need_id=need.information_need_id,
        selected_evidence_ref=choices["options"][1]["evidence_ref"],
        displayed_choice_set_digest=choices["digest"],
    )
    assert accepted["owner_inventory_only"] is True
    assert accepted["device_control_verified"] is False
    assert runtime.confirmed_ref == "fresh-aep-option-b"
    assert runtime.resumes == 1


@pytest.mark.asyncio
async def test_production_gicc_tool_provider_keeps_discovery_offers_across_turns(
    tmp_path: Path,
) -> None:
    """Action/read tool-list refreshes must not erase an offered scan scope."""
    from tests.test_gicc_network_consent import _data, _planner

    from jarvis.conversation import ConversationSession
    from jarvis.goal_intelligence.network_consent import (
        prepare_pending_device_discovery_consent,
    )

    store, goal, need = _data(tmp_path)
    conversation = ConversationSession(session_id=goal.source_session_id)
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "Find my television.")
    result = GoalIntakeResult(
        disposition=GoalIntakeDisposition.WAITING_INFORMATION,
        goal=goal,
        information_needs=(need,),
    )

    class Runtime(CompletedExecutionRuntime):
        def __init__(self) -> None:
            super().__init__(result)
            self.scan_calls = 0

        def prepare_network_discovery_consent(self, *, goal_id, session_id):
            return prepare_pending_device_discovery_consent(
                store=store,
                goal_id=goal_id,
                session_id=session_id,
                planner=_planner(),
            )

        def authorize_and_discover_network(
            self, *, goal_id, session_id, owner_turn_id, expected_scope_material
        ):
            assert goal_id == goal.goal_id
            assert session_id == goal.source_session_id
            assert owner_turn_id == conversation.turns[-1].turn_id
            assert expected_scope_material[1] == "upnp"
            self.scan_calls += 1
            return SimpleNamespace(need=need)

    runtime = Runtime()
    provider = build_session_scoped_gicc_tools(
        FailingGoalCoordinator(),
        store,
        execution_runtime=runtime,
    )
    first = provider(conversation)
    assert provider(conversation) is first
    assert provider(conversation).action_tools
    assert provider(conversation).read_tools == []
    offered = await provider(conversation).pursue_owner_goal(None)
    assert offered["network_discovery"]["protocol"] == "upnp"

    # The voice tool registry is refreshed, as it is on each speech turn.
    assert provider(conversation) is first
    conversation.accept_turn(ConversationRole.USER, "I approve the network discovery.")
    approved = await provider(conversation).authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert approved["status"] == "authorized_discovery_observation_recorded"
    assert runtime.scan_calls == 1

    unrelated = ConversationSession(session_id="different-owner-session")
    unrelated.start()
    unrelated.accept_turn(ConversationRole.USER, "I approve the network discovery.")
    assert provider(unrelated) is not first
    denied = await provider(unrelated).authorize_bounded_network_discovery(
        None, goal_id=goal.goal_id
    )
    assert denied["status"] == "discovery_goal_not_current_or_not_waiting"
    assert runtime.scan_calls == 1
