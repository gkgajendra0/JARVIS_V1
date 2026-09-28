"""Deterministic autonomy budget accounting and admission for Phase 10A."""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from typing import Any, Self

from jarvis.autonomy.models import (
    ActionCandidateV1,
    ActionKind,
    AutonomyBudgetPolicyV1,
    AutonomyMode,
    CandidateDisposition,
)
from jarvis.autonomy.store import (
    AutonomyConflictError,
    AutonomyIntegrityError,
    AutonomyStore,
)
from jarvis.engineering_knowledge.canonical import JSONValue
from jarvis.engineering_substrate.canonical import canonical_digest

BUDGET_DIMENSION_NEW_WORK = "new_autonomous_work"
BUDGET_DIMENSION_REPEAT_DISPATCH = "repeat_dispatch"
BUDGET_DIMENSION_OWNER_NOTIFICATION = "owner_attention_notification"
BUDGET_DIMENSION_PROVIDER_MODEL_WORK = "provider_model_work"

_ALLOWED_DIMENSIONS = frozenset(
    {
        BUDGET_DIMENSION_NEW_WORK,
        BUDGET_DIMENSION_REPEAT_DISPATCH,
        BUDGET_DIMENSION_OWNER_NOTIFICATION,
        BUDGET_DIMENSION_PROVIDER_MODEL_WORK,
    }
)


def _text(value: object, field: str, *, max_length: int = 500) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _token(value: object, field: str) -> str:
    return _text(value, field, max_length=200).casefold()


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _nonnegative_float(
    value: object | None,
    field: str,
    *,
    optional: bool = False,
) -> float | None:
    if value is None:
        if optional:
            return None
        raise ValueError(f"{field} must not be None")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _epoch(value: object, field: str) -> float:
    normalized = _nonnegative_float(value, field)
    assert normalized is not None
    return normalized


@dataclass(frozen=True, slots=True)
class BudgetUsageV1:
    active_autonomous_work_items: int
    new_autonomous_work_items_in_window: int
    active_candidates_for_objective: int
    repeated_dispatches_for_finding_window: int
    owner_attention_notifications_in_window: int
    provider_model_work_used: float | None = None
    urgent_root_attention_override: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "active_autonomous_work_items",
            "new_autonomous_work_items_in_window",
            "active_candidates_for_objective",
            "repeated_dispatches_for_finding_window",
            "owner_attention_notifications_in_window",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_int(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "provider_model_work_used",
            _nonnegative_float(
                self.provider_model_work_used,
                "provider_model_work_used",
                optional=True,
            ),
        )
        if not isinstance(self.urgent_root_attention_override, bool):
            raise TypeError("urgent_root_attention_override must be boolean")


@dataclass(frozen=True, slots=True)
class BudgetAssessmentV1:
    disposition: CandidateDisposition
    reason_codes: tuple[str, ...]
    policy_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, CandidateDisposition):
            raise TypeError("disposition must be a CandidateDisposition")
        normalized = tuple(
            sorted({_token(value, "reason_code") for value in self.reason_codes})
        )
        if not normalized:
            raise ValueError("reason_codes must not be empty")
        object.__setattr__(self, "reason_codes", normalized)
        if self.policy_id is not None:
            object.__setattr__(
                self,
                "policy_id",
                _text(self.policy_id, "policy_id"),
            )


