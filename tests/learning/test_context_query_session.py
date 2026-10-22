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
