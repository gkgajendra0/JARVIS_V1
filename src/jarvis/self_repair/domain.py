"""Deterministic Self-Repair domain contracts.

This module is intentionally side-effect free. It defines the typed records and
validation rules used by later persistence, supervisor and effector layers.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum, IntEnum
from collections.abc import Iterable

from jarvis.self_model.health import HealthState

MAX_EVIDENCE_REFERENCES = 16


class RepairRiskClass(IntEnum):
    R0_OBSERVE = 0
    R1_RETRY_RECONNECT = 1
    R2_RESTART = 2
    R3_RUNTIME_MUTATION = 3
    R4_SOURCE_REPAIR = 4
    R5_PROTECTED_MUTATION = 5


class RepairActionKind(str, Enum):
    RETRY_OPERATION = "retry_operation"
    RECONNECT_SUBSYSTEM = "reconnect_subsystem"
    RESTART_RUNTIME_CHILD = "restart_runtime_child"
    NO_ACTION_ESCALATE = "no_action_escalate"


class RepairVerdict(str, Enum):
    RECOVERED = "recovered"
    NOT_RECOVERED = "not_recovered"
    INCONCLUSIVE = "inconclusive"
    ESCALATED = "escalated"


class RepairEscalation(str, Enum):
    STOP_AND_ESCALATE = "stop_and_escalate"


class RepairPolicyError(ValueError):
    """A repair policy is internally inconsistent or unsafe."""


class RepairAuthorizationError(RuntimeError):
    """A proposed repair action is not authorized by the registry."""


class RepairPolicyConflictError(RuntimeError):
    """More than one registered policy matched the same trigger."""


def _required_token(value: object, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _optional_identifier(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _evidence_references(values: Iterable[object]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        reference = str(value).strip()
        if reference and reference not in normalized:
            normalized.append(reference)
    if len(normalized) > MAX_EVIDENCE_REFERENCES:
        raise ValueError(f"repair evidence references exceed {MAX_EVIDENCE_REFERENCES}")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class RepairTrigger:
    """Normalized immutable evidence signal entering Self-Repair."""

    trigger_id: str
    component_id: str
    reason_code: str
    source: str
    observed_at_epoch: float
    health_state: HealthState
    process_exit_code: int | None = None
    evidence_references: tuple[str, ...] = ()
    correlation_id: str | None = None
    session_id: str | None = None
    work_id: str | None = None

    def __post_init__(self) -> None:
        trigger_id = str(self.trigger_id).strip()
        if not trigger_id:
            raise ValueError("trigger_id must not be empty")
        if not isinstance(self.health_state, HealthState):
            raise TypeError("health_state must be a HealthState")
        if self.process_exit_code is not None and (
            isinstance(self.process_exit_code, bool)
            or not isinstance(self.process_exit_code, int)
        ):
            raise TypeError("process_exit_code must be an integer or None")

        object.__setattr__(self, "trigger_id", trigger_id)
        object.__setattr__(
            self,
            "component_id",
            _required_token(self.component_id, field="component_id"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _required_token(self.reason_code, field="reason_code"),
        )
        object.__setattr__(
            self,
            "source",
            _required_token(self.source, field="source"),
        )
        object.__setattr__(
            self,
            "evidence_references",
            _evidence_references(self.evidence_references),
        )
        object.__setattr__(
            self,
            "correlation_id",
            _optional_identifier(self.correlation_id),
        )
        object.__setattr__(self, "session_id", _optional_identifier(self.session_id))
        object.__setattr__(self, "work_id", _optional_identifier(self.work_id))

    @classmethod
    def create(
        cls,
        *,
        component_id: str,
        reason_code: str,
        source: str,
        health_state: HealthState,
        observed_at_epoch: float | None = None,
        process_exit_code: int | None = None,
        evidence_references: Iterable[str] = (),
        correlation_id: str | None = None,
        session_id: str | None = None,
        work_id: str | None = None,
        trigger_id: str | None = None,
    ) -> RepairTrigger:
        return cls(
            trigger_id=trigger_id or str(uuid.uuid4()),
            component_id=component_id,
            reason_code=reason_code,
            source=source,
            observed_at_epoch=(
                time.time() if observed_at_epoch is None else observed_at_epoch
            ),
            health_state=health_state,
            process_exit_code=process_exit_code,
            evidence_references=tuple(evidence_references),
            correlation_id=correlation_id,
            session_id=session_id,
            work_id=work_id,
        )


_ACTION_RISK = {
    RepairActionKind.RETRY_OPERATION: RepairRiskClass.R1_RETRY_RECONNECT,
    RepairActionKind.RECONNECT_SUBSYSTEM: RepairRiskClass.R1_RETRY_RECONNECT,
    RepairActionKind.RESTART_RUNTIME_CHILD: RepairRiskClass.R2_RESTART,
    RepairActionKind.NO_ACTION_ESCALATE: RepairRiskClass.R0_OBSERVE,
}


@dataclass(frozen=True, slots=True)
class RepairPolicy:
    """Version-controlled deterministic rule for one exact failure signature."""

    policy_id: str
    version: int
    trigger_source: str
    component_id: str
    reason_code: str
    action_kind: RepairActionKind
    risk_class: RepairRiskClass
    preconditions: tuple[str, ...]
    max_attempts: int
    rolling_window_seconds: float
    cooldown_seconds: float
    backoff_multiplier: float
    verification_contract: str
    escalation: RepairEscalation = RepairEscalation.STOP_AND_ESCALATE
    health_states: tuple[HealthState, ...] = ()
    idempotent: bool = False
    reversible: bool = False
    automatic: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_id",
            _required_token(self.policy_id, field="policy_id"),
        )
        object.__setattr__(
            self,
            "trigger_source",
            _required_token(self.trigger_source, field="trigger_source"),
        )
        object.__setattr__(
            self,
            "component_id",
            _required_token(self.component_id, field="component_id"),
        )
        object.__setattr__(
            self,
            "reason_code",
            _required_token(self.reason_code, field="reason_code"),
        )
        object.__setattr__(
            self,
            "verification_contract",
            _required_token(
                self.verification_contract,
                field="verification_contract",
            ),
        )
        object.__setattr__(
            self,
            "preconditions",
            tuple(
                dict.fromkeys(
                    _required_token(item, field="precondition")
                    for item in self.preconditions
                )
            ),
        )

        if not isinstance(self.action_kind, RepairActionKind):
            raise RepairPolicyError("action_kind must be a RepairActionKind")
        if not isinstance(self.risk_class, RepairRiskClass):
            raise RepairPolicyError("risk_class must be a RepairRiskClass")
        if not isinstance(self.escalation, RepairEscalation):
            raise RepairPolicyError("escalation must be a RepairEscalation")
        if self.version <= 0:
            raise RepairPolicyError("policy version must be positive")
        if self.max_attempts <= 0:
            raise RepairPolicyError("max_attempts must be positive")
        if self.rolling_window_seconds <= 0:
            raise RepairPolicyError("rolling_window_seconds must be positive")
        if self.cooldown_seconds < 0:
            raise RepairPolicyError("cooldown_seconds must not be negative")
        if self.backoff_multiplier < 1:
            raise RepairPolicyError("backoff_multiplier must be at least 1")

        expected_risk = _ACTION_RISK[self.action_kind]
        if self.risk_class is not expected_risk:
            raise RepairPolicyError(
                f"{self.action_kind.value} requires risk {expected_risk.name}"
            )

        if self.automatic:
            if self.risk_class not in {
                RepairRiskClass.R1_RETRY_RECONNECT,
                RepairRiskClass.R2_RESTART,
            }:
                raise RepairPolicyError(
                    "automatic repair is limited to registered R1/R2 policies"
                )
            if not self.reversible:
                raise RepairPolicyError(
                    "automatic R1/R2 policy must declare reversible=True"
                )

        for state in self.health_states:
            if not isinstance(state, HealthState):
                raise TypeError("health_states must contain HealthState values")

    def matches(self, trigger: RepairTrigger) -> bool:
        if trigger.source != self.trigger_source:
            return False
        if trigger.component_id != self.component_id:
            return False
        if trigger.reason_code != self.reason_code:
            return False
        return not self.health_states or trigger.health_state in self.health_states


@dataclass(frozen=True, slots=True)
class RepairAction:
    """Typed action created from a registered policy; never a shell command."""

    action_id: str
    policy_id: str
    policy_version: int
    trigger_id: str
    component_id: str
    kind: RepairActionKind
    risk_class: RepairRiskClass
    created_at_epoch: float

    @classmethod
    def create(
        cls,
        policy: RepairPolicy,
        trigger: RepairTrigger,
        *,
        now_epoch: float | None = None,
        action_id: str | None = None,
    ) -> RepairAction:
        if not policy.matches(trigger):
            raise RepairAuthorizationError(
                "policy does not match the supplied repair trigger"
            )
        return cls(
            action_id=action_id or str(uuid.uuid4()),
            policy_id=policy.policy_id,
            policy_version=policy.version,
            trigger_id=trigger.trigger_id,
            component_id=trigger.component_id,
            kind=policy.action_kind,
            risk_class=policy.risk_class,
            created_at_epoch=time.time() if now_epoch is None else now_epoch,
        )


@dataclass(frozen=True, slots=True)
class RepairAttempt:
    """Immutable execution record; persistence is added in the next phase."""

    attempt_id: str
    incident_id: str
    trigger_id: str
    policy_id: str
    policy_version: int
    action: RepairAction
    attempt_number: int
    started_at_epoch: float
    pre_repair_evidence: tuple[str, ...] = ()
    finished_at_epoch: float | None = None
    execution_result: str | None = None
    post_repair_evidence: tuple[str, ...] = ()
    verifier_result: str | None = None
    next_retry_eligible_epoch: float | None = None
    verdict: RepairVerdict | None = None

    def __post_init__(self) -> None:
        if self.attempt_number <= 0:
            raise ValueError("attempt_number must be positive")
        if not str(self.incident_id).strip():
            raise ValueError("incident_id must not be empty")
        if self.trigger_id != self.action.trigger_id:
            raise ValueError("attempt trigger_id must match action trigger_id")
        if self.policy_id != self.action.policy_id:
            raise ValueError("attempt policy_id must match action policy_id")
        if self.policy_version != self.action.policy_version:
            raise ValueError("attempt policy_version must match action policy_version")
        object.__setattr__(
            self,
            "pre_repair_evidence",
            _evidence_references(self.pre_repair_evidence),
        )
        object.__setattr__(
            self,
            "post_repair_evidence",
            _evidence_references(self.post_repair_evidence),
        )

    @classmethod
    def start(
        cls,
        *,
        incident_id: str,
        trigger: RepairTrigger,
        policy: RepairPolicy,
        action: RepairAction,
        attempt_number: int,
        now_epoch: float | None = None,
        attempt_id: str | None = None,
    ) -> RepairAttempt:
        if not policy.matches(trigger):
            raise RepairAuthorizationError(
                "attempt policy does not match the supplied trigger"
            )
        if action.trigger_id != trigger.trigger_id:
            raise RepairAuthorizationError(
                "attempt action belongs to a different trigger"
            )
        if action.policy_id != policy.policy_id:
            raise RepairAuthorizationError(
                "attempt action belongs to a different policy"
            )
        if action.policy_version != policy.version:
            raise RepairAuthorizationError(
                "attempt action policy version does not match"
            )
        if action.component_id != trigger.component_id:
            raise RepairAuthorizationError(
                "attempt action target does not match trigger component"
            )
        if action.kind is not policy.action_kind:
            raise RepairAuthorizationError("attempt action kind does not match policy")
        if action.risk_class is not policy.risk_class:
            raise RepairAuthorizationError("attempt action risk does not match policy")
        return cls(
            attempt_id=attempt_id or str(uuid.uuid4()),
            incident_id=str(incident_id).strip(),
            trigger_id=trigger.trigger_id,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            action=action,
            attempt_number=attempt_number,
            started_at_epoch=time.time() if now_epoch is None else now_epoch,
            pre_repair_evidence=trigger.evidence_references,
        )

    def complete(
        self,
        *,
        execution_result: str,
        verifier_result: str,
        verdict: RepairVerdict,
        post_repair_evidence: Iterable[str] = (),
        next_retry_eligible_epoch: float | None = None,
        now_epoch: float | None = None,
    ) -> RepairAttempt:
        return replace(
            self,
            finished_at_epoch=time.time() if now_epoch is None else now_epoch,
            execution_result=str(execution_result).strip(),
            post_repair_evidence=tuple(post_repair_evidence),
            verifier_result=str(verifier_result).strip(),
            next_retry_eligible_epoch=next_retry_eligible_epoch,
            verdict=verdict,
        )

    @property
    def recovered(self) -> bool:
        return self.verdict is RepairVerdict.RECOVERED
