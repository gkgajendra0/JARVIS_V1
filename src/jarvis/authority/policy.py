from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from .approval import ApprovalRecord
from .proposal import ActionProposal
from .types import (
    ApprovalRequirement,
    AuthorityEffect,
    InteractionContext,
    RiskClass,
    TrustTier,
)


@dataclass(frozen=True, slots=True)
class PolicyRequirements:
    required_trust: TrustTier
    approval_requirement: ApprovalRequirement
    require_owner_attentive: bool = False
    require_actor_unambiguous: bool = False
    audit_required: bool = True


@dataclass(frozen=True, slots=True)
class PolicyInput:
    proposal: ActionProposal
    risk_class: RiskClass
    context: InteractionContext
    approval: ApprovalRecord | None

    def as_opa_input(self) -> dict[str, object]:
        approval_payload: dict[str, object] | None = None
        if self.approval is not None:
            approval_payload = {
                "approval_id": self.approval.approval_id,
                "status": self.approval.status.value,
                "method": (
                    self.approval.method.value
                    if self.approval.method is not None
                    else None
                ),
                "requirement": self.approval.requirement.name.lower(),
            }
        return {
            "proposal": self.proposal.policy_view(),
            "risk_class": self.risk_class.name,
            "risk_level": int(self.risk_class),
            "context": {
                "session_id": self.context.session_id,
                "trust_tier": self.context.trust_tier.name,
                "trust_level": int(self.context.trust_tier),
                "owner_attentive": self.context.owner_attentive,
                "actor_unambiguous": self.context.actor_unambiguous,
                "windows_session_valid": self.context.windows_session_valid,
            },
            "approval": approval_payload,
        }


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    effect: AuthorityEffect
    requirements: PolicyRequirements
    reason_codes: tuple[str, ...]
    policy_version: str

    @classmethod
    def deny(cls, reason: str, *, policy_version: str) -> PolicyDecision:
        return cls(
            effect=AuthorityEffect.DENY,
            requirements=PolicyRequirements(
                required_trust=TrustTier.VERIFIED_OWNER,
                approval_requirement=ApprovalRequirement.STRONG,
                require_owner_attentive=True,
                require_actor_unambiguous=True,
                audit_required=True,
            ),
            reason_codes=(reason,),
            policy_version=policy_version,
        )


class PolicyEngine(Protocol):
    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision: ...


def hard_floor_for(risk_class: RiskClass) -> PolicyRequirements:
    if risk_class is RiskClass.ROUTINE:
        return PolicyRequirements(
            required_trust=TrustTier.UNVERIFIED,
            approval_requirement=ApprovalRequirement.NONE,
            audit_required=False,
        )
    if risk_class is RiskClass.PRIVATE_READ:
        return PolicyRequirements(
            required_trust=TrustTier.CORROBORATED_OWNER,
            approval_requirement=ApprovalRequirement.NONE,
            audit_required=True,
        )
    if risk_class is RiskClass.REVERSIBLE_LOCAL_CHANGE:
        return PolicyRequirements(
            required_trust=TrustTier.CORROBORATED_OWNER,
            approval_requirement=ApprovalRequirement.NONE,
            audit_required=True,
        )
    if risk_class is RiskClass.PERSISTENT_OR_EXTERNAL:
        return PolicyRequirements(
            required_trust=TrustTier.CORROBORATED_OWNER,
            approval_requirement=ApprovalRequirement.DIRECT_INTENT,
            audit_required=True,
        )
    if risk_class is RiskClass.CRITICAL:
        return PolicyRequirements(
            required_trust=TrustTier.VERIFIED_OWNER,
            approval_requirement=ApprovalRequirement.STRONG,
            audit_required=True,
        )
    return PolicyRequirements(
        required_trust=TrustTier.VERIFIED_OWNER,
        approval_requirement=ApprovalRequirement.STRONG,
        require_owner_attentive=True,
        require_actor_unambiguous=True,
        audit_required=True,
    )


def combine_requirements(
    floor: PolicyRequirements,
    policy: PolicyRequirements,
) -> PolicyRequirements:
    return PolicyRequirements(
        required_trust=max(floor.required_trust, policy.required_trust),
        approval_requirement=max(
            floor.approval_requirement,
            policy.approval_requirement,
        ),
        require_owner_attentive=(
            floor.require_owner_attentive or policy.require_owner_attentive
        ),
        require_actor_unambiguous=(
            floor.require_actor_unambiguous or policy.require_actor_unambiguous
        ),
        audit_required=floor.audit_required or policy.audit_required,
    )


class OpaPolicyEngine:
    """Fail-closed OPA adapter using only the Python standard library."""

    def __init__(
        self,
        *,
        endpoint: str = ("http://127.0.0.1:8181/v1/data/jarvis/authority/decision"),
        timeout_seconds: float = 0.5,
        expected_policy_version: str = "step3-v1",
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("OPA endpoint must be loopback HTTP")
        if timeout_seconds <= 0:
            raise ValueError("OPA timeout must be positive")
        if not expected_policy_version.strip():
            raise ValueError("expected policy version must not be empty")
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._expected_policy_version = expected_policy_version

    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        body = json.dumps(
            {"input": policy_input.as_opa_input()},
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (
            OSError,
            TimeoutError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ):
            return PolicyDecision.deny(
                "policy_unavailable_or_invalid",
                policy_version="opa:unavailable",
            )
        try:
            decision = self._parse_result(payload)
        except (KeyError, TypeError, ValueError):
            return PolicyDecision.deny(
                "policy_malformed_result",
                policy_version="opa:malformed",
            )
        if decision.policy_version != self._expected_policy_version:
            return PolicyDecision.deny(
                "policy_version_mismatch",
                policy_version=decision.policy_version,
            )
        return decision

    @staticmethod
    def _parse_result(payload: object) -> PolicyDecision:
        if not isinstance(payload, dict):
            raise TypeError("OPA payload must be an object")
        result = payload["result"]
        if not isinstance(result, dict):
            raise TypeError("OPA result must be an object")

        allow = result["allow"]
        if not isinstance(allow, bool):
            raise TypeError("OPA allow must be boolean")
        required_trust = TrustTier(int(result["required_trust"]))
        approval_requirement = ApprovalRequirement[
            str(result["approval_requirement"]).upper()
        ]
        require_owner_attentive = result.get(
            "require_owner_attentive",
            False,
        )
        require_actor_unambiguous = result.get(
            "require_actor_unambiguous",
            False,
        )
        audit_required = result.get("audit_required", True)
        if not all(
            isinstance(value, bool)
            for value in (
                require_owner_attentive,
                require_actor_unambiguous,
                audit_required,
            )
        ):
            raise TypeError("OPA boolean requirement fields must be boolean")
        raw_reasons = result.get("reason_codes", [])
        if not isinstance(raw_reasons, list) or not all(
            isinstance(reason, str) for reason in raw_reasons
        ):
            raise TypeError("OPA reason_codes must be a string list")
        policy_version = str(result.get("policy_version", "opa:unknown"))
        return PolicyDecision(
            effect=(AuthorityEffect.ALLOW if allow else AuthorityEffect.DENY),
            requirements=PolicyRequirements(
                required_trust=required_trust,
                approval_requirement=approval_requirement,
                require_owner_attentive=require_owner_attentive,
                require_actor_unambiguous=require_actor_unambiguous,
                audit_required=audit_required,
            ),
            reason_codes=tuple(raw_reasons),
            policy_version=policy_version,
        )
