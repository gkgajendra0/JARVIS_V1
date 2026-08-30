from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable

from .types import RiskClass


class PermitStatus(str, Enum):
    PENDING = "pending"
    CONSUMED = "consumed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ExecutionPermit:
    permit_id: str
    decision_id: str
    proposal_id: str
    proposal_fingerprint: str
    session_id: str
    approval_id: str | None
    risk_class: RiskClass
    policy_version: str
    issued_at_monotonic: float
    expires_at_monotonic: float
    status: PermitStatus


class PermitRegistry:
    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_seconds: float = 5.0,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("permit ttl must be positive")
        self._clock = clock
        self._ttl_seconds = ttl_seconds
        self._permits: dict[str, ExecutionPermit] = {}
        self.lock = threading.RLock()

    def issue(
        self,
        *,
        decision_id: str,
        proposal_id: str,
        proposal_fingerprint: str,
        session_id: str,
        approval_id: str | None,
        risk_class: RiskClass,
        policy_version: str,
        proposal_expires_at: float,
    ) -> ExecutionPermit:
        now = self._clock()
        expires_at = min(
            now + self._ttl_seconds,
            proposal_expires_at,
        )
        if expires_at <= now:
            raise ValueError("cannot issue permit for expired proposal")
        permit = ExecutionPermit(
            permit_id=str(uuid.uuid4()),
            decision_id=decision_id,
            proposal_id=proposal_id,
            proposal_fingerprint=proposal_fingerprint,
            session_id=session_id,
            approval_id=approval_id,
            risk_class=risk_class,
            policy_version=policy_version,
            issued_at_monotonic=now,
            expires_at_monotonic=expires_at,
            status=PermitStatus.PENDING,
        )
        with self.lock:
            self._permits[permit.permit_id] = permit
        return permit

    def get_locked(self, permit_id: str) -> ExecutionPermit:
        try:
            permit = self._permits[permit_id]
        except KeyError as exc:
            raise ValueError("unknown execution permit") from exc
        if (
            permit.status is PermitStatus.PENDING
            and self._clock() >= permit.expires_at_monotonic
        ):
            permit = replace(
                permit,
                status=PermitStatus.EXPIRED,
            )
            self._permits[permit_id] = permit
        return permit

    def set_status_locked(
        self,
        permit: ExecutionPermit,
        status: PermitStatus,
    ) -> ExecutionPermit:
        updated = replace(permit, status=status)
        self._permits[permit.permit_id] = updated
        return updated

    def invalidate_session(self, session_id: str) -> None:
        with self.lock:
            for permit_id, permit in tuple(self._permits.items()):
                if (
                    permit.session_id == session_id
                    and permit.status is PermitStatus.PENDING
                ):
                    self._permits[permit_id] = replace(
                        permit,
                        status=PermitStatus.INVALIDATED,
                    )
