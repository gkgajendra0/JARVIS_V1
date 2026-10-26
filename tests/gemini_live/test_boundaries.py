import asyncio
import threading
from dataclasses import replace

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context, environment, until
from tests.learning.conftest import authority, authority_parts, clock, learning
from tests.learning.context_query_helpers import context_session, seed_item

from jarvis.memory.types import AuthorityClass, MemorySourceClass

__all__ = ["authority", "authority_parts", "clock", "learning"]


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["lock", "forget", "expiry"])
async def test_real_private_guard_revoked_during_budget_wait_prevents_paid_disclosure(
    tmp_path, monkeypatch, learning, authority_parts, clock, revocation
):
    selected = await seed_item(learning)
    async with context_session(learning) as (personal, canonical, retired):
        catalog = await personal.catalog()
        assert (await personal.read(catalog["catalog_id"], [0]))["status"] == "selected"
        env = environment(tmp_path, authorize=personal.validate_transport_restore)
        env.model.admission.session_id = canonical.session_id
        gate, entered = threading.Event(), threading.Event()
        original = env.runtime.paid_budget.reserve

        def delayed(**kwargs):
            result = original(**kwargs)
            entered.set()
            assert gate.wait(10)
            return result

        monkeypatch.setattr(env.runtime.paid_budget, "reserve", delayed)
        try:
            await context(env.session)
            result = env.session.generate_reply()
            assert await asyncio.to_thread(entered.wait, 10)
            if revocation == "lock":
                authority_parts.windows.lock_unlock()
            elif revocation == "expiry":
                clock.advance(301)
            else:
                source = replace(
                    learning.plan.mutations[0].source,
                    source_id="fictional-forget",
                    source_class=MemorySourceClass.OWNER_EXPLICIT,
                    authority_class=AuthorityClass.OWNER_EXPLICIT,
                )
                await learning.service.forget_exact(
                    predicate=selected.predicate, source=source
                )
            gate.set()
            with pytest.raises(llm.RealtimeError):
                await asyncio.wait_for(result, 5)
            assert env.endpoint.clients == 0
            assert env.runtime.paid_budget.status().reserved_inr_minor == 0
            assert len(authority_parts.hello.calls) == 1 and retired
        finally:
            gate.set()
            await env.model.aclose()


@pytest.mark.asyncio
async def test_raw_provider_error_payload_is_not_released_to_sdk_logs(tmp_path):
    env = environment(tmp_path)
    errors = []
    env.session.on("error", errors.append)
    canary = "synthetic-private-key-and-personal-error-payload"
    try:
        await context(env.session)
        future = env.session.generate_reply()
        await until(lambda: env.endpoint.wires)
        env.endpoint.wires[0].events.put_nowait(RuntimeError(canary))
        with pytest.raises(llm.RealtimeError):
            await asyncio.wait_for(future, 5)
        await until(lambda: errors)
        assert canary not in repr(errors[0])
        assert canary not in str(errors[0].error)
    finally:
        await env.model.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["lock", "forget", "expiry"])
async def test_queued_public_tool_and_output_streams_recheck_real_private_source_before_release(
    tmp_path, learning, authority_parts, clock, revocation
):
    from tests.gemini_live.test_contract import raw_usage
    from tests.gemini_live.test_tools import lookup_vehicle

    selected = await seed_item(learning)
    async with context_session(learning) as (personal, _, _):
        catalog = await personal.catalog()
        await personal.read(catalog["catalog_id"], [0])
        env = environment(tmp_path, authorize=personal.validate_transport_restore)
        try:
            await context(env.session)
            await env.session.update_tools([lookup_vehicle])
            future = env.session.generate_reply()
            await until(lambda: env.endpoint.wires)
            env.endpoint.wires[0].feed(
                tool_call={
                    "function_calls": [
                        {
                            "id": "queued-private",
                            "name": "lookup_vehicle",
                            "args": {"name": "City"},
                        }
                    ]
                },
                server_content={
                    "model_turn": {
                        "role": "model",
                        "parts": [{"text": "Private City"}],
                    },
                    "turn_complete": True,
                },
                usage_metadata=raw_usage(),
            )
            event = await asyncio.wait_for(future, 5)
            await revoke(learning, authority_parts, clock, selected, revocation)
            assert [call async for call in event.function_stream] == []
            assert [message async for message in event.message_stream] == []
        finally:
            await env.model.aclose()


