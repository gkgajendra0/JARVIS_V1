"""Memory-only session delegation through the canonical approval/permit owner."""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

from jarvis.capabilities.authority_bridge import (
    AuthorizedCapability,
)
from jarvis.capabilities.execution import PreparedCapability
from jarvis.capabilities.models import CapabilityRequest
from jarvis.personal_learning_scope import CATEGORIES, POLICY_VERSION, SUPPRESSION_KEYS

from .approval import ApprovalError
from .proposal import ActionProposal, canonical_json
from .types import (
    ActionAttributes,
    ActionOrigin,
    ApprovalRequirement,
    AuthorityEffect,
    InteractionContext,
    TrustTier,
)

POLICY_DIGEST = hashlib.sha256(
    canonical_json(
        {
            "version": POLICY_VERSION,
            "categories": sorted(CATEGORIES),
            "lifetime": "runtime_and_unlocked_windows_session",
            "session_policy_revision": 3,
            "sensitivity": "standard",
            "category_veto": "persistent",
            "scope_registry": 1,
        }
    ).encode()
).hexdigest()


@dataclass(frozen=True, eq=False)
class LearningGrantHandle:
    token: str


@dataclass(frozen=True, eq=False)
class LearningPermitHandle:
    token: str


@dataclass(frozen=True)
class LearningActionBinding:
    operation: str
    source_receipt_id: str
    payload_sha256: str
    categories: tuple[str, ...]
    targets: tuple[tuple[str, str | None], ...] = ()
    suppression_epochs: tuple[tuple[str, int], ...] = ()
    policy_version: str = POLICY_VERSION


@dataclass(frozen=True)
class LearningSessionState:
    status: str
    reason: str = ""


@dataclass
class _Grant:
    parent: AuthorizedCapability
    provider: str
    created: float
    last_input: float
    revoked: str = ""
    seen: set[str] = field(default_factory=set)
    sources: dict[str, float] = field(default_factory=dict)
    source_objects: dict[str, object] = field(default_factory=dict)


@dataclass
class _Child:
    grant: LearningGrantHandle
    binding: LearningActionBinding
    authorized: AuthorizedCapability
    consumed: bool = False


