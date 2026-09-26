"""Authority-bound, process-local secret leases and child-env materialization."""

from __future__ import annotations

import os
import re
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol

from jarvis.authority import (
    ActionAttributes,
    ActionOrigin,
    ActionProposal,
    AuthorityError,
    AuthorityService,
    InteractionContext,
    RiskClass,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import (
    SecretLease,
    SecretLifecycleState,
    SecretMaterializationMode,
)
from jarvis.engineering_substrate.secrets.store import SecretIntegrityError, SecretStore

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_MAX_LEASE_SECONDS = 300.0
_MAX_USE_BUDGET = 16


class SecretBrokerError(RuntimeError):
    """Base error for scoped secret leasing/materialization."""


class SecretAuthorizationError(SecretBrokerError):
    """Canonical Authority did not authorize this exact secret lease."""


class SecretLeaseError(SecretBrokerError):
    """A secret lease is absent, expired, exhausted, stale or scope-invalid."""


@dataclass(frozen=True, slots=True)
class SecretConsumerPolicy:
    consumer_id: str
    allowed_scopes: tuple[str, ...]
    secret_environment_variable: str
    inherited_environment_allowlist: tuple[str, ...] = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
    )

    def __post_init__(self) -> None:
        consumer = str(self.consumer_id).strip().casefold()
        scopes = tuple(
            dict.fromkeys(str(item).strip().casefold() for item in self.allowed_scopes)
        )
        variable = str(self.secret_environment_variable).strip()
        inherited = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in self.inherited_environment_allowlist
                if str(item).strip()
            )
        )
        if not consumer:
            raise ValueError("consumer_id must not be empty")
        if not scopes or any(not item for item in scopes):
            raise ValueError("allowed_scopes must contain non-empty scopes")
        if not _ENVIRONMENT_NAME.fullmatch(variable):
            raise ValueError("secret environment variable name is invalid")
        if variable.casefold() in {item.casefold() for item in inherited}:
            raise ValueError(
                "secret environment variable cannot be inherited from parent environment"
            )
        object.__setattr__(self, "consumer_id", consumer)
        object.__setattr__(self, "allowed_scopes", scopes)
        object.__setattr__(self, "secret_environment_variable", variable)
        object.__setattr__(self, "inherited_environment_allowlist", inherited)


class SecretConsumerRegistry:
    """Exact trusted consumer registry; models cannot invent env names or scopes."""

    def __init__(self, policies: tuple[SecretConsumerPolicy, ...] = ()) -> None:
        self._policies: dict[str, SecretConsumerPolicy] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: SecretConsumerPolicy) -> None:
        if not isinstance(policy, SecretConsumerPolicy):
            raise TypeError("policy must be a SecretConsumerPolicy")
        if policy.consumer_id in self._policies:
            raise SecretBrokerError(
                f"secret consumer already registered: {policy.consumer_id}"
            )
        self._policies[policy.consumer_id] = policy

    def require(self, consumer_id: str) -> SecretConsumerPolicy:
        key = str(consumer_id).strip().casefold()
        try:
            return self._policies[key]
        except KeyError as exc:
            raise SecretBrokerError(f"unregistered secret consumer: {key}") from exc

    def all(self) -> tuple[SecretConsumerPolicy, ...]:
        return tuple(self._policies[key] for key in sorted(self._policies))


