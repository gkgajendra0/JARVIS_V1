import pytest

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
                parameters={"app": "calculator"},
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
                parameters={"app": "calculator"},
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
    proposal.nodes[0].parameters = {
        "shell": "powershell -EncodedCommand deadbeef",
    }

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
