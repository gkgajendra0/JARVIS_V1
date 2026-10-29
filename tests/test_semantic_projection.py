"""Topic projection is limited to a fresh authorized named-topic response."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.context import ContextItemKind
from jarvis.memory.conversation_semantics import (
    EvidenceStrength,
    GroundedStateValue,
    TopicSnapshot,
)
from jarvis.memory.semantic_projection import (
    ContextReleaseDenied,
    SemanticContextProjector,
)
from jarvis.memory.types import Sensitivity


def field(source_id, value, *, completed=False, sensitivity=Sensitivity.STANDARD):
    return GroundedStateValue(
        value=value,
        evidence=value,
        source_turn_id=source_id,
        accepted_at=datetime(2026, 10, 29, tzinfo=UTC),
        sensitivity=sensitivity,
        evidence_strength=EvidenceStrength.LITERAL,
        completed=completed,
    )


def state():
    return TopicSnapshot(
        title="Nepal trip",
        goal=field("t-goal", "plan my Nepal road trip"),
        constraints=(
            ("permits", field("t-permits", "sorted")),
            ("budget", field("t-budget", "unrestricted")),
        ),
        steps=(
            ("route", field("t-route", "plan the route")),
            ("documents", field("t-documents", "documents completed", completed=True)),
        ),
    )


def request(text):
    session = ConversationSession()
    session.start()
    turn = session.accept_turn(ConversationRole.USER, text)
    return session, turn


def test_authorized_nepal_projection_includes_known_facts_and_only_pending_steps():
    c, turn = request("Continue with my Nepal trip")
    projector = SemanticContextProjector(
        validate_release=lambda *_: True,
        max_bytes=4096,
    )
    packet = projector.assemble_named(c, turn, state())
    kinds = [item.kind for item in packet.items]
    assert ContextItemKind.CURRENT_TURN in kinds
    assert ContextItemKind.ACTIVE_TOPIC in kinds
    assert ContextItemKind.ACTIVE_GOAL in kinds
    assert ContextItemKind.UNRESOLVED_WORK in kinds
    assert kinds.count(ContextItemKind.ENTITY) == 2
    texts = [item.text for item in packet.items]
    assert any("plan the route" in text for text in texts)
    assert any("unrestricted" in text for text in texts)
    assert not any("documents completed" in text for text in texts)
    assert sum(item.budget_units for item in packet.items) == packet.used_units


def test_unrequested_cross_day_context_is_denied():
    c, turn = request("Okay, continue")
    projector = SemanticContextProjector(validate_release=lambda *_: True)
    with pytest.raises(ContextReleaseDenied, match="does not name"):
        projector.assemble_named(c, turn, state())


def test_second_permit_check_blocks_release_after_revocation():
    c, turn = request("Continue Nepal trip")
    calls = [0]

    def permit(*_):
        calls[0] += 1
        return calls[0] == 1

    projector = SemanticContextProjector(validate_release=permit)
    with pytest.raises(ContextReleaseDenied, match="not authorized"):
        projector.assemble_named(c, turn, state())
    assert calls[0] == 2


def test_assistant_turn_cannot_request_context():
    c = ConversationSession()
    c.start()
    turn = c.accept_turn(ConversationRole.ASSISTANT, "Continue Nepal trip")
    projector = SemanticContextProjector(validate_release=lambda *_: True)
    with pytest.raises(ContextReleaseDenied, match="canonical owner"):
        projector.assemble_named(c, turn, state())


def test_restricted_context_is_not_released_even_with_a_valid_permit():
    c, turn = request("Continue Nepal trip")
    snapshot = TopicSnapshot(
        title="Nepal trip",
        goal=None,
        constraints=(
            ("health", field("private", "restricted value",
                             sensitivity=Sensitivity.LOCAL_ONLY)),
            ("budget", field("budget", "unrestricted")),
        ),
        steps=(),
    )
    projector = SemanticContextProjector(validate_release=lambda *_: True)
    packet = projector.assemble_named(c, turn, snapshot)
    texts = [item.text for item in packet.items]
    assert any("unrestricted" in text for text in texts)
    assert all("restricted value" not in text for text in texts)


def test_stale_request_cannot_release_previous_context():
    c, turn = request("Continue Nepal trip")
    c.accept_turn(ConversationRole.USER, "Let's discuss something else")
    projector = SemanticContextProjector(validate_release=lambda *_: True)
    with pytest.raises(ContextReleaseDenied, match="latest canonical"):
        projector.assemble_named(c, turn, state())
