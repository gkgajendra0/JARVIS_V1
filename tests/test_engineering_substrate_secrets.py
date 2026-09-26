from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path

import pytest

from jarvis.authority import (
    ActionOrigin,
    ApprovalRequirement,
    ApprovalService,
    AuthorityEffect,
    AuthorityService,
    InMemoryAuditEventStore,
    InteractionContext,
    PermitRegistry,
    PolicyDecision,
    PolicyInput,
    PolicyRequirements,
    RiskClass,
    RiskClassifier,
    StrongVerificationResult,
    StrongVerificationStatus,
    TrustTier,
)
from jarvis.authority.types import AuthorityEffect as Effect
from jarvis.engineering_substrate import (
    CanonicalAuthoritySecretGate,
    SecretAuthorizationError,
    SecretBroker,
    SecretConsumerPolicy,
    SecretConsumerRegistry,
    SecretIntegrityError,
    SecretLeaseError,
    SecretLeaseRequest,
    SecretLifecycleState,
    SecretRedactor,
    SecretStore,
    build_secret_lease_proposal,
)
from jarvis.engineering_substrate.secrets.cli import main as secret_cli_main
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.models import WorkItem, WorkType
from jarvis.work.store import SQLiteWorkStore
from jarvis.security import KeyProtectionError

SECRET_VALUE = b"phase5e-disposable-test-value"


class FakeProtector:
    protector_id = "fake-test-protector-v1"

    @staticmethod
    def _key(purpose: str) -> bytes:
        return hashlib.sha256(purpose.encode("utf-8")).digest()

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes:
        key = self._key(purpose)
        encrypted = bytes(
            value ^ key[index % len(key)] for index, value in enumerate(plaintext)
        )
        tag = hmac.new(key, plaintext, hashlib.sha256).digest()
        return b"F1" + tag + encrypted

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
        if not sealed.startswith(b"F1") or len(sealed) < 34:
            raise KeyProtectionError("fake sealed value is malformed")
        key = self._key(purpose)
        tag = sealed[2:34]
        encrypted = sealed[34:]
        plaintext = bytes(
            value ^ key[index % len(key)] for index, value in enumerate(encrypted)
        )
        if not hmac.compare_digest(
            tag,
            hmac.new(key, plaintext, hashlib.sha256).digest(),
        ):
            raise KeyProtectionError("fake sealed value integrity mismatch")
        return plaintext


def _store(tmp_path: Path) -> SecretStore:
    return SecretStore(
        tmp_path / "secrets.sqlite",
        protector=FakeProtector(),
        clock=lambda: 1_000.0,
    )


def _enroll(store: SecretStore, *, value: bytes = SECRET_VALUE):
    return store.enroll(
        secret_id="secret-demo",
        kind="api-token",
        service="example",
        allowed_consumers=("dependency.private-index.v1",),
        allowed_scopes=("repository.read",),
        value=value,
    )


def test_secret_store_persists_only_sealed_value_and_metadata(tmp_path: Path) -> None:
    store = _store(tmp_path)
    descriptor = _enroll(store)

    material = store.materialize(descriptor.secret_id)
    assert material.value == SECRET_VALUE
    assert material.descriptor == descriptor
    assert SECRET_VALUE.decode() not in repr(material)

    database_bytes = store.path.read_bytes()
    assert SECRET_VALUE not in database_bytes
    assert b"secret-demo" in database_bytes
    assert b"repository.read" in database_bytes


def test_secret_redactor_scrubs_text_bytes_and_repr() -> None:
    redactor = SecretRedactor.from_values(
        (SECRET_VALUE, SECRET_VALUE.decode()),
    )

    assert SECRET_VALUE.decode() not in repr(redactor)
    assert redactor.redact_text(
        "prefix " + SECRET_VALUE.decode() + " suffix"
    ) == "prefix [REDACTED_SECRET] suffix"
    assert redactor.redact_bytes(
        b"prefix " + SECRET_VALUE + b" suffix"
    ) == b"prefix [REDACTED_SECRET] suffix"

    redactor.clear()
    assert redactor.redact_text(SECRET_VALUE.decode()) == SECRET_VALUE.decode()


