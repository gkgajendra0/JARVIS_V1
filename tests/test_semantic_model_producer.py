"""Untrusted structured semantic proposals cannot bypass dispatch clearance."""

from __future__ import annotations

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.conversation_semantics import SemanticAction, SemanticRejected
from jarvis.memory.semantic_model_producer import RoutedSemanticProducer
from jarvis.memory.types import Sensitivity


class FakeModel:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0
        self.last_request = None

    async def parse(self, **kwargs):
        kwargs["before_dispatch"]()
        self.calls += 1
        self.last_request = kwargs
        return self.payload


class SequenceModel:
    def __init__(self, payloads):
        self.payloads = payloads
        self.requests = []
        self.before = lambda: None
        self.calls = 0

    async def parse(self, **kwargs):
        self.before()
        kwargs["before_dispatch"]()
        self.requests.append(kwargs)
        result = self.payloads[self.calls]
        self.calls += 1
        return result


@pytest.mark.asyncio
async def test_missing_model_value_gets_one_guarded_correction_before_reducer():
    from jarvis.memory.conversation_semantics import SemanticContextEngine

    conversation = ConversationSession()
    conversation.start()
    text = "I am planning a Nepal trip."
    source = conversation.accept_turn(ConversationRole.USER, text)
    client = SequenceModel(
        [
            {
                "proposals": [
                    {
                        "action": "topic",
                        "quote": text,
                        "topic": "MODEL_PAYLOAD_MUST_NOT_BE_ECHOED",
                    }
                ]
            },
            {"proposals": [{"action": "topic", "quote": text, "value": "Nepal trip"}]},
        ]
    )
    producer = RoutedSemanticProducer(
        client=client,
        source_clearance=lambda _: Sensitivity.STANDARD,
        scope_id=conversation.session_id,
    )
    proposals = await producer(source)
    state = SemanticContextEngine()
    state.apply(conversation, source, proposals, epoch=state.epoch)
    assert state.active_topic == "Nepal trip"
    assert client.calls == 2
    assert client.requests[0]["operation_id"] != client.requests[1]["operation_id"]
    assert "MODEL_PAYLOAD_MUST_NOT_BE_ECHOED" not in client.requests[1]["system_prompt"]
    assert [r["input_payload"] for r in client.requests] == [
        {"utterance": text},
        {"utterance": text},
    ]


@pytest.mark.asyncio
async def test_repeated_missing_value_stops_after_one_correction_attempt():
    text = "I am planning a Nepal trip."
    invalid = {"proposals": [{"action": "topic", "quote": text}]}
    client = SequenceModel([invalid, invalid])
    producer = RoutedSemanticProducer(
        client=client, source_clearance=lambda _: Sensitivity.STANDARD, scope_id="test"
    )
    with pytest.raises(SemanticRejected, match="missing semantic value"):
        await producer(user_turn(text))
    assert client.calls == 2


@pytest.mark.asyncio
async def test_revocation_before_correction_dispatch_blocks_second_request():
    text = "I am planning a Nepal trip."
    invalid = {"proposals": [{"action": "topic", "quote": text}]}
    client = SequenceModel([invalid])
    approved = [True]

    def before():
        if client.calls == 1:
            approved[0] = False

    client.before = before
    producer = RoutedSemanticProducer(
        client=client,
        source_clearance=lambda _: Sensitivity.STANDARD if approved[0] else None,
        scope_id="test",
    )
    with pytest.raises(SemanticRejected, match="denied"):
        await producer(user_turn(text))
    assert client.calls == 1