class AutonomyBudgetEvaluator:
    """Fail-closed deterministic budget admission; budgets never grant Authority."""

    def evaluate(
        self,
        candidate: ActionCandidateV1,
        *,
        mode: AutonomyMode,
        policy: AutonomyBudgetPolicyV1 | None,
        usage: BudgetUsageV1,
    ) -> BudgetAssessmentV1:
        if not isinstance(candidate, ActionCandidateV1):
            raise TypeError("candidate must be an ActionCandidateV1")
        if not isinstance(mode, AutonomyMode):
            raise TypeError("mode must be an AutonomyMode")
        if not isinstance(usage, BudgetUsageV1):
            raise TypeError("usage must be a BudgetUsageV1")
        if mode is AutonomyMode.SHADOW:
            return BudgetAssessmentV1(
                disposition=CandidateDisposition.SHADOW_ONLY,
                reason_codes=("shadow_mode_no_budget_admission",),
                policy_id=None if policy is None else policy.policy_id,
            )
        if mode in {AutonomyMode.OFF, AutonomyMode.OBSERVE}:
            return BudgetAssessmentV1(
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("mode_does_not_allow_dispatch",),
                policy_id=None if policy is None else policy.policy_id,
            )
        if mode is AutonomyMode.ACTIVE_BOUNDED:
            return BudgetAssessmentV1(
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("active_bounded_not_owner_enabled",),
                policy_id=None if policy is None else policy.policy_id,
            )
        if policy is None:
            return BudgetAssessmentV1(
                disposition=CandidateDisposition.BLOCKED_POLICY,
                reason_codes=("assisted_budget_policy_missing",),
                policy_id=None,
            )
        if not isinstance(policy, AutonomyBudgetPolicyV1):
            raise TypeError("policy must be an AutonomyBudgetPolicyV1")

        exceeded: list[str] = []
        if (
            usage.active_candidates_for_objective
            >= policy.max_active_candidates_per_objective
        ):
            exceeded.append("active_candidate_budget_exhausted")
        if (
            usage.repeated_dispatches_for_finding_window
            >= policy.max_repeat_dispatches_per_finding_window
        ):
            exceeded.append("repeat_dispatch_budget_exhausted")

        if candidate.action_kind in {
            ActionKind.WORK_ITEM,
            ActionKind.ENGINEERING_CHANGE,
        }:
            if (
                usage.active_autonomous_work_items
                >= policy.max_concurrent_autonomous_work_items
            ):
                exceeded.append("concurrent_work_budget_exhausted")
            if (
                usage.new_autonomous_work_items_in_window
                >= policy.max_new_autonomous_work_items_per_window
            ):
                exceeded.append("new_work_window_budget_exhausted")

        if (
            candidate.action_kind is ActionKind.OWNER_ATTENTION
            and not usage.urgent_root_attention_override
            and usage.owner_attention_notifications_in_window
            >= policy.max_owner_attention_notifications_per_window
        ):
            exceeded.append("owner_attention_budget_exhausted")

        ceiling = policy.provider_model_work_ceiling
        if ceiling is not None:
            if usage.provider_model_work_used is None:
                return BudgetAssessmentV1(
                    disposition=CandidateDisposition.BLOCKED_POLICY,
                    reason_codes=("provider_model_metering_unavailable",),
                    policy_id=policy.policy_id,
                )
            if usage.provider_model_work_used >= ceiling:
                exceeded.append("provider_model_work_budget_exhausted")

        if exceeded:
            return BudgetAssessmentV1(
                disposition=CandidateDisposition.DEFERRED_BUDGET,
                reason_codes=tuple(exceeded),
                policy_id=policy.policy_id,
            )
        return BudgetAssessmentV1(
            disposition=CandidateDisposition.ADMITTED,
            reason_codes=("within_explicit_budget",),
            policy_id=policy.policy_id,
        )


@dataclass(frozen=True, slots=True)
class AutonomyBudgetWindowV1:
    policy_id: str
    dimension_key: str
    window_started_epoch: float
    window_seconds: float
    used_value: float
    version: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_id",
            _text(self.policy_id, "policy_id"),
        )
        dimension = _token(self.dimension_key, "dimension_key")
        if dimension not in _ALLOWED_DIMENSIONS:
            raise ValueError(f"unsupported budget dimension: {dimension}")
        object.__setattr__(self, "dimension_key", dimension)
        object.__setattr__(
            self,
            "window_started_epoch",
            _epoch(self.window_started_epoch, "window_started_epoch"),
        )
        seconds = _nonnegative_float(self.window_seconds, "window_seconds")
        if seconds == 0:
            raise ValueError("window_seconds must be greater than zero")
        object.__setattr__(self, "window_seconds", seconds)
        object.__setattr__(
            self,
            "used_value",
            _nonnegative_float(self.used_value, "used_value"),
        )
        if isinstance(self.version, bool) or not isinstance(self.version, int):
            raise TypeError("version must be an integer")
        if self.version <= 0:
            raise ValueError("version must be positive")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "policy_id": self.policy_id,
            "dimension_key": self.dimension_key,
            "window_started_epoch": self.window_started_epoch,
            "window_seconds": self.window_seconds,
            "used_value": self.used_value,
            "version": self.version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        return cls(**payload)


