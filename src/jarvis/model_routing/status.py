"""Bounded owner-visible routing status derived from durable provenance."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from jarvis.model_routing.store import ModelRoutingStore


class VerificationStatus(StrEnum):
    UNKNOWN = "unknown"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class RoutingStatus:
    decision_id: str
    routing_request_id: str
    work_id: str
    change_id: str | None
    stage_key: str | None
    strategy_key: str
    strategy_version: int
    strategy_digest: str
    registry_digest: str
    policy_digest: str
    selected_target_id: str
    selected_role: str
    reason_codes: tuple[str, ...]
    ordered_target_ids: tuple[str, ...]
    fallback_budget: int
    fallback_path: tuple[str, ...]
    attempt_count: int
    target_health: dict[str, str]
    total_latency_ms: float | None
    aggregate_usage: dict[str, float] | None
    estimated_total_cost_usd: float | None
    final_target_id: str | None
    verification_status: VerificationStatus
    verifier_reference: str | None
    outcome_evidence_reference: str | None


class RoutingStatusReader:
    """Read routing telemetry without exposing prompts, credentials or secret handles."""

    def __init__(
        self,
        store: ModelRoutingStore,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(store, ModelRoutingStore):
            raise TypeError("store must be a ModelRoutingStore")
        self._store = store
        self._clock = clock

    @staticmethod
    def _aggregate_latency(attempts) -> float | None:
        if not attempts or any(attempt.latency_ms is None for attempt in attempts):
            return None
        return sum(float(attempt.latency_ms) for attempt in attempts)

    @staticmethod
    def _aggregate_usage(attempts) -> dict[str, float] | None:
        if not attempts or any(not attempt.usage for attempt in attempts):
            return None
        aggregate: dict[str, float] = {}
        for attempt in attempts:
            for key, value in attempt.usage.items():
                aggregate[key] = aggregate.get(key, 0.0) + float(value)
        return aggregate

    @staticmethod
    def _aggregate_cost(attempts) -> float | None:
        if not attempts or any(
            attempt.estimated_cost_usd is None for attempt in attempts
        ):
            return None
        return sum(float(attempt.estimated_cost_usd) for attempt in attempts)

    @staticmethod
    def _verification(outcome) -> VerificationStatus:
        if (
            outcome is None
            or outcome.verifier_reference is None
            or outcome.accepted_result is None
        ):
            return VerificationStatus.UNKNOWN
        return (
            VerificationStatus.ACCEPTED
            if outcome.accepted_result
            else VerificationStatus.REJECTED
        )

    def for_decision(self, decision_id: str) -> RoutingStatus | None:
        persisted = self._store.get_decision(decision_id)
        if persisted is None:
            return None
        attempts = self._store.list_attempts(decision_id)
        outcome = self._store.get_outcome(decision_id)
        now = float(self._clock())

        health: dict[str, str] = {}
        for target_id in persisted.decision.ordered_target_ids:
            record = self._store.get_health(target_id)
            health[target_id] = (
                "unknown"
                if record is None
                else record.effective_state(now_epoch=now).value
            )

        final_target_id = None
        if outcome is not None:
            final_target_id = outcome.final_target_id
        else:
            successful = [
                attempt for attempt in attempts if attempt.failure_class is None
            ]
            if successful:
                final_target_id = successful[-1].target_id

        total_latency_ms = (
            outcome.total_latency_ms
            if outcome is not None
            else self._aggregate_latency(attempts)
        )
        aggregate_usage = (
            dict(outcome.aggregate_usage)
            if outcome is not None and outcome.aggregate_usage
            else self._aggregate_usage(attempts)
        )
        estimated_total_cost_usd = (
            outcome.estimated_total_cost_usd
            if outcome is not None
            else self._aggregate_cost(attempts)
        )

        return RoutingStatus(
            decision_id=persisted.decision.decision_id,
            routing_request_id=persisted.decision.routing_request_id,
            work_id=persisted.work_id,
            change_id=persisted.change_id,
            stage_key=persisted.stage_key,
            strategy_key=persisted.decision.strategy_key,
            strategy_version=persisted.decision.strategy_version,
            strategy_digest=persisted.decision.strategy_digest,
            registry_digest=persisted.registry_digest,
            policy_digest=persisted.eligibility.policy_digest,
            selected_target_id=persisted.decision.selected_target_id,
            selected_role=persisted.decision.selected_role,
            reason_codes=persisted.decision.reason_codes,
            ordered_target_ids=persisted.decision.ordered_target_ids,
            fallback_budget=persisted.decision.fallback_budget,
            fallback_path=tuple(attempt.target_id for attempt in attempts),
            attempt_count=len(attempts),
            target_health=health,
            total_latency_ms=total_latency_ms,
            aggregate_usage=aggregate_usage,
            estimated_total_cost_usd=estimated_total_cost_usd,
            final_target_id=final_target_id,
            verification_status=self._verification(outcome),
            verifier_reference=(
                None if outcome is None else outcome.verifier_reference
            ),
            outcome_evidence_reference=(
                None if outcome is None else outcome.outcome_evidence_reference
            ),
        )

    def latest_for_work(self, work_id: str) -> RoutingStatus | None:
        decisions = self._store.list_decisions_for_work(work_id, limit=1)
        if not decisions:
            return None
        return self.for_decision(decisions[0].decision.decision_id)


def gemini_fallback_status(runtime) -> dict:
    """Local facts only: presence is not credential validity or provider health."""
    from dataclasses import asdict

    from jarvis.ai_provider import gemini_credential_ref, resolve_credential_api_key
    from jarvis.model_routing.pricing import PricingUnavailable
    from jarvis.voice.gemini_budget import GeminiLiveBudget

    def present(slot):
        try:
            return bool(
                resolve_credential_api_key("gemini", gemini_credential_ref(slot))
            )
        except (RuntimeError, ValueError):
            return False

    now = float(runtime.clock())
    health = {}
    for target in runtime.router.target_registry.all():
        record = runtime.store.get_health(target.target_id)
        health[target.target_id] = {
            "state": "unknown" if record is None else record.state.value,
            "cooldown_until_epoch": None
            if record is None
            else record.cooldown_until_epoch,
        }
    for record in runtime.store.list_health():
        health[record.target_id] = {
            "state": record.state.value,
            "cooldown_until_epoch": record.cooldown_until_epoch,
        }
    valid = 0
    versions = []
    for price in runtime.prices.values():
        versions.append(
            {
                "model_id": price.model_id,
                "service_key": price.service_key,
                "price_profile_id": price.profile.profile_id,
                "price_version": price.profile.version,
                "price_source": price.source,
                "fx_version": price.fx_version,
                "fx_source": price.fx_source,
            }
        )
        try:
            price.validate_at(now)
        except PricingUnavailable:
            continue
        valid += 1
    budget = asdict(runtime.paid_budget.status())
    return {
        "mode": "free_first_paid_fallback" if runtime.config.enabled else "disabled",
        "local_spending_enforcement": runtime.config.budget_enforced,
        "ledger_scope": "current_budget"
        if runtime.config.budget_enforced
        else "historical_budget_records_only",
        "free_credential_available": present("free"),
        "paid_credential_available": present("paid"),
        "credential_validity_verified": False,
        "paid_credential_blocked": runtime.store.credential_blocked(
            gemini_credential_ref("paid")
        ),
        "valid_price_count": valid,
        "price_versions": versions,
        "pricing_error": runtime.pricing_error
        if valid or not runtime.prices
        else "reviewed_pricing_expired",
        "live_paid_available": not runtime.config.budget_enforced
        or GeminiLiveBudget.available,
        "live_paid_reason": GeminiLiveBudget.reason
        if runtime.config.budget_enforced
        else "automatic_fallback_without_local_spending_gate",
        "target_health": health,
        **budget,
    }


def paid_live_ledger_status(runtime) -> list[dict]:
    """Numeric local operational status, never a provider invoice or balance."""
    with runtime.store.work_store.extension_transaction() as c:
        rows = c.execute(
            "SELECT reservation_id,state,reserved_minor,accounted_minor,operational_json FROM paid_fallback_reservations WHERE budget_id=? AND admission_kind='operational_live_v1' ORDER BY reserved_at,reservation_id",
            (runtime.config.budget_id,),
        ).fetchall()
    result = []
    from jarvis.model_routing.live_policy import digest

    for row in rows:
        data = runtime.store.work_store.decode_extension_json(row["operational_json"])
        result.append(
            {
                "reservation_id": row["reservation_id"],
                "state": row["state"],
                "known_minor": row["accounted_minor"],
                "held_minor": max(0, row["reserved_minor"] - row["accounted_minor"])
                if row["state"] not in {"settled", "cancelled"}
                else 0,
                "policy_ref": digest(data["policy"]),
                "profile_ref": digest(data["profile"]) if data["profile"] else None,
                "usage_status": "unknown"
                if row["state"] in {"uncertain", "acknowledged_unknown"}
                else (
                    "pending" if row["state"] in {"reserved", "dispatched"} else "final"
                ),
                "soft_stop_minor": data["policy"]["soft_stop_minor"],
                "allowance_minor": row["reserved_minor"],
            }
        )
    return result
