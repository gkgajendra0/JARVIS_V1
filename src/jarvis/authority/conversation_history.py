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

    def read_scope(self, permit):
        from contextlib import contextmanager

        @contextmanager
        def scope():
            with self._broker._lock:
                self.consume_read(permit)
                self.validate_read(permit)
                yield
                self.validate_read(permit)

        return scope()

    def authorize_project_deletion(self, material):
        return self._authorize_history_change(
            material,
            target={"project_id": material["project_id"]},
            summary="Forget this project's retained conversation content and derived state, including "
            f"{int(material.get('derived_count', 0))} Jarvis replies or tool results in other projects "
            "that were generated with it in context; your own messages elsewhere are kept. "
            "Minimal deletion identities are preserved to block late writes.",
            destructive=True,
        )

    def authorize_mention_deletion(self, material):
        """Fresh owner approval (Windows Hello) to forget what was said about
        something: only rows containing all the words, and Jarvis replies or
        tool results generated with them in context."""
        if material.get("operation") != "forget_mentions":
            raise ValueError("mention deletion material required")
        words = " ".join(material.get("terms", ()))
        where = ", ".join(material.get("projects", ())) or "no project"
        facts = int(material.get("personal_facts", 0))
        personal = (
            f" Also {facts} personal fact{'s' if facts != 1 else ''} saved from "
            "those messages."
            if facts
            else ""
        )
        return self._authorize_history_change(
            material,
            target={"mentions": material["digest"]},
            summary=f"Forget saved conversation mentioning '{words}': "
            f"{int(material.get('owner_rows', 0))} of your messages and "
            f"{int(material.get('jarvis_rows', 0))} Jarvis replies or tool results "
            f"generated with them, in: {where}.{personal} Everything else is kept. "
            "Minimal deletion identities are preserved to block late writes.",
            destructive=True,
        )

    def authorize_quarantine_resolution(self, material):
        """Fresh owner approval to end the upgrade quarantine (Windows Hello)."""
        if material.get("action") not in {"delete", "restore"}:
            raise ValueError("quarantine action must be delete or restore")
        where = ", ".join(
            f"{title} ({count})" for title, count in material.get("projects", ())
        )
        count = int(material.get("count", 0))
        summary = (
            f"Permanently delete {count} older Jarvis replies/tool results that may "
            f"repeat a forgotten project, in: {where}. Your own messages are kept."
            if material["action"] == "delete"
            else f"Restore {count} older Jarvis replies/tool results in: {where}. "
            "They may repeat information from a project you forgot."
        )
        return self._authorize_history_change(
            material,
            target={"quarantine": "upgrade"},
            summary=summary,
            destructive=material["action"] == "delete",
        )

    def _authorize_history_change(self, material, *, target, summary, destructive):
        from uuid import uuid4

        from jarvis.authority.personal_learning import LearningPermitHandle
        from jarvis.authority.types import ActionAttributes, ActionOrigin
        from jarvis.capabilities.execution import PreparedCapability
        from jarvis.capabilities.models import CapabilityRequest
        from jarvis.memory.project_conversation_store import archive_digest

        digest = archive_digest(material)
        prepared = PreparedCapability(
            CapabilityRequest(
                str(uuid4()),
                self.CAPABILITY,
                "forget",
                {"payload_sha256": digest},
                ActionOrigin.DIRECT_USER,
            ),
            target,
            {"payload_sha256": digest},
            summary,
            ActionAttributes(persistent_write=True, destructive=destructive),
            {},
        )
        with self._broker._lock:
            authorized = self._broker.authorize_fresh_owner(prepared)
            if not hasattr(self, "_deletions"):
                self._deletions = {}
            if len(self._deletions) >= 32:
                raise PermissionError("deletion approval limit")
            handle = LearningPermitHandle(str(uuid4()))
            self._deletions[handle] = (digest, authorized)
            return handle

    def deletion_scope(self, permit, material):
        from contextlib import contextmanager

        from jarvis.memory.project_conversation_store import archive_digest

        @contextmanager
        def scope():
            with self._broker._lock:
                record = getattr(self, "_deletions", {}).pop(permit, None)
                if record is None or record[0] != archive_digest(material):
                    raise PermissionError("exact project deletion approval required")
                self._broker.validate_binding(record[1])
                self._broker.consume(record[1])
                yield lambda: self._broker.validate_binding(record[1])
                self._broker.validate_binding(record[1])

        return scope()
