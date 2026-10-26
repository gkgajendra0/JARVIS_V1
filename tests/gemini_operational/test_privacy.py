import asyncio
import threading

import pytest
from livekit.agents import llm
from tests.gemini_live.helpers import context
from tests.gemini_live.test_boundaries import revoke
from tests.learning.conftest import authority, authority_parts, clock, learning
from tests.learning.context_query_helpers import context_session, seed_item

from .helpers import environment

__all__ = ["authority", "authority_parts", "clock", "learning"]


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["lock", "forget", "expiry"])
async def test_original_private_authority_is_not_renewed_while_operational_reserve_waits(
    tmp_path, monkeypatch, learning, authority_parts, clock, revocation
):
    selected = await seed_item(learning)
    async with context_session(learning) as (personal, canonical, retired):
        catalog = await personal.catalog()
        await personal.read(catalog["catalog_id"], [0])
        e = environment(tmp_path)
        e.model.admission.authorize = personal.validate_transport_restore
        e.model.admission.session_id = canonical.session_id
        e.model.state.authorize = personal.validate_transport_restore
        entered, release = threading.Event(), threading.Event()
        reserve = e.runtime.paid_budget.reserve_operational_live

        def wait(**kwargs):
            r = reserve(**kwargs)
            entered.set()
            assert release.wait(10)
            return r

        monkeypatch.setattr(e.runtime.paid_budget, "reserve_operational_live", wait)
        try:
            await context(e.session)
            f = e.session.generate_reply()
            assert await asyncio.to_thread(entered.wait, 10)
            await revoke(learning, authority_parts, clock, selected, revocation)
            release.set()
            with pytest.raises(llm.RealtimeError):
                await asyncio.wait_for(f, 5)
            assert e.endpoint.clients == 0
            assert e.runtime.paid_budget.status().reserved_inr_minor == 0
            assert len(authority_parts.hello.calls) == 1 and retired
        finally:
            release.set()
            await e.model.aclose()