class PersonalLearningAuthority:
    """One issuer per runtime; handles have identity, never serialized authority."""

    def __init__(self, broker):
        self._broker = broker
        self._grants: dict[LearningGrantHandle, _Grant] = {}
        self._children: dict[LearningPermitHandle, _Child] = {}
        self._reenables = {}

    def open(self, runtime_id: str, provider: str) -> LearningGrantHandle:
        if not runtime_id or provider not in {"gemini", "openai"}:
            raise ValueError("invalid learning runtime/provider")
        parameters = {"policy_sha256": POLICY_DIGEST, "provider": provider}
        prepared = PreparedCapability(
            CapabilityRequest(
                runtime_id,
                "memory:personal_learning",
                "open",
                parameters,
                ActionOrigin.DIRECT_USER,
            ),
            {"subject_scope": "personal", "subject": "owner"},
            parameters,
            "Open an owner-operated memory session for this Jarvis runtime and "
            "the same unlocked Windows session, including idle periods. Windows "
            "lock, user/session change or Jarvis shutdown ends permission. "
            "Automatically read and learn standard owned items, "
            "preferences, background/work, relationships relevant to the user, "
            "current activities, dated experiences and future plans with stated "
            "time, place and reasons. No per-fact prompt; "
            "later speaker identity is not verified. No sensitive facts/actions.",
            ActionAttributes(security_or_permission_change=True),
            {},
        )
        with self._broker._lock:
            try:
                parent = self._broker.authorize_fresh_owner(prepared)
                self._broker.consume(parent)
            except Exception as exc:
                raise PermissionError("learning session was not authorized") from exc
            now = self._broker._clock()
            handle = LearningGrantHandle(str(uuid4()))
            self._grants[handle] = _Grant(parent, provider, now, now)
            self._broker._approvals.register_delegation(
                handle, lambda proposal: self._proof(handle, proposal)
            )
            return handle

    def authorize_reenable_category(self, category):
        if category not in SUPPRESSION_KEYS:
            raise PermissionError("unknown learning category")
        parameters = {"category": category, "policy_sha256": POLICY_DIGEST}
        prepared = PreparedCapability(
            CapabilityRequest(
                str(uuid4()),
                "memory:personal_learning",
                "reenable",
                parameters,
                ActionOrigin.DIRECT_USER,
            ),
            {"subject_scope": "personal", "subject": "owner", "category": category},
            parameters,
            f"Explicitly re-enable automatic learning for {category}; old accepted sources remain invalid.",
            ActionAttributes(persistent_write=True, security_or_permission_change=True),
            {},
        )
        with self._broker._lock:
            try:
                authorized = self._broker.authorize_fresh_owner(prepared)
            except Exception as exc:
                raise PermissionError("category re-enable was not authorized") from exc

            def guard():
                try:
                    self._broker.validate_binding(authorized)
                except Exception as exc:
                    raise PermissionError(
                        "category approval expired or invalidated"
                    ) from exc

            self._reenables[guard] = (category, authorized)
            return guard

    @contextmanager
    def reenable_scope(self, category, guard):
        # Enter on the writer thread and retain the same lock through SQL commit.
        with self._broker._lock:
            registered = self._reenables.get(guard)
            if registered is None or registered[0] != category:
                raise PermissionError("exact registered category approval required")
            self._reenables.pop(guard)
            try:
                guard()
                self._broker.consume(registered[1])
                # Invalidate all pre-reenable receipts, including windows accepted
                # under another still-active wake conversation.
                for record in self._grants.values():
                    record.sources.clear()
                    record.source_objects.clear()
                yield
                guard()
            except PermissionError:
                raise
            except Exception as exc:
                raise PermissionError("category approval unavailable") from exc

    def _snapshot(self, grant):
        record = self._grants.get(grant)
        if record is None:
            return LearningSessionState("denied", "unregistered")
        if record.revoked:
            return LearningSessionState("revoked", record.revoked)
        return LearningSessionState("active")

    def validate(self, grant: LearningGrantHandle) -> LearningSessionState:
        with self._broker._lock:
            state = self._snapshot(grant)
            # Session permission survives idle periods; every protected operation
            # still requires continuity of the original unlocked Windows session.
            if state.status not in {"active", "expired"}:
                return state
            record = self._grants[grant]
            try:
                current = self._broker._current_windows_session()
                parent = record.parent
                if (
                    not self._broker._same_windows_session(
                        parent.windows_session, current
                    )
                    or parent.security_epoch != self._broker._security_epoch
                    or parent.session_epoch
                    != self._broker._session_epochs.get(parent.context.session_id, 0)
                ):
                    raise PermissionError("continuity changed")
            except Exception:  # noqa: BLE001 - unavailable OS evidence revokes authority
                self.revoke(grant, "continuity_unavailable")
                return LearningSessionState("revoked", "continuity_unavailable")
            return state

    def _require(self, grant):
        if self.validate(grant).status != "active":
            raise PermissionError("learning delegation is not active")
        return self._grants[grant]

    def observe_accepted_input(self, grant, turn_id):
        with self._broker._lock:
            record = self._require(grant)
            if not isinstance(turn_id, str) or not turn_id:
                raise ValueError("canonical turn identity required")
            if turn_id not in record.seen:
                if len(record.seen) >= 4096:
                    self.revoke(grant, "input_limit")
                    raise PermissionError("learning session input limit")
                record.seen.add(turn_id)
                record.last_input = self._broker._clock()

    def runtime_id_for(self, grant):
        with self._broker._lock:
            return self._require(grant).parent.context.session_id

    def register_source(self, grant, receipt_id, *, source=None):
        with self._broker._lock:
            record = self._require(grant)
            now = self._broker._clock()
            record.sources = {k: v for k, v in record.sources.items() if now < v}
            record.source_objects = {
                k: v for k, v in record.source_objects.items() if k in record.sources
            }
            if not receipt_id or len(record.sources) >= 128:
                raise PermissionError("source receipt unavailable")
            if source is not None:
                from jarvis.memory.learning_contracts import AcceptedLearningSource

                if (
                    not isinstance(source, AcceptedLearningSource)
                    or source.receipt_id != receipt_id
                    or source.runtime_id != record.parent.context.session_id
                ):
                    raise PermissionError("invalid canonical source")
                if (
                    receipt_id in record.source_objects
                    and record.source_objects[receipt_id] is not source
                ):
                    raise PermissionError("source identity changed")
                record.source_objects[receipt_id] = source
            record.sources.setdefault(receipt_id, now + 30)

    def release_source(self, grant, receipt_id):
        with self._broker._lock:
            record = self._grants.get(grant)
            if record:
                record.sources.pop(receipt_id, None)
                record.source_objects.pop(receipt_id, None)

    def source_for(self, permit):
        with self._broker._lock:
            child = self._child(permit)
            return self._grants[child.grant].source_objects.get(
                child.binding.source_receipt_id
            )

    def validate_write(self, permit):
        with self._broker._lock:
            child = self._child(permit)
            if (
                child.binding.operation not in {"admit", "suppress"}
                or not child.consumed
            ):
                raise PermissionError("unconsumed write child")

    def revoke(self, grant, reason="manual_clear"):
        with self._broker._lock:
            record = self._grants.get(grant)
            if record is not None:
                record.revoked = reason
                record.sources.clear()
                record.source_objects.clear()
                self._broker._approvals.revoke_delegation(grant)

    def _proof(self, grant, proposal):
        # Nonblocking under ApprovalService's lock: OS checks happen in the
        # broker-serialized issue/consume/commit path, avoiding inverted locks.
        if self._snapshot(grant).status != "active":
            raise ApprovalError("delegation expired or revoked")
        record = self._grants[grant]
        p = proposal.parameters()
        if (
            proposal.capability != "memory:personal_learning"
            or proposal.operation not in {"read", "admit", "suppress"}
            or proposal.origin is not ActionOrigin.SYSTEM
            or proposal.session_id != record.parent.context.session_id
            or p.get("policy_sha256") != POLICY_DIGEST
            or p.get("parent_delegation_id") != grant.token
            or self._broker._clock()
            >= record.sources.get(p.get("source_receipt_id"), 0)
            or not set(p.get("categories", ())) <= CATEGORIES
            or not p.get("categories")
        ):
            raise ApprovalError("delegation scope mismatch")
        return grant.token

    def issue_child(self, grant, binding: LearningActionBinding):
        with self._broker._lock:
            record = self._require(grant)
            if (
                not isinstance(binding, LearningActionBinding)
                or binding.operation not in {"read", "admit", "suppress"}
                or binding.policy_version != POLICY_VERSION
                or not binding.categories
                or not set(binding.categories) <= CATEGORIES
                or len(binding.payload_sha256) != 64
                or any(c not in "0123456789abcdef" for c in binding.payload_sha256)
                or self._broker._clock()
                >= record.sources.get(binding.source_receipt_id, 0)
            ):
                raise PermissionError("invalid learning child binding")
            parameters = {
                "parent_delegation_id": grant.token,
                "policy_sha256": POLICY_DIGEST,
                "source_receipt_id": binding.source_receipt_id,
                "payload_sha256": binding.payload_sha256,
                "categories": list(binding.categories),
                "targets": list(binding.targets),
                "suppression_epochs": list(binding.suppression_epochs),
            }
            proposal = ActionProposal.create(
                session_id=record.parent.context.session_id,
                capability="memory:personal_learning",
                operation=binding.operation,
                target={"subject_scope": "personal", "subject": "owner"},
                parameters=parameters,
                material_summary="Scoped standard owner memory",
                attributes=ActionAttributes(
                    private_read=binding.operation == "read",
                    persistent_write=binding.operation in {"admit", "suppress"},
                ),
                origin=ActionOrigin.SYSTEM,
                ttl_seconds=30,
                now_monotonic=self._broker._clock(),
            )
            approvals = self._broker._approvals
            pending = approvals.request(
                proposal,
                session_id=proposal.session_id,
                requirement=ApprovalRequirement.EXPLICIT,
                ttl_seconds=30,
            )
            approval = approvals.grant_delegated(
                pending.approval_id,
                proposal=proposal,
                session_id=proposal.session_id,
                grant=grant,
            )
            context = InteractionContext(
                session_id=proposal.session_id,
                trust_tier=TrustTier.CORROBORATED_OWNER,
                windows_session_valid=True,
            )
            decision = self._broker._authority.evaluate(
                proposal=proposal, context=context, approval_id=approval.approval_id
            )
            if (
                decision.effect is not AuthorityEffect.ALLOW
                or not decision.execution_permit
            ):
                raise PermissionError("learning child denied by policy")
            child = AuthorizedCapability(
                proposal,
                context,
                decision.execution_permit.permit_id,
                record.parent.windows_session,
                self._broker._security_epoch,
                record.parent.session_epoch,
            )
            # Old read handles have no authority after their short source lease.
            now = self._broker._clock()
            self._children = {
                k: v
                for k, v in self._children.items()
                if now < v.authorized.proposal.expires_at_monotonic
            }
            if len(self._children) >= 128:
                raise PermissionError("learning child limit")
            handle = LearningPermitHandle(str(uuid4()))
            self._children[handle] = _Child(grant, binding, child)
            return handle

    def _child(self, permit):
        child = self._children.get(permit)
        if child is None:
            raise PermissionError("unknown learning permit")
        self._require(child.grant)
        if child.authorized.proposal.is_expired(self._broker._clock()):
            raise PermissionError("learning child expired")
        self._proof(child.grant, child.authorized.proposal)
        return child

    def describe_child(self, permit):
        with self._broker._lock:
            return self._child(permit).authorized

    def child_binding(self, permit):
        with self._broker._lock:
            return self._child(permit).binding

    def _consume(self, child):
        if child.consumed:
            raise PermissionError("learning child already consumed")
        try:
            self._broker._authority.revalidate_and_consume(
                permit_id=child.authorized.permit_id,
                proposal=child.authorized.proposal,
                context=child.authorized.context,
            )
        except Exception as exc:
            raise PermissionError("learning permit consumption denied") from exc
        child.consumed = True

    @contextmanager
    def commit_scope(self, permit):
        with self._broker._lock:
            child = self._child(permit)
            if child.binding.operation not in {"admit", "suppress"}:
                raise PermissionError("not a write child")
            self._consume(child)
            try:
                yield
                self._child(permit)
            finally:
                self._children.pop(permit, None)

    def consume_read(self, permit):
        with self._broker._lock:
            child = self._child(permit)
            if child.binding.operation != "read":
                raise PermissionError("not a read child")
            self._consume(child)

    def validate_read(self, permit):
        with self._broker._lock:
            child = self._child(permit)
            if child.binding.operation != "read" or not child.consumed:
                raise PermissionError("unconsumed read child")

    def close(self):
        for grant in tuple(self._grants):
            self.revoke(grant, "runtime_closed")
        self._children.clear()
        self._reenables.clear()