async def revoke(learning, parts, clock, selected, kind):
    if kind == "lock":
        parts.windows.lock_unlock()
    elif kind == "expiry":
        clock.advance(301)
    else:
        source = replace(
            learning.plan.mutations[0].source,
            source_id="fictional-boundary-forget",
            source_class=MemorySourceClass.OWNER_EXPLICIT,
            authority_class=AuthorityClass.OWNER_EXPLICIT,
        )
        await learning.service.forget_exact(predicate=selected.predicate, source=source)


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["lock", "forget", "expiry"])
@pytest.mark.parametrize("boundary", ["setup", "tool"])
async def test_real_private_source_is_not_renewed_during_setup_or_tool_reply(
    tmp_path, monkeypatch, learning, authority_parts, clock, revocation, boundary
):
    from contextlib import asynccontextmanager

    from tests.gemini_live.test_contract import raw_usage
    from tests.gemini_live.test_tools import lookup_vehicle

    selected = await seed_item(learning)
    async with context_session(learning) as (personal, _, retired):
        catalog = await personal.catalog()
        await personal.read(catalog["catalog_id"], [0])
        env = environment(tmp_path, authorize=personal.validate_transport_restore)
        gate, entered = asyncio.Event(), asyncio.Event()
        try:
            await context(env.session)
            if boundary == "setup":
                original = env.endpoint.connect

                @asynccontextmanager
                async def connect(**kwargs):
                    entered.set()
                    await gate.wait()
                    async with original(**kwargs) as wire:
                        yield wire

                env.endpoint.connect = connect
                result = env.session.generate_reply()
            else:
                await env.session.update_tools([lookup_vehicle])
                first = env.session.generate_reply()
                await until(lambda: env.endpoint.wires)
                wire = env.endpoint.wires[0]
                wire.feed(
                    tool_call={
                        "function_calls": [
                            {
                                "id": "private-result",
                                "name": "lookup_vehicle",
                                "args": {"name": "City"},
                            }
                        ]
                    },
                    server_content={"turn_complete": True},
                    usage_metadata=raw_usage(),
                )
                event = await asyncio.wait_for(first, 5)
                calls = [call async for call in event.function_stream]
                await until(
                    lambda: env.runtime.paid_budget.status().spent_inr_minor == 1
                )
                ctx = env.session.chat_ctx
                ctx.items.extend(
                    [
                        calls[0],
                        llm.FunctionCallOutput(
                            call_id="private-result",
                            name="lookup_vehicle",
                            output="City",
                            is_error=False,
                        ),
                    ]
                )
                await env.session.update_chat_ctx(ctx)
                original = env.model.admission.reserve

                async def reserve(*args, **kwargs):
                    permit = await original(*args, **kwargs)
                    entered.set()
                    await gate.wait()
                    return permit

                monkeypatch.setattr(env.model.admission, "reserve", reserve)
                result = env.session.generate_reply()
            await asyncio.wait_for(entered.wait(), 5)
            await revoke(learning, authority_parts, clock, selected, revocation)
            gate.set()
            with pytest.raises(llm.RealtimeError):
                await asyncio.wait_for(result, 5)
            if boundary == "setup":
                assert all(not wire.sent for wire in env.endpoint.wires)
                assert env.runtime.paid_budget.status().unknown_reservations == 1
            else:
                assert not any(kind == "tool" for kind, _ in env.endpoint.wires[0].sent)
                assert env.runtime.paid_budget.status().reserved_inr_minor == 0
            assert len(authority_parts.hello.calls) == 1 and retired
        finally:
            gate.set()
            await env.model.aclose()
