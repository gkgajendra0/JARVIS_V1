"""External-supervisor crash correlation and bounded restart planning."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from jarvis.incidents import (
    EvidenceReference,
    IncidentRecord,
    IncidentService,
    IncidentSeverity,
    IncidentStatus,
)
from jarvis.self_model import HealthState
from jarvis.self_repair.domain import (
    RepairAction,
    RepairActionKind,
    RepairAttempt,
    RepairPolicy,
    RepairRiskClass,
    RepairTrigger,
    RepairVerdict,
)
from jarvis.self_repair.registry import RepairRegistry


class SupervisorFailurePhase(str, Enum):
    STARTUP = "startup"
    RUNTIME = "runtime"


@dataclass(frozen=True, slots=True)
class CrashFingerprint:
    """Bounded deterministic crash identity safe for incident correlation."""

    fingerprint_id: str
    exit_code: int | None
    phase: SupervisorFailurePhase
    reason_code: str
    component_ids: tuple[str, ...]
    commit_sha: str

    @classmethod
    def create(
        cls,
        *,
        exit_code: int | None,
        phase: SupervisorFailurePhase,
        reason_code: str,
        component_ids: Iterable[str],
        commit_sha: str,
    ) -> CrashFingerprint:
        if not isinstance(phase, SupervisorFailurePhase):
            raise TypeError("crash phase must be a SupervisorFailurePhase")
        normalized_reason = str(reason_code).strip().lower()
        normalized_components = tuple(
            sorted(
                {
                    str(component_id).strip().lower()
                    for component_id in component_ids
                    if str(component_id).strip()
                }
            )
        )
        normalized_sha = str(commit_sha).strip().lower()
        if not normalized_reason:
            raise ValueError("crash reason_code must not be empty")
        if not normalized_components:
            raise ValueError("crash fingerprint requires at least one component")
        if not normalized_sha:
            raise ValueError("crash fingerprint commit_sha must not be empty")
        if exit_code is not None and (
            isinstance(exit_code, bool) or not isinstance(exit_code, int)
        ):
            raise TypeError("crash exit_code must be an integer or None")

        payload = {
            "commit_sha": normalized_sha,
            "component_ids": normalized_components,
            "exit_code": exit_code,
            "phase": phase.value,
            "reason_code": normalized_reason,
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return cls(
            fingerprint_id=digest,
            exit_code=exit_code,
            phase=phase,
            reason_code=normalized_reason,
            component_ids=normalized_components,
            commit_sha=normalized_sha,
        )

    @property
    def evidence_reference(self) -> str:
        return f"crash_fingerprint:{self.fingerprint_id}"


@dataclass(frozen=True, slots=True)
class RestartBudgetDecision:
    allowed: bool
    exhausted: bool
    attempt_number: int | None
    budget_index: int | None
    wait_seconds: float
    recent_attempts: int


@dataclass(frozen=True, slots=True)
class SupervisorRepairPlan:
    fingerprint: CrashFingerprint
    incident: IncidentRecord
    trigger: RepairTrigger
    policy: RepairPolicy
    action: RepairAction | None
    budget: RestartBudgetDecision

    @property
    def exhausted(self) -> bool:
        return self.budget.exhausted


def build_runtime_child_exit_policy(
    *,
    max_attempts: int = 3,
    rolling_window_seconds: float = 300.0,
    cooldown_seconds: float = 2.0,
    backoff_multiplier: float = 2.0,
) -> RepairPolicy:
    return RepairPolicy(
        policy_id="supervisor-runtime-child-exit-v1",
        version=1,
        trigger_source="dev_supervisor",
        component_id="voice_runtime",
        reason_code="unexpected_child_exit",
        action_kind=RepairActionKind.RESTART_RUNTIME_CHILD,
        risk_class=RepairRiskClass.R2_RESTART,
        preconditions=("same_local_revision", "restart_budget_available"),
        max_attempts=max_attempts,
        rolling_window_seconds=rolling_window_seconds,
        cooldown_seconds=cooldown_seconds,
        backoff_multiplier=backoff_multiplier,
        verification_contract="startup_readiness_and_liveness_stabilization",
        health_states=(HealthState.FAILED,),
        idempotent=False,
        reversible=True,
        automatic=True,
    )


def _delay_for_budget_index(policy: RepairPolicy, budget_index: int) -> float:
    if budget_index <= 0:
        raise ValueError("budget_index must be positive")
    return policy.cooldown_seconds * (policy.backoff_multiplier ** (budget_index - 1))


def evaluate_restart_budget(
    policy: RepairPolicy,
    attempts: Iterable[RepairAttempt],
    *,
    now_epoch: float,
) -> RestartBudgetDecision:
    all_attempts = tuple(
        sorted(
            (
                attempt
                for attempt in attempts
                if attempt.policy_id == policy.policy_id
                and attempt.policy_version == policy.version
            ),
            key=lambda attempt: (
                attempt.started_at_epoch,
                attempt.attempt_number,
                attempt.attempt_id,
            ),
        )
    )
    cutoff = now_epoch - policy.rolling_window_seconds
    recent = tuple(
        attempt for attempt in all_attempts if attempt.started_at_epoch >= cutoff
    )
    if len(recent) >= policy.max_attempts:
        return RestartBudgetDecision(
            allowed=False,
            exhausted=True,
            attempt_number=None,
            budget_index=None,
            wait_seconds=0.0,
            recent_attempts=len(recent),
        )

    next_attempt_number = (
        max((attempt.attempt_number for attempt in all_attempts), default=0) + 1
    )
    budget_index = len(recent) + 1
    if recent:
        latest = recent[-1]
        if latest.next_retry_eligible_epoch is not None:
            wait_seconds = max(
                0.0,
                latest.next_retry_eligible_epoch - now_epoch,
            )
        else:
            base_epoch = (
                latest.finished_at_epoch
                if latest.finished_at_epoch is not None
                else latest.started_at_epoch
            )
            wait_seconds = max(
                0.0,
                base_epoch + _delay_for_budget_index(policy, budget_index) - now_epoch,
            )
    else:
        wait_seconds = _delay_for_budget_index(policy, budget_index)

    return RestartBudgetDecision(
        allowed=True,
        exhausted=False,
        attempt_number=next_attempt_number,
        budget_index=budget_index,
        wait_seconds=wait_seconds,
        recent_attempts=len(recent),
    )


class SupervisorRepairController:
    """Build and persist bounded supervisor repair attempts."""

    def __init__(
        self,
        incidents: IncidentService,
        *,
        policy: RepairPolicy | None = None,
    ) -> None:
        self._incidents = incidents
        self.policy = policy or build_runtime_child_exit_policy()
        self.registry = RepairRegistry((self.policy,))

    def plan_unexpected_exit(
        self,
        *,
        exit_code: int | None,
        commit_sha: str,
        now_epoch: float,
    ) -> SupervisorRepairPlan:
        fingerprint = CrashFingerprint.create(
            exit_code=exit_code,
            phase=SupervisorFailurePhase.RUNTIME,
            reason_code="unexpected_child_exit",
            component_ids=("voice_runtime",),
            commit_sha=commit_sha,
        )
        incident = self._find_or_create_incident(
            fingerprint,
            now_epoch=now_epoch,
        )
        trigger = RepairTrigger.create(
            component_id="voice_runtime",
            reason_code="unexpected_child_exit",
            source="dev_supervisor",
            health_state=HealthState.FAILED,
            process_exit_code=exit_code,
            evidence_references=(fingerprint.evidence_reference,),
            correlation_id=fingerprint.fingerprint_id,
            observed_at_epoch=now_epoch,
        )
        matched = self.registry.match(trigger)
        if matched is None:
            raise RuntimeError("runtime child exit repair policy is not registered")

        attempts = self._incidents.list_repair_attempts(
            incident.incident_id,
            limit=max(self.policy.max_attempts * 10, 100),
        )
        budget = evaluate_restart_budget(
            matched,
            attempts,
            now_epoch=now_epoch,
        )
        if budget.exhausted:
            self._record_budget_exhaustion(
                incident,
                fingerprint,
                now_epoch=now_epoch,
            )
            return SupervisorRepairPlan(
                fingerprint=fingerprint,
                incident=incident,
                trigger=trigger,
                policy=matched,
                action=None,
                budget=budget,
            )

        action = self.registry.action_for(trigger, now_epoch=now_epoch)
        if action is None:
            raise RuntimeError("registered runtime repair produced no action")
        self.registry.assert_executable(
            trigger,
            action,
            satisfied_preconditions=(
                "same_local_revision",
                "restart_budget_available",
            ),
        )
        return SupervisorRepairPlan(
            fingerprint=fingerprint,
            incident=incident,
            trigger=trigger,
            policy=matched,
            action=action,
            budget=budget,
        )

    def start_attempt(
        self,
        plan: SupervisorRepairPlan,
        *,
        now_epoch: float,
    ) -> RepairAttempt:
        if plan.action is None:
            raise RuntimeError("cannot start an exhausted repair plan")
        if plan.budget.attempt_number is None:
            raise RuntimeError("repair plan has no attempt number")
        attempt = RepairAttempt.start(
            incident_id=plan.incident.incident_id,
            trigger=plan.trigger,
            policy=plan.policy,
            action=plan.action,
            attempt_number=plan.budget.attempt_number,
            now_epoch=now_epoch,
        )
        return self._incidents.record_repair_attempt(attempt)

    def complete_attempt(
        self,
        plan: SupervisorRepairPlan,
        attempt: RepairAttempt,
        *,
        execution_result: str,
        verifier_result: str,
        verdict: RepairVerdict,
        post_repair_evidence: Iterable[str] = (),
        now_epoch: float,
    ) -> RepairAttempt:
        budget_index = plan.budget.budget_index
        if budget_index is None:
            raise RuntimeError("repair plan has no budget index")
        next_retry_eligible_epoch = now_epoch + _delay_for_budget_index(
            plan.policy,
            budget_index + 1,
        )
        completed = attempt.complete(
            execution_result=execution_result,
            verifier_result=verifier_result,
            verdict=verdict,
            post_repair_evidence=tuple(post_repair_evidence),
            next_retry_eligible_epoch=next_retry_eligible_epoch,
            now_epoch=now_epoch,
        )
        return self._incidents.record_repair_attempt(completed)

    def _find_or_create_incident(
        self,
        fingerprint: CrashFingerprint,
        *,
        now_epoch: float,
    ) -> IncidentRecord:
        for incident in self._incidents.list_recent(limit=100):
            if incident.status not in {
                IncidentStatus.OPEN,
                IncidentStatus.INVESTIGATING,
                IncidentStatus.MITIGATED,
            }:
                continue
            if "voice_runtime" not in incident.affected_components:
                continue
            if any(
                evidence.reference == fingerprint.evidence_reference
                for evidence in incident.evidence
            ):
                return incident

        incident = self._incidents.create_manual(
            title="JARVIS runtime child exited unexpectedly",
            symptom=(
                "voice runtime child exited unexpectedly "
                f"(exit_code={fingerprint.exit_code})"
            ),
            affected_components=("voice_runtime",),
            severity=IncidentSeverity.ERROR,
            now_epoch=now_epoch,
        )
        evidence = EvidenceReference.create(
            kind="crash_fingerprint",
            reference=fingerprint.evidence_reference,
            summary=(
                f"runtime exit code={fingerprint.exit_code}; "
                f"commit={fingerprint.commit_sha[:12]}"
            ),
            component_id="voice_runtime",
            occurred_at_epoch=now_epoch,
        )
        return self._incidents.add_evidence(
            incident.incident_id,
            evidence,
            now_epoch=now_epoch,
        )

    def _record_budget_exhaustion(
        self,
        incident: IncidentRecord,
        fingerprint: CrashFingerprint,
        *,
        now_epoch: float,
    ) -> None:
        reference = f"repair_budget_exhausted:{fingerprint.fingerprint_id}"
        if any(item.reference == reference for item in incident.evidence):
            return
        evidence = EvidenceReference.create(
            kind="repair_budget_exhausted",
            reference=reference,
            summary=(
                "runtime restart budget exhausted; automatic restart stopped "
                "and owner escalation is required"
            ),
            component_id="voice_runtime",
            occurred_at_epoch=now_epoch,
        )
        self._incidents.add_evidence(
            incident.incident_id,
            evidence,
            now_epoch=now_epoch,
        )
