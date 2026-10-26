"""Transport limits independent of strict billing proof."""

from dataclasses import dataclass, replace

from jarvis.model_routing.live_policy import OperationalLivePolicy
from jarvis.voice.gemini_live_contract import LiveModelContract


@dataclass(frozen=True, slots=True)
class LiveTransportControls:
    model_id: str
    max_physical_seconds: float
    max_activity_seconds: float
    output_token_limit: int
    max_tool_continuations: int
    setup_timeout_seconds: float
    fast_tool_wait_seconds: float
    final_usage_wait_seconds: float

    @property
    def dispatch_seconds(self):
        return self.max_physical_seconds - 3

    def bounded_by_experiment(self, authorization):
        if authorization is None:
            return self
        return replace(
            self,
            max_physical_seconds=min(
                self.max_physical_seconds, authorization.max_seconds
            ),
            max_tool_continuations=min(
                self.max_tool_continuations, authorization.max_generations - 1
            ),
        )

    @classmethod
    def from_strict(cls, contract):
        if not isinstance(contract, LiveModelContract):
            raise TypeError("Strict contract required")
        return cls(
            contract.model_id,
            contract.max_physical_seconds,
            contract.max_activity_seconds,
            contract.output_token_limit,
            32,
            5,
            5,
            0,
        )

    @classmethod
    def from_operational(cls, policy):
        if not isinstance(policy, OperationalLivePolicy):
            raise TypeError("Operational policy required")
        return cls(
            policy.model_id,
            policy.max_physical_seconds,
            policy.max_activity_seconds,
            policy.output_token_limit,
            policy.max_tool_continuations,
            policy.setup_timeout_seconds,
            policy.fast_tool_wait_seconds,
            policy.final_usage_wait_seconds,
        )
