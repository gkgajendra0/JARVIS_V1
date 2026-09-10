"""Canonical Step-3 authority binding for governed capability execution."""

from __future__ import annotations

import os
import pathlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from jarvis.authority.approval import ApprovalError, ApprovalService
from jarvis.authority.audit import AuditEvent, SqliteAuditEventStore
from jarvis.authority.local_opa import LocalOpaError, ManagedOpaServer
from jarvis.authority.permit import PermitRegistry
from jarvis.authority.policy import OpaPolicyEngine
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityError, AuthorityService
from jarvis.authority.strong_approval import StrongApprovalService
from jarvis.authority.types import (
    ActionOrigin,
    ApprovalMethod,
    ApprovalRequirement,
    AttentionState,
    AuthorityEffect,
    InteractionContext,
    RiskClass,
    TrustTier,
)
from jarvis.authority.verifier import WindowsHelloVerifier
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import CapabilityResult

_TRUSTED_OWNER_TTL_SECONDS = 30.0 * 60.0
_PROPOSAL_APPROVAL_TTL_SECONDS = 120.0


class CapabilityAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthorizedCapability:
    proposal: ActionProposal
    context: InteractionContext
    permit_id: str


def _default_audit_path() -> pathlib.Path:
    configured = os.getenv("JARVIS_AUTHORITY_AUDIT_DB")
    if configured:
        return pathlib.Path(configured).expanduser()
    return pathlib.Path.home() / ".jarvis" / "authority" / "step7_audit.sqlite3"


