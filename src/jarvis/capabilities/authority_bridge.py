"""Canonical Step-3 authority binding for Step-7 capability execution."""

from __future__ import annotations

import os
import pathlib
import threading
from dataclasses import dataclass

from jarvis.authority.approval import ApprovalService
from jarvis.authority.audit import AuditEvent, SqliteAuditEventStore
from jarvis.authority.local_opa import LocalOpaError, ManagedOpaServer
from jarvis.authority.permit import PermitRegistry
from jarvis.authority.policy import OpaPolicyEngine
from jarvis.authority.proposal import ActionProposal
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityError, AuthorityService
from jarvis.authority.strong_approval import StrongApprovalService
from jarvis.authority.types import (
    AttentionState,
    AuthorityEffect,
    InteractionContext,
    TrustTier,
)
from jarvis.authority.verifier import WindowsHelloVerifier
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import CapabilityResult


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
    """Lazy OPA + Windows Hello bridge using the canonical AuthorityService."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._opa: ManagedOpaServer | None = None
        self._authority: AuthorityService | None = None
        self._approvals: ApprovalService | None = None
        self._strong: StrongApprovalService | None = None
        self._audit: SqliteAuditEventStore | None = None

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
                risk_classifier=RiskClassifier(),
                policy_engine=OpaPolicyEngine(endpoint=opa.endpoint),
                approvals=approvals,
                audit_store=audit,
                permits=PermitRegistry(),
            )

    def authorize(self, prepared: PreparedCapability) -> AuthorizedCapability:
        try:
            self._ensure_started()
        except LocalOpaError as exc:
            raise CapabilityAuthorizationError(str(exc)) from exc
        except OSError as exc:
            raise CapabilityAuthorizationError("authority audit store is unavailable") from exc
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
            ttl_seconds=120.0,
        )
        approval_id: str | None = None
        if prepared.attributes.private_read:
            outcome = strong.verify_and_resolve(
                proposal=proposal,
                session_id=prepared.request.session_id,
            )
            if not outcome.granted:
                reasons = ",".join(outcome.verification.reason_codes) or "not_verified"
                raise CapabilityAuthorizationError(
                    f"strong owner verification was not granted: {reasons}"
                )
            approval_id = outcome.approval.approval_id
            context = InteractionContext(
                session_id=prepared.request.session_id,
                trust_tier=TrustTier.VERIFIED_OWNER,
                attention_state=AttentionState.ATTENTIVE,
                actor_unambiguous=True,
                windows_session_valid=True,
            )
        else:
            context = InteractionContext(
                session_id=prepared.request.session_id,
                trust_tier=TrustTier.UNVERIFIED,
                windows_session_valid=True,
            )
        decision = authority.evaluate(
            proposal=proposal,
            context=context,
            approval_id=approval_id,
        )
        if decision.effect is not AuthorityEffect.ALLOW or decision.execution_permit is None:
            reasons = ",".join(decision.reason_codes) or "authority_denied"
            raise CapabilityAuthorizationError(f"authority denied capability: {reasons}")
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
            if self._opa is not None:
                self._opa.close()
            if self._audit is not None:
                self._audit.close()
            self._opa = None
            self._audit = None
            self._authority = None
            self._approvals = None
            self._strong = None
