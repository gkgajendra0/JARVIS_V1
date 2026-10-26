"""Operational admission reuses strict target/source checks, never strict proof."""

import asyncio
import inspect

from jarvis.model_routing.budget import PaidBudgetDenied, PaidOutcomeUnknown
from jarvis.model_routing.live_budget_admin import resolve_qualified_live_profile
from jarvis.model_routing.live_policy import (
    LiveUsageProfile,
    OperationalLivePolicy,
    digest,
    identity,
)
from jarvis.voice.gemini_live_budget import ControlledLiveAdmission


def operational_live_policy():
    return OperationalLivePolicy(provenance="jarvis-operational-live-v1-20261023")


def build_operational_live_admission(runtime, *, session_id, authorize):
    policy = operational_live_policy()
    if (
        not runtime.config.enabled
        or runtime.config.live_policy_mode != "operational_v1"
    ):
        raise PaidBudgetDenied("Operational Paid Live is disabled")
    profile = resolve_qualified_live_profile(runtime, policy=policy)
    if profile is None:
        raise PaidBudgetDenied("Production-qualified Live reporting profile required")

    async def current():
        # Qualification can expire during an open connection; check at dispatch boundaries.
        resolved = await asyncio.to_thread(
            resolve_qualified_live_profile, runtime, policy=policy
        )
        if resolved is None or resolved.fingerprint != profile.fingerprint:
            return False
        value = authorize()
        return await value if inspect.isawaitable(value) else value

    return OperationalLiveAdmission(
        runtime,
        session_id=session_id,
        authorize=current,
        policy=policy,
        profile=profile,
    )


def rebind_live_admission(admission, *, authorize):
    if type(admission) is OperationalLiveAdmission:
        return OperationalLiveAdmission(
            admission.runtime,
            session_id=admission.session_id,
            authorize=authorize,
            policy=admission.policy,
            profile=admission.profile,
            capture_only=admission.capture_only,
            experiment_authorization=admission.experiment_authorization,
        )
    return ControlledLiveAdmission(
        admission.runtime,
        session_id=admission.session_id,
        authorize=authorize,
        contract=admission.contract,
    )


class OperationalLiveAdmission(ControlledLiveAdmission):
    def __init__(
        self,
        runtime,
        *,
        session_id,
        authorize,
        policy,
        profile,
        capture_only=False,
        experiment_authorization=None,
    ):
        if not isinstance(policy, OperationalLivePolicy) or not callable(authorize):
            raise PaidBudgetDenied("Typed policy and original source required")
        if profile is not None and (
            not isinstance(profile, LiveUsageProfile)
            or profile.config_ref != policy.fingerprint
        ):
            raise PaidBudgetDenied("Usage interpretation does not match policy")
        if capture_only and (
            experiment_authorization is None
            or not callable(getattr(runtime, "validate_live_experiment", None))
        ):
            raise PaidBudgetDenied(
                "Capture requires separate audited exact experiment authority"
            )
        if profile is None and not capture_only:
            raise PaidBudgetDenied("Operational reporting profile required")
        self.runtime, self.session_id, self.authorize = (
            runtime,
            identity(session_id),
            authorize,
        )
        self.policy, self.profile = policy, profile
        self.capture_only, self.experiment_authorization = (
            capture_only,
            experiment_authorization,
        )

    @property
    def model_id(self):
        return self.policy.model_id

    async def require_authority(self):
        await super().require_authority()
        if self.experiment_authorization is not None:
            result = self.runtime.validate_live_experiment(
                self.experiment_authorization
            )
            if inspect.isawaitable(result):
                result = await result
            if result is not True:
                raise PaidBudgetDenied("Experiment authorization unavailable/expired")

    def _reserve_sync(self, target, connection_id):
        self._require_eligible_target(target)
        price = self.runtime.pricing_for(target)
        reservation = self.runtime.paid_budget.reserve_operational_live(
            invocation_id="live-operational:"
            + digest([self.session_id, connection_id, target.target_id]),
            target=target,
            pricing=price,
            policy=self.policy,
            profile=self.profile,
            scope_id=self.session_id,
            capture_only=self.capture_only,
        )
        if reservation.state != "reserved":
            raise PaidOutcomeUnknown("Operational demand already dispatched/finalized")
        if self.experiment_authorization is not None:
            try:
                self.runtime.live_diagnostics.bind_parent(
                    self.experiment_authorization, reservation, price
                )
            except BaseException:
                self.runtime.paid_budget.cancel_unsent(reservation.reservation_id)
                raise
        return reservation, price

    async def reserve_parent(self, target, *, connection_id):
        identity(connection_id)
        await self.require_authority()
        operation = asyncio.create_task(
            asyncio.to_thread(self._reserve_sync, target, connection_id)
        )
        try:
            reservation, price = await asyncio.shield(operation)
        except asyncio.CancelledError:
            reservation, _ = await operation
            await asyncio.to_thread(
                self.runtime.paid_budget.cancel_unsent, reservation.reservation_id
            )
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
        return reservation, price