class CapabilityAuthorityBroker:
    """Lazy canonical authority bridge with bounded owner-session trust.

    A successful direct-user strong verification establishes an in-memory T2 owner
    trust window for the same JARVIS session. Non-critical direct-user actions may
    reuse that trust while retaining fresh proposal-bound approval, permit, policy,
    and audit checks. Critical and restricted actions always require exact-action T3
    strong verification.
    """

    def __init__(
        self,
        *,
        trusted_session_ttl_seconds: float = _TRUSTED_OWNER_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if trusted_session_ttl_seconds <= 0:
            raise ValueError("trusted session ttl must be positive")
        self._lock = threading.RLock()
        self._opa: ManagedOpaServer | None = None
        self._authority: AuthorityService | None = None
        self._approvals: ApprovalService | None = None
        self._strong: StrongApprovalService | None = None
        self._audit: SqliteAuditEventStore | None = None
        self._risk_classifier = RiskClassifier()
        self._trusted_session_ttl_seconds = float(trusted_session_ttl_seconds)
        self._clock = clock
        self._trusted_sessions: dict[str, float] = {}

    def _ensure_started(self) -> None:
        with self._lock:
            if self._authority is not None:
                return
            audit_path = _default_audit_path()
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit = SqliteAuditEventStore(audit_path)
            opa = ManagedOpaServer()
            try:
                opa.start()
            except Exception:
                audit.close()
                raise
            approvals = ApprovalService()
            self._opa = opa
            self._audit = audit
            self._approvals = approvals
            self._strong = StrongApprovalService(
                approvals=approvals,
                verifier=WindowsHelloVerifier(),
            )
            self._authority = AuthorityService(
                risk_classifier=self._risk_classifier,
                policy_engine=OpaPolicyEngine(endpoint=opa.endpoint),
                approvals=approvals,
                audit_store=audit,
                permits=PermitRegistry(),
            )

    def _trusted_session_available(self, session_id: str) -> bool:
        with self._lock:
            expires_at = self._trusted_sessions.get(session_id)
            if expires_at is None:
                return False
            if self._clock() >= expires_at:
                self._trusted_sessions.pop(session_id, None)
                return False
            return True

    def _remember_trusted_session(self, session_id: str) -> None:
        with self._lock:
            self._trusted_sessions[session_id] = (
                self._clock() + self._trusted_session_ttl_seconds
            )

    def _grant_trusted_session_approval(
        self,
        *,
        proposal: ActionProposal,
        risk_class: RiskClass,
    ) -> str:
        approvals = self._approvals
        if approvals is None:
            raise CapabilityAuthorizationError("approval runtime is unavailable")

        if risk_class is RiskClass.PERSISTENT_OR_EXTERNAL:
            requirement = ApprovalRequirement.EXPLICIT
            # A direct-user command is the exact explicit instruction. SPOKEN is the
            # existing EXPLICIT-level method for direct voice/text owner commands.
            method = ApprovalMethod.SPOKEN
        else:
            requirement = ApprovalRequirement.DIRECT_INTENT
            method = ApprovalMethod.DIRECT_INTENT

        try:
            pending = approvals.request(
                proposal,
                session_id=proposal.session_id,
                requirement=requirement,
                ttl_seconds=_PROPOSAL_APPROVAL_TTL_SECONDS,
            )
            granted = approvals.grant(
                pending.approval_id,
                proposal=proposal,
                session_id=proposal.session_id,
                method=method,
            )
        except ApprovalError as exc:
            raise CapabilityAuthorizationError(str(exc)) from exc
        return granted.approval_id

    def authorize(self, prepared: PreparedCapability) -> AuthorizedCapability:
        try:
            self._ensure_started()
        except LocalOpaError as exc:
            raise CapabilityAuthorizationError(str(exc)) from exc
        except OSError as exc:
            raise CapabilityAuthorizationError(
                "authority audit store is unavailable"
            ) from exc
        authority = self._authority
        strong = self._strong
        if authority is None or strong is None:
            raise CapabilityAuthorizationError("authority runtime did not initialize")

        proposal = ActionProposal.create(
            session_id=prepared.request.session_id,
            capability=prepared.request.capability_key,
            operation=prepared.request.operation,
            target=prepared.target,
            parameters=prepared.parameters,
            material_summary=prepared.material_summary,
            attributes=prepared.attributes,
            origin=prepared.request.origin,
            ttl_seconds=_PROPOSAL_APPROVAL_TTL_SECONDS,
        )
        assessment = self._risk_classifier.classify(prepared.attributes)
        session_id = prepared.request.session_id
        direct_user = prepared.request.origin is ActionOrigin.DIRECT_USER
        can_reuse_owner_trust = (
            direct_user
            and RiskClass.ROUTINE < assessment.risk_class < RiskClass.CRITICAL
            and self._trusted_session_available(session_id)
        )

        approval_id: str | None = None
        used_strong_verification = False
        if assessment.risk_class is RiskClass.ROUTINE:
            context = InteractionContext(
                session_id=session_id,
                trust_tier=TrustTier.UNVERIFIED,
                windows_session_valid=True,
            )
        elif can_reuse_owner_trust:
            approval_id = self._grant_trusted_session_approval(
                proposal=proposal,
                risk_class=assessment.risk_class,
            )
            context = InteractionContext(
                session_id=session_id,
                trust_tier=TrustTier.CORROBORATED_OWNER,
                attention_state=AttentionState.ATTENTIVE,
                actor_unambiguous=True,
                windows_session_valid=True,
            )
        else:
            outcome = strong.verify_and_resolve(
                proposal=proposal,
                session_id=session_id,
            )
            if not outcome.granted:
                reasons = ",".join(outcome.verification.reason_codes) or "not_verified"
                raise CapabilityAuthorizationError(
                    f"strong owner verification was not granted: {reasons}"
                )
            approval_id = outcome.approval.approval_id
            used_strong_verification = True
            context = InteractionContext(
                session_id=session_id,
                trust_tier=TrustTier.VERIFIED_OWNER,
                attention_state=AttentionState.ATTENTIVE,
                actor_unambiguous=True,
                windows_session_valid=True,
            )

        decision = authority.evaluate(
            proposal=proposal,
            context=context,
            approval_id=approval_id,
        )
        if (
            decision.effect is not AuthorityEffect.ALLOW
            or decision.execution_permit is None
        ):
            reasons = ",".join(decision.reason_codes) or "authority_denied"
            raise CapabilityAuthorizationError(
                f"authority denied capability: {reasons}"
            )

        if used_strong_verification and direct_user:
            self._remember_trusted_session(session_id)

        return AuthorizedCapability(
            proposal=proposal,
            context=context,
            permit_id=decision.execution_permit.permit_id,
        )

    def consume(self, authorized: AuthorizedCapability) -> None:
        authority = self._authority
        if authority is None:
            raise CapabilityAuthorizationError("authority runtime is unavailable")
        try:
            authority.revalidate_and_consume(
                permit_id=authorized.permit_id,
                proposal=authorized.proposal,
                context=authorized.context,
            )
        except AuthorityError as exc:
            raise CapabilityAuthorizationError(str(exc)) from exc

    def audit_result(
        self,
        *,
        session_id: str,
        authorized: AuthorizedCapability,
        result: CapabilityResult,
    ) -> None:
        audit = self._audit
        if audit is None:
            return
        audit.append(
            AuditEvent.create(
                event_type="capability_execution_result",
                component="capability_runtime",
                session_id=session_id,
                proposal_id=authorized.proposal.proposal_id,
                proposal_fingerprint=authorized.proposal.fingerprint,
                reason_codes=((result.reason,) if result.reason else ()),
                metadata={
                    "capability": result.capability_key,
                    "operation": result.operation,
                    "status": result.status.value,
                    "elapsed_ms": round(result.elapsed_ms, 1),
                    "truncated": result.truncated,
                },
            )
        )

    def close(self) -> None:
        with self._lock:
            self._trusted_sessions.clear()
            if self._opa is not None:
                self._opa.close()
            if self._audit is not None:
                self._audit.close()
            self._opa = None
            self._audit = None
            self._authority = None
            self._approvals = None
            self._strong = None
