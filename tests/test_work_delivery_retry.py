from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from jarvis.work.provider_retry import (
    delivery_retry_delay_seconds,
    provider_retry_hint,
)
from jarvis.work.models import (
    DeliveryPolicy,
    WorkDeliveryKind,
    WorkDeliveryState,
    WorkItem,
    WorkType,
)
from jarvis.work.store import SQLiteWorkStore


class GeminiQuotaError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("429 RESOURCE_EXHAUSTED")
        self.code = 429
        self.details = {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Please retry in 53.4s.",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "53s",
                    }
                ],
            }
        }


def _create_work(store: SQLiteWorkStore) -> WorkItem:
    work = WorkItem(
        request="Research retry behavior",
        work_type=WorkType.RESEARCH,
        source_session_id="retry-session",
        source_turn_id="retry-turn",
        delivery_policy=DeliveryPolicy.WHEN_IDLE,
    )
    return store.create(work)


def test_provider_retry_hint_prefers_structured_retry_info_through_wrapper() -> None:
    provider_error = GeminiQuotaError()
    wrapper = RuntimeError("failed to synthesize speech after retries")
    wrapper.__cause__ = provider_error

    hint = provider_retry_hint(wrapper)

    assert hint is not None
    assert hint.status_code == 429
    assert hint.reason == "rate_limit"
    assert hint.retry_after_seconds == 53.0


def test_provider_retry_hint_parses_retry_delay_from_error_text() -> None:
    error = RuntimeError(
        "429 RESOURCE_EXHAUSTED: quota exceeded. Please retry in 47.744895045s."
    )

    hint = provider_retry_hint(error)

    assert hint is not None
    assert hint.status_code == 429
    assert hint.retry_after_seconds == pytest.approx(47.744895045)


def test_delivery_retry_uses_bounded_exponential_fallback() -> None:
    assert delivery_retry_delay_seconds(failed_attempts=0, provider_hint=None) == 5.0
    assert delivery_retry_delay_seconds(failed_attempts=1, provider_hint=None) == 10.0
    assert delivery_retry_delay_seconds(failed_attempts=5, provider_hint=None) == 160.0
    assert delivery_retry_delay_seconds(failed_attempts=6, provider_hint=None) == 300.0
    assert delivery_retry_delay_seconds(failed_attempts=20, provider_hint=None) == 300.0


def test_provider_retry_delay_overrides_fallback() -> None:
    hint = provider_retry_hint(GeminiQuotaError())
    assert hint is not None

    assert (
        delivery_retry_delay_seconds(
            failed_attempts=8,
            provider_hint=hint,
        )
        == 53.0
    )


def test_work_delivery_retry_state_survives_store_reopen(tmp_path: Path) -> None:
    path = tmp_path / "work.sqlite"
    store = SQLiteWorkStore(path)
    work = _create_work(store)
    delivery = store.enqueue_delivery(
        work=work,
        kind=WorkDeliveryKind.COMPLETION,
        message="Research is complete.",
        event_key="completion:v1",
    )
    assert delivery is not None

    deferred = store.schedule_delivery_retry(
        delivery.delivery_id,
        delay_seconds=60.0,
        reason="provider_rate_limit_429",
    )

    assert deferred.state is WorkDeliveryState.PENDING
    assert deferred.failed_attempts == 1
    assert deferred.next_attempt_at is not None
    assert deferred.last_failure_reason == "provider_rate_limit_429"
    assert store.list_due_deliveries() == ()

    reopened = SQLiteWorkStore(path)
    persisted = reopened.list_pending_deliveries()
    assert len(persisted) == 1
    assert persisted[0].delivery_id == delivery.delivery_id
    assert persisted[0].failed_attempts == 1
    assert persisted[0].next_attempt_at == deferred.next_attempt_at
    assert persisted[0].last_failure_reason == "provider_rate_limit_429"

    due = reopened.list_due_deliveries(
        now=deferred.next_attempt_at + timedelta(seconds=1)
    )
    assert [item.delivery_id for item in due] == [delivery.delivery_id]

    delivered = reopened.mark_delivery_delivered(delivery.delivery_id)
    assert delivered.state is WorkDeliveryState.DELIVERED
    assert delivered.failed_attempts == 1
    assert delivered.next_attempt_at is None
    assert delivered.last_failure_reason is None
    assert reopened.list_pending_deliveries() == ()


def test_due_delivery_does_not_block_later_ready_delivery(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    first_work = _create_work(store)
    first = store.enqueue_delivery(
        work=first_work,
        kind=WorkDeliveryKind.COMPLETION,
        message="First complete.",
        event_key="completion:first",
    )
    assert first is not None
    store.schedule_delivery_retry(
        first.delivery_id,
        delay_seconds=120.0,
        reason="provider_rate_limit_429",
    )

    second_work = WorkItem(
        request="Second task",
        work_type=WorkType.RESEARCH,
        source_session_id="retry-session",
        source_turn_id="retry-turn-2",
        delivery_policy=DeliveryPolicy.WHEN_IDLE,
    )
    store.create(second_work)
    second = store.enqueue_delivery(
        work=second_work,
        kind=WorkDeliveryKind.COMPLETION,
        message="Second complete.",
        event_key="completion:second",
    )
    assert second is not None

    due = store.list_due_deliveries()

    assert [item.delivery_id for item in due] == [second.delivery_id]


def test_legacy_work_delivery_schema_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE work_deliveries (
                delivery_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                policy TEXT NOT NULL,
                event_key TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                delivered_at TEXT,
                UNIQUE(work_id, event_key)
            )
            """
        )

    SQLiteWorkStore(path)

    with sqlite3.connect(path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(work_deliveries)"
            ).fetchall()
        }

    assert {
        "failed_attempts",
        "next_attempt_at",
        "last_failure_reason",
    }.issubset(columns)


def test_due_filter_accepts_explicit_utc_time(tmp_path: Path) -> None:
    store = SQLiteWorkStore(tmp_path / "work.sqlite")
    work = _create_work(store)
    delivery = store.enqueue_delivery(
        work=work,
        kind=WorkDeliveryKind.COMPLETION,
        message="Done.",
        event_key="completion:utc",
    )
    assert delivery is not None

    deferred = store.schedule_delivery_retry(
        delivery.delivery_id,
        delay_seconds=30.0,
        reason="provider_temporarily_unavailable_503",
    )
    assert deferred.next_attempt_at is not None

    before = datetime.now(UTC)
    assert deferred.next_attempt_at > before
    assert store.list_due_deliveries(now=before) == ()
