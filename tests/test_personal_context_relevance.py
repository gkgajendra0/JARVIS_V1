"""Facet proposals carry no values or release authority; no network in tests."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from jarvis.memory.personal_context_relevance import GeminiPersonalFacetSelector
from jarvis.memory.query_plan import MemoryFacetCatalog, MemoryFacetKey

CATALOG = MemoryFacetCatalog(
    tuple(
        MemoryFacetKey("personal", "owner", p)
        for p in ("diet_preference", "food_allergy", "reading_preference")
    )
)


def client_for(output, calls):
    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text=output)

    return SimpleNamespace(
        aio=SimpleNamespace(interactions=SimpleNamespace(create=create))
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    [
        "What should I have for dinner?",
        "Dinner mein kya khaun?",
        "आज रात खाने में क्या खाऊँ?",
    ],
)
async def test_advice_selects_multiple_existing_facets_without_memory_values(question):
    calls = []
    client = client_for('{"personal_context_useful":true,"facet_indices":[0,1]}', calls)
    selector = GeminiPersonalFacetSelector(client=client, model="gemini-3.8-flash")
    assert await selector.select(question, CATALOG) == CATALOG.facets[:2]
    assert len(calls) == 1
    assert calls[0]["store"] is False
    payload = json.loads(calls[0]["input"])
    assert payload["user_query"] == question
    assert all(
        set(item) == {"facet_index", "subject_scope", "subject", "predicate"}
        for item in payload["eligible_facets"]
    )
    assert "vegetarian" not in calls[0]["input"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "output",
    [
        '{"personal_context_useful":true,"facet_indices":[99]}',
        '{"personal_context_useful":true,"facet_indices":[true]}',
        '{"personal_context_useful":true,"facet_indices":[0,0]}',
        '{"personal_context_useful":false,"facet_indices":[0]}',
        '{"personal_context_useful":true,"facet_indices":[]}',
        '{"personal_context_useful":true,"facet_indices":[0],"value":"invented"}',
        "not json",
    ],
)
async def test_invalid_proposal_is_unavailable_not_a_memory_fact(output):
    selector = GeminiPersonalFacetSelector(
        client=client_for(output, []), model="gemini-3.8-flash"
    )
    with pytest.raises(ValueError):
        await selector.select("What should I eat?", CATALOG)


@pytest.mark.asyncio
async def test_no_catalog_or_empty_question_never_calls_provider():
    calls = []
    selector = GeminiPersonalFacetSelector(
        client=client_for("", calls), model="gemini-3.8-flash"
    )
    assert await selector.select("What should I eat?", MemoryFacetCatalog(())) == ()
    assert await selector.select(" ", CATALOG) == ()
    assert calls == []


@pytest.mark.asyncio
async def test_general_question_can_abstain():
    selector = GeminiPersonalFacetSelector(
        client=client_for('{"personal_context_useful":false,"facet_indices":[]}', []),
        model="gemini-3.8-flash",
    )
    assert await selector.select("Why is the sky blue?", CATALOG) == ()


@pytest.mark.asyncio
async def test_selector_has_bounded_provider_wait():
    async def wait(**kwargs):
        await asyncio.Future()

    client = SimpleNamespace(
        aio=SimpleNamespace(interactions=SimpleNamespace(create=wait))
    )
    selector = GeminiPersonalFacetSelector(
        client=client, model="gemini-3.8-flash", timeout_seconds=0.01
    )
    with pytest.raises(TimeoutError):
        await selector.select("What should I eat?", CATALOG)


@pytest.mark.asyncio
async def test_non_owner_catalog_rejected_before_network():
    calls = []
    selector = GeminiPersonalFacetSelector(
        client=client_for("", calls), model="gemini-3.8-flash"
    )
    with pytest.raises(ValueError):
        await selector.select(
            "What should I eat?",
            MemoryFacetCatalog((MemoryFacetKey("personal", "guest", "diet"),)),
        )
    assert not calls


@pytest.mark.asyncio
async def test_oversized_facet_name_rejected_before_network():
    calls = []
    selector = GeminiPersonalFacetSelector(
        client=client_for("", calls), model="gemini-3.8-flash"
    )
    catalog = MemoryFacetCatalog((MemoryFacetKey("personal", "owner", "x" * 40_000),))
    with pytest.raises(ValueError):
        await selector.select("What should I eat?", catalog)
    assert not calls
