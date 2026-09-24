"""Deterministic Self-Repair domain contracts.

This module is intentionally side-effect free. It defines the typed records and
validation rules used by later persistence, supervisor and effector layers.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum, IntEnum
from typing import Any

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


class RepairVerificationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


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


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
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


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


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


@dataclass(frozen=True, slots=True)
class RepairTriggerSnapshot:
    """Immutable historical trigger material retained with a repair attempt."""

    trigger_id: str
    component_id: str
    reason_code: str
    source: str
    observed_at_epoch: float
    health_state: HealthState
    process_exit_code: int | None
    evidence_references: tuple[str, ...]
    correlation_id: str | None
    session_id: str | None
    work_id: str | None

    @classmethod
    def from_trigger(cls, trigger: RepairTrigger) -> RepairTriggerSnapshot:
        return cls(
            trigger_id=trigger.trigger_id,
            component_id=trigger.component_id,
            reason_code=trigger.reason_code,
            source=trigger.source,
            observed_at_epoch=trigger.observed_at_epoch,
            health_state=trigger.health_state,
            process_exit_code=trigger.process_exit_code,
            evidence_references=trigger.evidence_references,
            correlation_id=trigger.correlation_id,
            session_id=trigger.session_id,
            work_id=trigger.work_id,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "component_id": self.component_id,
            "reason_code": self.reason_code,
            "source": self.source,
            "observed_at_epoch": self.observed_at_epoch,
            "health_state": self.health_state.value,
            "process_exit_code": self.process_exit_code,
            "evidence_references": list(self.evidence_references),
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "work_id": self.work_id,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RepairTriggerSnapshot:
        trigger = RepairTrigger(
            trigger_id=str(payload["trigger_id"]),
            component_id=str(payload["component_id"]),
            reason_code=str(payload["reason_code"]),
            source=str(payload["source"]),
            observed_at_epoch=float(payload["observed_at_epoch"]),
            health_state=HealthState(str(payload["health_state"])),
            process_exit_code=payload.get("process_exit_code"),
            evidence_references=tuple(payload.get("evidence_references") or ()),
            correlation_id=payload.get("correlation_id"),
            session_id=payload.get("session_id"),
            work_id=payload.get("work_id"),
        )
        return cls.from_trigger(trigger)


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
class RepairPolicySnapshot:
    """Immutable versioned policy material persisted with each new attempt."""

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
    escalation: RepairEscalation
    health_states: tuple[HealthState, ...]
    idempotent: bool
    reversible: bool
    automatic: bool

    @classmethod
    def from_policy(cls, policy: RepairPolicy) -> RepairPolicySnapshot:
        return cls(
            policy_id=policy.policy_id,
            version=policy.version,
            trigger_source=policy.trigger_source,
            component_id=policy.component_id,
            reason_code=policy.reason_code,
            action_kind=policy.action_kind,
            risk_class=policy.risk_class,
            preconditions=policy.preconditions,
            max_attempts=policy.max_attempts,
            rolling_window_seconds=policy.rolling_window_seconds,
            cooldown_seconds=policy.cooldown_seconds,
            backoff_multiplier=policy.backoff_multiplier,
            verification_contract=policy.verification_contract,
            escalation=policy.escalation,
            health_states=policy.health_states,
            idempotent=policy.idempotent,
            reversible=policy.reversible,
            automatic=policy.automatic,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "trigger_source": self.trigger_source,
            "component_id": self.component_id,
            "reason_code": self.reason_code,
            "action_kind": self.action_kind.value,
            "risk_class": int(self.risk_class),
            "preconditions": list(self.preconditions),
            "max_attempts": self.max_attempts,
            "rolling_window_seconds": self.rolling_window_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "verification_contract": self.verification_contract,
            "escalation": self.escalation.value,
            "health_states": [state.value for state in self.health_states],
            "idempotent": self.idempotent,
            "reversible": self.reversible,
            "automatic": self.automatic,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_payload()).encode()).hexdigest()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RepairPolicySnapshot:
        policy = RepairPolicy(
            policy_id=str(payload["policy_id"]),
            version=int(payload["version"]),
            trigger_source=str(payload["trigger_source"]),
            component_id=str(payload["component_id"]),
            reason_code=str(payload["reason_code"]),
            action_kind=RepairActionKind(str(payload["action_kind"])),
            risk_class=RepairRiskClass(int(payload["risk_class"])),
            preconditions=tuple(payload.get("preconditions") or ()),
            max_attempts=int(payload["max_attempts"]),
            rolling_window_seconds=float(payload["rolling_window_seconds"]),
            cooldown_seconds=float(payload["cooldown_seconds"]),
            backoff_multiplier=float(payload["backoff_multiplier"]),
            verification_contract=str(payload["verification_contract"]),
            escalation=RepairEscalation(str(payload["escalation"])),
            health_states=tuple(
                HealthState(str(value))
                for value in payload.get("health_states") or ()
            ),
            idempotent=bool(payload["idempotent"]),
            reversible=bool(payload["reversible"]),
            automatic=bool(payload["automatic"]),
        )
        return cls.from_policy(policy)


@dataclass(frozen=True, slots=True)
class RepairExecutionContext:
    """Typed deterministic state used to evaluate execution preconditions."""

    expected_revision: str | None = None
    current_revision: str | None = None
    restart_budget_available: bool = False

    def satisfies(self, precondition: str) -> bool:
        normalized = _required_token(precondition, field="precondition")
        if normalized == "same_local_revision":
            expected = _optional_identifier(self.expected_revision)
            current = _optional_identifier(self.current_revision)
            return (
                expected is not None
                and current is not None
                and expected.casefold() == current.casefold()
            )
        if normalized == "restart_budget_available":
            return self.restart_budget_available
        return False


@dataclass(frozen=True, slots=True)
class RepairVerificationResult:
    """Typed verifier proof; model text alone cannot create RECOVERED."""

    verifier_id: str
    verifier_version: int
    contract_id: str
    status: RepairVerificationStatus
    summary: str
    evidence_references: tuple[str, ...]
    observed_at_epoch: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "verifier_id",
            _required_token(self.verifier_id, field="verifier_id"),
        )
        object.__setattr__(
            self,
            "contract_id",
            _required_token(self.contract_id, field="contract_id"),
        )
        object.__setattr__(
            self,
            "summary",
            _required_text(self.summary, field="verification summary"),
        )
        object.__setattr__(
            self,
            "evidence_references",
            _evidence_references(self.evidence_references),
        )
        if self.verifier_version <= 0:
            raise ValueError("verifier_version must be positive")
        if not isinstance(self.status, RepairVerificationStatus):
            raise TypeError("status must be a RepairVerificationStatus")

    @classmethod
    def create(
        cls,
        *,
        verifier_id: str,
        verifier_version: int,
        contract_id: str,
        status: RepairVerificationStatus,
        summary: str,
        evidence_references: Iterable[str] = (),
        observed_at_epoch: float | None = None,
    ) -> RepairVerificationResult:
        return cls(
            verifier_id=verifier_id,
            verifier_version=verifier_version,
            contract_id=contract_id,
            status=status,
            summary=summary,
            evidence_references=tuple(evidence_references),
            observed_at_epoch=(
                time.time() if observed_at_epoch is None else observed_at_epoch
            ),
        )

    @property
    def verdict(self) -> RepairVerdict:
        if self.status is RepairVerificationStatus.PASS:
            return RepairVerdict.RECOVERED
        if self.status is RepairVerificationStatus.FAIL:
            return RepairVerdict.NOT_RECOVERED
        return RepairVerdict.INCONCLUSIVE

    def to_payload(self) -> dict[str, Any]:
        return {
            "verifier_id": self.verifier_id,
            "verifier_version": self.verifier_version,
            "contract_id": self.contract_id,
            "status": self.status.value,
            "summary": self.summary,
            "evidence_references": list(self.evidence_references),
            "observed_at_epoch": self.observed_at_epoch,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> RepairVerificationResult:
        return cls(
            verifier_id=str(payload["verifier_id"]),
            verifier_version=int(payload["verifier_version"]),
            contract_id=str(payload["contract_id"]),
            status=RepairVerificationStatus(str(payload["status"])),
            summary=str(payload["summary"]),
            evidence_references=tuple(payload.get("evidence_references") or ()),
            observed_at_epoch=float(payload["observed_at_epoch"]),
        )


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
    """Immutable execution record persisted under the canonical incident."""

    attempt_id: str
    incident_id: str
    trigger_id: str
    policy_id: str
    policy_version: int
    action: RepairAction
    attempt_number: int
    started_at_epoch: float
    pre_repair_evidence: tuple[str, ...] = ()
    trigger_snapshot: RepairTriggerSnapshot | None = None
    policy_snapshot: RepairPolicySnapshot | None = None
    finished_at_epoch: float | None = None
    execution_result: str | None = None
    post_repair_evidence: tuple[str, ...] = ()
    verifier_result: str | None = None
    verification: RepairVerificationResult | None = None
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

        trigger_snapshot = self.trigger_snapshot
        policy_snapshot = self.policy_snapshot
        verification = self.verification

        if trigger_snapshot is not None:
            if trigger_snapshot.trigger_id != self.trigger_id:
                raise ValueError("trigger snapshot identity does not match attempt")
            if trigger_snapshot.component_id != self.action.component_id:
                raise ValueError("trigger snapshot component does not match action")

        if policy_snapshot is not None:
            if policy_snapshot.policy_id != self.policy_id:
                raise ValueError("policy snapshot identity does not match attempt")
            if policy_snapshot.version != self.policy_version:
                raise ValueError("policy snapshot version does not match attempt")
            if policy_snapshot.action_kind is not self.action.kind:
                raise ValueError("policy snapshot action kind does not match action")
            if policy_snapshot.risk_class is not self.action.risk_class:
                raise ValueError("policy snapshot risk class does not match action")

        if trigger_snapshot is not None and policy_snapshot is not None:
            if trigger_snapshot.source != policy_snapshot.trigger_source:
                raise ValueError("trigger snapshot source does not match policy")
            if trigger_snapshot.component_id != policy_snapshot.component_id:
                raise ValueError("trigger snapshot component does not match policy")
            if trigger_snapshot.reason_code != policy_snapshot.reason_code:
                raise ValueError("trigger snapshot reason does not match policy")
            if (
                policy_snapshot.health_states
                and trigger_snapshot.health_state not in policy_snapshot.health_states
            ):
                raise ValueError("trigger snapshot health state does not match policy")

        if verification is not None:
            if (
                policy_snapshot is not None
                and verification.contract_id
                != policy_snapshot.verification_contract
            ):
                raise ValueError("verification contract does not match policy snapshot")
            if self.verdict is not verification.verdict:
                raise ValueError("repair verdict does not match verification status")
            if self.verifier_result != verification.summary:
                raise ValueError("verifier_result must match typed verification summary")
        elif (
            self.verdict is RepairVerdict.RECOVERED
            and policy_snapshot is not None
        ):
            raise ValueError("RECOVERED requires typed verification proof")

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
            trigger_snapshot=RepairTriggerSnapshot.from_trigger(trigger),
            policy_snapshot=RepairPolicySnapshot.from_policy(policy),
        )

    def complete(
        self,
        *,
        execution_result: str,
        verification: RepairVerificationResult,
        post_repair_evidence: Iterable[str] = (),
        next_retry_eligible_epoch: float | None = None,
        now_epoch: float | None = None,
    ) -> RepairAttempt:
        if not isinstance(verification, RepairVerificationResult):
            raise TypeError("verification must be a RepairVerificationResult")
        policy_snapshot = self.policy_snapshot
        if policy_snapshot is None:
            raise ValueError("new repair completion requires a policy snapshot")
        if verification.contract_id != policy_snapshot.verification_contract:
            raise ValueError("verification contract does not match policy snapshot")
        return replace(
            self,
            finished_at_epoch=time.time() if now_epoch is None else now_epoch,
            execution_result=_required_text(
                execution_result,
                field="execution_result",
            ),
            post_repair_evidence=tuple(post_repair_evidence),
            verifier_result=verification.summary,
            verification=verification,
            next_retry_eligible_epoch=next_retry_eligible_epoch,
            verdict=verification.verdict,
        )

    @property
    def recovered(self) -> bool:
        return self.verdict is RepairVerdict.RECOVERED