def test_work_and_engineering_change_metadata_never_persist_plaintext_secret(
    tmp_path: Path,
) -> None:
    work_path = tmp_path / "work.sqlite3"
    work_store = SQLiteWorkStore(work_path)
    item = WorkItem(
        request="phase5e metadata-only secret lease test",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="phase5e-session",
        source_turn_id="phase5e-turn",
        result={
            "secret_id": "secret-demo",
            "consumer_id": "dependency.private-index.v1",
            "scopes": ["repository.read"],
            "policy_digest": "b" * 64,
        },
    )
    work_store.create(item)

    changes = ChangeStore(work_store)
    change = changes.create(
        request="phase5e metadata-only change",
        process_key=ChangeStore.DEFAULT_PROCESS.key,
        process_version=ChangeStore.DEFAULT_PROCESS.version,
        source_session_id="phase5e-change-session",
        source_turn_id="phase5e-change-turn",
    )
    changes.add_artifact(
        change.change_id,
        kind="secret_lease_metadata",
        payload={
            "secret_id": "secret-demo",
            "consumer_id": "dependency.private-index.v1",
            "scopes": ["repository.read"],
            "policy_digest": "b" * 64,
        },
    )

    persisted = b"".join(
        path.read_bytes()
        for path in tmp_path.iterdir()
        if path.is_file() and path.name.startswith("work.sqlite3")
    )
    assert SECRET_VALUE not in persisted
    assert b"secret-demo" in persisted
    assert b"repository.read" in persisted


def test_projection_tamper_is_detected_against_sealed_envelope(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _enroll(store)

    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE secrets SET allowed_scopes_json = ? WHERE secret_id = ?",
            (json.dumps(["repository.read", "admin"]), "secret-demo"),
        )

    with pytest.raises(SecretIntegrityError, match="does not match sealed"):
        store.verified_descriptor("secret-demo")
    with pytest.raises(SecretIntegrityError, match="does not match sealed"):
        store.list_descriptors()


def test_rotate_replaces_ciphertext_and_revoke_is_versioned(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _enroll(store)
    first_blob = store.path.read_bytes()

    second = store.rotate("secret-demo", value=b"rotated-test-value", now_epoch=1_100)
    assert second.version == first.version + 1
    assert store.materialize("secret-demo").value == b"rotated-test-value"
    assert SECRET_VALUE not in store.path.read_bytes()
    assert store.path.read_bytes() != first_blob

    revoked = store.revoke("secret-demo", now_epoch=1_200)
    assert revoked.version == second.version + 1
    assert revoked.lifecycle_state is SecretLifecycleState.REVOKED
    with pytest.raises(Exception, match="revoked"):
        store.materialize("secret-demo")


class CriticalPolicy:
    version = "phase5e-test-v1"

    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        assert policy_input.risk_class is RiskClass.CRITICAL
        return PolicyDecision(
            effect=Effect.ALLOW,
            requirements=PolicyRequirements(
                required_trust=TrustTier.VERIFIED_OWNER,
                approval_requirement=ApprovalRequirement.STRONG,
            ),
            reason_codes=(),
            policy_version=self.version,
        )


def _authority(now: float = 50.0):
    approvals = ApprovalService(clock=lambda: now)
    permits = PermitRegistry(clock=lambda: now, ttl_seconds=10)
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=CriticalPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=permits,
        clock=lambda: now,
    )
    return authority, approvals


