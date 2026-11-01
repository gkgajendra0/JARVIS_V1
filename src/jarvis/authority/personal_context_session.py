"""One Windows Hello approval for a bounded, read-only personal-fact session.

This replaces a fresh Hello on every personal question with one owner approval
that lasts at most 30 minutes, ends after 10 minutes without a personal read,
and ends at once on Windows lock, user/session change or Jarvis shutdown. It
only reads standard current owner facts. Remembering, correcting and
forgetting facts, and every Hands or Work action, keep their own approvals.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from jarvis.personal_learning_scope import CATEGORIES

from .personal_learning import (
    LearningActionBinding,
    LearningSessionState,
    PersonalLearningAuthority,
)
from .proposal import canonical_json

SESSION_POLICY_VERSION = "personal-context-session-v1"
ABSOLUTE_LIMIT_SECONDS = 30 * 60
IDLE_LIMIT_SECONDS = 10 * 60

SESSION_POLICY_DIGEST = hashlib.sha256(
    canonical_json(
        {
            "version": SESSION_POLICY_VERSION,
            "categories": sorted(CATEGORIES),
            "operations": ["read"],
            "absolute_seconds": ABSOLUTE_LIMIT_SECONDS,
            "idle_seconds": IDLE_LIMIT_SECONDS,
            "lifetime": "runtime_and_unlocked_windows_session",
            "sensitivity": "standard",
        }
    ).encode()
).hexdigest()


@dataclass(frozen=True)
class PersonalContextSessionBinding(LearningActionBinding):
    policy_version: str = SESSION_POLICY_VERSION


class PersonalContextSessionAuthority(PersonalLearningAuthority):
    CAPABILITY = "memory:personal_context_session"
    POLICY_VERSION = SESSION_POLICY_VERSION
    POLICY_DIGEST = SESSION_POLICY_DIGEST
    BINDING_TYPE = PersonalContextSessionBinding
    SESSION_SUMMARY = (
        "Let Jarvis read your standard saved personal facts when they help answer, "
        "for up to 30 minutes in this unlocked Windows session. It ends after 10 "
        "minutes without a personal question, or at once on Windows lock, user or "
        "session change, or Jarvis shutdown. Read only: remembering, correcting or "
        "forgetting facts and every action still ask separately. Later speaker "
        "identity is not verified. No sensitive facts."
    )

    def _snapshot(self, grant):
        state = super()._snapshot(grant)
        if state.status != "active":
            return state
        record = self._grants[grant]
        now = self._broker._clock()
        if now - record.created >= ABSOLUTE_LIMIT_SECONDS:
            return LearningSessionState("expired", "absolute_limit")
        if now - record.last_input >= IDLE_LIMIT_SECONDS:
            return LearningSessionState("expired", "idle_limit")
        return state

    def validate(self, grant):
        with self._broker._lock:
            state = super().validate(grant)
            if state.status == "expired":
                # Expiry is final: a new session needs a new owner approval.
                self.revoke(grant, state.reason)
            return state

    def issue_child(self, grant, binding):
        if getattr(binding, "operation", None) != "read":
            raise PermissionError("personal context session is read-only")
        with self._broker._lock:
            handle = super().issue_child(grant, binding)
            # Idle time counts from the last personal read, not the last utterance.
            self._grants[grant].last_input = self._broker._clock()
            return handle

    def observe_accepted_input(self, grant, turn_id):
        # Ordinary speech does not keep a read session alive; only reads do.
        with self._broker._lock:
            self._require(grant)

    def authorize_reenable_category(self, category):
        raise PermissionError("personal context session cannot change categories")
