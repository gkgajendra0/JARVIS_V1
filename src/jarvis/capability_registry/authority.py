"""Existing-Authority bridge for Phase-8 capability lifecycle mutations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, fields
from enum import Enum

from jarvis.authority.approval import ApprovalError, ApprovalService
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityError, AuthorityService
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ActionScope,
    ApprovalMethod,
    ApprovalRequirement,
    AttentionState,
    AuthorityEffect,
    InteractionContext,
    RiskClass,
    TrustTier,
)
from jarvis.authority.verifier import StrongVerifier
from jarvis.engineering_change.gates import GateChallenge, GateDecision


class CapabilityLifecycleAuthorizationError(RuntimeError):
    pass


class CapabilityLifecycleAction(str, Enum):
    ENABLE = "enable"
    DISABLE = "disable"
    SELECT_VERSION = "select_version"
    ROLLBACK_VERSION = "rollback_version"
    RETIRE_PACKAGE = "retire_package"
    QUARANTINE_PACKAGE = "quarantine_package"


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleAuthoritySource:
    """Provenance for a state-changing lifecycle request."""

    source_session_id: str
    source_turn_id: str | None = None
    engineering_gate_id: str | None = None

    def __post_init__(self) -> None:
        session_id = str(self.source_session_id).strip()
        turn_id = (
            None if self.source_turn_id is None else str(self.source_turn_id).strip()
        )
        gate_id = (
            None
            if self.engineering_gate_id is None
            else str(self.engineering_gate_id).strip()
        )
        if not session_id:
            raise ValueError("source_session_id must not be empty")
        if bool(turn_id) == bool(gate_id):
            raise ValueError(
                "lifecycle source requires exactly one owner turn or engineering gate"
            )
        object.__setattr__(self, "source_session_id", session_id)
        object.__setattr__(self, "source_turn_id", turn_id)
        object.__setattr__(self, "engineering_gate_id", gate_id)

    @classmethod
    def owner_turn(
        cls,
        *,
        session_id: str,
        turn_id: str,
    ) -> CapabilityLifecycleAuthoritySource:
        return cls(
            source_session_id=session_id,
            source_turn_id=turn_id,
        )

    @classmethod
    def engineering_gate(
        cls,
        *,
        authority_session_id: str,
        gate_id: str,
    ) -> CapabilityLifecycleAuthoritySource:
        return cls(
            source_session_id=authority_session_id,
            engineering_gate_id=gate_id,
        )


@dataclass(frozen=True, slots=True)
class CapabilityLifecycleProposalBinding:
    action: CapabilityLifecycleAction
    capability_id: str
    expected_generation: int
    package_id: str | None
    package_version: str | None
    package_digest: str | None
    compatibility_digest: str
    manifest_risk_floor: RiskClass
    manifest_authority_attributes: tuple[str, ...]
    source: CapabilityLifecycleAuthoritySource

    def __post_init__(self) -> None:
        if not isinstance(self.action, CapabilityLifecycleAction):
            raise TypeError("action must be CapabilityLifecycleAction")
        capability_id = str(self.capability_id).strip().casefold()
        if not capability_id:
            raise ValueError("capability_id must not be empty")
        if type(self.expected_generation) is not int or self.expected_generation <= 0:
            raise ValueError("expected_generation must be a positive integer")
        package_id = (
            None if self.package_id is None else str(self.package_id).strip().casefold()
        )
        package_version = (
            None if self.package_version is None else str(self.package_version).strip()
        )
        package_digest = (
            None if self.package_digest is None else str(self.package_digest).strip()
        )
        if (package_id is None) != (package_version is None):
            raise ValueError("package identity requires package_id and package_version")
        if package_id is None and package_digest is not None:
            raise ValueError("package digest requires package identity")
        if package_digest is not None and (
            len(package_digest) != 64
            or any(char not in "0123456789abcdef" for char in package_digest.casefold())
        ):
            raise ValueError("package_digest must be SHA-256")
        compatibility = str(self.compatibility_digest).strip().casefold()
        if len(compatibility) != 64 or any(
            char not in "0123456789abcdef" for char in compatibility
        ):
            raise ValueError("compatibility_digest must be SHA-256")
        if not isinstance(self.manifest_risk_floor, RiskClass):
            raise TypeError("manifest_risk_floor must be RiskClass")
        authority_attributes = tuple(
            sorted(
                {
                    str(item).strip().casefold()
                    for item in self.manifest_authority_attributes
                }
            )
        )
        if any(not item for item in authority_attributes):
            raise ValueError("manifest authority attributes must be non-empty tokens")
        object.__setattr__(self, "capability_id", capability_id)
        object.__setattr__(self, "package_id", package_id)
        object.__setattr__(self, "package_version", package_version)
        object.__setattr__(
            self,
            "package_digest",
            None if package_digest is None else package_digest.casefold(),
        )
        object.__setattr__(self, "compatibility_digest", compatibility)
        object.__setattr__(
            self,
            "manifest_authority_attributes",
            authority_attributes,
        )


@dataclass(frozen=True, slots=True)
class AuthorizedCapabilityLifecycle:
    proposal: ActionProposal
    context: InteractionContext
    permit_id: str
    decision_id: str
    authority_ref: str
    risk_class: RiskClass
    verification_id: str | None = None


GateReader = Callable[[str], GateDecision | GateChallenge | None]


class CapabilityLifecycleAuthorityBridge:
    """Bind lifecycle state changes to the existing one-shot Authority service."""

    def __init__(
        self,
        *,
        approvals: ApprovalService,
        authority: AuthorityService,
        verifier: StrongVerifier,
        gate_reader: GateReader | None = None,
    ) -> None:
        self._approvals = approvals
        self._authority = authority
        self._verifier = verifier
        self._gate_reader = gate_reader
        self._risk_classifier = RiskClassifier()

    @staticmethod
    def _attributes(binding: CapabilityLifecycleProposalBinding) -> ActionAttributes:
        boolean_fields = {
            item.name for item in fields(ActionAttributes) if item.name != "scope"
        }
        unknown = set(binding.manifest_authority_attributes) - boolean_fields
        if unknown:
            raise CapabilityLifecycleAuthorizationError(
                "unknown manifest Authority attribute(s): "
                + ", ".join(sorted(unknown))
            )
        values = {name: False for name in boolean_fields}
        for name in binding.manifest_authority_attributes:
            values[name] = True
        values["persistent_write"] = True
        return ActionAttributes(
            **values,
            scope=ActionScope.SINGLE,
        )

    def _source_payload(
        self,
        binding: CapabilityLifecycleProposalBinding,
        *,
        authority_session_id: str,
    ) -> tuple[dict[str, object], ActionOrigin, bool]:
        source = binding.source
        if source.source_session_id != authority_session_id:
            raise CapabilityLifecycleAuthorizationError(
                "lifecycle source session does not match Authority session"
            )
        if source.source_turn_id is not None:
            return (
                {
                    "kind": "owner_turn",
                    "source_session_id": source.source_session_id,
                    "source_turn_id": source.source_turn_id,
                },
                ActionOrigin.DIRECT_USER,
                True,
            )

        gate_id = source.engineering_gate_id
        if gate_id is None or self._gate_reader is None:
            raise CapabilityLifecycleAuthorizationError(
                "engineering-gate lifecycle source cannot be verified"
            )
        resolved = self._gate_reader(gate_id)
        if not isinstance(resolved, GateDecision):
            raise CapabilityLifecycleAuthorizationError(
                "engineering gate is not an approved decision"
            )
        if not resolved.approved or resolved.actor_id != "owner":
            raise CapabilityLifecycleAuthorizationError(
                "engineering gate was not approved by the owner"
            )
        challenge = resolved.challenge
        return (
            {
                "kind": "engineering_gate",
                "gate_id": challenge.gate_id,
                "gate_kind": challenge.kind.value,
                "change_id": challenge.change_id,
                "artifact_id": challenge.artifact_id,
                "artifact_digest": challenge.artifact_digest,
                "decision_source_session_id": resolved.source_session_id,
                "decision_source_turn_id": resolved.source_turn_id,
                "decision_request_key": resolved.request_key,
            },
            ActionOrigin.SYSTEM,
            False,
        )

    def build_proposal(
        self,
        binding: CapabilityLifecycleProposalBinding,
        *,
        authority_session_id: str,
    ) -> tuple[ActionProposal, RiskClass, bool]:
        if not isinstance(binding, CapabilityLifecycleProposalBinding):
            raise TypeError("binding must be CapabilityLifecycleProposalBinding")
        session_id = str(authority_session_id).strip()
        if not session_id:
            raise ValueError("authority_session_id must not be empty")
        source_payload, origin, direct_owner_turn = self._source_payload(
            binding,
            authority_session_id=session_id,
        )
        attributes = self._attributes(binding)
        risk = self._risk_classifier.classify(attributes).risk_class
        if risk < RiskClass.PERSISTENT_OR_EXTERNAL:
            raise CapabilityLifecycleAuthorizationError(
                "lifecycle mutation risk is below persistent-system-change floor"
            )
        if risk < binding.manifest_risk_floor:
            raise CapabilityLifecycleAuthorizationError(
                "lifecycle mutation lowers the accepted manifest Authority floor"
            )
        if risk is RiskClass.RESTRICTED_DEV_ONLY:
            raise CapabilityLifecycleAuthorizationError(
                "restricted manifest Authority floor cannot be activated in production"
            )

        proposal = ActionProposal.create(
            session_id=session_id,
            capability="capability_registry_lifecycle",
            operation=binding.action.value,
            target={
                "capability_id": binding.capability_id,
                "package_id": binding.package_id,
                "package_version": binding.package_version,
            },
            parameters={
                "package_digest": binding.package_digest,
                "expected_generation": binding.expected_generation,
                "compatibility_digest": binding.compatibility_digest,
                "manifest_risk_floor": binding.manifest_risk_floor.name,
                "source": source_payload,
            },
            material_summary=(
                f"{binding.action.value} capability {binding.capability_id} "
                f"at registry generation {binding.expected_generation}; "
                f"package={binding.package_id or 'none'}@"
                f"{binding.package_version or 'none'}; compatibility SHA-256 "
                f"{binding.compatibility_digest}"
            ),
            attributes=attributes,
            origin=origin,
            ttl_seconds=120.0,
        )
        return proposal, risk, direct_owner_turn

    def authorize(
        self,
        binding: CapabilityLifecycleProposalBinding,
        *,
        authority_session_id: str,
    ) -> AuthorizedCapabilityLifecycle:
        proposal, risk, direct_owner_turn = self.build_proposal(
            binding,
            authority_session_id=authority_session_id,
        )
        verification_id: str | None = None
        if direct_owner_turn and risk is RiskClass.PERSISTENT_OR_EXTERNAL:
            try:
                pending = self._approvals.request(
                    proposal,
                    session_id=proposal.session_id,
                    requirement=ApprovalRequirement.EXPLICIT,
                    ttl_seconds=60.0,
                )
                approval = self._approvals.grant(
                    pending.approval_id,
                    proposal=proposal,
                    session_id=proposal.session_id,
                    method=ApprovalMethod.SPOKEN,
                )
            except ApprovalError as exc:
                raise CapabilityLifecycleAuthorizationError(str(exc)) from exc
            context = InteractionContext(
                session_id=proposal.session_id,
                trust_tier=TrustTier.CORROBORATED_OWNER,
                attention_state=AttentionState.ATTENTIVE,
                actor_unambiguous=True,
                windows_session_valid=True,
            )
        else:
            verification = self._verifier.verify(
                proposal=proposal,
                session_id=proposal.session_id,
            )
            if not verification.verified or not verification.is_bound_to(
                proposal=proposal,
                session_id=proposal.session_id,
            ):
                reasons = ",".join(verification.reason_codes) or "not_verified"
                raise CapabilityLifecycleAuthorizationError(
                    f"strong owner verification required: {reasons}"
                )
            verification_id = verification.verification_id
            try:
                pending = self._approvals.request(
                    proposal,
                    session_id=proposal.session_id,
                    requirement=ApprovalRequirement.STRONG,
                    ttl_seconds=60.0,
                )
                approval = self._approvals.grant_verified_strong(
                    pending.approval_id,
                    proposal=proposal,
                    session_id=proposal.session_id,
                    verification=verification,
                )
            except ApprovalError as exc:
                raise CapabilityLifecycleAuthorizationError(str(exc)) from exc
            context = InteractionContext(
                session_id=proposal.session_id,
                trust_tier=TrustTier.VERIFIED_OWNER,
                attention_state=AttentionState.ATTENTIVE,
                actor_unambiguous=True,
                windows_session_valid=True,
            )

        decision = self._authority.evaluate(
            proposal=proposal,
            context=context,
            approval_id=approval.approval_id,
        )
        if (
            decision.effect is not AuthorityEffect.ALLOW
            or decision.execution_permit is None
        ):
            reasons = ",".join(decision.reason_codes) or "authority_denied"
            raise CapabilityLifecycleAuthorizationError(
                f"Authority denied lifecycle mutation: {reasons}"
            )
        if decision.risk_class < binding.manifest_risk_floor:
            raise CapabilityLifecycleAuthorizationError(
                "Authority decision risk fell below manifest floor"
            )
        authority_ref = (
            f"authority:{decision.decision_id}:{proposal.fingerprint}"
        )
        return AuthorizedCapabilityLifecycle(
            proposal=proposal,
            context=context,
            permit_id=decision.execution_permit.permit_id,
            decision_id=decision.decision_id,
            authority_ref=authority_ref,
            risk_class=decision.risk_class,
            verification_id=verification_id,
        )

    def consume(self, authorized: AuthorizedCapabilityLifecycle) -> None:
        try:
            self._authority.revalidate_and_consume(
                permit_id=authorized.permit_id,
                proposal=authorized.proposal,
                context=authorized.context,
            )
        except AuthorityError as exc:
            raise CapabilityLifecycleAuthorizationError(str(exc)) from exc
