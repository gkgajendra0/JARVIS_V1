"""Read-only Global Supervisor shadow evaluation.

S11 deliberately grants no mutation authority. The shadow runner observes one
ObjectiveWorkspace, asks a Supervisor advisor for a typed proposal, validates that
proposal against deterministic legal actions, and records agreement/divergence for
replay and live evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.workspace import (
    ObjectiveWorkspaceProjector,
    ObjectiveWorkspaceV1,
)

from .supervisor import (
    DeterministicSupervisorAdvisor,
    GlobalSupervisor,
    SupervisorAction,
    SupervisorAdvisor,
    SupervisorDecisionV1,
    SupervisorProposalV1,
    supervisor_context_from_workspace,
)


class ShadowAgreement(StrEnum):
    PRIMARY_MATCH = "primary_match"
    LEGAL_ALTERNATIVE = "legal_alternative"
    REJECTED = "rejected"
    ADVISOR_ERROR = "advisor_error"


class ShadowFaultKind(StrEnum):
    PROVIDER_OUTAGE = "provider_outage"
    MALFORMED_RESPONSE = "malformed_response"
    STALE_ARTIFACT = "stale_artifact"
    DUPLICATE_EVENT = "duplicate_event"
    PROCESS_CRASH = "process_crash"
    IRRELEVANT_CANDIDATE = "irrelevant_candidate"
    SPECIALIST_LOOP = "specialist_loop"
    FAILED_DEPENDENCY = "failed_dependency"


@dataclass(frozen=True, slots=True)
class SupervisorShadowObservationV1:
    schema: str
    goal_id: str
    workspace_digest: str
    context_digest: str
    expected_actions: tuple[SupervisorAction, ...]
    primary_expected_action: SupervisorAction | None
    proposed_action: SupervisorAction | None
    proposal_digest: str | None
    decision_digest: str | None
    accepted: bool
    rejection_codes: tuple[str, ...]
    agreement: ShadowAgreement
    duplicate_state: bool
    loop_detected: bool
    mutation_authority: bool
    fault_kind: ShadowFaultKind | None
    error_type: str | None
    error_detail: str | None
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "workspace_digest": self.workspace_digest,
            "context_digest": self.context_digest,
            "expected_actions": [item.value for item in self.expected_actions],
            "primary_expected_action": (
                None
                if self.primary_expected_action is None
                else self.primary_expected_action.value
            ),
            "proposed_action": (
                None if self.proposed_action is None else self.proposed_action.value
            ),
            "proposal_digest": self.proposal_digest,
            "decision_digest": self.decision_digest,
            "accepted": self.accepted,
            "rejection_codes": list(self.rejection_codes),
            "agreement": self.agreement.value,
            "duplicate_state": self.duplicate_state,
            "loop_detected": self.loop_detected,
            "mutation_authority": self.mutation_authority,
            "fault_kind": None if self.fault_kind is None else self.fault_kind.value,
            "error_type": self.error_type,
            "error_detail": self.error_detail,
        }

    def __post_init__(self) -> None:
        if self.schema != "supervisor_shadow_observation.v1":
            raise ValueError("unsupported Supervisor shadow observation schema")
        if self.mutation_authority:
            raise ValueError("Supervisor shadow mode may not have mutation authority")
        if self.accepted and self.agreement in {
            ShadowAgreement.REJECTED,
            ShadowAgreement.ADVISOR_ERROR,
        }:
            raise ValueError("accepted shadow observation has invalid agreement")
        if (
            self.digest != "pending"
            and canonical_digest(self.canonical_payload()) != self.digest
        ):
            raise ValueError("Supervisor shadow observation digest mismatch")


@dataclass(frozen=True, slots=True)
class ShadowFaultCaseV1:
    fault_kind: ShadowFaultKind
    requirement: str
    evidence_tests: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.requirement.strip():
            raise ValueError("shadow fault requirement must not be empty")
        if not self.evidence_tests:
            raise ValueError("shadow fault evidence_tests must not be empty")


GLOBAL_SUPERVISOR_S11_FAULT_MATRIX_V1: tuple[ShadowFaultCaseV1, ...] = (
    ShadowFaultCaseV1(
        ShadowFaultKind.PROVIDER_OUTAGE,
        "Provider pressure must remain recoverable and shadow reasoning must prefer a legal wait/retry action.",
        (
            "tests/test_goal_objective_workspace.py::test_supervisor_shadow_matches_provider_outage_action_without_writes",
            "tests/test_work_orchestration.py::test_provider_pressure_uses_durable_backoff_without_failure_budget",
        ),
    ),
    ShadowFaultCaseV1(
        ShadowFaultKind.MALFORMED_RESPONSE,
        "Malformed advisor output must be contained as shadow evidence and never become canonical state.",
        (
            "tests/test_goal_objective_workspace.py::test_supervisor_shadow_contains_malformed_advisor_output",
            "tests/test_development_engine_codex.py::test_codex_engine_repairs_one_malformed_directive_in_same_thread",
        ),
    ),
    ShadowFaultCaseV1(
        ShadowFaultKind.STALE_ARTIFACT,
        "A proposal bound to stale workspace or artifact state must be rejected before action.",
        (
            "tests/test_goal_objective_workspace.py::test_supervisor_shadow_rejects_stale_proposal_without_writes",
        ),
    ),
    ShadowFaultCaseV1(
        ShadowFaultKind.DUPLICATE_EVENT,
        "Repeated observation of identical canonical state must be idempotent and visible as duplicate shadow state.",
        (
            "tests/test_goal_objective_workspace.py::test_supervisor_shadow_detects_duplicate_state_and_restart_consistency",
            "tests/test_work_dbos.py::test_dbos_control_messages_use_idempotency_keys",
        ),
    ),
    ShadowFaultCaseV1(
        ShadowFaultKind.PROCESS_CRASH,
        "A fresh shadow process must reconstruct the same decision from the same canonical workspace.",
        (
            "tests/test_goal_objective_workspace.py::test_supervisor_shadow_detects_duplicate_state_and_restart_consistency",
            "tests/test_goal_objective_workspace.py::test_global_supervisor_decision_is_restart_deterministic",
        ),
    ),
    ShadowFaultCaseV1(
        ShadowFaultKind.IRRELEVANT_CANDIDATE,
        "Target-incompatible candidates must remain rejected before Supervisor-controlled architecture or development.",
        (
            "tests/test_capability_acquisition_resolver.py::test_target_specific_goal_does_not_reuse_unscoped_operation_match",
            "tests/test_capability_acquisition_resolver.py::test_target_specific_goal_reuses_only_explicitly_scoped_capability",
        ),
    ),
    ShadowFaultCaseV1(
        ShadowFaultKind.SPECIALIST_LOOP,
        "Repeated identical accepted proposals against unchanged state must be detected as a shadow specialist loop.",
        (
            "tests/test_goal_objective_workspace.py::test_supervisor_shadow_detects_specialist_loop_without_acting",
        ),
    ),
    ShadowFaultCaseV1(
        ShadowFaultKind.FAILED_DEPENDENCY,
        "Historical failed dependencies must not poison the current authoritative development path.",
        (
            "tests/test_engineering_change_authoritative_dependencies.py::test_development_depends_only_on_authoritative_research_attempt",
            "tests/test_work_orchestration.py::test_failed_dependency_fails_only_dependent_work",
        ),
    ),
)


def validate_global_supervisor_s11_fault_matrix() -> None:
    expected = set(ShadowFaultKind)
    actual = {item.fault_kind for item in GLOBAL_SUPERVISOR_S11_FAULT_MATRIX_V1}
    if actual != expected:
        raise ValueError(
            "S11 fault matrix must cover every ShadowFaultKind exactly once"
        )
    if len(GLOBAL_SUPERVISOR_S11_FAULT_MATRIX_V1) != len(actual):
        raise ValueError("S11 fault matrix contains duplicate fault kinds")


class SupervisorShadowRunner:
    """Evaluate Supervisor proposals with zero mutation authority."""

    def __init__(self, advisor: SupervisorAdvisor | None = None) -> None:
        self._advisor = advisor or DeterministicSupervisorAdvisor()

    def project_and_evaluate(
        self,
        projector: ObjectiveWorkspaceProjector,
        goal_id: str,
        *,
        history: tuple[SupervisorShadowObservationV1, ...] = (),
        fault_kind: ShadowFaultKind | None = None,
    ) -> SupervisorShadowObservationV1:
        if not isinstance(projector, ObjectiveWorkspaceProjector):
            raise TypeError("projector must be ObjectiveWorkspaceProjector")
        workspace = projector.project(goal_id)
        return self.evaluate(
            workspace,
            history=history,
            fault_kind=fault_kind,
        )

    def evaluate(
        self,
        workspace: ObjectiveWorkspaceV1,
        *,
        history: tuple[SupervisorShadowObservationV1, ...] = (),
        fault_kind: ShadowFaultKind | None = None,
    ) -> SupervisorShadowObservationV1:
        if not isinstance(workspace, ObjectiveWorkspaceV1):
            raise TypeError("workspace must be ObjectiveWorkspaceV1")
        context = supervisor_context_from_workspace(workspace)
        try:
            proposal = self._advisor.propose(context)
            if not isinstance(proposal, SupervisorProposalV1):
                raise TypeError("Supervisor advisor must return SupervisorProposalV1")
            decision = GlobalSupervisor.validate(context, proposal)
            return self._observation(
                context=context,
                proposal=proposal,
                decision=decision,
                history=history,
                fault_kind=fault_kind,
            )
        except Exception as exc:  # noqa: BLE001 - shadow boundary contains advisor faults
            return self._error_observation(
                context=context,
                history=history,
                fault_kind=fault_kind,
                exc=exc,
            )

    def evaluate_stale_proposal(
        self,
        workspace: ObjectiveWorkspaceV1,
    ) -> SupervisorShadowObservationV1:
        context = supervisor_context_from_workspace(workspace)
        proposal = self._advisor.propose(context)
        if not isinstance(proposal, SupervisorProposalV1):
            return self._error_observation(
                context=context,
                history=(),
                fault_kind=ShadowFaultKind.STALE_ARTIFACT,
                exc=TypeError("Supervisor advisor must return SupervisorProposalV1"),
            )
        payload = proposal.canonical_payload()
        payload["workspace_digest"] = "0" * 64
        stale = replace(
            proposal,
            workspace_digest="0" * 64,
            digest=canonical_digest(payload),
        )
        decision = GlobalSupervisor.validate(context, stale)
        return self._observation(
            context=context,
            proposal=stale,
            decision=decision,
            history=(),
            fault_kind=ShadowFaultKind.STALE_ARTIFACT,
        )

    @staticmethod
    def _agreement(
        decision: SupervisorDecisionV1,
        expected_actions: tuple[SupervisorAction, ...],
    ) -> ShadowAgreement:
        if not decision.accepted:
            return ShadowAgreement.REJECTED
        if expected_actions and decision.proposal.action == expected_actions[0]:
            return ShadowAgreement.PRIMARY_MATCH
        return ShadowAgreement.LEGAL_ALTERNATIVE

    @staticmethod
    def _duplicate_state(
        *,
        workspace_digest: str,
        proposed_action: SupervisorAction | None,
        history: tuple[SupervisorShadowObservationV1, ...],
    ) -> bool:
        if not history:
            return False
        latest = history[-1]
        return (
            latest.workspace_digest == workspace_digest
            and latest.proposed_action == proposed_action
        )

    @staticmethod
    def _loop_detected(
        *,
        workspace_digest: str,
        proposed_action: SupervisorAction | None,
        history: tuple[SupervisorShadowObservationV1, ...],
    ) -> bool:
        if proposed_action is None or len(history) < 2:
            return False
        recent = history[-2:]
        return all(
            item.accepted
            and item.workspace_digest == workspace_digest
            and item.proposed_action == proposed_action
            for item in recent
        )

    def _observation(
        self,
        *,
        context,
        proposal: SupervisorProposalV1,
        decision: SupervisorDecisionV1,
        history: tuple[SupervisorShadowObservationV1, ...],
        fault_kind: ShadowFaultKind | None,
    ) -> SupervisorShadowObservationV1:
        expected = context.allowed_actions
        observation = SupervisorShadowObservationV1(
            schema="supervisor_shadow_observation.v1",
            goal_id=context.goal_id,
            workspace_digest=context.workspace_digest,
            context_digest=context.digest,
            expected_actions=expected,
            primary_expected_action=None if not expected else expected[0],
            proposed_action=proposal.action,
            proposal_digest=proposal.digest,
            decision_digest=decision.digest,
            accepted=decision.accepted,
            rejection_codes=decision.rejection_codes,
            agreement=self._agreement(decision, expected),
            duplicate_state=self._duplicate_state(
                workspace_digest=context.workspace_digest,
                proposed_action=proposal.action,
                history=history,
            ),
            loop_detected=self._loop_detected(
                workspace_digest=context.workspace_digest,
                proposed_action=proposal.action,
                history=history,
            ),
            mutation_authority=False,
            fault_kind=fault_kind,
            error_type=None,
            error_detail=None,
            digest="pending",
        )
        return replace(
            observation,
            digest=canonical_digest(observation.canonical_payload()),
        )

    def _error_observation(
        self,
        *,
        context,
        history: tuple[SupervisorShadowObservationV1, ...],
        fault_kind: ShadowFaultKind | None,
        exc: Exception,
    ) -> SupervisorShadowObservationV1:
        expected = context.allowed_actions
        detail = " ".join(str(exc).split()).strip()[:400] or None
        observation = SupervisorShadowObservationV1(
            schema="supervisor_shadow_observation.v1",
            goal_id=context.goal_id,
            workspace_digest=context.workspace_digest,
            context_digest=context.digest,
            expected_actions=expected,
            primary_expected_action=None if not expected else expected[0],
            proposed_action=None,
            proposal_digest=None,
            decision_digest=None,
            accepted=False,
            rejection_codes=("advisor_error",),
            agreement=ShadowAgreement.ADVISOR_ERROR,
            duplicate_state=self._duplicate_state(
                workspace_digest=context.workspace_digest,
                proposed_action=None,
                history=history,
            ),
            loop_detected=False,
            mutation_authority=False,
            fault_kind=fault_kind,
            error_type=type(exc).__name__,
            error_detail=detail,
            digest="pending",
        )
        return replace(
            observation,
            digest=canonical_digest(observation.canonical_payload()),
        )
