import asyncio

import pytest
from context_query_helpers import context_session, seed_item

VEHICLES = [{"scope_key": "owned_item.vehicle"}]
DEVICES = [{"scope_key": "owned_item.device"}]


@pytest.mark.asyncio
async def test_query_uses_current_question_only_and_replays_without_more_facts(
    learning, authority_parts
):
    await seed_item(learning)
    await seed_item(learning, "Phone", "device")
    for _ in range(2):
        async with context_session(learning) as (s, _, _):
            first = await s.query_for_question(VEHICLES)
            assert first["status"] == "selected" and "City" in str(first)
            assert len(s._learning_source.turns) == 1
            assert "PREVIOUS-PRIVATE" not in str(s._learning_source.turns)
            assert await s.query_for_question(VEHICLES) == first
            assert (await s.query_for_question(DEVICES))[
                "status"
            ] == "invalid_selection"
            first["facts"][0]["text"] = "caller mutation"
            assert "caller mutation" not in str(await s.query_for_question(VEHICLES))
            assert await s.allow_audio()
    assert len(authority_parts.hello.calls) == 1


@pytest.mark.asyncio
async def test_three_invalid_or_empty_queries_exhaust_turn_without_extra_read(
    learning, monkeypatch
):
    await seed_item(learning)
    async with context_session(learning) as (s, _, _):
        original = s._retrieval.learning_context_snapshot
        calls = []

        async def counted():
            calls.append(True)
            return await original()

        monkeypatch.setattr(s._retrieval, "learning_context_snapshot", counted)
        assert (await s.query_for_question(None))["status"] == "invalid_selection"
        assert (await s.query_for_question(DEVICES))["status"] == "no_match"
        assert (await s.query_for_question([]))["status"] == "invalid_selection"
        assert (await s.query_for_question(VEHICLES))["status"] == "invalid_selection"
        assert len(calls) == 1 and not s._released


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["legacy", "query"])
async def test_legacy_and_new_query_share_one_release_path(learning, winner):
    await seed_item(learning)
    async with context_session(learning) as (s, _, _):
        catalog = await s.catalog()
        if winner == "legacy":
            assert (await s.read(catalog["catalog_id"], [0]))["status"] == "selected"
            assert (await s.query_for_question(VEHICLES))[
                "status"
            ] == "invalid_selection"
            assert (await s.read(catalog["catalog_id"], [0]))["status"] == "selected"
        else:
            assert (await s.query_for_question(VEHICLES))["status"] == "selected"
            assert (await s.read(catalog["catalog_id"], [0]))[
                "status"
            ] == "invalid_selection"


@pytest.mark.asyncio
async def test_concurrent_queries_cannot_expand_release(learning, monkeypatch):
    await seed_item(learning)
    await seed_item(learning, "Phone", "device")
    async with context_session(learning) as (s, _, _):
        original = s._retrieval.learning_context_snapshot
        entered, release = asyncio.Event(), asyncio.Event()

        async def paused():
            entered.set()
            await release.wait()
            return await original()

        monkeypatch.setattr(s._retrieval, "learning_context_snapshot", paused)
        first = asyncio.create_task(s.query_for_question(VEHICLES))
        await entered.wait()
        second = asyncio.create_task(s.query_for_question(DEVICES))
        release.set()
        a, b = await asyncio.gather(first, second)
        assert a["status"] == "selected" and b["status"] == "invalid_selection"
        assert "Phone" not in str(a) and len(s._released) == 1


@pytest.mark.asyncio
async def test_unavailable_and_invalid_diagnostics_do_not_echo_owner_data(
    learning, monkeypatch, caplog
):
    async with context_session(learning) as (s, _, _):

        async def broken():
            raise RuntimeError("PRIVATE-CANARY")

        monkeypatch.setattr(s._retrieval, "learning_context_snapshot", broken)
        result = await s.query_for_question(VEHICLES)
        assert (
            result["status"] == "unavailable"
            and "PRIVATE-CANARY" not in str(result) + caplog.text
        )


@pytest.mark.asyncio
async def test_missing_learning_mode_or_revoked_grant_never_opens_exact_consent(
    learning, authority_parts
):
    async with context_session(learning, delegated=False) as (s, _, _):
        assert not s.supports_question_query
        assert (await s.query_for_question(VEHICLES))["status"] == "denied"
    async with context_session(learning) as (s, _, _):
        authority_parts.windows.lock_unlock()
        assert (await s.query_for_question(VEHICLES))["status"] == "denied"
        assert not await s.allow_audio()
    assert len(authority_parts.hello.calls) == 1