@pytest.mark.asyncio
async def test_gemini_wire_schema_requires_value_and_valid_reply_needs_no_correction():
    import json
    from types import SimpleNamespace

    from jarvis.hands.provider_adapters import GeminiStructuredOutputClient
    from jarvis.memory.conversation_semantics import SemanticContextEngine

    calls = []
    text = "I am planning a Nepal trip."

    async def create(**kwargs):
        calls.append(kwargs)
        wire = kwargs["response_format"]["schema"]["$defs"]["StructuredSemanticPatch"]
        assert "value" in wire["required"]
        return SimpleNamespace(
            output_text=json.dumps(
                {
                    "proposals": [
                        {"action": "topic", "quote": text, "value": "Nepal trip"},
                    ]
                }
            )
        )

    sdk = SimpleNamespace(
        aio=SimpleNamespace(interactions=SimpleNamespace(create=create))
    )
    adapter = GeminiStructuredOutputClient(client=sdk, model="synthetic-model")

    class Boundary:
        async def parse(self, **kwargs):
            kwargs["before_dispatch"]()
            return await adapter.parse(
                system_prompt=kwargs["system_prompt"],
                input_payload=kwargs["input_payload"],
                response_model=kwargs["response_model"],
            )

    conversation = ConversationSession()
    conversation.start()
    source = conversation.accept_turn(ConversationRole.USER, text)
    producer = RoutedSemanticProducer(
        client=Boundary(),
        source_clearance=lambda _: Sensitivity.STANDARD,
        scope_id=conversation.session_id,
    )
    state = SemanticContextEngine()
    proposals = await producer(source)
    state.apply(conversation, source, proposals, epoch=state.epoch)
    assert state.active_topic == "Nepal trip"
    assert len(calls) == 1


def user_turn(text):
    conversation = ConversationSession()
    conversation.start()
    return conversation.accept_turn(ConversationRole.USER, text)


@pytest.mark.asyncio
async def test_model_producer_preserves_quoted_hinglish_evidence():
    turn = user_turn("Budget ka issue nahi hai")
    client = FakeModel(
        {
            "proposals": [
                {
                    "action": "constraint",
                    "quote": "Budget ka issue nahi hai",
                    "key": "budget",
                    "value": "unrestricted",
                }
            ]
        }
    )
    producer = RoutedSemanticProducer(
        client=client,
        source_clearance=lambda _: Sensitivity.STANDARD,
        scope_id="current-owner-runtime",
    )
    patches = await producer(turn)
    assert len(patches) == 1
    assert patches[0].action is SemanticAction.CONSTRAINT
    assert patches[0].quote == turn.text
    assert patches[0].start == 0
    assert patches[0].end == len(turn.text)
    assert patches[0].value == "unrestricted"
    assert client.calls == 1
    assert client.last_request["input_payload"] == {"utterance": turn.text}


@pytest.mark.asyncio
async def test_single_explicit_topic_precedes_dependent_goal_in_model_batch():
    from jarvis.memory.conversation_semantics import SemanticContextEngine

    conversation = ConversationSession()
    conversation.start()
    text = "I am planning a Nepal trip"
    source = conversation.accept_turn(ConversationRole.USER, text)
    client = FakeModel(
        {
            "proposals": [
                {
                    "action": "goal",
                    "quote": text,
                    "value": "planning a Nepal trip",
                    "topic": "Nepal trip",
                },
                {"action": "topic", "quote": text, "value": "Nepal trip"},
            ]
        }
    )
    producer = RoutedSemanticProducer(
        client=client,
        source_clearance=lambda _: Sensitivity.STANDARD,
        scope_id=conversation.session_id,
    )
    patches = await producer(source)
    state = SemanticContextEngine()
    assert state.apply(conversation, source, patches, epoch=state.epoch) == 2
    assert state.snapshot().title == "Nepal trip"
    assert state.snapshot().goal.value == "planning a Nepal trip"


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["", "Other trip"])
async def test_topic_order_repair_never_guesses_implicit_or_foreign_target(target):
    from jarvis.memory.conversation_semantics import SemanticContextEngine

    conversation = ConversationSession()
    conversation.start()
    text = "I am planning a Nepal trip"
    source = conversation.accept_turn(ConversationRole.USER, text)
    producer = RoutedSemanticProducer(
        client=FakeModel(
            {
                "proposals": [
                    {
                        "action": "goal",
                        "quote": text,
                        "value": "planning a Nepal trip",
                        "topic": target,
                    },
                    {"action": "topic", "quote": text, "value": "Nepal trip"},
                ]
            }
        ),
        source_clearance=lambda _: Sensitivity.STANDARD,
        scope_id=conversation.session_id,
    )
    state = SemanticContextEngine()
    patches = await producer(source)
    with pytest.raises(SemanticRejected):
        state.apply(conversation, source, patches, epoch=state.epoch)
    assert state.snapshot() is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clearance",
    (None, Sensitivity.PRIVATE, Sensitivity.LOCAL_ONLY, Sensitivity.SECRET_PROHIBITED),
)
async def test_model_never_receives_uncleared_source(clearance):
    turn = user_turn("My medical details are private")
    client = FakeModel({"proposals": []})
    producer = RoutedSemanticProducer(
        client=client,
        source_clearance=lambda _: clearance,
        scope_id="current-owner-runtime",
    )
    with pytest.raises(SemanticRejected, match="denied"):
        await producer(turn)
    assert client.calls == 0


