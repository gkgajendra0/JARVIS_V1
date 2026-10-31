"""Semantic dispatch stays bound to the accepted source and owner generation."""

from dataclasses import replace

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_semantics import SemanticRejected
from jarvis.memory.semantic_model_producer import build_session_semantic_producer
from jarvis.memory.types import Sensitivity


class Client:
    def __init__(self):
        self.calls = 0
        self.before = lambda: None
        self.after = lambda: None

    async def parse(self, **kwargs):
        self.before()
        kwargs["before_dispatch"]()
        self.calls += 1
        self.after()
        return {"proposals": []}


def setup():
    conversation = ConversationSession()
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Nepal trip")
    binding = ["owner-grant-1"]
    client = Client()
    producer = build_session_semantic_producer(
        conversation=conversation,
        client=client,
        authorization_binding=lambda: binding[0],
        source_clearance=lambda _: Sensitivity.STANDARD,
    )
    return conversation, turn, binding, client, producer


@pytest.mark.asyncio
async def test_current_source_with_live_owner_is_dispatched():
    _, turn, _, client, producer = setup()
    assert await producer(turn) == []
    assert client.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["copied", "foreign", "assistant", "closed", "missing"]
)
async def test_noncanonical_or_unauthorized_source_never_dispatches(kind):
    conversation, turn, binding, client, producer = setup()
    if kind == "copied":
        turn = replace(turn)
    elif kind == "foreign":
        other = ConversationSession()
        other.start()
        turn = other.accept_turn(ConversationRole.USER, turn.text)
    elif kind == "assistant":
        turn = conversation.accept_turn(ConversationRole.ASSISTANT, "Nepal trip")
    elif kind == "closed":
        conversation.close()
    else:
        binding[0] = None
    with pytest.raises(SemanticRejected):
        await producer(turn)
    assert client.calls == 0


@pytest.mark.asyncio
async def test_owner_rotation_before_network_dispatch_denies_release():
    _, turn, binding, client, producer = setup()
    client.before = lambda: binding.__setitem__(0, "owner-grant-2")
    with pytest.raises(SemanticRejected):
        await producer(turn)
    assert client.calls == 0


@pytest.mark.asyncio
async def test_owner_rotation_during_inference_discards_result():
    _, turn, binding, client, producer = setup()
    client.after = lambda: binding.__setitem__(0, "owner-grant-2")
    with pytest.raises(SemanticRejected):
        await producer(turn)
    assert client.calls == 1


@pytest.mark.asyncio
async def test_privacy_callback_cannot_rotate_authority_and_release_source():
    conversation, turn, binding, client, _ = setup()

    def classify(_):
        binding[0] = "owner-grant-2"
        return Sensitivity.STANDARD

    producer = build_session_semantic_producer(
        conversation=conversation,
        client=client,
        authorization_binding=lambda: binding[0],
        source_clearance=classify,
    )
    with pytest.raises(SemanticRejected):
        await producer(turn)
    assert client.calls == 0


@pytest.mark.asyncio
async def test_privacy_failure_is_denied_without_dispatch():
    conversation, turn, binding, client, _ = setup()

    def classify(_):
        raise RuntimeError("classifier unavailable")

    producer = build_session_semantic_producer(
        conversation=conversation,
        client=client,
        authorization_binding=lambda: binding[0],
        source_clearance=classify,
    )
    with pytest.raises(SemanticRejected):
        await producer(turn)
    assert client.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision",
    [
        None,
        Sensitivity.PRIVATE,
        Sensitivity.LOCAL_ONLY,
        Sensitivity.SECRET_PROHIBITED,
        "standard",
    ],
)
async def test_session_producer_does_not_relax_privacy_decisions(decision):
    conversation, turn, binding, client, _ = setup()
    producer = build_session_semantic_producer(
        conversation=conversation,
        client=client,
        authorization_binding=lambda: binding[0],
        source_clearance=lambda _: decision,
    )
    with pytest.raises(SemanticRejected):
        await producer(turn)
    assert client.calls == 0
