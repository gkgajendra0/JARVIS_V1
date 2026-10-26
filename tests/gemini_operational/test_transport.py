import asyncio

import pytest
from tests.gemini_live.helpers import context, until

from .helpers import environment, expensive_usage, usage


@pytest.mark.asyncio
async def test_operational_config_has_1024_output_and_45_second_lifetime(tmp_path):
    e = environment(tmp_path)
    try:
        await context(e.session)
        response = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        assert e.endpoint.configs[0].generation_config.max_output_tokens == 1024
        assert e.session._lease.controls.max_physical_seconds == 45
        e.endpoint.wires[0].feed(
            server_content={"turn_complete": True}, usage_metadata=usage()
        )
        await asyncio.wait_for(response, 5)
        await until(lambda: e.runtime.paid_budget.status().reserved_inr_minor == 0)
        assert e.runtime.paid_budget.status().spent_inr_minor == 1
    finally:
        await e.model.aclose()


@pytest.mark.asyncio
async def test_early_usage_plus_later_output_is_not_final(tmp_path):
    e = environment(tmp_path)
    try:
        await context(e.session)
        f = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        w = e.endpoint.wires[0]
        w.feed(usage_metadata=usage())
        w.feed(
            server_content={
                "output_transcription": {"text": "later"},
                "turn_complete": True,
            }
        )
        await asyncio.wait_for(f, 5)
        await until(lambda: e.runtime.paid_budget.status().unknown_reservations == 1)
        assert e.runtime.paid_budget.status().reserved_inr_minor == 999
    finally:
        await e.model.aclose()


@pytest.mark.asyncio
async def test_qualified_post_completion_metadata_can_finish_without_resending(
    tmp_path,
):
    e = environment(tmp_path, terminal_mode="post_turn_complete")
    try:
        await context(e.session)
        f = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        w = e.endpoint.wires[0]
        w.feed(server_content={"turn_complete": True})
        await asyncio.wait_for(f, 5)
        w.feed(usage_metadata=usage())
        await until(lambda: e.runtime.paid_budget.status().reserved_inr_minor == 0)
        assert e.endpoint.clients == 1
    finally:
        await e.model.aclose()


@pytest.mark.asyncio
async def test_soft_stop_closes_now_without_releasing_partial_usage_hold(tmp_path):
    e = environment(tmp_path)
    try:
        await context(e.session)
        f = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        w = e.endpoint.wires[0]
        w.feed(usage_metadata=expensive_usage())
        await until(lambda: w.closed)
        await asyncio.gather(f, return_exceptions=True)
        await until(lambda: e.runtime.paid_budget.status().unknown_reservations == 1)
        s = e.runtime.paid_budget.status()
        assert (s.spent_inr_minor, s.reserved_inr_minor) == (850, 150)
    finally:
        await e.model.aclose()


@pytest.mark.asyncio
async def test_complete_850_usage_settles_after_soft_stop_close(tmp_path):
    e = environment(tmp_path)
    try:
        await context(e.session)
        f = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        e.endpoint.wires[0].feed(
            server_content={"turn_complete": True}, usage_metadata=expensive_usage()
        )
        await until(lambda: e.endpoint.wires[0].closed)
        await asyncio.gather(f, return_exceptions=True)
        await until(lambda: e.runtime.paid_budget.status().reserved_inr_minor == 0)
        assert e.runtime.paid_budget.status().spent_inr_minor == 850
    finally:
        await e.model.aclose()


@pytest.mark.asyncio
async def test_blocked_setup_is_bounded_and_preserves_unknown(tmp_path):
    from contextlib import asynccontextmanager

    e = environment(tmp_path)

    @asynccontextmanager
    async def blocked(**kwargs):
        await asyncio.Event().wait()
        yield

    e.endpoint.connect = blocked
    try:
        await context(e.session)
        f = e.session.generate_reply()
        await until(lambda: e.endpoint.clients == 1)
        await asyncio.wait_for(asyncio.gather(f, return_exceptions=True), 7)
        await until(lambda: e.runtime.paid_budget.status().unknown_reservations == 1)
        assert e.endpoint.clients == 1
    finally:
        await e.model.aclose()


@pytest.mark.asyncio
async def test_absolute_watchdog_does_not_use_epoch_clock(tmp_path):
    e = environment(tmp_path)
    try:
        await context(e.session)
        f = e.session.generate_reply()
        await until(lambda: e.endpoint.wires and e.endpoint.wires[0].sent)
        e.runtime.clock = lambda: -100000
        # Epoch movement cannot renew the event-loop watchdog's dispatch deadline.
        timer = e.session._timer
        remaining = timer.when() - asyncio.get_running_loop().time()
        assert 0 < remaining <= 42
        timer._callback(*timer._args)
        await until(lambda: e.endpoint.wires[0].closed)
        await asyncio.gather(f, return_exceptions=True)
        assert e.endpoint.clients == 1
    finally:
        await e.model.aclose()
