import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_contracts import AcceptedLearningSource, LearningCatalog
from jarvis.memory.learning_extractors import LearningProviderAdapter


def source(text):
    c = ConversationSession()
    c.start()
    t = c.accept_turn(ConversationRole.USER, text)
    return AcceptedLearningSource.from_turn("runtime", c, t, now=100)


def client(payload):
    call = AsyncMock(return_value=SimpleNamespace(output_text=json.dumps(payload)))
    return SimpleNamespace(
        aio=SimpleNamespace(
            interactions=SimpleNamespace(create=call), aclose=AsyncMock()
        )
    ), call


@pytest.mark.asyncio
async def test_two_vehicles_grounded_with_original_quotes_and_one_request():
    s = source("मेरे पास सिटी और क्लासिक हैं")
    payload = {
        "candidates": [
            {
                "category": "owned_item",
                "kind": "vehicle",
                "intent": "new",
                "label": value,
                "value": value,
                "evidence": [{"turn_id": s.turn_id, "quote": s.text}],
            }
            for value in ["सिटी", "क्लासिक"]
        ]
    }
    fake, call = client(payload)
    adapter = LearningProviderAdapter("gemini", fake, "gemini-3.5-flash-lite")
    batch = await adapter.extract(s)
    assert [x.value for x in batch.candidates] == ["सिटी", "क्लासिक"]
    assert call.await_count == 1
    kwargs = call.call_args.kwargs
    assert kwargs["store"] is False
    assert kwargs["model"] == "gemini-3.5-flash-lite"
    assert "permit" not in kwargs["input"]
    assert kwargs["response_format"]["schema"]
    await adapter.close()
    fake.aio.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_veto_source_is_not_sent_and_no_retry():
    fake, call = client({"candidates": []})
    adapter = LearningProviderAdapter("gemini", fake, "model")
    assert not (await adapter.extract(source("Don't remember this City"))).candidates
    call.assert_not_awaited()
    call.side_effect = RuntimeError("PRIVATE PROVIDER BODY")
    with pytest.raises(RuntimeError, match="learning_provider_unavailable") as error:
        await adapter.extract(source("I own a City"))
    assert "PRIVATE" not in str(error.value)
    assert call.await_count == 1


@pytest.mark.asyncio
async def test_repeated_or_missing_quote_cannot_ground_fact():
    s = source("City City")
    fake, _ = client(
        {
            "candidates": [
                {
                    "category": "owned_item",
                    "intent": "new",
                    "label": "City",
                    "value": "City",
                    "evidence": [{"turn_id": s.turn_id, "quote": "City"}],
                }
            ]
        }
    )
    adapter = LearningProviderAdapter("gemini", fake, "model")
    assert not (await adapter.extract(s)).candidates


@pytest.mark.asyncio
async def test_empty_authorized_catalog_needs_no_second_model_call():
    s = source("I own a City")
    fake, call = client(
        {
            "candidates": [
                {
                    "category": "owned_item",
                    "intent": "new",
                    "label": "City",
                    "value": "City",
                    "evidence": [{"turn_id": s.turn_id, "quote": s.text}],
                }
            ]
        }
    )
    adapter = LearningProviderAdapter("gemini", fake, "model")
    batch = await adapter.extract(s)
    result = await adapter.resolve(s, batch, LearningCatalog())
    assert result.resolutions[0].decision == "new"
    assert call.await_count == 1


@pytest.mark.asyncio
async def test_openai_schema_requires_every_field_and_closes_nested_objects():
    call = AsyncMock(return_value=SimpleNamespace(output_text='{"candidates":[]}'))
    adapter = LearningProviderAdapter(
        "openai",
        SimpleNamespace(responses=SimpleNamespace(create=call)),
        "gpt-5.6-terra",
    )
    await adapter.extract(source("I own a camera"))
    schema = call.call_args.kwargs["text"]["format"]["schema"]

    def check(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(schema)


@pytest.mark.asyncio
async def test_gemini_wire_avoids_rejected_grammar_bounds_but_keeps_local_limits():
    s = source("I own a City")
    fake, call = client({"candidates": []})
    adapter = LearningProviderAdapter("gemini", fake, "model")
    await adapter.extract(s)
    wire = call.call_args.kwargs["response_format"]["schema"]

    def check(node):
        if isinstance(node, dict):
            assert not ({"maxItems", "minItems", "minimum", "maximum"} & set(node))
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"])
            for item in node.values():
                check(item)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(wire)
    proposal = {
        "category": "owned_item",
        "kind": "vehicle",
        "intent": "new",
        "label": "City",
        "value": "City",
        "evidence": [{"turn_id": s.turn_id, "quote": s.text}],
    }
    call.return_value = SimpleNamespace(
        output_text=json.dumps({"candidates": [proposal] * 9})
    )
    with pytest.raises(RuntimeError, match="invalid_schema"):
        await adapter.extract(s)