@pytest.mark.asyncio
async def test_revocation_before_network_dispatch_fails_closed():
    turn = user_turn("Nepal trip")
    checks = [0]

    def permission(_):
        checks[0] += 1
        return Sensitivity.STANDARD if checks[0] == 1 else None

    client = FakeModel({"proposals": []})
    producer = RoutedSemanticProducer(
        client=client,
        source_clearance=permission,
        scope_id="current-owner-runtime",
    )
    with pytest.raises(SemanticRejected, match="denied"):
        await producer(turn)
    assert client.calls == 0


@pytest.mark.asyncio
async def test_repeated_or_unsupported_quote_is_rejected():
    turn = user_turn("Nepal and Nepal")
    client = FakeModel(
        {"proposals": [{"action": "topic", "quote": "Nepal", "value": "Nepal"}]}
    )
    producer = RoutedSemanticProducer(
        client=client,
        source_clearance=lambda _: Sensitivity.STANDARD,
        scope_id="current-owner-runtime",
    )
    with pytest.raises(SemanticRejected, match="ambiguous"):
        await producer(turn)


@pytest.mark.asyncio
async def test_normal_chatter_can_yield_no_context_update():
    turn = user_turn("How are you?")
    producer = RoutedSemanticProducer(
        client=FakeModel({"proposals": []}),
        source_clearance=lambda _: Sensitivity.STANDARD,
        scope_id="current-owner-runtime",
    )
    assert await producer(turn) == []


@pytest.mark.asyncio
async def test_routed_semantic_factory_uses_approved_free_paid_router(monkeypatch):
    from jarvis.hands import provider_adapters
    from jarvis.memory.semantic_model_producer import (
        build_routed_semantic_producer,
    )

    constructed = []

    class FakeRouted:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        async def parse(self, **kwargs):
            kwargs["before_dispatch"]()
            return {"proposals": []}

    monkeypatch.setattr(provider_adapters, "RoutedStructuredOutputClient", FakeRouted)
    runtime = object()
    producer = build_routed_semantic_producer(
        routing_runtime=runtime,
        model="test-model",
        source_clearance=lambda _turn: Sensitivity.STANDARD,
        scope_id="owner-voice-session",
    )
    assert await producer(user_turn("Nepal trip")) == []
    assert constructed == [
        {
            "routing_runtime": runtime,
            "role": "memory.extraction",
            "model": "test-model",
            "max_output_tokens": 1024,
            "free_output_tokens": 1024,
        }
    ]


def test_routed_semantics_require_explicit_source_clearance():
    from jarvis.memory.semantic_model_producer import (
        build_routed_semantic_producer,
    )

    with pytest.raises(TypeError, match="independent source clearance"):
        build_routed_semantic_producer(
            routing_runtime=object(),
            model="test-model",
            source_clearance=None,
            scope_id="owner-voice-session",
        )
