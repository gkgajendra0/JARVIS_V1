from __future__ import annotations

import uuid

import pytest

from jarvis.authority import (
    ApprovalRequirement,
    ApprovalService,
    AuthorityEffect,
    AuthorityService,
    InMemoryAuditEventStore,
    PermitRegistry,
    PolicyDecision,
    PolicyInput,
    PolicyRequirements,
    RiskClassifier,
    StrongApprovalService,
    StrongVerificationResult,
    StrongVerificationStatus,
    TrustTier,
)
from jarvis.authority.session import AuthoritySession
from jarvis.identity import (
    BiometricModality,
    OwnerProfileAuthorizationDenied,
    OwnerProfileLifecycleService,
    SqliteOwnerProfileStore,
    TemplateInput,
    TemplateMetadata,
)


class TestKeyProtector:
    protector_id = "test-key-protector-v1"

    def seal(self, plaintext: bytes, *, purpose: str) -> bytes:
        return b"sealed:" + purpose.encode() + b":" + plaintext

    def unseal(self, sealed: bytes, *, purpose: str) -> bytes:
        prefix = b"sealed:" + purpose.encode() + b":"
        if not sealed.startswith(prefix):
            raise RuntimeError("test key cannot be unsealed")
        return sealed[len(prefix) :]


class AllowPolicy:
    def evaluate(self, policy_input: PolicyInput) -> PolicyDecision:
        return PolicyDecision(
            effect=AuthorityEffect.ALLOW,
            requirements=PolicyRequirements(
                required_trust=TrustTier.UNVERIFIED,
                approval_requirement=ApprovalRequirement.NONE,
                audit_required=False,
            ),
            reason_codes=("identity_profile_change",),
            policy_version="step3-v1",
        )


class VerifiedStrongVerifier:
    def verify(self, *, proposal, session_id):
        return StrongVerificationResult(
            status=StrongVerificationStatus.VERIFIED,
            verifier_id="test-strong-verifier",
            verification_id=str(uuid.uuid4()),
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
            reason_codes=("verified",),
        )


class CanceledStrongVerifier:
    def verify(self, *, proposal, session_id):
        return StrongVerificationResult(
            status=StrongVerificationStatus.CANCELED,
            verifier_id="test-strong-verifier",
            verification_id=str(uuid.uuid4()),
            proposal_fingerprint=proposal.fingerprint,
            session_id=session_id,
            reason_codes=("user_canceled",),
        )


class StaticSessionProvider:
    def __init__(self, session: AuthoritySession) -> None:
        self.session = session

    def current_session(self) -> AuthoritySession:
        return self.session


class SwitchingSessionProvider:
    def __init__(self, first: AuthoritySession, second: AuthoritySession) -> None:
        self._sessions = [first, second]
        self._index = 0

    def current_session(self) -> AuthoritySession:
        value = self._sessions[min(self._index, len(self._sessions) - 1)]
        self._index += 1
        return value


def session(session_id: str = "wts:7", *, unlocked: bool = True) -> AuthoritySession:
    return AuthoritySession(
        session_id=session_id,
        windows_session_id=7,
        windows_user_sid_hash=None,
        active_unlocked=unlocked,
        generation=0,
        created_at_monotonic=1.0,
    )


def face_template(payload: bytes = b"face-template") -> TemplateInput:
    return TemplateInput(
        metadata=TemplateMetadata(
            modality=BiometricModality.FACE,
            provider_id="opencv-sface",
            model_id="sface-test",
            model_version="1",
            model_sha256="a" * 64,
            embedding_dimension=128,
            calibration_version="unaccepted-test",
            enrollment_compatibility_version="sface-v1",
        ),
        payload=payload,
    )


def lifecycle(tmp_path, *, verifier, session_provider):
    approvals = ApprovalService()
    store = SqliteOwnerProfileStore(
        tmp_path / "identity.db",
        key_protector=TestKeyProtector(),
    )
    authority = AuthorityService(
        risk_classifier=RiskClassifier(),
        policy_engine=AllowPolicy(),
        approvals=approvals,
        audit_store=InMemoryAuditEventStore(),
        permits=PermitRegistry(),
    )
    service = OwnerProfileLifecycleService(
        store=store,
        strong_approval=StrongApprovalService(
            approvals=approvals,
            verifier=verifier,
        ),
        authority=authority,
        session_provider=session_provider,
    )
    return store, service


def test_verified_strong_flow_can_create_owner(tmp_path) -> None:
    store, service = lifecycle(
        tmp_path,
        verifier=VerifiedStrongVerifier(),
        session_provider=StaticSessionProvider(session()),
    )

    result = service.create_owner([face_template()])

    assert result.operation == "create_owner"
    assert result.profile is not None
    assert result.profile.profile_id == "OWNER"
    assert store.load_template(BiometricModality.FACE).payload == b"face-template"
    store.close()


def test_canceled_strong_verification_cannot_create_owner(tmp_path) -> None:
    store, service = lifecycle(
        tmp_path,
        verifier=CanceledStrongVerifier(),
        session_provider=StaticSessionProvider(session()),
    )

    with pytest.raises(OwnerProfileAuthorizationDenied, match="canceled"):
        service.create_owner([face_template()])

    assert not store.has_owner()
    store.close()


def test_locked_windows_session_cannot_start_profile_change(tmp_path) -> None:
    store, service = lifecycle(
        tmp_path,
        verifier=VerifiedStrongVerifier(),
        session_provider=StaticSessionProvider(session(unlocked=False)),
    )

    with pytest.raises(OwnerProfileAuthorizationDenied, match="active/unlocked"):
        service.create_owner([face_template()])

    assert not store.has_owner()
    store.close()


def test_session_switch_after_hello_invalidates_profile_change(tmp_path) -> None:
    first = session("wts:7")
    second = session("wts:9")
    store, service = lifecycle(
        tmp_path,
        verifier=VerifiedStrongVerifier(),
        session_provider=SwitchingSessionProvider(first, second),
    )

    with pytest.raises(OwnerProfileAuthorizationDenied, match="session changed"):
        service.create_owner([face_template()])

    assert not store.has_owner()
    store.close()


def test_replace_and_delete_each_require_a_new_strong_flow(tmp_path) -> None:
    store, service = lifecycle(
        tmp_path,
        verifier=VerifiedStrongVerifier(),
        session_provider=StaticSessionProvider(session()),
    )

    created = service.create_owner([face_template(b"v1")])
    replaced = service.replace_owner([face_template(b"v2")])
    deleted = service.delete_owner()

    assert created.profile is not None
    assert created.profile.profile_version == 1
    assert replaced.profile is not None
    assert replaced.profile.profile_version == 2
    assert deleted.profile is None
    assert not store.has_owner()
    store.close()
