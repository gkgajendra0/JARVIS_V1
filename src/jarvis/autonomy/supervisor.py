"""Bounded Global Supervisor reasoning over governed workspace ledgers."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.ledgers import (
    ProgressLedgerV1,
    TaskLedgerV1,
    build_progress_ledger,
    build_task_ledger,
)
from jarvis.goal_intelligence.workspace import ObjectiveWorkspaceV1


class SupervisorAction(StrEnum):
    CONTINUE = "CONTINUE"
    WAIT_RESOURCE = "WAIT_RESOURCE"
    RETRY = "RETRY"
    REQUEST_RESEARCH = "REQUEST_RESEARCH"
    REQUEST_ARCHITECTURE = "REQUEST_ARCHITECTURE"
    RESUME_DEVELOPMENT = "RESUME_DEVELOPMENT"
    VERIFY_ASSUMPTION = "VERIFY_ASSUMPTION"
    SUPERSEDE_ATTEMPT = "SUPERSEDE_ATTEMPT"
    REPLAN = "REPLAN"
    ASK_OWNER = "ASK_OWNER"
    TERMINAL = "TERMINAL"


@dataclass(frozen=True, slots=True)
class SupervisorContextV1:
    schema: str
    goal_id: str
    task_ledger: TaskLedgerV1
    progress_ledger: ProgressLedgerV1
    workspace_digest: str
    observed_blockers: tuple[str, ...]
    open_questions: tuple[str, ...]
    current_architecture_refs: tuple[str, ...]
    allowed_actions: tuple[SupervisorAction, ...]
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "task_ledger_digest": self.task_ledger.digest,
            "progress_ledger_digest": self.progress_ledger.digest,
            "workspace_digest": self.workspace_digest,
            "observed_blockers": list(self.observed_blockers),
            "open_questions": list(self.open_questions),
            "current_architecture_refs": list(self.current_architecture_refs),
            "allowed_actions": [item.value for item in self.allowed_actions],
        }

    def __post_init__(self) -> None:
        if self.schema != "supervisor_context.v1":
            raise ValueError("unsupported SupervisorContext schema")
        if self.task_ledger.goal_id != self.goal_id:
            raise ValueError("TaskLedger belongs to another goal")
        if self.progress_ledger.goal_id != self.goal_id:
            raise ValueError("ProgressLedger belongs to another goal")
        if self.task_ledger.source_workspace_digest != self.workspace_digest:
            raise ValueError("TaskLedger is stale for Supervisor workspace")
        if self.progress_ledger.source_workspace_digest != self.workspace_digest:
            raise ValueError("ProgressLedger is stale for Supervisor workspace")
        if self.digest != "pending" and canonical_digest(
            self.canonical_payload()
        ) != self.digest:
            raise ValueError("SupervisorContext digest mismatch")


@dataclass(frozen=True, slots=True)
class SupervisorProposalV1:
    schema: str
    goal_id: str
    action: SupervisorAction
    rationale: str
    workspace_digest: str
    task_ledger_digest: str
    progress_ledger_digest: str
    target_change_id: str | None
    target_work_id: str | None
    bounded_question: str | None
    evidence_refs: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        context: SupervisorContextV1,
        *,
        action: SupervisorAction,
        rationale: str,
        target_change_id: str | None = None,
        target_work_id: str | None = None,
        bounded_question: str | None = None,
        evidence_refs: tuple[str, ...] = (),
    ) -> SupervisorProposalV1:
        if not isinstance(context, SupervisorContextV1):
            raise TypeError("context must be SupervisorContextV1")
        if not isinstance(action, SupervisorAction):
            raise TypeError("action must be SupervisorAction")
        normalized_rationale = " ".join(str(rationale).split()).strip()
        if not normalized_rationale:
            raise ValueError("rationale must not be empty")
        question = (
            None
            if bounded_question is None
            else " ".join(str(bounded_question).split()).strip() or None
        )
        payload = {
            "schema": "supervisor_proposal.v1",
            "goal_id": context.goal_id,
            "action": action.value,
            "rationale": normalized_rationale,
            "workspace_digest": context.workspace_digest,
            "task_ledger_digest": context.task_ledger.digest,
            "progress_ledger_digest": context.progress_ledger.digest,
            "target_change_id": target_change_id,
            "target_work_id": target_work_id,
            "bounded_question": question,
            "evidence_refs": list(evidence_refs),
        }
        return cls(
            schema="supervisor_proposal.v1",
            goal_id=context.goal_id,
            action=action,
            rationale=normalized_rationale,
            workspace_digest=context.workspace_digest,
            task_ledger_digest=context.task_ledger.digest,
            progress_ledger_digest=context.progress_ledger.digest,
            target_change_id=target_change_id,
            target_work_id=target_work_id,
            bounded_question=question,
            evidence_refs=tuple(evidence_refs),
            digest=canonical_digest(payload),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "goal_id": self.goal_id,
            "action": self.action.value,
            "rationale": self.rationale,
            "workspace_digest": self.workspace_digest,
            "task_ledger_digest": self.task_ledger_digest,
            "progress_ledger_digest": self.progress_ledger_digest,
            "target_change_id": self.target_change_id,
            "target_work_id": self.target_work_id,
            "bounded_question": self.bounded_question,
            "evidence_refs": list(self.evidence_refs),
        }

    def __post_init__(self) -> None:
        if self.schema != "supervisor_proposal.v1":
            raise ValueError("unsupported SupervisorProposal schema")
        if not isinstance(self.action, SupervisorAction):
            raise TypeError("action must be SupervisorAction")
        if not self.rationale.strip():
            raise ValueError("rationale must not be empty")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("SupervisorProposal digest mismatch")


@dataclass(frozen=True, slots=True)
class SupervisorDecisionV1:
    schema: str
    proposal: SupervisorProposalV1
    accepted: bool
    rejection_codes: tuple[str, ...]
    allowed_actions: tuple[SupervisorAction, ...]
    context_digest: str
    digest: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "proposal_digest": self.proposal.digest,
            "accepted": self.accepted,
            "rejection_codes": list(self.rejection_codes),
            "allowed_actions": [item.value for item in self.allowed_actions],
            "context_digest": self.context_digest,
        }

    def __post_init__(self) -> None:
        if self.schema != "supervisor_decision.v1":
            raise ValueError("unsupported SupervisorDecision schema")
        if self.accepted == bool(self.rejection_codes):
            raise ValueError("accepted decision and rejection codes disagree")
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("SupervisorDecision digest mismatch")


class SupervisorAdvisor(Protocol):
    def propose(self, context: SupervisorContextV1) -> SupervisorProposalV1: ...


def supervisor_context_from_workspace(
    workspace: ObjectiveWorkspaceV1,
) -> SupervisorContextV1:
    if not isinstance(workspace, ObjectiveWorkspaceV1):
        raise TypeError("workspace must be ObjectiveWorkspaceV1")
    task = build_task_ledger(workspace)
    progress = build_progress_ledger(workspace)
    actions = tuple(SupervisorAction(item) for item in progress.next_legal_actions)
    context = SupervisorContextV1(
        schema="supervisor_context.v1",
        goal_id=task.goal_id,
        task_ledger=task,
        progress_ledger=progress,
        workspace_digest=workspace.digest,
        observed_blockers=workspace.observed_blockers,
        open_questions=workspace.open_questions,
        current_architecture_refs=workspace.current_architecture_refs,
        allowed_actions=actions,
        digest="pending",
    )
    return replace(context, digest=canonical_digest(context.canonical_payload()))


class DeterministicSupervisorAdvisor:
    """Conservative fallback used when no model advisor is configured."""

    def propose(self, context: SupervisorContextV1) -> SupervisorProposalV1:
        if not context.allowed_actions:
            action = SupervisorAction.CONTINUE
        else:
            action = context.allowed_actions[0]
        return SupervisorProposalV1.create(
            context,
            action=action,
            rationale=(
                "Choose the first deterministic legal action from the current "
                "Progress Ledger."
            ),
            target_change_id=context.progress_ledger.active_change_id,
            target_work_id=context.progress_ledger.active_work_id,
        )


class GlobalSupervisor:
    """Reasoning may propose; deterministic code remains the authority boundary."""

    def __init__(
        self,
        advisor: SupervisorAdvisor | None = None,
    ) -> None:
        self._advisor = advisor or DeterministicSupervisorAdvisor()

    def evaluate(
        self,
        workspace: ObjectiveWorkspaceV1,
    ) -> SupervisorDecisionV1:
        context = supervisor_context_from_workspace(workspace)
        proposal = self._advisor.propose(context)
        if not isinstance(proposal, SupervisorProposalV1):
            raise TypeError("Supervisor advisor must return SupervisorProposalV1")
        return self.validate(context, proposal)

    @staticmethod
    def validate(
        context: SupervisorContextV1,
        proposal: SupervisorProposalV1,
    ) -> SupervisorDecisionV1:
        if not isinstance(context, SupervisorContextV1):
            raise TypeError("context must be SupervisorContextV1")
        if not isinstance(proposal, SupervisorProposalV1):
            raise TypeError("proposal must be SupervisorProposalV1")

        rejection_codes: list[str] = []
        if proposal.goal_id != context.goal_id:
            rejection_codes.append("goal_binding_mismatch")
        if proposal.workspace_digest != context.workspace_digest:
            rejection_codes.append("workspace_digest_mismatch")
        if proposal.task_ledger_digest != context.task_ledger.digest:
            rejection_codes.append("task_ledger_digest_mismatch")
        if proposal.progress_ledger_digest != context.progress_ledger.digest:
            rejection_codes.append("progress_ledger_digest_mismatch")
        if proposal.action not in context.allowed_actions:
            rejection_codes.append("action_not_legal")
        if (
            proposal.target_change_id is not None
            and proposal.target_change_id
            != context.progress_ledger.active_change_id
        ):
            rejection_codes.append("change_binding_mismatch")
        if (
            proposal.target_work_id is not None
            and proposal.target_work_id != context.progress_ledger.active_work_id
        ):
            rejection_codes.append("work_binding_mismatch")
        if (
            proposal.action is SupervisorAction.ASK_OWNER
            and not context.progress_ledger.owner_action_required
            and context.progress_ledger.phase
            not in {
                "information",
                "architecture",
                "owner_approval",
                "owner_acceptance",
                "promotion_approval",
            }
        ):
            rejection_codes.append("owner_attention_not_required")
        if proposal.action is SupervisorAction.TERMINAL and (
            context.progress_ledger.phase != "terminal"
            and context.progress_ledger.blocker_kind != "terminal"
        ):
            rejection_codes.append("terminal_not_proven")

        accepted = not rejection_codes
        payload = {
            "schema": "supervisor_decision.v1",
            "proposal_digest": proposal.digest,
            "accepted": accepted,
            "rejection_codes": sorted(set(rejection_codes)),
            "allowed_actions": [item.value for item in context.allowed_actions],
            "context_digest": context.digest,
        }
        return SupervisorDecisionV1(
            schema="supervisor_decision.v1",
            proposal=proposal,
            accepted=accepted,
            rejection_codes=tuple(payload["rejection_codes"]),
            allowed_actions=context.allowed_actions,
            context_digest=context.digest,
            digest=canonical_digest(payload),
        )