def _authorized_request():
    request = SecretLeaseRequest(
        secret_id="secret-demo",
        consumer_id="dependency.private-index.v1",
        scopes=("repository.read",),
        ttl_seconds=60,
        use_budget=1,
        change_id="change-5e",
        work_id="work-5e",
    )
    proposal = build_secret_lease_proposal(
        request,
        session_id="session-5e",
        origin=ActionOrigin.MODEL_SUGGESTED,
        now_monotonic=50,
    )
    context = InteractionContext(
        session_id="session-5e",
        trust_tier=TrustTier.VERIFIED_OWNER,
        actor_unambiguous=True,
    )
    return request, proposal, context


def _strong_permit(
    authority: AuthorityService,
    approvals: ApprovalService,
    *,
    proposal,
    context: InteractionContext,
) -> str:
    record = approvals.request(
        proposal,
        session_id=context.session_id,
        requirement=ApprovalRequirement.STRONG,
        ttl_seconds=30,
    )
    verification = StrongVerificationResult(
        status=StrongVerificationStatus.VERIFIED,
        verifier_id="phase5e-test-verifier",
        verification_id=f"verification-{record.approval_id}",
        proposal_fingerprint=proposal.fingerprint,
        session_id=context.session_id,
        reason_codes=("verified",),
    )
    granted = approvals.grant_verified_strong(
        record.approval_id,
        proposal=proposal,
        session_id=context.session_id,
        verification=verification,
    )
    decision = authority.evaluate(
        proposal=proposal,
        context=context,
        approval_id=granted.approval_id,
    )
    assert decision.effect is AuthorityEffect.ALLOW
    assert decision.execution_permit is not None
    assert decision.risk_class is RiskClass.CRITICAL
    return decision.execution_permit.permit_id


