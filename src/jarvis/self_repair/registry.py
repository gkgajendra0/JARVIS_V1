"""Deterministic RepairPolicy registry and execution gate."""

from __future__ import annotations

from collections.abc import Iterable

from jarvis.self_repair.domain import (
    RepairAction,
    RepairActionKind,
    RepairAuthorizationError,
    RepairPolicy,
    RepairPolicyConflictError,
    RepairRiskClass,
    RepairTrigger,
    _required_token,
)


class RepairRegistry:
    """Exact-match repair registry.

    Unknown triggers return no policy. Ambiguous matches and execution attempts
    outside the registered R1/R2 boundary fail closed.
    """

    def __init__(self, policies: Iterable[RepairPolicy] = ()) -> None:
        self._policies: dict[str, RepairPolicy] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: RepairPolicy) -> None:
        if not isinstance(policy, RepairPolicy):
            raise TypeError("policy must be a RepairPolicy")
        if policy.policy_id in self._policies:
            raise ValueError(f"duplicate repair policy_id: {policy.policy_id}")
        self._policies[policy.policy_id] = policy

    def get(self, policy_id: str) -> RepairPolicy | None:
        return self._policies.get(_required_token(policy_id, field="policy_id"))

    def policies(self) -> tuple[RepairPolicy, ...]:
        return tuple(self._policies[key] for key in sorted(self._policies))

    def match(self, trigger: RepairTrigger) -> RepairPolicy | None:
        matches = tuple(
            policy for policy in self._policies.values() if policy.matches(trigger)
        )
        if not matches:
            return None
        if len(matches) > 1:
            policy_ids = ", ".join(sorted(policy.policy_id for policy in matches))
            raise RepairPolicyConflictError(
                f"multiple repair policies matched one trigger: {policy_ids}"
            )
        return matches[0]

    def action_for(
        self,
        trigger: RepairTrigger,
        *,
        now_epoch: float | None = None,
    ) -> RepairAction | None:
        policy = self.match(trigger)
        if policy is None:
            return None
        return RepairAction.create(
            policy,
            trigger,
            now_epoch=now_epoch,
        )

    def assert_executable(
        self,
        trigger: RepairTrigger,
        action: RepairAction,
        *,
        satisfied_preconditions: Iterable[str] = (),
    ) -> RepairPolicy:
        policy = self._policies.get(action.policy_id)
        if policy is None:
            raise RepairAuthorizationError(
                "repair action references an unregistered policy"
            )
        if not policy.matches(trigger):
            raise RepairAuthorizationError(
                "registered policy does not match the current trigger"
            )
        if action.trigger_id != trigger.trigger_id:
            raise RepairAuthorizationError(
                "repair action belongs to a different trigger"
            )
        if action.policy_version != policy.version:
            raise RepairAuthorizationError(
                "repair action policy version is stale or invalid"
            )
        if action.component_id != trigger.component_id:
            raise RepairAuthorizationError(
                "repair action target does not match trigger component"
            )
        if action.kind is not policy.action_kind:
            raise RepairAuthorizationError(
                "repair action kind is not authorized by its policy"
            )
        if action.risk_class is not policy.risk_class:
            raise RepairAuthorizationError(
                "repair action risk does not match its policy"
            )
        if action.kind is RepairActionKind.NO_ACTION_ESCALATE:
            raise RepairAuthorizationError(
                "NO_ACTION_ESCALATE is not an executable repair effect"
            )
        if not policy.automatic:
            raise RepairAuthorizationError(
                "repair policy is not authorized for automatic execution"
            )
        if policy.risk_class not in {
            RepairRiskClass.R1_RETRY_RECONNECT,
            RepairRiskClass.R2_RESTART,
        }:
            raise RepairAuthorizationError(
                "automatic execution is limited to R1/R2 repair"
            )
        if not policy.reversible:
            raise RepairAuthorizationError(
                "automatic repair must be declared reversible"
            )

        satisfied = {
            _required_token(item, field="satisfied_precondition")
            for item in satisfied_preconditions
        }
        missing = tuple(item for item in policy.preconditions if item not in satisfied)
        if missing:
            raise RepairAuthorizationError(
                "repair preconditions are not satisfied: " + ", ".join(missing)
            )
        return policy
