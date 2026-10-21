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


import sqlite3

import pytest
import pytest_asyncio

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningCatalog,
    LearningResolution,
    LearningResolutionBatch,
)
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.service import MemoryService
from jarvis.memory.worker import SerialConnectionWorker


@pytest_asyncio.fixture
async def learning(tmp_path, authority):
    path = tmp_path / "fictional.db"

    def connect():
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys=ON")
        MemoryMigrationRunner().apply(connection)
        return connection

    writer = SerialConnectionWorker(connect, thread_name="learning-test-writer")
    reader = SerialConnectionWorker(connect, thread_name="learning-test-reader")
    await writer.start()
    await reader.start()
    lifecycle = MemoryLifecycleService(writer)
    service = MemoryService(lifecycle, CanonicalMemoryReader(reader))
    grant = authority.open("runtime", "gemini")
    service.bind_learning_authority(authority)
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "I own a City")
    source = AcceptedLearningSource.from_turn("runtime", conversation, turn, now=100)
    authority.register_source(grant, source.receipt_id, source=source)
    candidate = LearningCandidate(
        category="owned_item",
        kind="vehicle",
        intent="new",
        label="City",
        value="City",
        state="owned",
        evidence=[EvidenceSpan(turn_id=turn.turn_id, start=8, end=12)],
    )
    plan = LearningReconciler(None, None).plan(
        source,
        LearningBatch(candidates=[candidate]),
        LearningCatalog(),
        LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        ),
    )

    async def count(table="semantic_assertion"):
        assert table in {
            "semantic_assertion",
            "personal_learning_receipt",
            "memory_source",
        }
        return await reader.run(
            lambda c: c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        )

    h = SimpleNamespace(
        service=service,
        lifecycle=lifecycle,
        writer=writer,
        reader=reader,
        authority=authority,
        grant=grant,
        plan=plan,
        candidate=candidate,
        source=source,
        count=count,
        path=path,
    )
    h.new_permit = lambda plan=plan: authority.issue_child(grant, plan.binding())
    h.canonical_effect_count = count
    try:
        yield h
    finally:
        await reader.close()
        await writer.close()
