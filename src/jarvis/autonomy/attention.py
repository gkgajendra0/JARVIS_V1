"""Durable owner-attention lifecycle and transport adapter for Phase 10A."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol

from jarvis.autonomy.models import (
    AttentionStatus,
    OwnerAttentionEventV1,
    OwnerAttentionItemV1,
    deterministic_id,
)
from jarvis.autonomy.store import AutonomyStore
from jarvis.engineering_knowledge.canonical import JSONValue
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.work.models import (
    DeliveryPolicy,
    WorkDelivery,
    WorkDeliveryKind,
    WorkPriority,
)


def _text(value: object, field: str, *, max_length: int = 2000) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _reason_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(
        sorted(
            {_text(value, "reason_code", max_length=240).casefold() for value in values}
        )
    )
    if not normalized:
        raise ValueError("reason_codes must not be empty")
    return normalized


def _epoch(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if normalized < 0:
        raise ValueError(f"{field} must not be negative")
    return normalized


def attention_fingerprint_for(
    *,
    objective_id: str,
    finding_id: str,
    candidate_id: str | None,
    group_key: str,
    reason_codes: tuple[str, ...],
    question: str,
    option_metadata_json: dict[str, JSONValue],
    consequence_of_waiting: str,
) -> str:
    canonical_digest(option_metadata_json)
    return deterministic_id(
        "attention_fingerprint",
        {
            "objective_id": _text(objective_id, "objective_id", max_length=240),
            "finding_id": _text(finding_id, "finding_id", max_length=240),
            "candidate_id": (
                None
                if candidate_id is None
                else _text(candidate_id, "candidate_id", max_length=240)
            ),
            "group_key": _text(group_key, "group_key", max_length=500),
            "reason_codes": list(_reason_codes(reason_codes)),
            "question": _text(question, "question"),
            "option_metadata_json": option_metadata_json,
            "consequence_of_waiting": _text(
                consequence_of_waiting,
                "consequence_of_waiting",
            ),
        },
    )


def _attention_event(
    item: OwnerAttentionItemV1,
    *,
    kind: str,
    event_suffix: str,
    detail_json: dict[str, JSONValue],
    created_at_epoch: float,
) -> OwnerAttentionEventV1:
    event_key = f"{kind}:{event_suffix}"
    return OwnerAttentionEventV1(
        event_id=deterministic_id(
            "attention_event",
            {
                "attention_id": item.attention_id,
                "event_key": event_key,
            },
        ),
        attention_id=item.attention_id,
        event_key=event_key,
        kind=kind,
        detail_json=detail_json,
        created_at_epoch=created_at_epoch,
    )


@dataclass(frozen=True, slots=True)
class OwnerAttentionAdmissionV1:
    item: OwnerAttentionItemV1
    changed: bool
    deduplicated: bool
    inhibited: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.item, OwnerAttentionItemV1):
            raise TypeError("item must be an OwnerAttentionItemV1")
        for field_name in ("changed", "deduplicated", "inhibited"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be boolean")
        object.__setattr__(
            self,
            "reason_codes",
            _reason_codes(self.reason_codes),
        )


class OwnerAttentionManager:
    """Own canonical attention truth; delivery transports are downstream only."""

    def __init__(self, store: AutonomyStore) -> None:
        if not isinstance(store, AutonomyStore):
            raise TypeError("store must be an AutonomyStore")
        self.store = store

    def open_or_update(
        self,
        *,
        objective_id: str,
        finding_id: str,
        candidate_id: str | None,
        group_key: str,
        priority: WorkPriority,
        reason_codes: tuple[str, ...],
        question: str,
        option_metadata_json: dict[str, JSONValue],
        consequence_of_waiting: str,
        now_epoch: float,
        root_attention_id: str | None = None,
    ) -> OwnerAttentionAdmissionV1:
        if not isinstance(priority, WorkPriority):
            raise TypeError("priority must be a WorkPriority")
        now = _epoch(now_epoch, "now_epoch")
        group = _text(group_key, "group_key", max_length=500)
        reasons = _reason_codes(reason_codes)
        fingerprint = attention_fingerprint_for(
            objective_id=objective_id,
            finding_id=finding_id,
            candidate_id=candidate_id,
            group_key=group,
            reason_codes=reasons,
            question=question,
            option_metadata_json=option_metadata_json,
            consequence_of_waiting=consequence_of_waiting,
        )

        if root_attention_id is not None:
            root = self.store.require_owner_attention(root_attention_id)
            if root.group_key == group and root.status in {
                AttentionStatus.OPEN,
                AttentionStatus.ACKNOWLEDGED,
            }:
                event = _attention_event(
                    root,
                    kind="derivative_inhibited",
                    event_suffix=fingerprint,
                    detail_json={
                        "derivative_fingerprint": fingerprint,
                        "finding_id": finding_id,
                        "candidate_id": candidate_id,
                    },
                    created_at_epoch=now,
                )
                self.store.append_attention_event(event)
                return OwnerAttentionAdmissionV1(
                    item=root,
                    changed=False,
                    deduplicated=False,
                    inhibited=True,
                    reason_codes=("root_attention_inhibits_derivative",),
                )

        existing = self.store.find_owner_attention_by_fingerprint(fingerprint)
        if existing is not None:
            if existing.last_occurrence_epoch == now and existing.priority is priority:
                return OwnerAttentionAdmissionV1(
                    item=existing,
                    changed=False,
                    deduplicated=True,
                    inhibited=False,
                    reason_codes=("attention_replay_reused",),
                )
            updated = replace(
                existing,
                priority=priority,
                last_occurrence_epoch=now,
                version=existing.version + 1,
            )
            persisted = self.store.update_owner_attention(
                updated,
                expected_version=existing.version,
            )
            self.store.append_attention_event(
                _attention_event(
                    persisted,
                    kind="deduplicated",
                    event_suffix=f"v{persisted.version}",
                    detail_json={
                        "fingerprint": persisted.fingerprint,
                        "occurrence_epoch": now,
                    },
                    created_at_epoch=now,
                )
            )
            return OwnerAttentionAdmissionV1(
                item=persisted,
                changed=True,
                deduplicated=True,
                inhibited=False,
                reason_codes=("attention_deduplicated",),
            )

        terminal_matches = tuple(
            item
            for item in self.store.list_owner_attention(limit=500)
            if item.fingerprint == fingerprint
        )
        if terminal_matches:
            terminal = terminal_matches[0]
            return OwnerAttentionAdmissionV1(
                item=terminal,
                changed=False,
                deduplicated=True,
                inhibited=True,
                reason_codes=("terminal_attention_not_reopened_implicitly",),
            )

        item = OwnerAttentionItemV1(
            attention_id=deterministic_id(
                "attention",
                {"fingerprint": fingerprint},
            ),
            fingerprint=fingerprint,
            group_key=group,
            objective_id=_text(objective_id, "objective_id", max_length=240),
            finding_id=_text(finding_id, "finding_id", max_length=240),
            candidate_id=(
                None
                if candidate_id is None
                else _text(candidate_id, "candidate_id", max_length=240)
            ),
            priority=priority,
            reason_codes=reasons,
            question=_text(question, "question"),
            option_metadata_json=dict(option_metadata_json),
            consequence_of_waiting=_text(
                consequence_of_waiting,
                "consequence_of_waiting",
            ),
            first_occurrence_epoch=now,
            last_occurrence_epoch=now,
            next_renotify_epoch=now,
            status=AttentionStatus.OPEN,
            root_attention_id=root_attention_id,
        )
        persisted = self.store.create_owner_attention(item)
        self.store.append_attention_event(
            _attention_event(
                persisted,
                kind="opened",
                event_suffix="v1",
                detail_json={
                    "fingerprint": persisted.fingerprint,
                    "group_key": persisted.group_key,
                },
                created_at_epoch=now,
            )
        )
        return OwnerAttentionAdmissionV1(
            item=persisted,
            changed=True,
            deduplicated=False,
            inhibited=False,
            reason_codes=("attention_opened",),
        )

    def notification_due(
        self,
        item: OwnerAttentionItemV1,
        *,
        now_epoch: float,
    ) -> bool:
        if item.status not in {AttentionStatus.OPEN, AttentionStatus.ACKNOWLEDGED}:
            return False
        now = _epoch(now_epoch, "now_epoch")
        return item.next_renotify_epoch is None or now >= item.next_renotify_epoch

    def record_notification_outcome(
        self,
        item: OwnerAttentionItemV1,
        *,
        now_epoch: float,
        renotify_interval_seconds: float,
        delivered: bool,
        failure_reason: str | None = None,
    ) -> OwnerAttentionItemV1:
        current = self.store.require_owner_attention(item.attention_id)
        if current.version != item.version:
            raise ValueError("stale owner-attention delivery outcome")
        if current.status not in {AttentionStatus.OPEN, AttentionStatus.ACKNOWLEDGED}:
            return current
        now = _epoch(now_epoch, "now_epoch")
        interval = _epoch(
            renotify_interval_seconds,
            "renotify_interval_seconds",
        )
        if interval <= 0:
            raise ValueError("renotify_interval_seconds must be positive")
        if not isinstance(delivered, bool):
            raise TypeError("delivered must be boolean")
        normalized_failure = (
            None
            if failure_reason is None
            else _text(failure_reason, "failure_reason", max_length=500)
        )
        if delivered and normalized_failure is not None:
            raise ValueError("delivered notification cannot carry failure_reason")
        if not delivered and normalized_failure is None:
            raise ValueError("failed notification requires failure_reason")

        updated = replace(
            current,
            next_renotify_epoch=now + interval,
            version=current.version + 1,
        )
        persisted = self.store.update_owner_attention(
            updated,
            expected_version=current.version,
        )
        kind = "notification_delivered" if delivered else "notification_failed"
        self.store.append_attention_event(
            _attention_event(
                persisted,
                kind=kind,
                event_suffix=f"v{persisted.version}",
                detail_json={
                    "delivered": delivered,
                    "failure_reason": normalized_failure,
                    "next_renotify_epoch": persisted.next_renotify_epoch,
                },
                created_at_epoch=now,
            )
        )
        return persisted

    def transition_status(
        self,
        attention_id: str,
        *,
        status: AttentionStatus,
        now_epoch: float,
    ) -> OwnerAttentionItemV1:
        if status is AttentionStatus.OPEN:
            raise ValueError("OPEN must be created through open_or_update")
        current = self.store.require_owner_attention(attention_id)
        if current.status is status:
            return current
        if current.status in {
            AttentionStatus.RESOLVED,
            AttentionStatus.EXPIRED,
            AttentionStatus.SUPERSEDED,
        }:
            raise ValueError("terminal owner attention cannot transition")
        now = _epoch(now_epoch, "now_epoch")
        updated = replace(
            current,
            status=status,
            next_renotify_epoch=(
                current.next_renotify_epoch
                if status is AttentionStatus.ACKNOWLEDGED
                else None
            ),
            version=current.version + 1,
        )
        persisted = self.store.update_owner_attention(
            updated,
            expected_version=current.version,
        )
        self.store.append_attention_event(
            _attention_event(
                persisted,
                kind=status.value,
                event_suffix=f"v{persisted.version}",
                detail_json={
                    "from_status": current.status.value,
                    "to_status": status.value,
                },
                created_at_epoch=now,
            )
        )
        return persisted


class OwnerAttentionTransport(Protocol):
    def deliver(self, delivery: WorkDelivery) -> None: ...


@dataclass(frozen=True, slots=True)
class AttentionDeliveryAttemptV1:
    attention: OwnerAttentionItemV1
    delivery: WorkDelivery | None
    attempted: bool
    delivered: bool
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attention, OwnerAttentionItemV1):
            raise TypeError("attention must be an OwnerAttentionItemV1")
        for field_name in ("attempted", "delivered"):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be boolean")
        if self.delivered and not self.attempted:
            raise ValueError("delivery cannot succeed without an attempt")


class OwnerAttentionDeliveryAdapter:
    """Build WorkDelivery transport envelopes without creating fake WorkItems."""

    def __init__(
        self,
        manager: OwnerAttentionManager,
        transport: OwnerAttentionTransport,
    ) -> None:
        if not isinstance(manager, OwnerAttentionManager):
            raise TypeError("manager must be an OwnerAttentionManager")
        if not callable(getattr(transport, "deliver", None)):
            raise TypeError("transport must provide deliver(delivery)")
        self.manager = manager
        self.transport = transport

    def build_delivery(
        self,
        item: OwnerAttentionItemV1,
        *,
        now_epoch: float,
    ) -> WorkDelivery:
        now = _epoch(now_epoch, "now_epoch")
        event_key = f"owner-attention:{item.attention_id}:v{item.version}"
        return WorkDelivery(
            work_id=f"owner_attention:{item.attention_id}",
            kind=WorkDeliveryKind.OWNER_INPUT,
            message=item.question,
            policy=(
                DeliveryPolicy.INTERRUPT
                if item.priority is WorkPriority.URGENT
                else DeliveryPolicy.WHEN_IDLE
            ),
            event_key=event_key,
            delivery_id=deterministic_id(
                "attention_delivery",
                {
                    "attention_id": item.attention_id,
                    "version": item.version,
                    "event_key": event_key,
                },
            ),
            created_at=datetime.fromtimestamp(now, tz=UTC),
        )

    def attempt(
        self,
        item: OwnerAttentionItemV1,
        *,
        now_epoch: float,
        renotify_interval_seconds: float,
    ) -> AttentionDeliveryAttemptV1:
        if not self.manager.notification_due(item, now_epoch=now_epoch):
            return AttentionDeliveryAttemptV1(
                attention=item,
                delivery=None,
                attempted=False,
                delivered=False,
            )
        delivery = self.build_delivery(item, now_epoch=now_epoch)
        try:
            self.transport.deliver(delivery)
        except Exception as exc:  # noqa: BLE001 - transport failure becomes evidence
            failure_reason = type(exc).__name__
            updated = self.manager.record_notification_outcome(
                item,
                now_epoch=now_epoch,
                renotify_interval_seconds=renotify_interval_seconds,
                delivered=False,
                failure_reason=failure_reason,
            )
            return AttentionDeliveryAttemptV1(
                attention=updated,
                delivery=delivery,
                attempted=True,
                delivered=False,
                failure_reason=failure_reason,
            )

        updated = self.manager.record_notification_outcome(
            item,
            now_epoch=now_epoch,
            renotify_interval_seconds=renotify_interval_seconds,
            delivered=True,
        )
        return AttentionDeliveryAttemptV1(
            attention=updated,
            delivery=delivery,
            attempted=True,
            delivered=True,
        )
