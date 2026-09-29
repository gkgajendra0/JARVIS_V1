"""Provider-neutral cost estimation and mission-level telemetry reports."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from jarvis.model_routing.models import CostProfile, ModelTarget, RoutingAttempt
from jarvis.model_routing.store import ModelRoutingStore
from jarvis.work.store import SQLiteWorkStore


def estimate_usage_cost_usd(
    target: ModelTarget,
    usage: dict[str, int | float],
) -> float | None:
    """Estimate token cost when both usage and an effective target profile are known."""

    if not isinstance(target, ModelTarget):
        raise TypeError("target must be a ModelTarget")
    profile = target.cost_profile
    if profile is None:
        return None
    return estimate_profile_usage_cost_usd(profile, usage)


def estimate_profile_usage_cost_usd(
    profile: CostProfile,
    usage: dict[str, int | float],
) -> float | None:
    if not isinstance(profile, CostProfile):
        raise TypeError("profile must be a CostProfile")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if input_tokens is None or output_tokens is None:
        return None

    input_value = float(input_tokens)
    output_value = float(output_tokens)
    if input_value < 0 or output_value < 0:
        raise ValueError("token usage must not be negative")

    input_rate = profile.input_usd_per_million_tokens
    output_rate = profile.output_usd_per_million_tokens
    if input_value > 0 and input_rate is None:
        return None
    if output_value > 0 and output_rate is None:
        return None

    return (
        input_value * float(input_rate or 0.0)
        + output_value * float(output_rate or 0.0)
    ) / 1_000_000.0


def _required_text(value: str, *, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


@dataclass(frozen=True, slots=True)
class ProviderCostEvent:
    """One non-model provider charge attributable to a Work mission."""

    event_id: str
    work_id: str
    provider_id: str
    service_key: str
    cost_kind: str
    quantity: float
    unit_cost_usd: float | None
    estimated_cost_usd: float | None
    pricing_basis: str
    occurred_at_epoch: float
    stage_key: str | None = None
    correlation_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "event_id",
            _required_text(self.event_id, field_name="event_id"),
        )
        object.__setattr__(
            self,
            "work_id",
            _required_text(self.work_id, field_name="work_id"),
        )
        object.__setattr__(
            self,
            "provider_id",
            _required_text(self.provider_id, field_name="provider_id").casefold(),
        )
        object.__setattr__(
            self,
            "service_key",
            _required_text(self.service_key, field_name="service_key").casefold(),
        )
        object.__setattr__(
            self,
            "cost_kind",
            _required_text(self.cost_kind, field_name="cost_kind").casefold(),
        )
        quantity = float(self.quantity)
        if quantity < 0:
            raise ValueError("quantity must not be negative")
        object.__setattr__(self, "quantity", quantity)
        if self.unit_cost_usd is not None:
            unit_cost = float(self.unit_cost_usd)
            if unit_cost < 0:
                raise ValueError("unit_cost_usd must not be negative")
            object.__setattr__(self, "unit_cost_usd", unit_cost)
        if self.estimated_cost_usd is not None:
            estimated = float(self.estimated_cost_usd)
            if estimated < 0:
                raise ValueError("estimated_cost_usd must not be negative")
            object.__setattr__(self, "estimated_cost_usd", estimated)
        object.__setattr__(
            self,
            "pricing_basis",
            _required_text(self.pricing_basis, field_name="pricing_basis"),
        )
        occurred = float(self.occurred_at_epoch)
        if occurred < 0:
            raise ValueError("occurred_at_epoch must not be negative")
        object.__setattr__(self, "occurred_at_epoch", occurred)
        stage = _optional_text(self.stage_key)
        object.__setattr__(
            self,
            "stage_key",
            None if stage is None else stage.casefold(),
        )
        object.__setattr__(
            self,
            "correlation_key",
            _optional_text(self.correlation_key),
        )


def _provider_event_payload(event: ProviderCostEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "work_id": event.work_id,
        "provider_id": event.provider_id,
        "service_key": event.service_key,
        "cost_kind": event.cost_kind,
        "quantity": event.quantity,
        "unit_cost_usd": event.unit_cost_usd,
        "estimated_cost_usd": event.estimated_cost_usd,
        "pricing_basis": event.pricing_basis,
        "occurred_at_epoch": event.occurred_at_epoch,
        "stage_key": event.stage_key,
        "correlation_key": event.correlation_key,
    }


def _provider_event_from_payload(payload: dict[str, object]) -> ProviderCostEvent:
    return ProviderCostEvent(
        event_id=str(payload["event_id"]),
        work_id=str(payload["work_id"]),
        provider_id=str(payload["provider_id"]),
        service_key=str(payload["service_key"]),
        cost_kind=str(payload["cost_kind"]),
        quantity=float(payload["quantity"]),
        unit_cost_usd=(
            None
            if payload["unit_cost_usd"] is None
            else float(payload["unit_cost_usd"])
        ),
        estimated_cost_usd=(
            None
            if payload["estimated_cost_usd"] is None
            else float(payload["estimated_cost_usd"])
        ),
        pricing_basis=str(payload["pricing_basis"]),
        occurred_at_epoch=float(payload["occurred_at_epoch"]),
        stage_key=(
            None if payload.get("stage_key") is None else str(payload["stage_key"])
        ),
        correlation_key=(
            None
            if payload.get("correlation_key") is None
            else str(payload["correlation_key"])
        ),
    )


class ProviderCostEventStore:
    """Durable non-token provider costs sharing the canonical protected WorkStore."""

    def __init__(self, work_store: SQLiteWorkStore) -> None:
        if not isinstance(work_store, SQLiteWorkStore):
            raise TypeError("work_store must be a SQLiteWorkStore")
        self._work_store = work_store
        self._initialize()

    def _initialize(self) -> None:
        with self._work_store.extension_transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_cost_events (
                    event_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    service_key TEXT NOT NULL,
                    cost_kind TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    occurred_at_epoch REAL NOT NULL,
                    FOREIGN KEY(work_id) REFERENCES work_items(work_id)
                );

                CREATE INDEX IF NOT EXISTS idx_provider_cost_events_work
                    ON provider_cost_events(work_id, occurred_at_epoch);
                """
            )

    def record(self, event: ProviderCostEvent) -> ProviderCostEvent:
        if not isinstance(event, ProviderCostEvent):
            raise TypeError("event must be a ProviderCostEvent")
        payload = self._work_store.encode_extension_json(
            _provider_event_payload(event)
        )
        try:
            with self._work_store.extension_transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO provider_cost_events (
                        event_id, work_id, provider_id, service_key, cost_kind,
                        event_json, occurred_at_epoch
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.work_id,
                        event.provider_id,
                        event.service_key,
                        event.cost_kind,
                        payload,
                        event.occurred_at_epoch,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(
                f"provider cost event cannot be recorded: {event.event_id}"
            ) from exc
        return event

    def list_for_work(self, work_id: str) -> tuple[ProviderCostEvent, ...]:
        normalized = _required_text(work_id, field_name="work_id")
        with self._work_store.extension_transaction() as connection:
            rows = connection.execute(
                """
                SELECT event_json
                FROM provider_cost_events
                WHERE work_id = ?
                ORDER BY occurred_at_epoch, event_id
                """,
                (normalized,),
            ).fetchall()
        return tuple(
            _provider_event_from_payload(
                self._work_store.decode_extension_json(row["event_json"])
            )
            for row in rows
        )

    def list_for_work_ids(
        self,
        work_ids: tuple[str, ...],
    ) -> tuple[ProviderCostEvent, ...]:
        normalized = tuple(
            _required_text(work_id, field_name="work_id") for work_id in work_ids
        )
        if not normalized:
            return ()
        placeholders = ", ".join("?" for _ in normalized)
        with self._work_store.extension_transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT event_json
                FROM provider_cost_events
                WHERE work_id IN ({placeholders})
                ORDER BY occurred_at_epoch, event_id
                """,
                normalized,
            ).fetchall()
        return tuple(
            _provider_event_from_payload(
                self._work_store.decode_extension_json(row["event_json"])
            )
            for row in rows
        )


@dataclass(frozen=True, slots=True)
class CostTelemetryBucket:
    stage_key: str
    provider_id: str
    model_id: str
    attempt_count: int
    fallback_attempts: int
    failed_attempts: int
    missing_usage_attempts: int
    unpriced_attempts: int
    aggregate_usage: dict[str, float] = field(default_factory=dict)
    known_estimated_cost_usd: float = 0.0
    estimated_total_cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ProviderCostTelemetryBucket:
    stage_key: str
    provider_id: str
    service_key: str
    cost_kind: str
    event_count: int
    unpriced_events: int
    quantity: float
    known_estimated_cost_usd: float
    estimated_total_cost_usd: float | None


@dataclass(frozen=True, slots=True)
class CostTelemetryReport:
    scope_kind: str
    scope_id: str
    attempt_count: int
    fallback_attempts: int
    failed_attempts: int
    missing_usage_attempts: int
    unpriced_attempts: int
    aggregate_usage: dict[str, float] = field(default_factory=dict)
    known_estimated_cost_usd: float = 0.0
    estimated_total_cost_usd: float | None = None
    breakdown: tuple[CostTelemetryBucket, ...] = ()
    provider_cost_event_count: int = 0
    unpriced_provider_cost_events: int = 0
    known_model_cost_usd: float = 0.0
    known_provider_cost_usd: float = 0.0
    provider_cost_breakdown: tuple[ProviderCostTelemetryBucket, ...] = ()


@dataclass
class _MutableBucket:
    attempts: int = 0
    fallbacks: int = 0
    failures: int = 0
    missing_usage: int = 0
    unpriced: int = 0
    usage: dict[str, float] = field(default_factory=dict)
    known_cost: float = 0.0

    def add(self, attempt: RoutingAttempt) -> None:
        self.attempts += 1
        if attempt.kind.value == "fallback":
            self.fallbacks += 1
        if attempt.failure_class is not None:
            self.failures += 1
        if not attempt.usage_observed:
            self.missing_usage += 1
        for key, value in attempt.usage.items():
            self.usage[key] = self.usage.get(key, 0.0) + float(value)
        if attempt.estimated_cost_usd is None:
            self.unpriced += 1
        else:
            self.known_cost += float(attempt.estimated_cost_usd)

    def freeze(
        self, *, stage_key: str, provider_id: str, model_id: str
    ) -> CostTelemetryBucket:
        return CostTelemetryBucket(
            stage_key=stage_key,
            provider_id=provider_id,
            model_id=model_id,
            attempt_count=self.attempts,
            fallback_attempts=self.fallbacks,
            failed_attempts=self.failures,
            missing_usage_attempts=self.missing_usage,
            unpriced_attempts=self.unpriced,
            aggregate_usage=dict(sorted(self.usage.items())),
            known_estimated_cost_usd=self.known_cost,
            estimated_total_cost_usd=(self.known_cost if self.unpriced == 0 else None),
        )


@dataclass
class _MutableProviderBucket:
    events: int = 0
    unpriced: int = 0
    quantity: float = 0.0
    known_cost: float = 0.0

    def add(self, event: ProviderCostEvent) -> None:
        self.events += 1
        self.quantity += event.quantity
        if event.estimated_cost_usd is None:
            self.unpriced += 1
        else:
            self.known_cost += event.estimated_cost_usd

    def freeze(
        self,
        *,
        stage_key: str,
        provider_id: str,
        service_key: str,
        cost_kind: str,
    ) -> ProviderCostTelemetryBucket:
        return ProviderCostTelemetryBucket(
            stage_key=stage_key,
            provider_id=provider_id,
            service_key=service_key,
            cost_kind=cost_kind,
            event_count=self.events,
            unpriced_events=self.unpriced,
            quantity=self.quantity,
            known_estimated_cost_usd=self.known_cost,
            estimated_total_cost_usd=(
                self.known_cost if self.unpriced == 0 else None
            ),
        )


def summarize_cost_attempts(
    *,
    scope_kind: str,
    scope_id: str,
    attempts: tuple[RoutingAttempt, ...],
    provider_events: tuple[ProviderCostEvent, ...] = (),
) -> CostTelemetryReport:
    normalized_kind = str(scope_kind).strip().casefold()
    normalized_id = str(scope_id).strip()
    if not normalized_kind:
        raise ValueError("scope_kind must not be empty")
    if not normalized_id:
        raise ValueError("scope_id must not be empty")

    overall = _MutableBucket()
    groups: dict[tuple[str, str, str], _MutableBucket] = {}
    for attempt in attempts:
        overall.add(attempt)
        key = (
            attempt.stage_key or "unknown",
            attempt.provider_id or "unknown",
            attempt.model_id or "unknown",
        )
        groups.setdefault(key, _MutableBucket()).add(attempt)

    provider_overall = _MutableProviderBucket()
    provider_groups: dict[
        tuple[str, str, str, str], _MutableProviderBucket
    ] = {}
    for event in provider_events:
        if event.work_id not in {attempt.work_id for attempt in attempts} and (
            normalized_kind == "work" and event.work_id != normalized_id
        ):
            raise ValueError("provider cost event is outside requested cost scope")
        provider_overall.add(event)
        key = (
            event.stage_key or "unknown",
            event.provider_id,
            event.service_key,
            event.cost_kind,
        )
        provider_groups.setdefault(key, _MutableProviderBucket()).add(event)

    breakdown = tuple(
        groups[key].freeze(
            stage_key=key[0],
            provider_id=key[1],
            model_id=key[2],
        )
        for key in sorted(groups)
    )
    provider_breakdown = tuple(
        provider_groups[key].freeze(
            stage_key=key[0],
            provider_id=key[1],
            service_key=key[2],
            cost_kind=key[3],
        )
        for key in sorted(provider_groups)
    )
    combined_known_cost = overall.known_cost + provider_overall.known_cost
    complete = overall.unpriced == 0 and provider_overall.unpriced == 0
    return CostTelemetryReport(
        scope_kind=normalized_kind,
        scope_id=normalized_id,
        attempt_count=overall.attempts,
        fallback_attempts=overall.fallbacks,
        failed_attempts=overall.failures,
        missing_usage_attempts=overall.missing_usage,
        unpriced_attempts=overall.unpriced,
        aggregate_usage=dict(sorted(overall.usage.items())),
        known_estimated_cost_usd=combined_known_cost,
        estimated_total_cost_usd=(combined_known_cost if complete else None),
        breakdown=breakdown,
        provider_cost_event_count=provider_overall.events,
        unpriced_provider_cost_events=provider_overall.unpriced,
        known_model_cost_usd=overall.known_cost,
        known_provider_cost_usd=provider_overall.known_cost,
        provider_cost_breakdown=provider_breakdown,
    )


class CostTelemetryReader:
    """Aggregate durable model and non-model provider costs by mission."""

    def __init__(
        self,
        store: ModelRoutingStore,
        *,
        provider_cost_store: ProviderCostEventStore | None = None,
    ) -> None:
        if not isinstance(store, ModelRoutingStore):
            raise TypeError("store must be a ModelRoutingStore")
        self._store = store
        self._provider_cost_store = (
            provider_cost_store or ProviderCostEventStore(store.work_store)
        )

    def for_work(self, work_id: str) -> CostTelemetryReport:
        return summarize_cost_attempts(
            scope_kind="work",
            scope_id=work_id,
            attempts=self._store.list_attempts_for_work(work_id),
            provider_events=self._provider_cost_store.list_for_work(work_id),
        )

    def for_change(self, change_id: str) -> CostTelemetryReport:
        work_ids = self._store.list_work_ids_for_change(change_id)
        return summarize_cost_attempts(
            scope_kind="engineering_change",
            scope_id=change_id,
            attempts=self._store.list_attempts_for_change(change_id),
            provider_events=self._provider_cost_store.list_for_work_ids(work_ids),
        )
