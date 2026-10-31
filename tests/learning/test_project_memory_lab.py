import pytest

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.voice.project_memory_lab import (
    prepare_project_profile,
    standard_history_source,
    verify_source,
)


def test_project_profile_is_isolated_marked_and_resumable(tmp_path):
    from jarvis.machine_config import save_machine_settings

    source = tmp_path / "production" / "machine.json"
    source.parent.mkdir()
    save_machine_settings({"JARVIS_AI_PROVIDER": "gemini"}, source)
    original = source.read_text()
    lab = tmp_path / "lab"
    profile = prepare_project_profile(source, lab, resume=False)
    assert profile.parent == lab and profile.exists()
    assert prepare_project_profile(source, lab, resume=True) == profile
    assert source.read_text() == original
    (lab / "project-memory.marker").write_text("wrong")
    with pytest.raises(ValueError):
        prepare_project_profile(source, lab, resume=True)
    with pytest.raises(ValueError):
        prepare_project_profile(source, source.parent, resume=False)


def test_history_eligibility_preserves_negative_statements_but_excludes_secrets():
    assert standard_history_source(
        ConversationTurn(ConversationRole.USER, "We will not take the Jimny")
    )
    assert not standard_history_source(
        ConversationTurn(ConversationRole.USER, "My password is secret123")
    )
    assert not standard_history_source(
        ConversationTurn(ConversationRole.USER, "My medical diagnosis is private")
    )


def test_exact_source_verification_rejects_unavailable_revision(tmp_path):
    with pytest.raises(ValueError):
        verify_source(tmp_path, "a" * 40)


@pytest.mark.asyncio
async def test_text_lab_reads_real_canonical_personal_facts_with_exact_owner_consent(
    learning, authority_parts
):
    from types import SimpleNamespace

    from jarvis.capabilities.discovery import CapabilityResolver
    from jarvis.capabilities.runtime import CapabilityRuntime
    from jarvis.conversation import ConversationSession
    from jarvis.memory.retrieval import SemanticRetrievalService
    from jarvis.voice.project_memory_lab import build_project_personal_session

    await learning.service.admit_learning(learning.plan, learning.new_permit())
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, "What vehicle can I take to Nepal?")
    capability = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=authority_parts.broker,
    )
    memory = SimpleNamespace(retrieval=SemanticRetrievalService(learning.reader))
    session = build_project_personal_session(conversation, memory, capability)
    try:
        result = await session.query_for_question([{"scope_key": "owned_item.vehicle"}])
        assert result["status"] == "selected"
        assert "City" in str(result["facts"])
        assert len(authority_parts.hello.calls) == 2
    finally:
        session.close()
