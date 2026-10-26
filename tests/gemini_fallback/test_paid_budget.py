from dataclasses import replace

import pytest

from .helpers import budget_fixture, exposure


def test_default_ceiling_exact_boundary_and_restart(tmp_path):
    from jarvis.model_routing.budget import PaidBudgetDenied

    path = tmp_path / "cost.db"
    governor, _, target, price = budget_fixture(path)
    reservation = governor.reserve(
        invocation_id="first",
        target=target,
        exposure=exposure(10000, 7500),
        pricing=price,
    )
    assert reservation.reserved_inr_minor == 35000
    restarted, _, _, _ = budget_fixture(path)
    assert restarted.status().ceiling_inr_minor == 35000
    assert restarted.status().reserved_inr_minor == 35000
    with pytest.raises(PaidBudgetDenied):
        restarted.reserve(
            invocation_id="extra", target=target, exposure=exposure(1, 1), pricing=price
        )


def test_duplicate_reservation_and_dispatch_cannot_repeat_request(tmp_path):
    from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown

    governor, _, target, price = budget_fixture(tmp_path / "cost.db")
    args = {
        "invocation_id": "first",
        "target": target,
        "exposure": exposure(),
        "pricing": price,
    }
    first = governor.reserve(**args)
    assert governor.reserve(**args).reservation_id == first.reservation_id
    assert governor.status().reserved_inr_minor == 20000
    with pytest.raises(PaidBudgetDenied):
        governor.reserve(**{**args, "exposure": exposure(100, 100)})
    governor.mark_dispatched(first.reservation_id)
    with pytest.raises(PaidOutcomeUnknown):
        governor.mark_dispatched(first.reservation_id)
    with pytest.raises(PaidOutcomeUnknown):
        governor.cancel_unsent(first.reservation_id)


def test_settlement_uses_observed_usage_and_duplicate_event_is_idempotent(tmp_path):
    governor, store, target, price = budget_fixture(tmp_path / "cost.db")
    r = governor.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    governor.mark_dispatched(r.reservation_id)
    args = {
        "reservation_id": r.reservation_id,
        "usage": {"input_tokens": 1000, "output_tokens": 500},
        "usage_complete": True,
        "event_id": "usage-1",
    }
    governor.settle(**args)
    governor.settle(**args)
    status = governor.status()
    assert (
        status.spent_inr_minor,
        status.reserved_inr_minor,
        status.unknown_reservations,
    ) == (3000, 0, 0)
    from jarvis.model_routing.cost import CostTelemetryReader

    assert CostTelemetryReader(store).paid_fallback_status().spent_inr_minor == 3000


def test_missing_usage_keeps_reservation_unknown_and_blocks_new_paid(tmp_path):
    from jarvis.model_routing.budget import PaidBudgetDenied

    path = tmp_path / "cost.db"
    governor, _, target, price = budget_fixture(path)
    r = governor.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    governor.mark_dispatched(r.reservation_id)
    governor.settle(
        reservation_id=r.reservation_id,
        usage={},
        usage_complete=False,
        event_id="lost-response",
    )
    restarted, _, _, _ = budget_fixture(path)
    status = restarted.status()
    assert status.spent_inr_minor == 0 and status.reserved_inr_minor == 20000
    assert status.unknown_reservations == 1 and status.estimated_total_inr_minor is None
    with pytest.raises(PaidBudgetDenied):
        restarted.reserve(
            invocation_id="new", target=target, exposure=exposure(1, 1), pricing=price
        )


def test_only_unsent_cancellation_refunds_and_cannot_dispatch_cancelled(tmp_path):
    from jarvis.model_routing.budget import PaidOutcomeUnknown

    governor, _, target, price = budget_fixture(tmp_path / "cost.db")
    r = governor.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    governor.cancel_unsent(r.reservation_id)
    assert governor.status().reserved_inr_minor == 0
    with pytest.raises(PaidOutcomeUnknown):
        governor.mark_dispatched(r.reservation_id)


def test_restart_after_dispatch_retains_exposure_and_cannot_resend(tmp_path):
    from jarvis.model_routing.budget import PaidOutcomeUnknown

    path = tmp_path / "cost.db"
    governor, _, target, price = budget_fixture(path)
    r = governor.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    governor.mark_dispatched(r.reservation_id)
    restarted, _, _, _ = budget_fixture(path)
    same = restarted.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    assert (
        same.reservation_id == r.reservation_id
        and restarted.status().reserved_inr_minor == 20000
    )
    with pytest.raises(PaidOutcomeUnknown):
        restarted.mark_dispatched(r.reservation_id)