@pytest.mark.asyncio
async def test_replaced_permit_cannot_release_waiting_query(learning, monkeypatch):
    await seed_item(learning)
    async with context_session(learning) as (s, _, retired):
        original = s._retrieval.learning_context_snapshot

        async def replaced():
            result = await original()
            s._operation = "correct"
            s._permit = object()
            return result

        monkeypatch.setattr(s._retrieval, "learning_context_snapshot", replaced)
        assert (await s.query_for_question(VEHICLES))["status"] == "denied"
        assert not s._released and retired


@pytest.mark.asyncio
async def test_long_prior_history_does_not_deny_current_question_or_pollute_digest(
    learning,
):
    import hashlib
    import json

    await seed_item(learning)
    async with context_session(learning, "My City?", history="x" * 8000) as (s, c, _):
        packet = await s.query_for_question(VEHICLES)
        assert packet["status"] == "selected"
        current = c.turns[-1]
        expected = hashlib.sha256(
            json.dumps([(current.turn_id, "My City?")], ensure_ascii=False).encode()
        ).hexdigest()
        assert s._learning_source.turns == (current,)
        assert s._learning_source.digest == expected


@pytest.mark.asyncio
async def test_corrected_text_projects_value_without_durable_storage_identity(learning):
    from dataclasses import replace

    from jarvis.memory.types import AuthorityClass, MemorySourceClass

    await learning.service.admit_learning(learning.plan, learning.new_permit())
    record = (await learning.service.canonical_reader.learning_current())[0]
    source = replace(
        learning.plan.mutations[0].source,
        source_id="safe-correction",
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )
    await learning.service.correct_text(
        predicate=record.predicate, value="Nexon", source=source
    )
    async with context_session(learning) as (s, _, _):
        packet = await s.query_for_question(VEHICLES)
        assert packet["status"] == "selected"
        assert packet["facts"][0]["text"] == "owned_item.vehicle: Nexon"
        assert record.predicate.removeprefix("owned_item_") not in str(packet)


@pytest.mark.asyncio
@pytest.mark.parametrize("winner", ["legacy", "query"])
async def test_concurrent_legacy_and_query_release_only_one_path(
    learning, monkeypatch, winner
):
    await seed_item(learning)
    await seed_item(learning, "Phone", "device")
    async with context_session(learning) as (s, _, _):
        catalog = await s.catalog()
        entered, release = asyncio.Event(), asyncio.Event()
        method = (
            "learning_context_snapshot"
            if winner == "query"
            else "retrieve_exact_current_facet"
        )
        original = getattr(s._retrieval, method)

        async def paused(*args, **kwargs):
            result = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

        monkeypatch.setattr(s._retrieval, method, paused)

        async def legacy():
            index = next(
                i
                for i, key in enumerate(s._facets)
                if key.predicate.startswith("owned_item_")
            )
            return await s.read(catalog["catalog_id"], [index])

        calls = {"legacy": legacy, "query": lambda: s.query_for_question(VEHICLES)}
        first = asyncio.create_task(calls[winner]())
        await entered.wait()
        second = asyncio.create_task(
            calls["legacy" if winner == "query" else "query"]()
        )
        release.set()
        a, b = await asyncio.gather(first, second)
        assert a["status"] == "selected" and b["status"] == "invalid_selection"
        assert len(s._released) == 1 and len(a["facts"]) == 1


@pytest.mark.asyncio
async def test_combined_preference_goal_query_uses_both_and_excludes_device(learning):
    from dataclasses import replace

    from jarvis.memory.types import AuthorityClass, MemorySourceClass

    source = replace(
        learning.plan.mutations[0].source,
        source_id="combined",
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
    )
    await learning.service.remember_text(
        predicate="diet preference", value="vegetarian", source=source
    )
    draft = replace(
        learning.plan.mutations[0].draft,
        predicate="goal_fitness",
        value={
            "schema": "personal-learning-v1",
            "category": "goal",
            "kind": "other",
            "label": "Fitness",
            "value": "Run regularly",
            "state": "active",
        },
        normalized_text="Fitness goal: run regularly",
    )
    await learning.lifecycle.create(draft, replace(source, source_id="goal-source"))
    await seed_item(learning, "DEVICE-CANARY", "device")
    async with context_session(learning, "What should I eat for my fitness goal?") as (
        s,
        _,
        _,
    ):
        result = await s.query_for_question(
            [{"scope_key": "food_preference"}, {"scope_key": "goal"}]
        )
        assert result["status"] == "selected" and len(result["facts"]) == 2
        assert {f["scope_key"] for f in result["facts"]} == {"food_preference", "goal"}
        assert "vegetarian" in str(result) and "run regularly" in str(result)
        assert "DEVICE-CANARY" not in str(result)
