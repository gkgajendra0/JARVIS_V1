from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable

from .approval import ApprovalError, ApprovalRecord, ApprovalService
from .audit import AuditError, AuditEvent, AuditEventStore
from .permit import ExecutionPermit, PermitRegistry, PermitStatus
from .policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyInput,
    PolicyRequirements,
    combine_requirements,
    hard_floor_for,
)
from .proposal import ActionProposal
from .risk import RiskAssessment, RiskClassifier
from .types import (
    ActionOrigin,
    ApprovalMethod,
    ApprovalRequirement,
    AttentionState,
    AuthorityEffect,
    InteractionContext,
    RiskClass,
)


class AuthorityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    decision_id: str
    effect: AuthorityEffect
    proposal_id: str
    proposal_fingerprint: str
    session_id: str
    risk_class: RiskClass
    requirements: PolicyRequirements
    policy_version: str
    reason_codes: tuple[str, ...]
    approval_id: str | None = None
    execution_permit: ExecutionPermit | None = None


@dataclass(frozen=True, slots=True)
class _Assessment:
    risk: RiskAssessment
    policy: PolicyDecision
    requirements: PolicyRequirements
    approval: ApprovalRecord | None


class AuthorityService:
    def __init__(
        self,
        *,
        risk_classifier: RiskClassifier,
        policy_engine: PolicyEngine,
        approvals: ApprovalService,
        audit_store: AuditEventStore,
        permits: PermitRegistry,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._risk_classifier = risk_classifier
        self._policy_engine = policy_engine
        self._approvals = approvals
        self._audit_store = audit_store
        self._permits = permits
        self._clock = clock

    def evaluate(
        self,
        *,
        proposal: ActionProposal,
        context: InteractionContext,
        approval_id: str | None = None,
    ) -> AuthorityDecision:
        decision_id = str(uuid.uuid4())
        initial_risk = self._risk_classifier.classify(
            proposal.attributes
        ).risk_class
        try:
            assessment = self._assess(
                proposal=proposal,
                context=context,
                approval_id=approval_id,
            )
        except AuthorityError as exc:
            return self._deny(
                decision_id=decision_id,
                proposal=proposal,
                context=context,
                reason=str(exc),
                risk_class=initial_risk,
            )

        if assessment.requirements.audit_required:
            try:
                self._audit_store.append(
                    self._event(
                        event_type="authority_allow",
                        decision_id=decision_id,
                        proposal=proposal,
                        context=context,
                        assessment=assessment,
                    )
                )
            except AuditError:
                return self._deny(
                    decision_id=decision_id,
                    proposal=proposal,
                    context=context,
                    reason="audit_unavailable",
                    risk_class=assessment.risk.risk_class,
                    requirements=assessment.requirements,
                    policy_version=assessment.policy.policy_version,
                )

        try:
            permit = self._permits.issue(
                decision_id=decision_id,
                proposal_id=proposal.proposal_id,
                proposal_fingerprint=proposal.fingerprint,
                session_id=context.session_id,
                approval_id=(
                    assessment.approval.approval_id
                    if assessment.approval is not None
                    else None
                ),
                risk_class=assessment.risk.risk_class,
                policy_version=assessment.policy.policy_version,
                proposal_expires_at=proposal.expires_at_monotonic,
            )
        except ValueError:
            return self._deny(
                decision_id=decision_id,
                proposal=proposal,
                context=context,
                reason="proposal_expired_before_permit",
                risk_class=assessment.risk.risk_class,
                requirements=assessment.requirements,
                policy_version=assessment.policy.policy_version,
            )
        return AuthorityDecision(
            decision_id=decision_id,
            effect=AuthorityEffect.ALLOW,
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint,
            session_id=context.session_id,
            risk_class=assessment.risk.risk_class,
            requirements=assessment.requirements,
            policy_version=assessment.policy.policy_version,
            reason_codes=assessment.policy.reason_codes,
            approval_id=(
                assessment.approval.approval_id
                if assessment.approval is not None
                else None
            ),
            execution_permit=permit,
        )

    def revalidate_and_consume(
        self,
        *,
        permit_id: str,
        proposal: ActionProposal,
        context: InteractionContext,
    ) -> ExecutionPermit:
        with self._permits.lock:
            permit = self._permits.get_locked(permit_id)
            if permit.status is not PermitStatus.PENDING:
                raise AuthorityError(
                    f"execution permit is {permit.status.value}"
                )
            try:
                self._assert_permit_binding(
                    permit=permit,
                    proposal=proposal,
                    context=context,
                )
                assessment = self._assess(
                    proposal=proposal,
                    context=context,
                    approval_id=permit.approval_id,
                )
                if assessment.risk.risk_class is not permit.risk_class:
                    raise AuthorityError("risk_changed_after_authorization")
                if assessment.policy.policy_version != permit.policy_version:
                    raise AuthorityError("policy_changed_after_authorization")
                if assessment.requirements.audit_required:
                    self._audit_store.append(
                        self._event(
                            event_type="pre_execution_authorized",
                            decision_id=permit.decision_id,
                            proposal=proposal,
                            context=context,
                            assessment=assessment,
                        )
                    )
                if assessment.approval is not None:
                    self._approvals.consume(
                        assessment.approval.approval_id,
                        proposal=proposal,
                        session_id=context.session_id,
                        minimum_requirement=(
                            assessment.requirements.approval_requirement
                        ),
                    )
            except (ApprovalError, AuditError, AuthorityError) as exc:
                self._permits.set_status_locked(
                    permit,
                    PermitStatus.INVALIDATED,
                )
                if isinstance(exc, AuthorityError):
                    raise
                if isinstance(exc, AuditError):
                    raise AuthorityError("audit_unavailable") from exc
                raise AuthorityError("approval_invalid_at_execution") from exc

            return self._permits.set_status_locked(
                permit,
                PermitStatus.CONSUMED,
            )

    def invalidate_session(self, session_id: str) -> None:
        self._approvals.invalidate_session(session_id)
        self._permits.invalidate_session(session_id)

    def _assess(
        self,
        *,
        proposal: ActionProposal,
        context: InteractionContext,
        approval_id: str | None,
    ) -> _Assessment:
        if proposal.session_id != context.session_id:
            raise AuthorityError("proposal_session_mismatch")
        if not proposal.has_valid_fingerprint():
            raise AuthorityError("proposal_integrity_invalid")
        if proposal.is_expired(self._clock()):
            raise AuthorityError("proposal_expired")
        if not context.windows_session_valid:
            raise AuthorityError("windows_session_invalid")

        risk = self._risk_classifier.classify(proposal.attributes)
        if risk.risk_class is RiskClass.RESTRICTED_DEV_ONLY:
            raise AuthorityError("restricted_dev_only")

        approval: ApprovalRecord | None = None
        if approval_id is not None:
            try:
                approval = self._approvals.validate(
                    approval_id,
                    proposal=proposal,
                    session_id=context.session_id,
                    minimum_requirement=ApprovalRequirement.DIRECT_INTENT,
                )
            except ApprovalError as exc:
                raise AuthorityError("approval_invalid") from exc

        try:
            policy = self._policy_engine.evaluate(
                PolicyInput(
                    proposal=proposal,
                    risk_class=risk.risk_class,
                    context=context,
                    approval=approval,
                )
            )
        except Exception as exc:
            raise AuthorityError("policy_engine_exception") from exc
        if policy.effect is AuthorityEffect.DENY:
            reason = (
                policy.reason_codes[0]
                if policy.reason_codes
                else "policy_denied"
            )
            raise AuthorityError(reason)

        requirements = combine_requirements(
            hard_floor_for(risk.risk_class),
            policy.requirements,
        )
        if context.trust_tier < requirements.required_trust:
            raise AuthorityError("insufficient_trust")
        if (
            requirements.require_owner_attentive
            and not context.owner_attentive
        ):
            raise AuthorityError("owner_attention_required")
        if (
            requirements.require_actor_unambiguous
            and not context.actor_unambiguous
        ):
            raise AuthorityError("actor_ambiguous")

        if requirements.approval_requirement is not ApprovalRequirement.NONE:
            if approval is None:
                raise AuthorityError("approval_required")
            try:
                approval = self._approvals.validate(
                    approval.approval_id,
                    proposal=proposal,
                    session_id=context.session_id,
                    minimum_requirement=requirements.approval_requirement,
                )
            except ApprovalError as exc:
                raise AuthorityError("approval_too_weak") from exc
            self._validate_approval_semantics(
                proposal=proposal,
                context=context,
                approval=approval,
            )
        return _Assessment(
            risk=risk,
            policy=policy,
            requirements=requirements,
            approval=approval,
        )

    @staticmethod
    def _validate_approval_semantics(
        *,
        proposal: ActionProposal,
        context: InteractionContext,
        approval: ApprovalRecord,
    ) -> None:
        if approval.method is ApprovalMethod.DIRECT_INTENT:
            if proposal.origin is not ActionOrigin.DIRECT_USER:
                raise AuthorityError("direct_intent_origin_mismatch")
        if approval.method is ApprovalMethod.SPOKEN:
            if context.attention_state is not AttentionState.ATTENTIVE:
                raise AuthorityError("spoken_approval_requires_attention")
            if not context.actor_unambiguous:
                raise AuthorityError(
                    "spoken_approval_requires_actor_binding"
                )

    def _assert_permit_binding(
        self,
        *,
        permit: ExecutionPermit,
        proposal: ActionProposal,
        context: InteractionContext,
    ) -> None:
        if not proposal.has_valid_fingerprint():
            raise AuthorityError("proposal_integrity_invalid")
        if permit.session_id != context.session_id:
            raise AuthorityError("permit_session_mismatch")
        if proposal.session_id != context.session_id:
            raise AuthorityError("proposal_session_mismatch")
        if permit.proposal_id != proposal.proposal_id:
            raise AuthorityError("permit_proposal_id_mismatch")
        if permit.proposal_fingerprint != proposal.fingerprint:
            raise AuthorityError("permit_proposal_fingerprint_mismatch")
        if proposal.is_expired(self._clock()):
            raise AuthorityError("proposal_expired")

    def _deny(
        self,
        *,
        decision_id: str,
        proposal: ActionProposal,
        context: InteractionContext,
        reason: str,
        risk_class: RiskClass = RiskClass.RESTRICTED_DEV_ONLY,
        requirements: PolicyRequirements | None = None,
        policy_version: str = "jarvis:pre-policy",
    ) -> AuthorityDecision:
        safe_requirements = requirements or hard_floor_for(risk_class)
        try:
            self._audit_store.append(
                AuditEvent.create(
                    event_type="authority_deny",
                    component="authority_service",
                    session_id=context.session_id,
                    proposal_id=proposal.proposal_id,
                    proposal_fingerprint=proposal.fingerprint,
                    reason_codes=(reason,),
                    metadata={
                        "decision_id": decision_id,
                        "risk_class": risk_class.name,
                        "policy_version": policy_version,
                    },
                )
            )
        except AuditError:
            pass
        return AuthorityDecision(
            decision_id=decision_id,
            effect=AuthorityEffect.DENY,
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint,
            session_id=context.session_id,
            risk_class=risk_class,
            requirements=safe_requirements,
            policy_version=policy_version,
            reason_codes=(reason,),
        )

    @staticmethod
    def _event(
        *,
        event_type: str,
        decision_id: str,
        proposal: ActionProposal,
        context: InteractionContext,
        assessment: _Assessment,
    ) -> AuditEvent:
        return AuditEvent.create(
            event_type=event_type,
            component="authority_service",
            session_id=context.session_id,
            proposal_id=proposal.proposal_id,
            proposal_fingerprint=proposal.fingerprint,
            reason_codes=assessment.policy.reason_codes,
            metadata={
                "decision_id": decision_id,
                "risk_class": assessment.risk.risk_class.name,
                "policy_version": assessment.policy.policy_version,
                "approval_requirement": (
                    assessment.requirements.approval_requirement.name
                ),
                "trust_tier": context.trust_tier.name,
            },
        )
