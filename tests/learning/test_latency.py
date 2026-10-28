import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import LearningBatch, LearningResolutionBatch
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.learning_runtime import PersonalLearningRuntime


def worker(learning, extractor, clock):
    async def resolve(*args):
        from jarvis.memory.learning_contracts import LearningResolution

        return LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, decision="new")]
        )

    return PersonalLearningRuntime(
        learning.authority,
        learning.service,
        extractor,
        SimpleNamespace(resolve=resolve),
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        clock=clock,
        diagnostics=True,
    )


@pytest.mark.asyncio
async def test_extraction_over_old_ten_second_limit_finishes(learning):
    calls = []

    async def extract(source):
        calls.append(source)
        await asyncio.sleep(10.1)
        from jarvis.memory.learning_contracts import EvidenceSpan, LearningCandidate

        return LearningBatch(
            candidates=[
                LearningCandidate(
                    category="personal_fact",
                    intent="new",
                    label="Northstar Design Limited",
                    value="Northstar Design Limited",
                    evidence=[
                        EvidenceSpan(
                            turn_id=source.turn_id, start=0, end=len(source.text)
                        )
                    ],
                )
            ]
        )

    r = worker(learning, SimpleNamespace(extract=extract), lambda: 100)
    c = ConversationSession()
    c.start()
    try:
        r.bind(c, learning.grant)(
            c.accept_turn(
                ConversationRole.USER, "I work for Northstar Design Limited."
            )
        )
        await asyncio.wait_for(r.drain(), 13)
        assert r.status().reason == "committed" and len(calls) == 1
        assert await learning.count() == 1
        assert r.status().dropped == 0
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_expired_processing_budget_does_not_dispatch(learning):
    from jarvis.memory.learning_contracts import AcceptedLearningSource

    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, "I own a City")
    source = AcceptedLearningSource.from_turn("runtime", c, t, now=100)
    r = worker(learning, SimpleNamespace(), lambda: 129)
    operation = AsyncMock()
    try:
        with pytest.raises(TimeoutError):
            await r._infer(source, operation)
        operation.assert_not_awaited()
    finally:
        await r.close()


@pytest.mark.asyncio
async def test_inference_deadline_uses_remaining_source_age(learning, monkeypatch):
    import jarvis.memory.learning_runtime as module
    from jarvis.memory.learning_contracts import AcceptedLearningSource

    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, "I own a City")
    source = AcceptedLearningSource.from_turn("runtime", c, t, now=100)
    r = worker(learning, SimpleNamespace(), lambda: 124)
    observed = []

    async def wait_for(awaitable, timeout):
        observed.append(timeout)
        return await awaitable

    monkeypatch.setattr(module.asyncio, "wait_for", wait_for)
    operation = AsyncMock(return_value="done")
    try:
        assert await r._infer(source, operation) == "done"
        assert 0 < observed[0] <= 4
    finally:
        await r.close()


def test_automatic_acknowledgement_does_not_imply_a_save():
    from jarvis.voice.agent import PERSONAL_LEARNING_QUERY_INSTRUCTIONS

    assert "I have noted" in PERSONAL_LEARNING_QUERY_INSTRUCTIONS
    assert "acknowledge understanding" in PERSONAL_LEARNING_QUERY_INSTRUCTIONS


def test_direct_sdk_timeout_matches_background_cap(monkeypatch):
    from google import genai

    import jarvis.memory.learning_extractors as module
    from jarvis.memory.learning_limits import INFERENCE_TIMEOUT

    captured = {}

    def client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            aio=SimpleNamespace(
                interactions=SimpleNamespace(
                    sdk_configuration=SimpleNamespace(retry_config="original")
                )
            )
        )

    monkeypatch.setattr(genai, "Client", client)
    monkeypatch.setattr(module, "require_provider_api_key", lambda *a, **k: "fictional")
    adapter, _ = module.build_learning_adapters("gemini", "model")
    assert captured["http_options"]["timeout"] == int(INFERENCE_TIMEOUT * 1000)
    assert adapter.client.aio.interactions.sdk_configuration.retry_config is None


@pytest.mark.asyncio
async def test_unrelated_catalog_needs_no_second_model_request():
    import json

    from jarvis.memory.learning_contracts import (
        AcceptedLearningSource,
        LearningCatalog,
        LearningCatalogEntry,
    )
    from jarvis.memory.learning_extractors import LearningProviderAdapter

    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, "I work at Northstar.")
    source = AcceptedLearningSource.from_turn("runtime", c, t, now=100)
    call = AsyncMock(
        return_value=SimpleNamespace(
            output_text=json.dumps(
                {
                    "candidates": [
                        {
                            "category": "personal_fact",
                            "intent": "new",
                            "label": "Northstar",
                            "value": "Northstar",
                            "evidence": [{"turn_id": t.turn_id, "quote": t.text}],
                        }
                    ]
                }
            )
        )
    )
    a = LearningProviderAdapter(
        "gemini",
        SimpleNamespace(aio=SimpleNamespace(interactions=SimpleNamespace(create=call))),
        "model",
    )
    batch = await a.extract(source)
    catalog = LearningCatalog(
        entries=[
            LearningCatalogEntry(
                assertion_id="bike",
                predicate="owned_item_bike",
                category="owned_item",
                kind="vehicle",
                text="a bike",
                value='{"label":"bike","value":"bike"}',
            )
        ]
    )
    result = await a.resolve(source, batch, catalog)
    assert result.resolutions[0].decision == "new"
    assert call.await_count == 1
