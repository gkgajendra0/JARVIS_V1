"""Atomic paid-inference admission in the canonical routing/cost store."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from jarvis.model_routing.gemini import GeminiFallbackConfig
from jarvis.model_routing.models import ModelTarget
from jarvis.model_routing.pricing import (
    PaidExposure,
    PricingSnapshot,
    PricingUnavailable,
)
from jarvis.model_routing.store import ModelRoutingStore


class PaidBudgetDenied(RuntimeError):
    pass


class PaidOutcomeUnknown(PaidBudgetDenied):
    pass


@dataclass(frozen=True, slots=True)
class PaidReservation:
    reservation_id: str
    budget_id: str
    invocation_id: str
    target_id: str
    price_profile_id: str
    price_version: int
    reserved_inr_minor: int
    state: str


@dataclass(frozen=True, slots=True)
class PaidBudgetStatus:
    budget_id: str
    ceiling_inr_minor: int
    spent_inr_minor: int
    reserved_inr_minor: int
    unknown_reservations: int
    estimated_total_inr_minor: int | None
    blocked_reason: str | None


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _reservation(row) -> PaidReservation:
    return PaidReservation(
        row["reservation_id"],
        row["budget_id"],
        row["invocation_id"],
        row["target_id"],
        row["price_profile_id"],
        row["price_version"],
        row["reserved_minor"],
        row["state"],
    )


def read_paid_budget_status(
    store: ModelRoutingStore, budget_id="gemini-paid-fallback-v1"
) -> PaidBudgetStatus | None:
    with store.work_store.extension_transaction() as connection:
        connection.execute("BEGIN")
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paid_fallback_budgets'"
        ).fetchone()
        if not exists:
            return None
        budget = connection.execute(
            "SELECT * FROM paid_fallback_budgets WHERE budget_id=?", (budget_id,)
        ).fetchone()
        if budget is None:
            return None
        rows = connection.execute(
            "SELECT reserved_minor,accounted_minor,state FROM paid_fallback_reservations WHERE budget_id=?",
            (budget_id,),
        ).fetchall()
    outstanding = sum(
        max(0, row["reserved_minor"] - row["accounted_minor"])
        for row in rows
        if row["state"] not in {"settled", "cancelled"}
    )
    unknown = sum(row["state"] in {"uncertain", "acknowledged_unknown"} for row in rows)
    pending = any(row["state"] not in {"settled", "cancelled"} for row in rows)
    return PaidBudgetStatus(
        budget_id,
        budget["ceiling_minor"],
        budget["spent_minor"],
        outstanding,
        unknown,
        None if pending else budget["spent_minor"],
        budget["blocked_reason"],
    )


@dataclass(frozen=True, slots=True)
class PaidCostRecord:
    invocation_id: str
    target_id: str
    scope_kind: str
    scope_id: str
    price_profile_id: str
    price_version: int
    price_source: str
    fx_version: str
    fx_source: str
    known_inr_minor: int
    reserved_inr_minor: int
    usage_complete: bool | None


def read_paid_cost_records(
    store: ModelRoutingStore, *, scope_kind=None, scope_id=None
) -> tuple[PaidCostRecord, ...]:
    with store.work_store.extension_transaction() as connection:
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paid_fallback_reservations'"
        ).fetchone():
            return ()
        query = "SELECT * FROM paid_fallback_reservations WHERE 1=1"
        params = []
        if scope_kind is not None:
            query += " AND scope_kind=?"
            params.append(scope_kind)
        if scope_id is not None:
            query += " AND scope_id=?"
            params.append(scope_id)
        rows = connection.execute(
            query + " ORDER BY reserved_at,reservation_id", params
        ).fetchall()
    records = []
    for row in rows:
        pricing = PricingSnapshot.from_payload(
            store.work_store.decode_extension_json(row["price_json"])
        )
        pending = row["state"] not in {"settled", "cancelled"}
        complete = (
            False
            if row["state"] in {"uncertain", "acknowledged_unknown"}
            else (None if pending else True)
        )
        records.append(
            PaidCostRecord(
                row["invocation_id"],
                row["target_id"],
                row["scope_kind"],
                row["scope_id"],
                row["price_profile_id"],
                row["price_version"],
                pricing.source,
                pricing.fx_version,
                pricing.fx_source,
                row["accounted_minor"],
                max(0, row["reserved_minor"] - row["accounted_minor"])
                if pending
                else 0,
                complete,
            )
        )
    return tuple(records)


class PaidBudgetGovernor:
    def __init__(
        self, store: ModelRoutingStore, *, config: GeminiFallbackConfig, clock
    ):
        if not isinstance(store, ModelRoutingStore) or not isinstance(
            config, GeminiFallbackConfig
        ):
            raise TypeError("Canonical routing store and fallback config required")
        self.store = store
        self.config = config
        self.clock = clock
        with store.work_store.extension_transaction() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS paid_fallback_budgets (
                    budget_id TEXT PRIMARY KEY, ceiling_minor INTEGER NOT NULL,
                    spent_minor INTEGER NOT NULL DEFAULT 0, blocked_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS paid_fallback_reservations (
                    reservation_id TEXT PRIMARY KEY, invocation_id TEXT NOT NULL UNIQUE,
                    budget_id TEXT NOT NULL, target_id TEXT NOT NULL,
                    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
                    binding_digest TEXT NOT NULL, price_profile_id TEXT NOT NULL,
                    price_version INTEGER NOT NULL, price_json TEXT NOT NULL,
                    reserved_at REAL NOT NULL, reserved_minor INTEGER NOT NULL,
                    accounted_minor INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL,
                    FOREIGN KEY(budget_id) REFERENCES paid_fallback_budgets(budget_id)
                );
                CREATE TABLE IF NOT EXISTS paid_fallback_usage_events (
                    event_id TEXT PRIMARY KEY, reservation_id TEXT NOT NULL,
                    event_digest TEXT NOT NULL, event_json TEXT NOT NULL,
                    FOREIGN KEY(reservation_id) REFERENCES paid_fallback_reservations(reservation_id)
                );
            """)
            connection.execute("BEGIN IMMEDIATE")
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(paid_fallback_reservations)"
                )
            }
            if "admission_kind" not in columns:
                connection.execute(
                    "ALTER TABLE paid_fallback_reservations ADD COLUMN admission_kind TEXT NOT NULL DEFAULT 'strict'"
                )
            if "operational_json" not in columns:
                connection.execute(
                    "ALTER TABLE paid_fallback_reservations ADD COLUMN operational_json TEXT"
                )
            old = connection.execute(
                "SELECT ceiling_minor FROM paid_fallback_budgets WHERE budget_id=?",
                (config.budget_id,),
            ).fetchone()
            if old is not None and old["ceiling_minor"] != config.ceiling_inr_minor:
                raise PaidBudgetDenied(
                    "Budget identity has a different immutable ceiling"
                )
            connection.execute(
                "INSERT OR IGNORE INTO paid_fallback_budgets(budget_id,ceiling_minor) VALUES (?,?)",
                (config.budget_id, config.ceiling_inr_minor),
            )

    def status(self, budget_id=None) -> PaidBudgetStatus:
        result = read_paid_budget_status(self.store, budget_id or self.config.budget_id)
        if result is None:
            raise PaidBudgetDenied("Unknown paid budget")
        return result

    def reserve(
        self,
        *,
        invocation_id: str,
        target: ModelTarget,
        exposure: PaidExposure,
        pricing: PricingSnapshot,
    ) -> PaidReservation:
        self.recover_operational_live_owners()
        if not self.config.enabled:
            raise PaidBudgetDenied("Paid fallback is disabled")
        if not isinstance(invocation_id, str) or not invocation_id.strip():
            raise PaidBudgetDenied("Invocation identity required")
        if (
            target.provider_id != "gemini"
            or target.credential_ref != "JARVIS_GEMINI_PAID_API_KEY"
        ):
            raise PaidBudgetDenied(
                "Only the approved Paid target may reserve this budget"
            )
        if not isinstance(exposure, PaidExposure) or not isinstance(
            pricing, PricingSnapshot
        ):
            raise PricingUnavailable("Bounded reviewed exposure and pricing required")
        if ("realtime_voice" in target.capabilities) != (pricing.service_key == "live"):
            raise PricingUnavailable("Price service does not match target capabilities")
        if pricing.service_key == "live" and exposure.max_seconds is None:
            raise PricingUnavailable("Live duration bound required")
        now = float(self.clock())
        amount = pricing.quote(exposure.usage_bounds, now_epoch=now, target=target)
        binding = _digest(
            {
                "budget_id": self.config.budget_id,
                "target_id": target.target_id,
                "credential_ref": target.credential_ref,
                "exposure": exposure.to_payload(),
                "pricing": pricing.to_payload(),
            }
        )
        with self.store.work_store.extension_transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM paid_fallback_reservations WHERE invocation_id=?",
                (invocation_id,),
            ).fetchone()
            if existing is not None:
                if existing["binding_digest"] != binding:
                    raise PaidBudgetDenied(
                        "Invocation identity is already bound to other exposure"
                    )
                return _reservation(existing)
            budget = connection.execute(
                "SELECT * FROM paid_fallback_budgets WHERE budget_id=?",
                (self.config.budget_id,),
            ).fetchone()
            if budget["blocked_reason"] is not None:
                raise PaidBudgetDenied("Paid budget requires reconciliation")
            pending = connection.execute(
                "SELECT COALESCE(SUM(MAX(0,reserved_minor-accounted_minor)),0) FROM paid_fallback_reservations WHERE budget_id=? AND state NOT IN ('settled','cancelled')",
                (self.config.budget_id,),
            ).fetchone()[0]
            if budget["spent_minor"] + pending + amount > budget["ceiling_minor"]:
                raise PaidBudgetDenied("Paid fallback internal ceiling exhausted")
            rid = "paid-reservation-" + _digest([self.config.budget_id, invocation_id])
            connection.execute(
                """INSERT INTO paid_fallback_reservations (
                reservation_id,invocation_id,budget_id,target_id,scope_kind,scope_id,
                binding_digest,price_profile_id,price_version,price_json,reserved_at,reserved_minor,state
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rid,
                    invocation_id,
                    self.config.budget_id,
                    target.target_id,
                    exposure.scope_kind,
                    exposure.scope_id,
                    binding,
                    pricing.profile.profile_id,
                    pricing.profile.version,
                    self.store.work_store.encode_extension_json(pricing.to_payload()),
                    now,
                    amount,
                    "reserved",
                ),
            )
            row = connection.execute(
                "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                (rid,),
            ).fetchone()
            return _reservation(row)

    def mark_dispatched(self, reservation_id: str) -> PaidReservation:
        with self.store.work_store.extension_transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if (
                row is None
                or row["budget_id"] != self.config.budget_id
                or row["state"] != "reserved"
                or row["admission_kind"] != "strict"
            ):
                raise PaidOutcomeUnknown(
                    "Paid invocation cannot be dispatched twice or after cancellation"
                )
            connection.execute(
                "UPDATE paid_fallback_reservations SET state='dispatched' WHERE reservation_id=?",
                (reservation_id,),
            )
            return _reservation(
                connection.execute(
                    "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
            )

    def cancel_unsent(self, reservation_id: str) -> None:
        with self.store.work_store.extension_transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if (
                row is None
                or row["budget_id"] != self.config.budget_id
                or row["state"] != "reserved"
            ):
                raise PaidOutcomeUnknown(
                    "A possibly accepted Paid invocation cannot be refunded"
                )
            connection.execute(
                "UPDATE paid_fallback_reservations SET state='cancelled' WHERE reservation_id=?",
                (reservation_id,),
            )

    def settle(
        self, *, reservation_id: str, usage: dict, usage_complete: bool, event_id: str
    ) -> PaidReservation:
        if (
            type(usage_complete) is not bool
            or not isinstance(event_id, str)
            or not event_id.strip()
        ):
            raise PaidBudgetDenied("Valid usage event identity required")
        if not isinstance(usage, dict):
            raise PaidBudgetDenied("Usage metadata must be a mapping")
        event = {"usage": usage, "usage_complete": usage_complete}
        event_digest = _digest(event)
        with self.store.work_store.extension_transaction() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if (
                row is None
                or row["budget_id"] != self.config.budget_id
                or row["state"] not in {"dispatched", "uncertain", "settled"}
                or row["admission_kind"] != "strict"
            ):
                raise PaidOutcomeUnknown("No dispatched Paid invocation to settle")
            duplicate = connection.execute(
                "SELECT * FROM paid_fallback_usage_events WHERE event_id=?", (event_id,)
            ).fetchone()
            if duplicate is not None:
                if (
                    duplicate["reservation_id"] != reservation_id
                    or duplicate["event_digest"] != event_digest
                ):
                    raise PaidBudgetDenied("Usage event identity collision")
                return _reservation(row)
            if row["state"] == "settled":
                raise PaidBudgetDenied("Paid invocation already has a final settlement")
            pricing = PricingSnapshot.from_payload(
                self.store.work_store.decode_extension_json(row["price_json"])
            )
            try:
                if not usage_complete:
                    raise PricingUnavailable("Usage incomplete")
                observed = pricing.quote_usage(usage, now_epoch=row["reserved_at"])
            except PricingUnavailable:
                observed = row["accounted_minor"]
                state = "uncertain"
                reason = "unknown_usage"
            else:
                state = "settled"
                reason = (
                    "observed_overrun" if observed > row["reserved_minor"] else None
                )
            if observed < row["accounted_minor"]:
                raise PaidBudgetDenied("Usage settlement cannot reduce accounted cost")
            connection.execute(
                "INSERT INTO paid_fallback_usage_events VALUES (?,?,?,?)",
                (
                    event_id,
                    reservation_id,
                    event_digest,
                    self.store.work_store.encode_extension_json(event),
                ),
            )
            connection.execute(
                "UPDATE paid_fallback_reservations SET accounted_minor=?,state=? WHERE reservation_id=?",
                (observed, state, reservation_id),
            )
            connection.execute(
                "UPDATE paid_fallback_budgets SET spent_minor=spent_minor+? WHERE budget_id=?",
                (observed - row["accounted_minor"], self.config.budget_id),
            )
            old_reason = connection.execute(
                "SELECT blocked_reason FROM paid_fallback_budgets WHERE budget_id=?",
                (self.config.budget_id,),
            ).fetchone()[0]
            if old_reason == "observed_overrun":
                reason = old_reason
            if reason is None:
                remaining = connection.execute(
                    "SELECT COUNT(*) FROM paid_fallback_reservations WHERE budget_id=? AND state='uncertain'",
                    (self.config.budget_id,),
                ).fetchone()[0]
                if remaining:
                    reason = "unknown_usage"
            connection.execute(
                "UPDATE paid_fallback_budgets SET blocked_reason=? WHERE budget_id=?",
                (reason, self.config.budget_id),
            )
            from jarvis.model_routing.operational_budget import _refresh_admin_block

            _refresh_admin_block(self, connection)
            return _reservation(
                connection.execute(
                    "SELECT * FROM paid_fallback_reservations WHERE reservation_id=?",
                    (reservation_id,),
                ).fetchone()
            )

    def reserve_operational_live(
        self,
        *,
        invocation_id,
        target,
        pricing,
        policy,
        profile,
        scope_id,
        capture_only=False,
    ):
        from jarvis.model_routing.operational_budget import reserve

        return reserve(
            self,
            invocation_id=invocation_id,
            target=target,
            pricing=pricing,
            policy=policy,
            profile=profile,
            scope_id=scope_id,
            capture_only=capture_only,
        )

    def checkpoint_operational_live(
        self, *, reservation_id, trigger_id, kind, round_id, tool_call_ids=()
    ):
        from jarvis.model_routing.operational_budget import checkpoint

        return checkpoint(
            self,
            reservation_id=reservation_id,
            trigger_id=trigger_id,
            kind=kind,
            round_id=round_id,
            tool_call_ids=tool_call_ids,
        )

    def observe_operational_live(
        self, *, reservation_id, report, event_id, diagnostics=None
    ):
        from jarvis.model_routing.operational_budget import observe

        return observe(
            self,
            reservation_id=reservation_id,
            report=report,
            event_id=event_id,
            diagnostics=diagnostics,
        )

    def finish_operational_live(
        self, *, reservation_id, complete, teardown_confirmed, event_id
    ):
        from jarvis.model_routing.operational_budget import finish

        return finish(
            self,
            reservation_id=reservation_id,
            complete=complete,
            teardown_confirmed=teardown_confirmed,
            event_id=event_id,
        )

    def recover_operational_live_owners(self):
        from jarvis.model_routing.operational_budget import recover

        return recover(self)

    def reconcile_operational_live(
        self, *, evidence, validate_owner, administrative_action_id
    ):
        from jarvis.model_routing.operational_budget import reconcile

        return reconcile(
            self,
            evidence=evidence,
            validate_owner=validate_owner,
            administrative_action_id=administrative_action_id,
        )
