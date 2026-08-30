from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable

from .proposal import ActionProposal
from .types import ApprovalMethod, ApprovalRequirement, ApprovalStatus


class ApprovalError(ValueError):
    pass


_METHOD_LEVEL = {
    ApprovalMethod.DIRECT_INTENT: ApprovalRequirement.DIRECT_INTENT,
    ApprovalMethod.SPOKEN: ApprovalRequirement.EXPLICIT,
    ApprovalMethod.STRONG_VERIFIER: ApprovalRequirement.STRONG,
}


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    approval_id: str
    proposal_id: str
    proposal_fingerprint: str
    session_id: str
    requirement: ApprovalRequirement
    status: ApprovalStatus
    requested_at_monotonic: float
    expires_at_monotonic: float
    method: ApprovalMethod | None = None
    resolved_at_monotonic: float | None = None


class ApprovalService:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = threading.RLock()

    def request(
        self,
        proposal: ActionProposal,
        *,
        session_id: str,
        requirement: ApprovalRequirement,
        ttl_seconds: float,
    ) -> ApprovalRecord:
        with self._lock:
            self._assert_proposal_session(proposal, session_id)
            if requirement < ApprovalRequirement.DIRECT_INTENT:
                raise ApprovalError(
                    "approval request requires an approval-bearing requirement"
                )
            if ttl_seconds <= 0:
                raise ApprovalError("approval ttl must be positive")
            if proposal.is_expired(self._clock()):
                raise ApprovalError("proposal is expired")
            now = self._clock()
            record = ApprovalRecord(
                approval_id=str(uuid.uuid4()),
                proposal_id=proposal.proposal_id,
                proposal_fingerprint=proposal.fingerprint,
                session_id=session_id,
                requirement=requirement,
                status=ApprovalStatus.PENDING,
                requested_at_monotonic=now,
                expires_at_monotonic=min(
                    now + ttl_seconds,
                    proposal.expires_at_monotonic,
                ),
            )
            self._records[record.approval_id] = record
            return record

    def grant(
        self,
        approval_id: str,
        *,
        proposal: ActionProposal,
        session_id: str,
        method: ApprovalMethod,
    ) -> ApprovalRecord:
        with self._lock:
            record = self._active_record(approval_id)
            self._assert_binding(record, proposal=proposal, session_id=session_id)
            if record.status is not ApprovalStatus.PENDING:
                raise ApprovalError(f"approval is not pending: {record.status.value}")
            if _METHOD_LEVEL[method] < record.requirement:
                raise ApprovalError(
                    f"{method.value} does not satisfy {record.requirement.name.lower()}"
                )
            granted = replace(
                record,
                status=ApprovalStatus.GRANTED,
                method=method,
                resolved_at_monotonic=self._clock(),
            )
            self._records[approval_id] = granted
            return granted

    def deny(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            return self._resolve_pending(approval_id, ApprovalStatus.DENIED)

    def cancel(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            return self._resolve_pending(approval_id, ApprovalStatus.CANCELED)

    def get(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            return self._active_record(approval_id)

    def validate(
        self,
        approval_id: str,
        *,
        proposal: ActionProposal,
        session_id: str,
        minimum_requirement: ApprovalRequirement,
    ) -> ApprovalRecord:
        with self._lock:
            record = self._active_record(approval_id)
            self._assert_binding(record, proposal=proposal, session_id=session_id)
            if record.status is not ApprovalStatus.GRANTED:
                raise ApprovalError(f"approval is not granted: {record.status.value}")
            if record.requirement < minimum_requirement:
                raise ApprovalError("approval requirement is too weak")
            if record.method is None:
                raise ApprovalError("approval method is missing")
            if _METHOD_LEVEL[record.method] < minimum_requirement:
                raise ApprovalError("approval method is too weak")
            return record

    def consume(
        self,
        approval_id: str,
        *,
        proposal: ActionProposal,
        session_id: str,
        minimum_requirement: ApprovalRequirement,
    ) -> ApprovalRecord:
        with self._lock:
            record = self.validate(
                approval_id,
                proposal=proposal,
                session_id=session_id,
                minimum_requirement=minimum_requirement,
            )
            consumed = replace(
                record,
                status=ApprovalStatus.CONSUMED,
                resolved_at_monotonic=self._clock(),
            )
            self._records[approval_id] = consumed
            return consumed

    def invalidate_session(self, session_id: str) -> None:
        with self._lock:
            now = self._clock()
            for approval_id, record in tuple(self._records.items()):
                if record.session_id != session_id:
                    continue
                if record.status not in (
                    ApprovalStatus.PENDING,
                    ApprovalStatus.GRANTED,
                ):
                    continue
                self._records[approval_id] = replace(
                    record,
                    status=ApprovalStatus.CANCELED,
                    resolved_at_monotonic=now,
                )

    def _resolve_pending(
        self,
        approval_id: str,
        status: ApprovalStatus,
    ) -> ApprovalRecord:
        record = self._active_record(approval_id)
        if record.status is not ApprovalStatus.PENDING:
            raise ApprovalError(f"approval is not pending: {record.status.value}")
        resolved = replace(
            record,
            status=status,
            resolved_at_monotonic=self._clock(),
        )
        self._records[approval_id] = resolved
        return resolved

    def _active_record(self, approval_id: str) -> ApprovalRecord:
        try:
            record = self._records[approval_id]
        except KeyError as exc:
            raise ApprovalError("unknown approval") from exc
        if (
            record.status in (ApprovalStatus.PENDING, ApprovalStatus.GRANTED)
            and self._clock() >= record.expires_at_monotonic
        ):
            record = replace(
                record,
                status=ApprovalStatus.EXPIRED,
                resolved_at_monotonic=self._clock(),
            )
            self._records[approval_id] = record
        return record

    @staticmethod
    def _assert_proposal_session(
        proposal: ActionProposal,
        session_id: str,
    ) -> None:
        if proposal.session_id != session_id:
            raise ApprovalError("proposal session mismatch")

    @classmethod
    def _assert_binding(
        cls,
        record: ApprovalRecord,
        *,
        proposal: ActionProposal,
        session_id: str,
    ) -> None:
        cls._assert_proposal_session(proposal, session_id)
        if record.session_id != session_id:
            raise ApprovalError("approval session mismatch")
        if record.proposal_id != proposal.proposal_id:
            raise ApprovalError("approval proposal id mismatch")
        if record.proposal_fingerprint != proposal.fingerprint:
            raise ApprovalError("approval proposal fingerprint mismatch")