@dataclass(frozen=True, slots=True)
class SecretLeaseRequest:
    secret_id: str
    consumer_id: str
    scopes: tuple[str, ...]
    ttl_seconds: float = 60.0
    use_budget: int = 1
    change_id: str | None = None
    work_id: str | None = None

    def __post_init__(self) -> None:
        secret_id = str(self.secret_id).strip()
        consumer = str(self.consumer_id).strip().casefold()
        scopes = tuple(
            dict.fromkeys(str(item).strip().casefold() for item in self.scopes)
        )
        ttl = float(self.ttl_seconds)
        budget = self.use_budget
        if not secret_id:
            raise ValueError("secret_id must not be empty")
        if not consumer:
            raise ValueError("consumer_id must not be empty")
        if not scopes or any(not item for item in scopes):
            raise ValueError("lease scopes must not be empty")
        if ttl <= 0 or ttl > _MAX_LEASE_SECONDS:
            raise ValueError(f"ttl_seconds must be within (0, {_MAX_LEASE_SECONDS:g}]")
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise TypeError("use_budget must be an integer")
        if budget <= 0 or budget > _MAX_USE_BUDGET:
            raise ValueError(f"use_budget must be within [1, {_MAX_USE_BUDGET}]")
        object.__setattr__(self, "secret_id", secret_id)
        object.__setattr__(self, "consumer_id", consumer)
        object.__setattr__(self, "scopes", scopes)
        object.__setattr__(self, "ttl_seconds", ttl)
        object.__setattr__(
            self,
            "change_id",
            None if self.change_id is None else str(self.change_id).strip() or None,
        )
        object.__setattr__(
            self,
            "work_id",
            None if self.work_id is None else str(self.work_id).strip() or None,
        )

    def authority_target(self) -> dict[str, object]:
        return {"secret_id": self.secret_id}

    def authority_parameters(self) -> dict[str, object]:
        return {
            "consumer_id": self.consumer_id,
            "scopes": list(self.scopes),
            "ttl_seconds": self.ttl_seconds,
            "use_budget": self.use_budget,
            "change_id": self.change_id,
            "work_id": self.work_id,
        }


def build_secret_lease_proposal(
    request: SecretLeaseRequest,
    *,
    session_id: str,
    origin: ActionOrigin,
    ttl_seconds: float = 120.0,
    now_monotonic: float | None = None,
) -> ActionProposal:
    """Build the exact Authority proposal used to approve one lease request."""

    if not isinstance(request, SecretLeaseRequest):
        raise TypeError("request must be a SecretLeaseRequest")
    return ActionProposal.create(
        session_id=session_id,
        capability="engineering:secret",
        operation="lease",
        target=request.authority_target(),
        parameters=request.authority_parameters(),
        material_summary=(
            f"Use secret {request.secret_id} for registered consumer "
            f"{request.consumer_id} with scopes {', '.join(request.scopes)}"
        ),
        attributes=ActionAttributes(secret_or_credential_access=True),
        origin=origin,
        ttl_seconds=ttl_seconds,
        now_monotonic=now_monotonic,
    )


@dataclass(frozen=True, slots=True)
class SecretAuthorityEvidence:
    decision_id: str
    proposal_fingerprint: str
    policy_version: str
    risk_class: str
    policy_digest: str


class SecretAuthorityGate(Protocol):
    def authorize(
        self,
        *,
        request: SecretLeaseRequest,
        proposal: ActionProposal,
        context: InteractionContext,
        permit_id: str,
    ) -> SecretAuthorityEvidence: ...


class CanonicalAuthoritySecretGate:
    """Consume the existing Authority permit for the exact typed lease request."""

    def __init__(self, authority: AuthorityService) -> None:
        if not isinstance(authority, AuthorityService):
            raise TypeError("authority must be an AuthorityService")
        self._authority = authority

    @staticmethod
    def _assert_binding(
        request: SecretLeaseRequest,
        proposal: ActionProposal,
        context: InteractionContext,
    ) -> None:
        if proposal.session_id != context.session_id:
            raise SecretAuthorizationError("secret proposal session mismatch")
        if proposal.capability != "engineering:secret" or proposal.operation != "lease":
            raise SecretAuthorizationError(
                "secret proposal operation is not registered"
            )
        if proposal.target() != request.authority_target():
            raise SecretAuthorizationError("secret proposal target mismatch")
        if proposal.parameters() != request.authority_parameters():
            raise SecretAuthorizationError("secret proposal parameters mismatch")
        if not proposal.attributes.secret_or_credential_access:
            raise SecretAuthorizationError(
                "secret proposal lacks credential-access risk attribute"
            )

    def authorize(
        self,
        *,
        request: SecretLeaseRequest,
        proposal: ActionProposal,
        context: InteractionContext,
        permit_id: str,
    ) -> SecretAuthorityEvidence:
        self._assert_binding(request, proposal, context)
        try:
            consumed = self._authority.revalidate_and_consume(
                permit_id=permit_id,
                proposal=proposal,
                context=context,
            )
        except AuthorityError as exc:
            raise SecretAuthorizationError(
                "canonical Authority rejected secret lease"
            ) from exc
        if consumed.risk_class is not RiskClass.CRITICAL:
            raise SecretAuthorizationError(
                "secret lease did not retain the CRITICAL Authority floor"
            )
        policy_digest = canonical_digest(
            {
                "decision_id": consumed.decision_id,
                "proposal_id": consumed.proposal_id,
                "proposal_fingerprint": consumed.proposal_fingerprint,
                "session_id": consumed.session_id,
                "risk_class": consumed.risk_class.name,
                "policy_version": consumed.policy_version,
                "approval_id": consumed.approval_id,
            }
        )
        return SecretAuthorityEvidence(
            decision_id=consumed.decision_id,
            proposal_fingerprint=consumed.proposal_fingerprint,
            policy_version=consumed.policy_version,
            risk_class=consumed.risk_class.name,
            policy_digest=policy_digest,
        )


