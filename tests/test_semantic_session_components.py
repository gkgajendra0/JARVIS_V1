"""Each voice wake resolves its own guarded semantic components."""

import pytest

from jarvis.conversation import ConversationSession
from jarvis.voice.semantic_context_bridge import (
    SemanticSessionComponents,
    resolve_session_components,
)


async def producer(turn):
    return []


def test_factory_receives_exact_conversation_and_constructs_once_per_wake():
    seen = []

    def factory(conversation):
        seen.append(conversation)
        return SemanticSessionComponents(
            conversation=conversation,
            producer=producer,
            authorization_binding=lambda: conversation.session_id,
        )

    one, two = ConversationSession(), ConversationSession()
    first = resolve_session_components(one, factory=factory)
    second = resolve_session_components(two, factory=factory)
    assert seen == [one, two]
    assert first is not second
    assert first.authorization_binding() != second.authorization_binding()


@pytest.mark.parametrize("result", [None, {}, producer])
def test_invalid_session_factory_result_is_rejected(result):
    with pytest.raises(TypeError):
        resolve_session_components(ConversationSession(), factory=lambda _: result)


def test_noncallable_factory_is_rejected():
    with pytest.raises(TypeError):
        resolve_session_components(ConversationSession(), factory=object())


def test_persistence_requires_accepted_epoch():
    with pytest.raises(TypeError):
        SemanticSessionComponents(
            conversation=ConversationSession(),
            producer=producer,
            authorization_binding=lambda: "grant",
            on_applied=producer,
        )


@pytest.mark.parametrize(
    "field", ["producer", "authorization_binding", "on_applied", "accepted_plan_epoch"]
)
def test_noncallable_components_are_rejected(field):
    values = {
        "conversation": ConversationSession(),
        "producer": producer,
        "authorization_binding": lambda: "grant",
    }
    values[field] = object()
    with pytest.raises(TypeError):
        SemanticSessionComponents(**values)


def test_components_bound_to_another_wake_are_rejected():
    other = ConversationSession()
    components = SemanticSessionComponents(
        conversation=other, producer=producer, authorization_binding=lambda: "grant"
    )
    with pytest.raises(ValueError, match="conversation"):
        resolve_session_components(ConversationSession(), factory=lambda _: components)
