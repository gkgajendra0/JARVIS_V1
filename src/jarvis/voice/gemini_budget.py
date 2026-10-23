"""Explicit Paid Live compatibility gate for the installed public SDK.

This is a denial, not a streaming accountant. A duration/token estimate and
post-connect metrics do not bound the SDK's automatic GoAway/tool reconnects
or server-driven turns. Do not admit Paid Live until a supported adapter can
reserve before every physical connect and generation. Structured inference
continues to use the shared PaidBudgetGovernor.
"""

from jarvis.model_routing.budget import PaidBudgetDenied


class GeminiLiveBudget:
    available = False
    reason = "live_transport_bound_unavailable"
    explanation = (
        "Paid Live unavailable: installed SDK reconnects without a supported "
        "pre-connect reservation hook; server-driven generation exposure is unbounded"
    )

    def reserve_transport(self, *, target, context, instructions, tools):
        raise PaidBudgetDenied(self.explanation)

    async def reserve_interval(self, exposure):
        raise PaidBudgetDenied(self.explanation)

    def before_connect(self):
        raise PaidBudgetDenied(self.explanation)

    def allow_input(self, *, modality, quantity, now_epoch):
        return False

    def observe_usage(self, *, event_id, usage, cumulative, complete):
        # No dispatched transport exists. Missing metrics cannot become zero cost.
        raise PaidBudgetDenied(self.explanation)

    def close(self, *, uncertain=True):
        # This compatibility gate never reserves or dispatches paid exposure.
        pass
