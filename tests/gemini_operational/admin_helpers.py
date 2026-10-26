from types import SimpleNamespace

from tests.test_hands_authority import MutableWindowsSessionProvider

from jarvis.authority.approval import ApprovalService
from jarvis.authority.audit import InMemoryAuditEventStore
from jarvis.authority.permit import PermitRegistry
from jarvis.authority.policy import PolicyDecision, hard_floor_for
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityService
from jarvis.authority.strong_approval import StrongApprovalService
from jarvis.authority.types import AuthorityEffect
from jarvis.authority.verifier import StrongVerificationResult, StrongVerificationStatus
from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker
from jarvis.model_routing.live_policy import (
    LiveReconciliationEvidence,
    LiveUsageReport,
    digest,
)

from .test_governor import checkpoint, finish, observe, reserve


class Verifier:
    def __init__(self):
        self.allowed = True
        self.sequence = 0

    def verify(self, *, proposal, session_id):
        self.sequence += 1
        return StrongVerificationResult(
            status=StrongVerificationStatus.VERIFIED
            if self.allowed
            else StrongVerificationStatus.FAILED,
            verifier_id="offline-boundary",
            verification_id="offline-verification-" + str(self.sequence),
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
        )


def broker():
    b = CapabilityAuthorityBroker(session_provider=MutableWindowsSessionProvider())
    approvals = ApprovalService()
    audit = InMemoryAuditEventStore()
    v = Verifier()
    policy = SimpleNamespace(
        evaluate=lambda request: PolicyDecision(
            effect=AuthorityEffect.ALLOW,
            requirements=hard_floor_for(request.risk_class),
            reason_codes=(),
            policy_version="offline-floor",
        )
    )
    b._authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=policy,
        approvals=approvals,
        audit_store=audit,
        permits=PermitRegistry(),
    )
    b._strong = StrongApprovalService(approvals=approvals, verifier=v)
    b._approvals = approvals
    b._audit = audit
    return b, v


def evidence_for(env, r):
    with env.store.work_store.extension_transaction() as c:
        events = c.execute(
            "SELECT * FROM paid_fallback_usage_events WHERE reservation_id=? ORDER BY event_id",
            (r.reservation_id,),
        ).fetchall()
    values = [
        env.store.work_store.decode_extension_json(e["event_json"]) for e in events
    ]
    reports = tuple(
        LiveUsageReport(**e["report"])
        for e in values
        if e.get("kind") == "operational_usage"
    )
    return LiveReconciliationEvidence(
        r.reservation_id,
        env.target.target_id,
        env.policy.fingerprint,
        env.profile.fingerprint,
        digest(env.price.to_payload()),
        reports,
        digest(
            [
                e["event_digest"]
                for e, v in zip(events, values, strict=True)
                if v.get("kind") in {"operational_usage", "operational_close"}
            ]
        ),
    )


def unknown_complete(env):
    r = reserve(env)
    checkpoint(env, r)
    observe(env, r, tokens=85000)
    finish(env, r, complete=False)
    return r, evidence_for(env, r)
