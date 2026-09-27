"""Single-verification bridge from promotion gate to one-shot execution Authority."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.authority.approval import ApprovalService
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.service import AuthorityService
from jarvis.authority.types import (
    ActionAttributes,
    ActionOrigin,
    ActionScope,
    ApprovalRequirement,
    AttentionState,
    AuthorityEffect,
    InteractionContext,
    TrustTier,
)
from jarvis.authority.verifier import StrongVerifier
from jarvis.engineering_change.gates import (
    GateChallenge,
    GateDecision,
    GateKind,
    GateService,
)
from jarvis.engineering_change.models import ChangeConflict
from jarvis.engineering_change.store import ChangeStore

from .models import PromotionAttempt, PromotionAttemptState, PromotionEvidenceV1
from .store import PromotionStore


class PromotionAuthorizationError(ChangeConflict):
    pass


@dataclass(frozen=True, slots=True)
class AuthorizedPromotion:
    gate_decision: GateDecision
    proposal: ActionProposal
    context: InteractionContext
    permit_id: str
    evidence_digest: str
    attempt_id: str


class PromotionAuthorityBridge:
    """Use one exact strong owner verification for gate + execution permit."""

    def __init__(
        self,
        changes: ChangeStore,
        promotions: PromotionStore,
        *,
        approvals: ApprovalService,
        authority: AuthorityService,
        verifier: StrongVerifier,
    ) -> None:
        if promotions.changes is not changes:
            raise ValueError("promotion store must share the canonical ChangeStore")
        self._changes = changes
        self._promotions = promotions
        self._approvals = approvals
        self._authority = authority
        self._verifier = verifier

    @staticmethod
    def _challenge(
        gate: GateChallenge | GateDecision | None,
    ) -> tuple[GateChallenge, GateDecision | None]:
        if gate is None:
            raise PromotionAuthorizationError("unknown promotion gate")
        if isinstance(gate, GateDecision):
            return gate.challenge, gate
        return gate, None

    @staticmethod
    def _proposal(
        *,
        challenge: GateChallenge,
        evidence: PromotionEvidenceV1,
        session_id: str,
        repository_full_name: str,
    ) -> ActionProposal:
        return ActionProposal.create(
            session_id=session_id,
            capability="engineering_promotion",
            operation="merge_and_deploy",
            target={
                "repository": repository_full_name,
                "change_id": evidence.change_id,
                "gate_id": challenge.gate_id,
                "pr_number": evidence.pr_number,
            },
            parameters={
                "promotion_artifact_id": challenge.artifact_id,
                "promotion_artifact_digest": challenge.artifact_digest,
                "evidence_id": evidence.evidence_id,
                "evidence_digest": evidence.digest,
                "candidate_base_sha": evidence.candidate_base_sha,
                "candidate_head_sha": evidence.candidate_head_sha,
                "tested_merge_sha": evidence.tested_merge_sha,
                "deployment_environment": evidence.deployment_environment,
                "lkg_release_sha": evidence.lkg_release_sha,
            },
            material_summary=(
                f"Promote EngineeringChange {evidence.change_id}, PR "
                f"#{evidence.pr_number}, exact candidate "
                f"{evidence.candidate_head_sha}, evidence SHA-256 "
                f"{evidence.digest}, then deploy to "
                f"{evidence.deployment_environment}"
            ),
            attributes=ActionAttributes(
                persistent_write=True,
                external_side_effect=True,
                executable_or_system_change=True,
                scope=ActionScope.SINGLE,
            ),
            origin=ActionOrigin.DIRECT_USER,
            ttl_seconds=120.0,
        )

    def authorize(
        self,
        *,
        gate_id: str,
        evidence: PromotionEvidenceV1,
        attempt: PromotionAttempt,
        session_id: str,
        source_turn_id: str,
        request_key: str,
        repository_full_name: str,
    ) -> AuthorizedPromotion:
        if attempt.state not in {
            PromotionAttemptState.EVIDENCE_READY,
            PromotionAttemptState.AUTHORIZED,
        }:
            raise PromotionAuthorizationError(
                "promotion attempt is not ready for authorization"
            )
        if attempt.change_id != evidence.change_id:
            raise PromotionAuthorizationError(
                "promotion attempt and evidence change do not match"
            )
        if (
            attempt.promotion_artifact_id is None
            or attempt.promotion_artifact_digest is None
        ):
            raise PromotionAuthorizationError(
                "promotion attempt has no persisted evidence artifact"
            )

        reader = GateService(self._changes, verify_owner=lambda *_: False)
        challenge, existing = self._challenge(reader.get(gate_id))
        if challenge.kind is not GateKind.PROMOTION:
            raise PromotionAuthorizationError("gate is not a promotion gate")
        if challenge.change_id != evidence.change_id:
            raise PromotionAuthorizationError("gate belongs to a different change")
        if (
            challenge.artifact_id != attempt.promotion_artifact_id
            or challenge.artifact_digest != attempt.promotion_artifact_digest
        ):
            raise PromotionAuthorizationError(
                "gate is not bound to the promotion attempt evidence"
            )
        artifact = self._changes.get_artifact(challenge.artifact_id)
        if (
            artifact is None
            or artifact.payload.get("evidence_id") != evidence.evidence_id
            or artifact.payload.get("digest") != evidence.digest
        ):
            raise PromotionAuthorizationError(
                "promotion artifact does not contain the exact evidence"
            )

        proposal = self._proposal(
            challenge=challenge,
            evidence=evidence,
            session_id=session_id,
            repository_full_name=repository_full_name,
        )
        verification = self._verifier.verify(
            proposal=proposal,
            session_id=session_id,
        )
        if not verification.verified or not verification.is_bound_to(
            proposal=proposal,
            session_id=session_id,
        ):
            reasons = ",".join(verification.reason_codes) or "not_verified"
            raise PromotionAuthorizationError(
                f"strong owner verification required: {reasons}"
            )

        if existing is None:
            trusted = GateService(
                self._changes,
                verify_owner=lambda actor, source_session, source_turn, gate, digest: (
                    actor == "owner"
                    and source_session == session_id
                    and source_turn == source_turn_id
                    and gate.gate_id == gate_id
                    and digest == challenge.artifact_digest
                    and verification.is_bound_to(
                        proposal=proposal,
                        session_id=session_id,
                    )
                ),
            )
            gate_decision = trusted.decide(
                gate_id,
                approved=True,
                artifact_digest=challenge.artifact_digest,
                actor_id="owner",
                source_session_id=session_id,
                source_turn_id=source_turn_id,
                request_key=request_key,
                verification_id=verification.verification_id,
                verifier_id=verification.verifier_id,
                proposal_fingerprint=proposal.fingerprint,
            )
        else:
            if not existing.approved:
                raise PromotionAuthorizationError("promotion gate was rejected")
            gate_decision = existing

        pending = self._approvals.request(
            proposal,
            session_id=session_id,
            requirement=ApprovalRequirement.STRONG,
            ttl_seconds=60.0,
        )
        granted = self._approvals.grant_verified_strong(
            pending.approval_id,
            proposal=proposal,
            session_id=session_id,
            verification=verification,
        )
        context = InteractionContext(
            session_id=session_id,
            trust_tier=TrustTier.VERIFIED_OWNER,
            attention_state=AttentionState.ATTENTIVE,
            actor_unambiguous=True,
            windows_session_valid=True,
        )
        decision = self._authority.evaluate(
            proposal=proposal,
            context=context,
            approval_id=granted.approval_id,
        )
        if (
            decision.effect is not AuthorityEffect.ALLOW
            or decision.execution_permit is None
        ):
            reasons = ",".join(decision.reason_codes) or "authority_denied"
            raise PromotionAuthorizationError(
                f"Authority denied promotion execution: {reasons}"
            )

        if attempt.state is PromotionAttemptState.EVIDENCE_READY:
            attempt = self._promotions.transition(
                attempt.attempt_id,
                PromotionAttemptState.AUTHORIZED,
                expected_version=attempt.version,
                reason=(
                    "exact promotion gate approved and one-shot Authority permit issued"
                ),
            )
        return AuthorizedPromotion(
            gate_decision=gate_decision,
            proposal=proposal,
            context=context,
            permit_id=decision.execution_permit.permit_id,
            evidence_digest=evidence.digest,
            attempt_id=attempt.attempt_id,
        )

    def consume(self, authorized: AuthorizedPromotion) -> None:
        self._authority.revalidate_and_consume(
            permit_id=authorized.permit_id,
            proposal=authorized.proposal,
            context=authorized.context,
        )