class AutonomyBudgetLedger:
    """Durable CAS-style accounting in the existing autonomy budget table."""

    def __init__(self, store: AutonomyStore) -> None:
        if not isinstance(store, AutonomyStore):
            raise TypeError("store must be an AutonomyStore")
        self.store = store

    @staticmethod
    def window_start(
        *,
        now_epoch: float,
        window_seconds: float,
    ) -> float:
        now = _epoch(now_epoch, "now_epoch")
        seconds = _nonnegative_float(window_seconds, "window_seconds")
        if seconds == 0:
            raise ValueError("window_seconds must be greater than zero")
        return math.floor(now / seconds) * seconds

    def read(
        self,
        policy: AutonomyBudgetPolicyV1,
        dimension_key: str,
        *,
        now_epoch: float,
    ) -> AutonomyBudgetWindowV1 | None:
        dimension = _token(dimension_key, "dimension_key")
        if dimension not in _ALLOWED_DIMENSIONS:
            raise ValueError(f"unsupported budget dimension: {dimension}")
        started = self.window_start(
            now_epoch=now_epoch,
            window_seconds=policy.window_seconds,
        )
        with self.store.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_budget_windows
                WHERE policy_id=? AND dimension_key=? AND window_started_epoch=?
                """,
                (policy.policy_id, dimension, started),
            ).fetchone()
        if row is None:
            return None
        payload = self.store.work.decode_extension_json(str(row["payload"]))
        if not isinstance(payload, dict):
            raise AutonomyIntegrityError("budget-window payload is not an object")
        expected = str(row["payload_digest"])
        if canonical_digest(payload) != expected:
            raise AutonomyIntegrityError("budget-window payload digest mismatch")
        window = AutonomyBudgetWindowV1.from_payload(payload)
        if window.window_seconds != policy.window_seconds:
            raise AutonomyIntegrityError(
                "budget policy window changed without policy identity change"
            )
        if (
            float(row["window_seconds"]) != window.window_seconds
            or float(row["used_value"]) != window.used_value
            or int(row["version"]) != window.version
        ):
            raise AutonomyIntegrityError("budget-window column mismatch")
        return window

    def increment(
        self,
        policy: AutonomyBudgetPolicyV1,
        dimension_key: str,
        *,
        amount: float = 1.0,
        now_epoch: float,
    ) -> AutonomyBudgetWindowV1:
        dimension = _token(dimension_key, "dimension_key")
        if dimension not in _ALLOWED_DIMENSIONS:
            raise ValueError(f"unsupported budget dimension: {dimension}")
        increment = _nonnegative_float(amount, "amount")
        if increment == 0:
            raise ValueError("budget increment must be greater than zero")
        started = self.window_start(
            now_epoch=now_epoch,
            window_seconds=policy.window_seconds,
        )

        with self.store.work.extension_transaction() as db:
            row = db.execute(
                """
                SELECT * FROM autonomy_budget_windows
                WHERE policy_id=? AND dimension_key=? AND window_started_epoch=?
                """,
                (policy.policy_id, dimension, started),
            ).fetchone()
            if row is None:
                window = AutonomyBudgetWindowV1(
                    policy_id=policy.policy_id,
                    dimension_key=dimension,
                    window_started_epoch=started,
                    window_seconds=policy.window_seconds,
                    used_value=increment,
                    version=1,
                )
                payload = window.to_payload()
                encoded = self.store.work.encode_extension_json(payload)
                digest = canonical_digest(payload)
                try:
                    db.execute(
                        """
                        INSERT INTO autonomy_budget_windows(
                            policy_id, dimension_key, window_started_epoch,
                            window_seconds, used_value, version,
                            payload_digest, payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            window.policy_id,
                            window.dimension_key,
                            window.window_started_epoch,
                            window.window_seconds,
                            window.used_value,
                            window.version,
                            digest,
                            encoded,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise AutonomyConflictError(
                        "budget-window creation conflict"
                    ) from exc
                return window

            payload = self.store.work.decode_extension_json(str(row["payload"]))
            if not isinstance(payload, dict):
                raise AutonomyIntegrityError("budget-window payload is not an object")
            if canonical_digest(payload) != str(row["payload_digest"]):
                raise AutonomyIntegrityError("budget-window payload digest mismatch")
            current = AutonomyBudgetWindowV1.from_payload(payload)
            if current.window_seconds != policy.window_seconds:
                raise AutonomyIntegrityError(
                    "budget policy window changed without policy identity change"
                )
            updated = AutonomyBudgetWindowV1(
                policy_id=current.policy_id,
                dimension_key=current.dimension_key,
                window_started_epoch=current.window_started_epoch,
                window_seconds=current.window_seconds,
                used_value=current.used_value + increment,
                version=current.version + 1,
            )
            updated_payload = updated.to_payload()
            encoded = self.store.work.encode_extension_json(updated_payload)
            digest = canonical_digest(updated_payload)
            cursor = db.execute(
                """
                UPDATE autonomy_budget_windows
                SET used_value=?, version=?, payload_digest=?, payload=?
                WHERE policy_id=? AND dimension_key=?
                  AND window_started_epoch=? AND version=?
                """,
                (
                    updated.used_value,
                    updated.version,
                    digest,
                    encoded,
                    updated.policy_id,
                    updated.dimension_key,
                    updated.window_started_epoch,
                    current.version,
                ),
            )
            if cursor.rowcount != 1:
                raise AutonomyConflictError("budget-window compare-and-swap failed")
            return updated
