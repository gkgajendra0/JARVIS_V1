import multiprocessing
import os

import pytest
from tests.gemini_fallback.helpers import budget_fixture, exposure

from jarvis.model_routing.budget import PaidOutcomeUnknown


def _crash_after_durable_boundary(path, settled):
    governor, _, target, price = budget_fixture(path)
    reservation = governor.reserve(
        invocation_id="crashed-invocation",
        target=target,
        exposure=exposure(),
        pricing=price,
    )
    governor.mark_dispatched(reservation.reservation_id)
    if settled:
        governor.settle(
            reservation_id=reservation.reservation_id,
            usage={"input_tokens": 10, "output_tokens": 5},
            usage_complete=True,
            event_id="crash-settlement",
        )
    os._exit(17)


@pytest.mark.parametrize("settled", [False, True])
def test_real_process_exit_cannot_refund_or_repeat_dispatched_exposure(
    tmp_path, settled
):
    path = tmp_path / "crash.db"
    budget_fixture(path)
    child = multiprocessing.get_context("spawn").Process(
        target=_crash_after_durable_boundary, args=(path, settled)
    )
    child.start()
    try:
        child.join(timeout=30)
        assert child.exitcode == 17
        governor, _, target, price = budget_fixture(path)
        reservation = governor.reserve(
            invocation_id="crashed-invocation",
            target=target,
            exposure=exposure(),
            pricing=price,
        )
        with pytest.raises(PaidOutcomeUnknown):
            governor.mark_dispatched(reservation.reservation_id)
        with pytest.raises(PaidOutcomeUnknown):
            governor.cancel_unsent(reservation.reservation_id)
        status = governor.status()
        assert status.reserved_inr_minor == (0 if settled else 20000)
        assert status.spent_inr_minor == (30 if settled else 0)
        assert status.estimated_total_inr_minor == (30 if settled else None)
        if settled:
            governor.settle(
                reservation_id=reservation.reservation_id,
                usage={"input_tokens": 10, "output_tokens": 5},
                usage_complete=True,
                event_id="crash-settlement",
            )
            assert governor.status().spent_inr_minor == 30
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=10)