def test_secret_lease_consumes_canonical_critical_authority_and_is_child_only(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _enroll(store)
    authority, approvals = _authority()
    request, proposal, context = _authorized_request()
    permit_id = _strong_permit(
        authority,
        approvals,
        proposal=proposal,
        context=context,
    )
    consumers = SecretConsumerRegistry(
        (
            SecretConsumerPolicy(
                consumer_id="dependency.private-index.v1",
                allowed_scopes=("repository.read",),
                secret_environment_variable="JARVIS_TEST_SECRET",
                inherited_environment_allowlist=("PATH",),
            ),
        )
    )
    broker = SecretBroker(
        store=store,
        consumers=consumers,
        authority_gate=CanonicalAuthoritySecretGate(authority),
        clock=lambda: 1_000.0,
        process_nonce="process-a",
    )

    lease = broker.issue_lease(
        request,
        proposal=proposal,
        context=context,
        permit_id=permit_id,
    )
    assert lease.consumer_id == "dependency.private-index.v1"
    assert lease.scopes == ("repository.read",)
    assert lease.secret_version == 1
    assert SECRET_VALUE.decode() not in repr(lease)

    before = dict(os.environ)
    held_environment: dict[str, str] | None = None
    with broker.child_environment(
        lease.lease_id,
        consumer_id=lease.consumer_id,
        parent_environment={
            "PATH": "trusted-path",
            "UNRELATED": "must-not-inherit",
            "JARVIS_TEST_SECRET": "parent-value-must-not-survive",
        },
    ) as environment:
        held_environment = environment
        assert environment == {
            "PATH": "trusted-path",
            "JARVIS_TEST_SECRET": SECRET_VALUE.decode(),
        }
        assert broker.remaining_uses(lease.lease_id) == 0
    assert held_environment == {}
    assert dict(os.environ) == before

    with (
        pytest.raises(SecretLeaseError, match="unknown|exhausted"),
        broker.child_environment(
            lease.lease_id,
            consumer_id=lease.consumer_id,
        ),
    ):
        pass


def test_authority_rejection_happens_before_secret_unseal(tmp_path: Path) -> None:
    class CountingProtector(FakeProtector):
        def __init__(self) -> None:
            self.unseal_calls = 0

        def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
            self.unseal_calls += 1
            return super().unseal(sealed, purpose=purpose)

    class RejectingGate:
        def authorize(self, **kwargs):
            raise SecretAuthorizationError("denied for test")

    protector = CountingProtector()
    store = SecretStore(
        tmp_path / "secrets.sqlite",
        protector=protector,
        clock=lambda: 1_000.0,
    )
    _enroll(store)
    consumers = SecretConsumerRegistry(
        (
            SecretConsumerPolicy(
                consumer_id="dependency.private-index.v1",
                allowed_scopes=("repository.read",),
                secret_environment_variable="JARVIS_TEST_SECRET",
            ),
        )
    )
    request, proposal, context = _authorized_request()
    broker = SecretBroker(
        store=store,
        consumers=consumers,
        authority_gate=RejectingGate(),
        clock=lambda: 1_000.0,
        process_nonce="process-a",
    )

    with pytest.raises(SecretAuthorizationError, match="denied"):
        broker.issue_lease(
            request,
            proposal=proposal,
            context=context,
            permit_id="denied",
        )

    assert protector.unseal_calls == 0


def test_lease_scope_consumer_rotation_revocation_and_restart_fail_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _enroll(store)
    consumers = SecretConsumerRegistry(
        (
            SecretConsumerPolicy(
                consumer_id="dependency.private-index.v1",
                allowed_scopes=("repository.read",),
                secret_environment_variable="JARVIS_TEST_SECRET",
            ),
        )
    )

    class AcceptingGate:
        def authorize(self, **kwargs):
            from jarvis.engineering_substrate.secrets import SecretAuthorityEvidence

            return SecretAuthorityEvidence(
                decision_id="decision",
                proposal_fingerprint=kwargs["proposal"].fingerprint,
                policy_version="test",
                risk_class="CRITICAL",
                policy_digest="b" * 64,
            )

    request, proposal, context = _authorized_request()
    broker = SecretBroker(
        store=store,
        consumers=consumers,
        authority_gate=AcceptingGate(),
        clock=lambda: 1_000.0,
        process_nonce="process-a",
    )
    lease = broker.issue_lease(
        request,
        proposal=proposal,
        context=context,
        permit_id="fake-test-permit",
    )

    store.rotate("secret-demo", value=b"rotated", now_epoch=1_100)
    with (
        pytest.raises(SecretLeaseError, match="rotated"),
        broker.child_environment(
            lease.lease_id,
            consumer_id=lease.consumer_id,
        ),
    ):
        pass

    restarted = SecretBroker(
        store=store,
        consumers=consumers,
        authority_gate=AcceptingGate(),
        clock=lambda: 1_000.0,
        process_nonce="process-b",
    )
    with (
        pytest.raises(SecretLeaseError, match="fresh lease"),
        restarted.child_environment(
            lease.lease_id,
            consumer_id=lease.consumer_id,
        ),
    ):
        pass

    store.revoke("secret-demo", now_epoch=1_200)
    with pytest.raises(SecretLeaseError, match="revoked"):
        restarted.issue_lease(
            request,
            proposal=proposal,
            context=context,
            permit_id="fake-test-permit",
        )


def test_cli_never_accepts_plaintext_argument_or_prints_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = _store(tmp_path)
    answers = iter(["cli-secret-value", "cli-secret-value"])
    monkeypatch.setattr(
        "jarvis.engineering_substrate.secrets.cli.getpass.getpass",
        lambda prompt: next(answers),
    )

    assert (
        secret_cli_main(
            [
                "enroll",
                "cli-secret",
                "--kind",
                "token",
                "--service",
                "example",
                "--consumer",
                "dependency.private-index.v1",
                "--scope",
                "repository.read",
            ],
            store=store,
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "cli-secret-value" not in output
    assert "cli-secret" in output
    assert b"cli-secret-value" not in store.path.read_bytes()

    with pytest.raises(SystemExit):
        secret_cli_main(
            [
                "rotate",
                "cli-secret",
                "--value",
                "must-never-be-accepted",
            ],
            store=store,
        )
