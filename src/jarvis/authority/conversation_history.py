"""Explicit original-history scope using the canonical memory delegation owner.

A personal-learning grant cannot be used here. The issuer registry, policy digest,
category and capability are distinct even though permit/lifetime mechanics are
shared. No transcript retention is enabled by merely constructing this issuer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .personal_learning import LearningActionBinding, PersonalLearningAuthority

HISTORY_POLICY_VERSION = "conversation-history-v1"
HISTORY_POLICY_DIGEST = hashlib.sha256(
    b"conversation-history-v1:eligible-original-events:runtime-unlocked-session:explicit-owner"
).hexdigest()


@dataclass(frozen=True)
class HistoryActionBinding(LearningActionBinding):
    categories: tuple[str, ...] = ("conversation_history",)
    policy_version: str = HISTORY_POLICY_VERSION


class ConversationHistoryAuthority(PersonalLearningAuthority):
    CAPABILITY = "memory:conversation_history"
    POLICY_VERSION = HISTORY_POLICY_VERSION
    POLICY_DIGEST = HISTORY_POLICY_DIGEST
    CATEGORIES = frozenset({"conversation_history"})
    SUPPRESSION_KEYS = CATEGORIES
    BINDING_TYPE = HistoryActionBinding
    SESSION_SUMMARY = (
        "Retain eligible original conversation user, assistant and tool events "
        "in encrypted local project history, and read that history for replies. "
        "Permission lasts for this Jarvis runtime and the same unlocked Windows "
        "session, including idle periods; lock, user/session change or shutdown "
        "ends permission. Later speaker identity is not verified. This is broader "
        "than selected personal facts. Source eligibility and pause/forget rules "
        "still apply. No separate cloud extraction call or sensitive-source bypass."
    )

    def register_source(self, grant, receipt_id, *, source=None):
        # Original-event admission is supplied by RequiredConversationRecorder.
        # Keep exact object identity, not a model-supplied source or serialized grant.
        if source is not None:
            from jarvis.memory.project_conversations import ConversationEvent

            if (
                not isinstance(source, ConversationEvent)
                or source.event_id != receipt_id
            ):
                raise PermissionError("canonical conversation event required")
        with self._broker._lock:
            super().register_source(grant, receipt_id)
            record = self._require(grant)
            if source is not None:
                previous = record.source_objects.get(receipt_id)
                if previous is not None and previous is not source:
                    raise PermissionError("history source identity changed")
                record.source_objects[receipt_id] = source

    def authorize_reenable_category(self, category):
        raise PermissionError("history retention requires project lifecycle controls")
