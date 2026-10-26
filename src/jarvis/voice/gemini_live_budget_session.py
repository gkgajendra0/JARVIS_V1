"""One physical budget lifecycle over the existing strict or operational owner."""

import asyncio
import time

from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown
from jarvis.model_routing.live_policy import digest, identity
from jarvis.voice.gemini_live_budget import ControlledLiveAdmission
from jarvis.voice.gemini_live_controls import LiveTransportControls
from jarvis.voice.gemini_live_usage import (
    normalize_operational_usage,
    usage_diagnostics,
)
from jarvis.voice.gemini_operational_budget import OperationalLiveAdmission


def create_connection_budget(admission, *, connection_id, target):
    if type(admission) not in {ControlledLiveAdmission, OperationalLiveAdmission}:
        raise PaidBudgetDenied("Exact typed Live admission required")
    return LiveConnectionBudget(admission, connection_id=connection_id, target=target)


class LiveConnectionBudget:
    def __init__(self, admission, *, connection_id, target):
        self.admission, self.connection_id, self.target = (
            admission,
            identity(connection_id),
            target,
        )
        self.operational = type(admission) is OperationalLiveAdmission
        self.controls = (
            LiveTransportControls.from_operational(
                admission.policy
            ).bounded_by_experiment(admission.experiment_authorization)
            if self.operational
            else LiveTransportControls.from_strict(admission.contract)
        )
        self.started_at = time.monotonic()
        self.reservation = self.price = self.strict_lease = None
        self.round_id = None
        self.round_complete = False
        self.closed = self.dispatched = self.stopped = False
        self.samples = 0
        self.lock = asyncio.Lock()
        self.last_observation = None
        self.policy_ref = admission.policy.fingerprint if self.operational else None
        self.profile_ref = (
            admission.profile.fingerprint
            if self.operational and admission.profile
            else None
        )

    @property
    def invocation_id(self):
        return (
            self.reservation.invocation_id + ":" + str(self.round_id)
            if self.operational
            else self.strict_lease.invocation_id
        )

    async def _require(self):
        await self.admission.require_authority()
        if (
            self.closed
            or self.stopped
            or time.monotonic() - self.started_at >= self.controls.dispatch_seconds
        ):
            raise PaidBudgetDenied("Original physical budget unavailable/expired")
        if self.operational:
            if (
                self.admission.policy.fingerprint != self.policy_ref
                or (
                    self.admission.profile.fingerprint
                    if self.admission.profile
                    else None
                )
                != self.profile_ref
            ):
                raise PaidBudgetDenied("Operational policy/reporting binding changed")
            await asyncio.to_thread(
                self.admission._require_eligible_target, self.target
            )
            if self.price is not None:

                def validate_price():
                    current = self.admission.runtime.pricing_for(self.target)
                    if current is None or digest(current.to_payload()) != digest(
                        self.price.to_payload()
                    ):
                        raise PaidBudgetDenied("Operational price binding changed")
                    current.validate_at(float(self.admission.runtime.clock()))

                await asyncio.to_thread(validate_price)
            await self.admission.require_authority()

    async def reserve_round(self, round_id):
        identity(round_id)
        async with self.lock:
            await self._require()
            if self.round_id is not None and not self.round_complete:
                raise PaidBudgetDenied("Previous round usage remains incomplete")
            if self.operational:
                if self.reservation is None:
                    self.reservation, self.price = await self.admission.reserve_parent(
                        self.target, connection_id=self.connection_id
                    )
            else:
                self.strict_lease = await self.admission.reserve(
                    self.target,
                    connection_id=self.connection_id,
                    trigger_id=round_id,
                    exposure=self.admission.contract.exposure(
                        self.admission.session_id
                    ),
                )
                self.reservation = self.strict_lease.reservation
            self.round_id = round_id
            self.round_complete = False

    async def before_send(self, kind, trigger_id, tool_call_ids=()):
        async with self.lock:
            await self._require()
            if self.reservation is None:
                raise PaidBudgetDenied("No connection allowance")
            if not self.operational:
                if not self.dispatched:
                    await self.strict_lease.mark_dispatched()
                    self.dispatched = True
                return
            operation = asyncio.create_task(
                asyncio.to_thread(
                    self.admission.runtime.paid_budget.checkpoint_operational_live,
                    reservation_id=self.reservation.reservation_id,
                    trigger_id=trigger_id,
                    kind=kind,
                    round_id=self.round_id,
                    tool_call_ids=tuple(tool_call_ids),
                )
            )
            try:
                permit = await asyncio.shield(operation)
            except asyncio.CancelledError:
                await operation
                self.dispatched = True
                await self._close_unlocked(teardown_confirmed=False, complete=False)
                raise
            self.dispatched = True
            # The public record remains current without another frame-path read.
            from dataclasses import replace

            self.reservation = replace(self.reservation, state="dispatched")
            await self._require()
            return permit

    async def validate_send(self):
        """Revalidate a reserved trigger after any intervening awaited SDK I/O."""
        async with self.lock:
            await self._require()

    async def observe(
        self, event_id, raw, *, sequence, turn_complete, last_output_sequence
    ):
        async with self.lock:
            if self.closed or self.reservation is None or not self.dispatched:
                raise PaidOutcomeUnknown("No dispatched Live usage owner")
            if not self.operational:
                self.strict_lease.observe(event_id, raw)
                self.round_complete = turn_complete
                return None
            if self.admission.profile is None:
                self.stopped = True
                return None
            report = normalize_operational_usage(
                raw,
                profile=self.admission.profile,
                round_id=self.round_id,
                sequence=sequence,
                after_round_complete=turn_complete,
                last_output_sequence=last_output_sequence,
            )
            operation = asyncio.create_task(
                asyncio.to_thread(
                    self.admission.runtime.paid_budget.observe_operational_live,
                    reservation_id=self.reservation.reservation_id,
                    report=report,
                    diagnostics=usage_diagnostics(raw, report),
                    event_id="live-usage-"
                    + digest([self.reservation.reservation_id, event_id]),
                )
            )
            try:
                observation = await asyncio.shield(operation)
            except asyncio.CancelledError:
                await operation
                self.stopped = True
                raise
            self.round_complete = report.complete and observation.unknown_reason is None
            self.last_observation = observation
            self.stopped = observation.stop_required
            return observation

    async def finish_round(self, round_id, *, complete):
        async with self.lock:
            if round_id != self.round_id or not complete or not self.round_complete:
                raise PaidOutcomeUnknown("Round lacks final attributable usage")
            if not self.operational:
                await self.strict_lease.finish(complete=True)
                self.dispatched = False

    def allow_frame(self, *, samples, sample_rate):
        if (
            self.closed
            or self.stopped
            or not self.dispatched
            or type(samples) is not int
            or samples <= 0
            or type(sample_rate) is not int
            or sample_rate != 16000
            or time.monotonic() - self.started_at >= self.controls.dispatch_seconds
            or self.samples + samples > self.controls.max_activity_seconds * 16000
        ):
            return False
        if not self.operational:
            return self.strict_lease.allow_frame(
                samples=samples, sample_rate=sample_rate
            )
        self.samples += samples
        return True

    async def _close_unlocked(self, *, teardown_confirmed, complete):
        if self.closed:
            return
        self.stopped = True
        if self.reservation is not None:
            if not self.operational:
                if self.dispatched:
                    await self.strict_lease.finish(
                        complete=complete and teardown_confirmed
                    )
                elif not self.strict_lease._finished:
                    await self.strict_lease.cancel_unsent()
            elif not self.dispatched:
                await asyncio.shield(
                    asyncio.to_thread(
                        self.admission.runtime.paid_budget.cancel_unsent,
                        self.reservation.reservation_id,
                    )
                )
            else:
                op = asyncio.create_task(
                    asyncio.to_thread(
                        self.admission.runtime.paid_budget.finish_operational_live,
                        reservation_id=self.reservation.reservation_id,
                        complete=complete,
                        teardown_confirmed=teardown_confirmed,
                        event_id=self.reservation.invocation_id + ":close",
                    )
                )
                try:
                    self.reservation = await asyncio.shield(op)
                except asyncio.CancelledError:
                    self.reservation = await op
                    self.closed = True
                    raise
        self.closed = True

    async def close(self, *, teardown_confirmed, complete):
        async with self.lock:
            await self._close_unlocked(
                teardown_confirmed=teardown_confirmed, complete=complete
            )