@dataclass(slots=True)
class _LeaseState:
    lease: SecretLease
    process_nonce: str
    remaining_uses: int


class SecretBroker:
    """Issue process-local leases and materialize only registered child environments."""

    def __init__(
        self,
        *,
        store: SecretStore,
        consumers: SecretConsumerRegistry,
        authority_gate: SecretAuthorityGate,
        clock=time.time,
        process_nonce: str | None = None,
    ) -> None:
        if not isinstance(store, SecretStore):
            raise TypeError("store must be a SecretStore")
        if not isinstance(consumers, SecretConsumerRegistry):
            raise TypeError("consumers must be a SecretConsumerRegistry")
        self._store = store
        self._consumers = consumers
        self._authority_gate = authority_gate
        self._clock = clock
        self._process_nonce = process_nonce or str(uuid.uuid4())
        self._leases: dict[str, _LeaseState] = {}
        self._lock = threading.RLock()

    def issue_lease(
        self,
        request: SecretLeaseRequest,
        *,
        proposal: ActionProposal,
        context: InteractionContext,
        permit_id: str,
    ) -> SecretLease:
        if not isinstance(request, SecretLeaseRequest):
            raise TypeError("request must be a SecretLeaseRequest")
        consumer = self._consumers.require(request.consumer_id)
        requested = set(request.scopes)
        if not requested.issubset(set(consumer.allowed_scopes)):
            raise SecretLeaseError("lease scope exceeds registered consumer")

        # Projection metadata can reject obviously invalid requests without decrypting.
        # It is not trusted as integrity evidence until after Authority is consumed.
        projected = self._store.descriptor(request.secret_id)
        if projected.lifecycle_state is not SecretLifecycleState.ACTIVE:
            raise SecretLeaseError("secret is revoked")
        if request.consumer_id not in projected.allowed_consumers:
            raise SecretLeaseError("secret is not allowed for this consumer")
        if not requested.issubset(set(projected.allowed_scopes)):
            raise SecretLeaseError("lease scope exceeds secret descriptor")

        evidence = self._authority_gate.authorize(
            request=request,
            proposal=proposal,
            context=context,
            permit_id=permit_id,
        )
        if evidence.risk_class != RiskClass.CRITICAL.name:
            raise SecretAuthorizationError(
                "secret authority evidence did not retain CRITICAL risk"
            )
        if evidence.proposal_fingerprint != proposal.fingerprint:
            raise SecretAuthorizationError(
                "secret authority evidence proposal fingerprint mismatch"
            )
        if (
            len(evidence.policy_digest) != 64
            or any(char not in "0123456789abcdef" for char in evidence.policy_digest)
        ):
            raise SecretAuthorizationError("secret authority evidence digest is invalid")

        # Only after Authority has been consumed may the sealed envelope be decrypted.
        descriptor = self._store.verified_descriptor(request.secret_id)
        if descriptor.lifecycle_state is not SecretLifecycleState.ACTIVE:
            raise SecretLeaseError("secret is revoked")
        if request.consumer_id not in descriptor.allowed_consumers:
            raise SecretLeaseError("secret is not allowed for this consumer")
        if not requested.issubset(set(descriptor.allowed_scopes)):
            raise SecretLeaseError("lease scope exceeds secret descriptor")

        now = float(self._clock())
        lease = SecretLease(
            lease_id=str(uuid.uuid4()),
            secret_id=descriptor.secret_id,
            secret_version=descriptor.version,
            consumer_id=consumer.consumer_id,
            scopes=request.scopes,
            materialization_mode=SecretMaterializationMode.CHILD_ENV,
            issued_at_epoch=now,
            expires_at_epoch=now + request.ttl_seconds,
            use_budget=request.use_budget,
            policy_digest=evidence.policy_digest,
            change_id=request.change_id,
            work_id=request.work_id,
        )
        with self._lock:
            self._leases[lease.lease_id] = _LeaseState(
                lease=lease,
                process_nonce=self._process_nonce,
                remaining_uses=lease.use_budget,
            )
        return lease

    def _active_state(self, lease_id: str, consumer_id: str) -> _LeaseState:
        key = str(lease_id).strip()
        consumer = str(consumer_id).strip().casefold()
        with self._lock:
            state = self._leases.get(key)
            if state is None:
                raise SecretLeaseError(
                    "unknown secret lease; process restart requires a fresh lease"
                )
            if state.process_nonce != self._process_nonce:
                raise SecretLeaseError("secret lease belongs to another process")
            if state.lease.consumer_id != consumer:
                raise SecretLeaseError("secret lease consumer mismatch")
            if float(self._clock()) >= state.lease.expires_at_epoch:
                self._leases.pop(key, None)
                raise SecretLeaseError("secret lease is expired")
            if state.remaining_uses <= 0:
                self._leases.pop(key, None)
                raise SecretLeaseError("secret lease use budget is exhausted")
            return state

    @contextmanager
    def child_environment(
        self,
        lease_id: str,
        *,
        consumer_id: str,
        parent_environment: Mapping[str, str] | None = None,
    ) -> Iterator[dict[str, str]]:
        """Yield a minimal child-only env map, then clear it after trusted invocation."""

        state = self._active_state(lease_id, consumer_id)
        policy = self._consumers.require(consumer_id)
        material = self._store.materialize(state.lease.secret_id, require_active=True)
        if material.descriptor.version != state.lease.secret_version:
            raise SecretLeaseError("secret rotated after lease issuance")
        if state.lease.consumer_id not in material.descriptor.allowed_consumers:
            raise SecretLeaseError("secret consumer permission changed")
        if not set(state.lease.scopes).issubset(
            set(material.descriptor.allowed_scopes)
        ):
            raise SecretLeaseError("secret scopes changed after lease issuance")

        try:
            secret_text = material.value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SecretIntegrityError("child-env secret must be valid UTF-8") from exc
        if "\x00" in secret_text:
            raise SecretIntegrityError("child-env secret cannot contain NUL")

        source = os.environ if parent_environment is None else parent_environment
        inherited_lookup = {
            key.casefold(): (key, value) for key, value in source.items()
        }
        environment: dict[str, str] = {}
        for allowed in policy.inherited_environment_allowlist:
            item = inherited_lookup.get(allowed.casefold())
            if item is not None:
                environment[item[0]] = item[1]
        environment[policy.secret_environment_variable] = secret_text

        with self._lock:
            current = self._leases.get(state.lease.lease_id)
            if current is not state or current.remaining_uses <= 0:
                raise SecretLeaseError("secret lease changed before materialization")
            current.remaining_uses -= 1
            if current.remaining_uses == 0:
                self._leases.pop(state.lease.lease_id, None)

        try:
            yield environment
        finally:
            if policy.secret_environment_variable in environment:
                environment[policy.secret_environment_variable] = ""
            environment.clear()
            secret_text = ""

    def remaining_uses(self, lease_id: str) -> int:
        with self._lock:
            state = self._leases.get(str(lease_id).strip())
            return 0 if state is None else state.remaining_uses

    def invalidate_all(self) -> None:
        with self._lock:
            self._leases.clear()


PRIVATE_INDEX_TOKEN_CONSUMER = SecretConsumerPolicy(
    consumer_id="dependency.private-index.v1",
    allowed_scopes=("repository.read",),
    secret_environment_variable="JARVIS_DEPENDENCY_INDEX_TOKEN",
)


def default_secret_consumer_registry() -> SecretConsumerRegistry:
    return SecretConsumerRegistry((PRIVATE_INDEX_TOKEN_CONSUMER,))
