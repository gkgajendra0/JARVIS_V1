import pytest

from jarvis.chatgpt_plan import _strict_json_schema

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.goal_intelligence.models import GoalKind, OwnerGoalV2, PlanNodeType
from jarvis.goal_intelligence.planning import (
    PlanNodeCandidate,
    PlanProgressGuard,
    PlanProposalV1,
    PlanValidationContext,
    PlanValidationError,
    PlanValidator,
)


def _goal() -> OwnerGoalV2:
    return OwnerGoalV2.create(
        source_session_id="session-plan",
        source_turn_id="turn-plan",
        exact_owner_request="Open Calculator.",
        goal_kind=GoalKind.ONE_SHOT,
        desired_outcome="Open Calculator.",
        completion_predicates=("app_open",),
        created_at="2026-10-01T15:00:00+00:00",
    )


def _catalog() -> CapabilityCatalog:
    descriptor = CapabilityDescriptor.create(
        capability_id="lifecycle",
        source_id="app",
        kind=CapabilityKind.NATIVE_API,
        name="Application lifecycle",
        description="Open applications.",
        operations=("open_app",),
        execution_enabled=True,
    )
    return CapabilityCatalog(
        sources=(
            DiscoverySnapshot(
                source_id="app",
                state=DiscoveryState.AVAILABLE,
                capabilities=(descriptor,),
            ),
        ),
        capabilities=(descriptor,),
    )


def _context() -> PlanValidationContext:
    return PlanValidationContext(
        catalog=_catalog(),
        allowed_capability_operations=(("app:lifecycle", "open_app"),),
        allowed_postcondition_refs=("app_open",),
    )


def _valid_proposal() -> PlanProposalV1:
    return PlanProposalV1(
        nodes=[
            PlanNodeCandidate(
                node_type=PlanNodeType.ACTION,
                summary="Open Calculator",
                capability_key="app:lifecycle",
                operation="open_app",
                parameters_json='{"app":"calculator"}',
                postcondition_ref="app_open",
            ),
            PlanNodeCandidate(
                node_type=PlanNodeType.VERIFY,
                summary="Verify Calculator opened",
                postcondition_ref="app_open",
                depends_on_indexes=[0],
            ),
        ]
    )


def test_valid_plan_uses_registered_capability_and_verify_node() -> None:
    plan = PlanValidator().validate(
        goal=_goal(),
        proposal=_valid_proposal(),
        context=_context(),
        created_at="2026-10-01T15:01:00+00:00",
    )

    assert tuple(node.node_type for node in plan.nodes) == (
        PlanNodeType.ACTION,
        PlanNodeType.VERIFY,
    )
    assert plan.nodes[0].parameters == {"app": "calculator"}
    assert plan.edges == ((plan.nodes[0].node_id, plan.nodes[1].node_id),)


def test_action_without_downstream_verify_is_rejected() -> None:
    proposal = PlanProposalV1(
        nodes=[
            PlanNodeCandidate(
                node_type=PlanNodeType.ACTION,
                summary="Open Calculator",
                capability_key="app:lifecycle",
                operation="open_app",
                parameters_json='{"app":"calculator"}',
                postcondition_ref="app_open",
            )
        ]
    )

    with pytest.raises(PlanValidationError, match="VERIFY"):
        PlanValidator().validate(
            goal=_goal(),
            proposal=proposal,
            context=_context(),
        )


def test_plan_cannot_embed_arbitrary_executable_payload() -> None:
    proposal = _valid_proposal()
    proposal.nodes[
        0
    ].parameters_json = '{"shell":"powershell -EncodedCommand deadbeef"}'

    with pytest.raises(PlanValidationError, match="executable field"):
        PlanValidator().validate(
            goal=_goal(),
            proposal=proposal,
            context=_context(),
        )


def test_plan_cannot_use_unregistered_postcondition() -> None:
    proposal = _valid_proposal()
    proposal.nodes[0].postcondition_ref = "model_says_done"
    proposal.nodes[1].postcondition_ref = "model_says_done"

    with pytest.raises(PlanValidationError, match="unregistered postcondition"):
        PlanValidator().validate(
            goal=_goal(),
            proposal=proposal,
            context=_context(),
        )


def test_catalog_operation_requires_satisfied_requirement_permission() -> None:
    context = PlanValidationContext(
        catalog=_catalog(),
        allowed_capability_operations=(),
        allowed_postcondition_refs=("app_open",),
    )

    with pytest.raises(
        PlanValidationError,
        match="satisfied canonical requirements",
    ):
        PlanValidator().validate(
            goal=_goal(),
            proposal=_valid_proposal(),
            context=context,
        )


def test_non_action_node_cannot_smuggle_capability_payload() -> None:
    proposal = PlanProposalV1(
        nodes=[
            PlanNodeCandidate(
                node_type=PlanNodeType.VERIFY,
                summary="Verify Calculator opened",
                capability_key="app:lifecycle",
                operation="open_app",
                parameters_json='{"app":"calculator"}',
                postcondition_ref="app_open",
            )
        ]
    )

    with pytest.raises(PlanValidationError, match="cannot carry executable"):
        PlanValidator().validate(
            goal=_goal(),
            proposal=proposal,
            context=_context(),
        )


def test_progress_guard_rejects_exact_repeat_and_bounds_replan() -> None:
    plan = PlanValidator().validate(
        goal=_goal(),
        proposal=_valid_proposal(),
        context=_context(),
    )
    guard = PlanProgressGuard(max_replans=1)
    action = plan.nodes[0]

    fingerprint = guard.admit_action(
        action,
        observed_state_digest="a" * 64,
    )
    assert len(fingerprint) == 64

    with pytest.raises(PlanValidationError, match="no progress"):
        guard.admit_action(
            action,
            observed_state_digest="a" * 64,
        )

    assert guard.admit_replan() == 1
    with pytest.raises(PlanValidationError, match="budget exhausted"):
        guard.admit_replan()


def _schema_nodes(value: object):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _schema_nodes(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _schema_nodes(nested)


def test_gicc_plan_proposal_is_openai_strict_schema_safe() -> None:
    schema = _strict_json_schema(PlanProposalV1.model_json_schema())

    assert isinstance(schema, dict)
    for node in _schema_nodes(schema):
        if node.get("type") != "object":
            continue
        assert node.get("additionalProperties") is False
        properties = node.get("properties")
        assert isinstance(properties, dict)
        assert set(node.get("required", ())) == set(properties)


def test_plan_parameters_json_decodes_to_bounded_object() -> None:
    candidate = PlanNodeCandidate(
        node_type=PlanNodeType.ACTION,
        summary="Open Calculator",
        parameters_json='{"app":"calculator","retry":1}',
        capability_key="app:lifecycle",
        operation="open_app",
        postcondition_ref="app_open",
    )

    assert candidate.parameters == {"app": "calculator", "retry": 1}

    with pytest.raises(ValueError, match="JSON object"):
        PlanNodeCandidate(
            node_type=PlanNodeType.WAIT,
            summary="Wait",
            parameters_json='["not","an","object"]',
        )
