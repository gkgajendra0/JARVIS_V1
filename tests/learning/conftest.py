"""Fictional inputs and real canonical authority, with fake OS/Hello only."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jarvis.authority.approval import ApprovalService
from jarvis.authority.audit import InMemoryAuditEventStore
from jarvis.authority.permit import PermitRegistry
from jarvis.authority.policy import PolicyDecision, hard_floor_for
from jarvis.authority.risk import RiskClassifier
from jarvis.authority.service import AuthorityService
from jarvis.authority.session import AuthoritySession
from jarvis.authority.strong_approval import StrongApprovalService
from jarvis.authority.types import ApprovalRequirement, AuthorityEffect
from jarvis.authority.verifier import StrongVerificationResult, StrongVerificationStatus
from jarvis.capabilities.authority_bridge import CapabilityAuthorityBroker


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Windows:
    def __init__(self):
        self.value = AuthoritySession("wts:1", 1, "fictional-owner", True, 0, 100)

    def current_session(self):
        return self.value

    def lock_unlock(self):
        self.value = replace(self.value, generation=self.value.generation + 2)


class Hello:
    def __init__(self):
        self.calls = []
        self.denied = False

    def verify(self, *, proposal, session_id):
        self.calls.append(proposal)
        return StrongVerificationResult(
            StrongVerificationStatus.CANCELED
            if self.denied
            else StrongVerificationStatus.VERIFIED,
            "fake-hello",
            str(uuid4()),
            proposal.fingerprint,
            session_id,
        )


class Policy:
    def evaluate(self, policy_input):
        requirements = hard_floor_for(policy_input.risk_class)
        if policy_input.proposal.operation in {"admit", "read"}:
            requirements = replace(
                requirements, approval_requirement=ApprovalRequirement.EXPLICIT
            )
        return PolicyDecision(AuthorityEffect.ALLOW, requirements, (), "test-policy")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def authority_parts(clock):
    windows, hello = Windows(), Hello()
    approvals = ApprovalService(clock=clock)
    broker = CapabilityAuthorityBroker(clock=clock, session_provider=windows)
    broker._approvals = approvals
    broker._audit = InMemoryAuditEventStore()
    broker._strong = StrongApprovalService(approvals=approvals, verifier=hello)
    broker._authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=Policy(),
        approvals=approvals,
        audit_store=broker._audit,
        permits=PermitRegistry(clock=clock),
        clock=clock,
    )
    return SimpleNamespace(
        broker=broker, windows=windows, hello=hello, approvals=approvals
    )


@pytest.fixture
def authority(authority_parts):
    from jarvis.authority.personal_learning import PersonalLearningAuthority

    return PersonalLearningAuthority(authority_parts.broker)
