"""Full transcript permission is separate from the existing fact-learning grant."""

from dataclasses import replace

import pytest

from jarvis.authority.conversation_history import (
    ConversationHistoryAuthority,
    HistoryActionBinding,
)
from jarvis.authority.personal_learning import LearningActionBinding


def test_history_requires_its_own_owner_permission(authority, authority_parts):
    old_grant = authority.open("runtime", "gemini")
    history = ConversationHistoryAuthority(authority_parts.broker)
    assert history.validate(old_grant).status == "denied"
    grant = history.open("runtime", "gemini")
    history.register_source(grant, "event-1")
    binding = HistoryActionBinding("admit", "event-1", "a" * 64)
    permit = history.issue_child(grant, binding)
    with history.commit_scope(permit):
        history.validate_write(permit)
    assert len(authority_parts.hello.calls) == 2
    assert "original conversation" in authority_parts.hello.calls[-1].material_summary
    with pytest.raises(PermissionError):
        history.issue_child(
            grant, LearningActionBinding("admit", "event-1", "a" * 64, ("plan",))
        )


def test_history_binding_cannot_be_consumed_by_fact_learning(
    authority, authority_parts
):
    history = ConversationHistoryAuthority(authority_parts.broker)
    grant = history.open("runtime", "gemini")
    history.register_source(grant, "event-1")
    permit = history.issue_child(
        grant, HistoryActionBinding("admit", "event-1", "a" * 64)
    )
    with pytest.raises(PermissionError), authority.commit_scope(permit):
        pass


def test_history_rechecks_windows_continuity_at_commit(authority_parts):
    history = ConversationHistoryAuthority(authority_parts.broker)
    grant = history.open("runtime", "gemini")
    history.register_source(grant, "event-1")
    permit = history.issue_child(
        grant, HistoryActionBinding("admit", "event-1", "a" * 64)
    )
    authority_parts.windows.lock_unlock()
    with pytest.raises(PermissionError), history.commit_scope(permit):
        pass


def test_history_child_cannot_expand_categories(authority_parts):
    history = ConversationHistoryAuthority(authority_parts.broker)
    grant = history.open("runtime", "gemini")
    history.register_source(grant, "event-1")
    with pytest.raises(PermissionError):
        history.issue_child(
            grant,
            replace(
                HistoryActionBinding("admit", "event-1", "a" * 64),
                categories=("owned_item",),
            ),
        )
