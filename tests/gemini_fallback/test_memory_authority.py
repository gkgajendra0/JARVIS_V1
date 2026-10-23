import json

import pytest
from google.genai.errors import APIError
from tests.gemini_fallback.test_hands_memory import response, shared
from tests.learning.conftest import (
    authority,
    authority_parts,
    clock,
    learning,
)

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_extractors import build_learning_adapters
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.learning_runtime import PersonalLearningRuntime

__all__ = ["authority", "authority_parts", "clock", "learning"]


def proposal(request):
    payload = json.loads(request["input"])
    return response(
        {
            "candidates": [
                {
                    "category": "owned_item",
                    "kind": "vehicle",
                    "intent": "new",
                    "label": "City",
                    "value": "City",
                    "state": "owned",
                    "evidence": [
                        {"turn_id": payload["current_turn_id"], "quote": "City"}
                    ],
                }
            ]
        }
    )


def start(learning, clock, routing):
    adapter, resolver = build_learning_adapters(
        "gemini", "gemini-budget-test", routing_runtime=routing
    )
    runtime = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        adapter,
        resolver,
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        clock=clock,
    )
    conversation = ConversationSession()
    conversation.start()
    observe = runtime.bind(conversation, learning.grant)
    observe(conversation.accept_turn(ConversationRole.USER, "I own a City"))
    return runtime


@pytest.mark.asyncio
async def test_paid_inference_still_produces_one_real_canonical_effect(
    tmp_path, monkeypatch, learning, clock
):
    routing, env = shared(
        tmp_path,
        monkeypatch,
        {"free-private-canary": [APIError(429, {})], "paid-private-canary": [proposal]},
    )
    runtime = start(learning, clock, routing)
    try:
        await runtime.drain()
        assert await learning.count() == 1
        assert runtime.status().committed == 1
        assert len(env[3]) == 2
    finally:
        await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("invalidates", ["source_expiry", "lock", "forget"])
async def test_source_invalidated_after_free_failure_is_not_released_to_paid(
    tmp_path, monkeypatch, learning, clock, authority_parts, invalidates
):
    active = []

    def free_failure(_):
        if invalidates == "source_expiry":
            clock.advance(31)
        elif invalidates == "lock":
            authority_parts.windows.lock_unlock()
        else:
            active[0].invalidate_sources(category="owned_item.vehicle")
        return APIError(429, {})

    routing, env = shared(
        tmp_path,
        monkeypatch,
        {"free-private-canary": [free_failure], "paid-private-canary": [proposal]},
    )
    runtime = start(learning, clock, routing)
    active.append(runtime)
    try:
        await runtime.drain()
        assert await learning.count() == 0
        assert len(env[3]) == 1
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_expiry_during_paid_answer_blocks_admission_without_extending_deadline(
    tmp_path, monkeypatch, learning, clock
):
    def expired_answer(request):
        clock.advance(31)
        return proposal(request)

    routing, env = shared(
        tmp_path,
        monkeypatch,
        {
            "free-private-canary": [APIError(429, {})],
            "paid-private-canary": [expired_answer],
        },
    )
    runtime = start(learning, clock, routing)
    try:
        await runtime.drain()
        assert len(env[3]) == 2
        assert await learning.count() == 0
        assert runtime.status().committed == 0
    finally:
        await runtime.close()
