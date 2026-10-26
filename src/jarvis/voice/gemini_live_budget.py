"""Controlled Live admission over the one existing durable PaidBudgetGovernor."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import dataclass, field

from jarvis.ai_provider import gemini_credential_ref
from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown
from jarvis.model_routing.eligibility import TargetHealthEligibility
from jarvis.model_routing.pricing import PaidExposure, PricingUnavailable
from jarvis.voice.gemini_live_contract import LiveModelContract, normalize_live_usage


def _identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise PaidBudgetDenied("Bounded original Live operation identity required")
    return value


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ControlledLiveAdmission:
    def __init__(self, runtime, *, session_id, authorize, contract: LiveModelContract):
        if not isinstance(contract, LiveModelContract) or not callable(authorize):
            raise PaidBudgetDenied(
                "Qualified Live contract and original source guard required"
            )
        self.runtime = runtime
        self.session_id = _identity(session_id)
        self.authorize = authorize
        self.contract = contract

    @property
    def model_id(self):
        return self.contract.model_id

    async def require_authority(self):
        valid = self.authorize()
        if inspect.isawaitable(valid):
            valid = await valid
        if valid is not True:
            raise PaidBudgetDenied(
                "Original Live source authorization is no longer current"
            )

    def _require_eligible_target(self, target):
        if (
            not self.runtime.config.enabled
            or not target.enabled
            or target.provider_id != "gemini"
            or target.credential_ref != gemini_credential_ref("paid")
            or target.model_id != self.model_id
            or "realtime_voice" not in target.capabilities
        ):
            raise PaidBudgetDenied(
                "Controlled Live requires the original eligible Paid target"
            )
        if self.runtime.store.credential_blocked(target.credential_ref):
            raise PaidBudgetDenied("Paid credential is unavailable")
        health = self.runtime.store.get_health(target.target_id)
        if health is not None and health.effective_state(
            now_epoch=self.runtime.clock()
        ) in {
            TargetHealthEligibility.COOLDOWN,
            TargetHealthEligibility.UNAVAILABLE,
            TargetHealthEligibility.DISABLED,
        }:
            raise PaidBudgetDenied("Paid Live target is unavailable")
        free_id = target.target_id.replace(".gemini.paid.", ".gemini.free.")
        pressure = self.runtime.store.get_health(free_id)
        if (
            pressure is None
            or pressure.state.value != "cooldown"
            or pressure.last_failure_kind not in {"quota_exhausted", "rate_limited"}
        ):
            raise PaidBudgetDenied("No eligible Free pressure authorizes Paid Live")

    def _reserve_sync(self, target, exposure, invocation_id):
        self._require_eligible_target(target)
        if (
            not isinstance(exposure, PaidExposure)
            or exposure.to_payload()
            != self.contract.exposure(self.session_id).to_payload()
        ):
            raise PaidBudgetDenied("Live envelope or original scope binding changed")
        price = self.runtime.pricing_for(target)
        if price is None or price.service_key != "live":
            raise PricingUnavailable("Reviewed Live price/FX required")
        if set(price.rates()) != set(exposure.usage_bounds):
            raise PricingUnavailable(
                "Complete exact Live modality/transcription prices required"
            )
        reservation = self.runtime.paid_budget.reserve(
            invocation_id=invocation_id, target=target, exposure=exposure, pricing=price
        )
        if reservation.state != "reserved":
            raise PaidOutcomeUnknown("Live trigger already dispatched or finalized")
        return reservation

    async def reserve(self, target, *, connection_id, trigger_id, exposure):
        connection_id, trigger_id = _identity(connection_id), _identity(trigger_id)
        await self.require_authority()
        invocation_id = "live:" + _digest(
            [self.session_id, connection_id, trigger_id, target.target_id]
        )
        operation = asyncio.create_task(
            asyncio.to_thread(self._reserve_sync, target, exposure, invocation_id)
        )
        try:
            reservation = await asyncio.shield(operation)
        except asyncio.CancelledError:
            # The transaction may already have committed. Wait for its outcome,
            # then release only the proven-unsent reserve; never lose its identity.
            try:
                reservation = await operation
                await asyncio.to_thread(
                    self.runtime.paid_budget.cancel_unsent, reservation.reservation_id
                )
            except PaidBudgetDenied:
                pass
            raise
        try:
            await self.require_authority()
        except BaseException:
            await asyncio.shield(
                asyncio.to_thread(
                    self.runtime.paid_budget.cancel_unsent, reservation.reservation_id
                )
            )
            raise
        return ControlledLiveLease(
            self, target, reservation, invocation_id, float(self.runtime.clock())
        )


@dataclass(slots=True)
class ControlledLiveLease:
    admission: ControlledLiveAdmission
    target: object
    reservation: object
    invocation_id: str
    admitted_at: float
    _samples: int = 0
    _finished: bool = False
    _dispatched: bool = False
    _closing: bool = False
    _invalid: bool = False
    _usage: dict = field(default_factory=dict)
    _complete_usage: bool = False
    _events: dict = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def contract(self):
        return self.admission.contract

    async def mark_dispatched(self):
        async with self._lock:
            if self._finished or self._dispatched:
                raise PaidOutcomeUnknown(
                    "Live permit cannot dispatch twice or after close"
                )
            try:
                await self.admission.require_authority()
                await asyncio.to_thread(
                    self.admission._require_eligible_target, self.target
                )
                await self.admission.require_authority()
                elapsed = float(self.admission.runtime.clock()) - self.admitted_at
                if elapsed < 0 or elapsed >= self.contract.max_physical_seconds:
                    raise PaidBudgetDenied(
                        "Live admission lifetime expired before dispatch"
                    )
            except BaseException:
                await asyncio.shield(
                    asyncio.to_thread(
                        self.admission.runtime.paid_budget.cancel_unsent,
                        self.reservation.reservation_id,
                    )
                )
                self._finished = True
                raise
            operation = asyncio.create_task(
                asyncio.to_thread(
                    self.admission.runtime.paid_budget.mark_dispatched,
                    self.reservation.reservation_id,
                )
            )
            try:
                self.reservation = await asyncio.shield(operation)
            except asyncio.CancelledError:
                self.reservation = await operation
                self._dispatched = True
                await self._finish_unlocked(False)
                raise
            self._dispatched = True
            try:
                await self.admission.require_authority()
                await asyncio.to_thread(
                    self.admission._require_eligible_target, self.target
                )
                await self.admission.require_authority()
                elapsed = float(self.admission.runtime.clock()) - self.admitted_at
                if elapsed < 0 or elapsed >= self.contract.max_physical_seconds:
                    raise PaidBudgetDenied(
                        "Live admission lifetime expired during dispatch"
                    )
            except BaseException:
                await self._finish_unlocked(False)
                raise
            return self.reservation

    def allow_frame(self, *, samples, sample_rate):
        if (
            self._finished
            or self._closing
            or not self._dispatched
            or type(samples) is not int
            or samples <= 0
            or sample_rate != 16000
            or type(sample_rate) is not int
        ):
            return False
        elapsed = float(self.admission.runtime.clock()) - self.admitted_at
        if elapsed < 0 or elapsed >= self.contract.max_physical_seconds:
            return False
        if self._samples + samples > self.contract.max_activity_seconds * 16000:
            return False
        self._samples += samples
        return True

    def observe(self, event_id, raw_usage):
        if self._finished or not self._dispatched:
            return
        event_id = _identity(event_id)
        if hasattr(raw_usage, "model_dump"):
            raw_usage = raw_usage.model_dump(mode="json")
        digest = _digest(raw_usage)
        prior = self._events.get(event_id)
        if prior is not None:
            if prior != digest:
                self._invalid = True
            return
        if len(self._events) >= 256:
            self._invalid = True
            return
        self._events[event_id] = digest
        usage, complete = normalize_live_usage(raw_usage, contract=self.contract)
        if any(value < self._usage.get(key, 0) for key, value in usage.items()):
            self._invalid = True
        for key, value in usage.items():
            self._usage[key] = max(value, self._usage.get(key, 0))
        self._complete_usage = complete and usage == self._usage

    async def _finish_unlocked(self, complete):
        if self._finished:
            return self.reservation
        if not self._dispatched:
            raise PaidOutcomeUnknown("Unsent Live permit must be explicitly cancelled")
        self._closing = True
        operation = asyncio.create_task(
            asyncio.to_thread(
                self.admission.runtime.paid_budget.settle,
                reservation_id=self.reservation.reservation_id,
                usage=dict(self._usage),
                usage_complete=complete and self._complete_usage and not self._invalid,
                event_id=self.invocation_id + ":final",
            )
        )
        try:
            self.reservation = await asyncio.shield(operation)
        except asyncio.CancelledError:
            self.reservation = await operation
            self._finished = True
            raise
        self._finished = True
        return self.reservation

    async def finish(self, *, complete):
        if type(complete) is not bool:
            raise PaidBudgetDenied("Explicit final Live outcome required")
        async with self._lock:
            return await self._finish_unlocked(complete)

    async def cancel_unsent(self):
        async with self._lock:
            if self._finished or self._dispatched:
                raise PaidOutcomeUnknown("Possibly dispatched Live cannot be refunded")
            await asyncio.shield(
                asyncio.to_thread(
                    self.admission.runtime.paid_budget.cancel_unsent,
                    self.reservation.reservation_id,
                )
            )
            self._finished = True