def test_observed_overrun_is_reported_not_clipped(tmp_path):
    from jarvis.model_routing.budget import PaidBudgetDenied

    governor, _, target, price = budget_fixture(tmp_path / "cost.db")
    r = governor.reserve(
        invocation_id="first", target=target, exposure=exposure(1, 1), pricing=price
    )
    governor.mark_dispatched(r.reservation_id)
    governor.settle(
        reservation_id=r.reservation_id,
        usage={"input_tokens": 20000, "output_tokens": 10000},
        usage_complete=True,
        event_id="overrun",
    )
    assert governor.status().spent_inr_minor == 60000
    assert governor.status().blocked_reason == "observed_overrun"
    with pytest.raises(PaidBudgetDenied):
        governor.reserve(
            invocation_id="next", target=target, exposure=exposure(1, 1), pricing=price
        )


def test_budget_identity_cannot_silently_change_ceiling(tmp_path):
    from jarvis.model_routing.budget import PaidBudgetDenied

    path = tmp_path / "cost.db"
    budget_fixture(path)
    with pytest.raises(PaidBudgetDenied):
        budget_fixture(path, ceiling=50000)


def test_cost_reader_exposes_lane_target_price_and_unknown_exposure(tmp_path):
    from jarvis.model_routing.cost import CostTelemetryReader

    governor, store, target, price = budget_fixture(tmp_path / "cost.db")
    r = governor.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    governor.mark_dispatched(r.reservation_id)
    governor.settle(
        reservation_id=r.reservation_id, usage={}, usage_complete=False, event_id="lost"
    )
    records = CostTelemetryReader(store).paid_fallback_records(
        scope_kind="memory", scope_id="source-budget"
    )
    assert len(records) == 1
    record = records[0]
    assert record.target_id == target.target_id and record.scope_kind == "memory"
    assert (
        record.price_profile_id == "synthetic-test-price" and record.price_version == 1
    )
    assert record.fx_version == "test-fx-v1"
    assert record.known_inr_minor == 0 and record.reserved_inr_minor == 20000
    assert record.usage_complete is False


def test_live_target_cannot_use_text_only_price(tmp_path):
    from jarvis.model_routing.pricing import PricingUnavailable

    governor, _, target, price = budget_fixture(tmp_path / "cost.db")
    live = replace(
        target,
        supports_streaming=True,
        supports_tools=True,
        capabilities=("realtime_voice", "tool_calling"),
    )
    with pytest.raises(PricingUnavailable):
        governor.reserve(
            invocation_id="live", target=live, exposure=exposure(), pricing=price
        )
    assert governor.status().reserved_inr_minor == 0


def test_settlement_pins_admission_price_after_profile_expiry(tmp_path):
    governor, _, target, price = budget_fixture(tmp_path / "cost.db")
    r = governor.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    governor.mark_dispatched(r.reservation_id)
    governor.clock = lambda: 2000
    governor.settle(
        reservation_id=r.reservation_id,
        usage={"input_tokens": 1000, "output_tokens": 500},
        usage_complete=True,
        event_id="final",
    )
    assert governor.status().spent_inr_minor == 3000


def test_budget_status_is_one_wal_snapshot_during_settlement(tmp_path, monkeypatch):
    from contextlib import contextmanager

    path = tmp_path / "cost.db"
    reader, store, target, price = budget_fixture(path)
    writer, _, _, _ = budget_fixture(path)
    r = reader.reserve(
        invocation_id="first", target=target, exposure=exposure(), pricing=price
    )
    reader.mark_dispatched(r.reservation_id)
    original = store.work_store.extension_transaction
    fired = []
    errors = []

    @contextmanager
    def traced_transaction():
        with original() as connection:

            def trace(sql):
                if "SELECT reserved_minor" in sql and not fired:
                    fired.append(True)
                    try:
                        writer.settle(
                            reservation_id=r.reservation_id,
                            usage={"input_tokens": 1000, "output_tokens": 500},
                            usage_complete=True,
                            event_id="interleaved",
                        )
                    except Exception as exc:  # noqa: BLE001 - surface failures otherwise swallowed by SQLite trace callbacks
                        errors.append(exc)

            connection.set_trace_callback(trace)
            try:
                yield connection
            finally:
                connection.set_trace_callback(None)

    monkeypatch.setattr(store.work_store, "extension_transaction", traced_transaction)
    status = reader.status()
    assert fired and not errors
    assert (status.spent_inr_minor, status.reserved_inr_minor) == (0, 20000)
    assert writer.status().spent_inr_minor == 3000
