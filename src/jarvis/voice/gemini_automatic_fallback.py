"""Explicit free-first Paid access without local monetary admission."""

import inspect

from jarvis.model_routing.budget import PaidBudgetDenied
from jarvis.voice.gemini_live_budget import ControlledLiveAdmission


class AutomaticLiveAdmission:
    def __init__(self, runtime, *, model_id, authorize):
        if (
            not runtime.config.enabled
            or runtime.config.budget_enforced
            or not callable(authorize)
        ):
            raise PaidBudgetDenied(
                "Automatic fallback without spending enforcement is not enabled"
            )
        self.runtime, self.model_id, self.authorize = runtime, model_id, authorize

    async def require_authority(self):
        valid = self.authorize()
        if inspect.isawaitable(valid):
            valid = await valid
        if valid is not True:
            raise PaidBudgetDenied(
                "Original Live source authorization is no longer current"
            )

    def validate_target(self, target):
        if self.runtime.config.budget_enforced:
            raise PaidBudgetDenied("Automatic fallback mode changed")
        # Share credential, target-health and original Free-pressure validation.
        # This method performs no monetary reservation or usage interpretation.
        ControlledLiveAdmission._require_eligible_target(self, target)

    def reserve_transport(self, *, target, **kwargs):
        self.validate_target(target)
